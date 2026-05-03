"""Hard risk controls. The trading loop must call `check()` before sending
any order; if it returns a non-empty reason, do NOT trade and trip the
kill switch."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import settings
from .db import trade_log
from .models import Trade, TradeStatus


@dataclass
class RiskState:
    starting_equity_today: float = 0.0
    peak_equity: float = 0.0
    consecutive_losses: int = 0
    last_loss_time: Optional[datetime] = None
    pause_until: Optional[datetime] = None
    kill_switch_tripped: bool = False
    kill_reason: Optional[str] = None
    day_anchor: Optional[datetime] = None  # UTC midnight of the trading day


class RiskManager:
    def __init__(self):
        self.state = RiskState()

    # --- daily reset ----------------------------------------------------
    def _reset_day_if_needed(self, now: datetime, equity: float) -> None:
        anchor = now.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if self.state.day_anchor != anchor:
            self.state.day_anchor = anchor
            self.state.starting_equity_today = equity
            if self.state.peak_equity == 0.0:
                self.state.peak_equity = equity

    def update_equity(self, now: datetime, equity: float) -> None:
        self._reset_day_if_needed(now, equity)
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    # --- post-trade -----------------------------------------------------
    def record_trade_close(self, t: Trade) -> None:
        if t.pnl is None:
            return
        if t.pnl < 0:
            self.state.consecutive_losses += 1
            self.state.last_loss_time = t.exit_time or datetime.now(timezone.utc)
            if self.state.consecutive_losses >= settings.CONSECUTIVE_LOSS_LIMIT:
                self.state.pause_until = self.state.last_loss_time + timedelta(
                    hours=24
                )
                trade_log.log_event(
                    "WARN",
                    "consecutive_loss_pause",
                    f"{self.state.consecutive_losses} losses; paused 24h",
                )
        else:
            self.state.consecutive_losses = 0

    # --- pre-trade gate -------------------------------------------------
    def daily_pnl_pct(self, equity: float) -> float:
        if self.state.starting_equity_today == 0.0:
            return 0.0
        return (
            100.0 * (equity - self.state.starting_equity_today)
            / self.state.starting_equity_today
        )

    def drawdown_pct(self, equity: float) -> float:
        if self.state.peak_equity == 0.0:
            return 0.0
        return 100.0 * (self.state.peak_equity - equity) / self.state.peak_equity

    def trip(self, reason: str) -> None:
        if self.state.kill_switch_tripped:
            return
        self.state.kill_switch_tripped = True
        self.state.kill_reason = reason
        trade_log.log_event("ERROR", "kill_switch", reason)

    def reset_kill_switch(self) -> None:
        self.state.kill_switch_tripped = False
        self.state.kill_reason = None

    def check(
        self, now: datetime, equity: float, open_count: int, trades_today: int
    ) -> Optional[str]:
        """Return a reason string if trading is blocked, else None."""
        self.update_equity(now, equity)

        if self.state.kill_switch_tripped:
            return f"kill_switch:{self.state.kill_reason}"

        if not settings.TRADING_ENABLED:
            return "trading_disabled"

        if self.state.pause_until and now < self.state.pause_until:
            return f"paused_until:{self.state.pause_until.isoformat()}"

        # daily loss kill switch — also trips the persistent flag
        dpl = self.daily_pnl_pct(equity)
        if dpl <= -settings.DAILY_LOSS_LIMIT_PCT:
            self.trip(f"daily_loss_limit hit at {dpl:.2f}%")
            return f"daily_loss_limit:{dpl:.2f}%"

        # max drawdown — also trips the persistent flag
        dd = self.drawdown_pct(equity)
        if dd >= settings.MAX_DRAWDOWN_PCT:
            self.trip(f"max_drawdown hit at {dd:.2f}%")
            return f"max_drawdown:{dd:.2f}%"

        if trades_today >= settings.MAX_TRADES_PER_DAY:
            return f"max_trades_today:{trades_today}"

        if open_count >= settings.MAX_CONCURRENT_POSITIONS:
            return f"max_concurrent:{open_count}"

        return None


risk = RiskManager()
