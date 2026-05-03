"""Live trading loop. Polls OANDA every 30s, evaluates the strategy on
newly-closed M5 candles, places orders through the risk manager, and
reconciles fills/closures into the local trade log."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from .config import settings
from .db import trade_log
from .models import EngineStatus, Side, Trade, TradeStatus
from .oanda_client import OandaClient, OandaError, get_client
from .risk import risk
from .strategy import StrategyState, evaluate, in_session, position_size


log = logging.getLogger("trader")


class Engine:
    def __init__(self):
        self.state = StrategyState()
        self.last_candle_time: Optional[datetime] = None
        self.last_signal_time: Optional[datetime] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._oanda_id_to_local: dict[str, int] = {}
        self._client: Optional[OandaClient] = None
        self._equity: float = 0.0

    # ------------------------------------------------------------------
    @property
    def client(self) -> OandaClient:
        if self._client is None:
            self._client = get_client()
        return self._client

    # ------------------------------------------------------------------
    async def warm_history(self, count: int = 200) -> None:
        candles = await self.client.candles(
            instrument=settings.INSTRUMENT,
            granularity=settings.GRANULARITY,
            count=count,
        )
        for c in candles:
            self.state.add(c)
        if candles:
            self.last_candle_time = candles[-1].time
        trade_log.log_event(
            "INFO", "warm_history", f"loaded {len(candles)} candles"
        )

    # ------------------------------------------------------------------
    async def tick(self) -> None:
        """One iteration: pull new candles, reconcile, evaluate, maybe trade."""
        snap = await self.client.account_snapshot()
        self._equity = snap.equity
        trade_log.snapshot_equity(snap)
        risk.update_equity(snap.timestamp, snap.equity)

        # Pull last 5 candles, only keep ones newer than what we have.
        candles = await self.client.candles(
            instrument=settings.INSTRUMENT,
            granularity=settings.GRANULARITY,
            count=5,
        )
        new_bar = False
        for c in candles:
            if self.last_candle_time is None or c.time > self.last_candle_time:
                self.state.add(c)
                self.last_candle_time = c.time
                new_bar = True

        await self._reconcile_closures()

        if not new_bar:
            return

        block = risk.check(
            now=snap.timestamp,
            equity=snap.equity,
            open_count=snap.open_position_count,
            trades_today=len(trade_log.trades_today(snap.timestamp)),
        )
        if block:
            return

        sig = evaluate(self.state, snap.equity)
        if sig is None:
            return
        self.last_signal_time = sig.time

        units, leverage_capped = position_size(snap.equity, sig.entry, sig.stop)
        if units <= 0:
            trade_log.log_event(
                "WARN", "size_zero",
                f"computed 0 units for entry={sig.entry} stop={sig.stop}",
            )
            return
        if leverage_capped:
            trade_log.log_event(
                "WARN", "leverage_capped",
                f"units capped to {units} on entry={sig.entry}",
            )
        signed_units = units if sig.side == Side.LONG else -units

        try:
            resp = await self.client.market_order(
                instrument=settings.INSTRUMENT,
                units=signed_units,
                stop_price=sig.stop,
                target_price=sig.target,   # may be None for trend follower
            )
        except OandaError as e:
            trade_log.log_event("ERROR", "order_failed", str(e))
            risk.trip(f"order_failed:{e}")
            return

        fill = resp.get("orderFillTransaction", {})
        oanda_trade_id = fill.get("tradeOpened", {}).get("tradeID")
        fill_price = float(fill.get("price", sig.entry))

        local_trade = Trade(
            oanda_trade_id=oanda_trade_id,
            instrument=settings.INSTRUMENT,
            side=sig.side,
            units=signed_units,
            entry_time=sig.time,
            entry_price=fill_price,
            stop_price=sig.stop,
            target_price=sig.target if sig.target is not None else 0.0,
            status=TradeStatus.OPEN,
            reason=sig.reason,
        )
        trade_id = trade_log.insert_trade(local_trade)
        if oanda_trade_id:
            self._oanda_id_to_local[oanda_trade_id] = trade_id
        tgt_str = f"{sig.target:.5f}" if sig.target is not None else "trail"
        trade_log.log_event(
            "INFO",
            "trade_opened",
            f"#{trade_id} {sig.side.value} {units}u @ {fill_price:.5f} "
            f"stop={sig.stop:.5f} tgt={tgt_str}",
        )

    # ------------------------------------------------------------------
    async def _reconcile_closures(self) -> None:
        """Any local OPEN trade not in OANDA's open list = closed. Pull the
        fill price from current price and mark closed."""
        try:
            oanda_open = await self.client.open_trades()
        except OandaError:
            return
        oanda_open_ids = {t["id"] for t in oanda_open}

        for t in trade_log.open_trades():
            if t.oanda_trade_id and t.oanda_trade_id not in oanda_open_ids:
                bid, ask = await self.client.current_price(t.instrument)
                exit_price = bid if t.side == Side.LONG else ask
                planned_risk = abs(t.entry_price - t.stop_price) * abs(t.units)
                actual = (
                    (exit_price - t.entry_price) * t.units
                    if t.side == Side.LONG
                    else (t.entry_price - exit_price) * abs(t.units)
                )
                pnl_pct = (
                    100.0 * actual / self._equity if self._equity > 0 else 0.0
                )
                r = actual / planned_risk if planned_risk > 0 else 0.0
                trade_log.close_trade(
                    trade_id=t.id,
                    exit_time=datetime.now(timezone.utc),
                    exit_price=exit_price,
                    pnl=actual,
                    pnl_pct=pnl_pct,
                    r_multiple=r,
                )
                t.exit_price = exit_price
                t.pnl = actual
                t.pnl_pct = pnl_pct
                t.r_multiple = r
                t.status = TradeStatus.CLOSED
                risk.record_trade_close(t)
                trade_log.log_event(
                    "INFO",
                    "trade_closed",
                    f"#{t.id} R={r:.2f} pnl=${actual:.2f}",
                )

    # ------------------------------------------------------------------
    async def _loop(self) -> None:
        try:
            await self.warm_history()
        except OandaError as e:
            log.error("warm_history failed: %s", e)
            trade_log.log_event("ERROR", "warm_failed", str(e))
            return

        while self._running:
            try:
                await self.tick()
            except Exception as e:  # noqa: BLE001
                log.exception("tick failed")
                trade_log.log_event("ERROR", "tick_exception", str(e))
            await asyncio.sleep(30)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        trade_log.log_event("INFO", "engine_start", "")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        trade_log.log_event("INFO", "engine_stop", "")

    # ------------------------------------------------------------------
    async def kill(self) -> None:
        """Hard stop: close all open positions and trip the kill switch."""
        risk.trip("manual_kill")
        try:
            await self.client.close_position(settings.INSTRUMENT)
        except OandaError as e:
            trade_log.log_event("ERROR", "kill_close_failed", str(e))
        trade_log.log_event("WARN", "manual_kill", "all positions closed")

    # ------------------------------------------------------------------
    def status(self) -> EngineStatus:
        now = datetime.now(timezone.utc)
        return EngineStatus(
            trading_enabled=settings.TRADING_ENABLED and not risk.state.kill_switch_tripped,
            kill_switch_tripped=risk.state.kill_switch_tripped,
            kill_reason=risk.state.kill_reason,
            in_session=in_session(now),
            consecutive_losses=risk.state.consecutive_losses,
            trades_today=len(trade_log.trades_today(now)),
            daily_pnl_pct=risk.daily_pnl_pct(self._equity),
            peak_equity=risk.state.peak_equity,
            current_drawdown_pct=risk.drawdown_pct(self._equity),
            last_signal_time=self.last_signal_time,
            last_candle_time=self.last_candle_time,
        )


engine = Engine()
