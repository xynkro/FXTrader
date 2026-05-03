"""Bar-by-bar backtester. Conservative fill assumptions:

  - Entry fills at signal candle close + 0.2 pip slippage on the trade direction
  - Spread cost: 0.5 pip charged on each entry (round-trip ≈ 1 pip)
  - If both stop and target are touched in the same later bar, assume STOP
    fills first (worst case — we have no tick data to disambiguate)
  - Position size scales with current equity using the same formula as live

Outputs:
  - List of completed trade dicts
  - Equity curve (per closed trade)
  - Aggregate stats: win rate, avg R, expectancy, Sharpe, max DD, profit factor
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from .config import settings
from .models import BacktestResult, Candle, Side
from .strategy import (
    StrategyParams,
    StrategyState,
    evaluate,
    in_session,
    position_size,
)


SPREAD_PIPS = 0.5            # one-side spread cost; round-trip ≈ 1 pip
SLIPPAGE_PIPS = 0.2
PIP = 0.0001                 # EUR/USD


@dataclass
class BTTrade:
    entry_time: str
    exit_time: str
    side: str
    units: int
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    pnl: float
    pnl_pct: float
    r_multiple: float
    bars_held: int
    exit_reason: str
    reason: str


def _apply_costs(side: Side, price: float, action: str) -> float:
    """`action` is 'entry' or 'exit'. We apply spread + slippage to the
    detriment of the trader."""
    cost = (SPREAD_PIPS / 2 + SLIPPAGE_PIPS) * PIP
    if action == "entry":
        return price + cost if side == Side.LONG else price - cost
    # exit
    return price - cost if side == Side.LONG else price + cost


def run_backtest(
    candles: list[Candle],
    starting_equity: float = 10_000.0,
    params: Optional[StrategyParams] = None,
    session_filter: bool = True,
    end_of_session_close: bool = True,
) -> tuple[BacktestResult, list[BTTrade], list[tuple[str, float]]]:
    if not candles:
        raise ValueError("no candles supplied")

    state = StrategyState(params=params or StrategyParams())
    equity = starting_equity
    peak = equity
    trades: list[BTTrade] = []
    equity_curve: list[tuple[str, float]] = [
        (candles[0].time.isoformat(), equity)
    ]

    open_trade: Optional[dict] = None
    bars_held = 0

    for i, bar in enumerate(candles):
        # 1) If we're in a trade, check for stop/target hit on THIS bar
        if open_trade is not None:
            bars_held += 1
            side = open_trade["side"]
            stop = open_trade["stop"]
            target = open_trade["target"]

            stop_hit = (
                bar.low <= stop if side == Side.LONG else bar.high >= stop
            )
            target_hit = (
                bar.high >= target if side == Side.LONG else bar.low <= target
            )

            exit_reason = None
            if stop_hit and target_hit:
                # Worst case: assume stop first
                fill = stop
                exit_reason = "stop_first_ambiguous"
            elif stop_hit:
                fill = stop
                exit_reason = "stop"
            elif target_hit:
                fill = target
                exit_reason = "target"

            # End-of-session timed close
            if (
                exit_reason is None
                and end_of_session_close
                and session_filter
                and not in_session(bar.time)
                and i > 0
                and in_session(candles[i - 1].time)
            ):
                fill = bar.open
                exit_reason = "session_end"

            if exit_reason is not None:
                exit_price = _apply_costs(side, fill, "exit")
                entry_px = open_trade["entry_price"]
                units = open_trade["units"]
                gross = (
                    (exit_price - entry_px) * units
                    if side == Side.LONG
                    else (entry_px - exit_price) * units
                )
                planned_risk = abs(entry_px - open_trade["stop"]) * units
                r_mult = gross / planned_risk if planned_risk > 0 else 0.0
                pnl_pct = 100.0 * gross / open_trade["equity_at_entry"]
                equity += gross
                peak = max(peak, equity)

                trades.append(
                    BTTrade(
                        entry_time=open_trade["entry_time"].isoformat(),
                        exit_time=bar.time.isoformat(),
                        side=side.value,
                        units=units,
                        entry_price=entry_px,
                        exit_price=exit_price,
                        stop_price=open_trade["stop"],
                        target_price=open_trade["target"],
                        pnl=gross,
                        pnl_pct=pnl_pct,
                        r_multiple=r_mult,
                        bars_held=bars_held,
                        exit_reason=exit_reason,
                        reason=open_trade["reason"],
                    )
                )
                equity_curve.append((bar.time.isoformat(), equity))
                open_trade = None
                bars_held = 0

        # 2) Always update strategy state with this bar
        state.add(bar)

        # 3) Evaluate for new signal (only if flat)
        if open_trade is None:
            sig = evaluate(state, equity)
            if sig is None:
                continue
            entry_px = _apply_costs(sig.side, sig.entry, "entry")
            units = position_size(equity, entry_px, sig.stop)
            if units <= 0:
                continue
            open_trade = {
                "side": sig.side,
                "entry_time": sig.time,
                "entry_price": entry_px,
                "stop": sig.stop,
                "target": sig.target,
                "units": units,
                "equity_at_entry": equity,
                "reason": sig.reason,
            }
            bars_held = 0

    # Close any dangling trade at the last bar's close
    if open_trade is not None:
        side = open_trade["side"]
        exit_price = _apply_costs(side, candles[-1].close, "exit")
        entry_px = open_trade["entry_price"]
        units = open_trade["units"]
        gross = (
            (exit_price - entry_px) * units
            if side == Side.LONG
            else (entry_px - exit_price) * units
        )
        planned_risk = abs(entry_px - open_trade["stop"]) * units
        r_mult = gross / planned_risk if planned_risk > 0 else 0.0
        pnl_pct = 100.0 * gross / open_trade["equity_at_entry"]
        equity += gross
        trades.append(
            BTTrade(
                entry_time=open_trade["entry_time"].isoformat(),
                exit_time=candles[-1].time.isoformat(),
                side=side.value,
                units=units,
                entry_price=entry_px,
                exit_price=exit_price,
                stop_price=open_trade["stop"],
                target_price=open_trade["target"],
                pnl=gross,
                pnl_pct=pnl_pct,
                r_multiple=r_mult,
                bars_held=bars_held,
                exit_reason="forced_eod",
                reason=open_trade["reason"],
            )
        )
        equity_curve.append((candles[-1].time.isoformat(), equity))

    return _summarize(candles, trades, equity_curve, starting_equity, equity), trades, equity_curve


def _summarize(
    candles: list[Candle],
    trades: list[BTTrade],
    equity_curve: list[tuple[str, float]],
    starting_equity: float,
    final_equity: float,
) -> BacktestResult:
    n = len(trades)
    if n == 0:
        return BacktestResult(
            start=candles[0].time,
            end=candles[-1].time,
            instrument=settings.INSTRUMENT,
            bars=len(candles),
            trades=0, wins=0, losses=0,
            win_rate=0.0, avg_r=0.0, expectancy_pct=0.0,
            total_return_pct=0.0, max_drawdown_pct=0.0,
            sharpe=0.0, profit_factor=0.0,
            final_equity=final_equity, starting_equity=starting_equity,
        )

    pnls = np.array([t.pnl for t in trades])
    rs = np.array([t.r_multiple for t in trades])
    pcts = np.array([t.pnl_pct for t in trades])
    wins = int((pnls > 0).sum())
    losses = int((pnls <= 0).sum())
    win_rate = 100.0 * wins / n
    avg_r = float(rs.mean())
    expectancy_pct = float(pcts.mean())
    total_ret_pct = 100.0 * (final_equity - starting_equity) / starting_equity

    # Max drawdown on equity curve
    eq = np.array([e for _, e in equity_curve])
    peaks = np.maximum.accumulate(eq)
    dd = (peaks - eq) / peaks
    max_dd_pct = float(dd.max() * 100.0) if len(dd) else 0.0

    # Sharpe on per-trade % returns, annualised by trades/year (conservative)
    days = max((candles[-1].time - candles[0].time).days, 1)
    trades_per_year = n * (365.0 / days)
    if pcts.std(ddof=0) > 0:
        sharpe = float(pcts.mean() / pcts.std(ddof=0) * math.sqrt(trades_per_year))
    else:
        sharpe = 0.0

    gross_win = float(pnls[pnls > 0].sum())
    gross_loss = float(-pnls[pnls < 0].sum())
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    return BacktestResult(
        start=candles[0].time,
        end=candles[-1].time,
        instrument=settings.INSTRUMENT,
        bars=len(candles),
        trades=n, wins=wins, losses=losses,
        win_rate=win_rate, avg_r=avg_r, expectancy_pct=expectancy_pct,
        total_return_pct=total_ret_pct, max_drawdown_pct=max_dd_pct,
        sharpe=sharpe, profit_factor=profit_factor,
        final_equity=final_equity, starting_equity=starting_equity,
    )


def save_results(
    result: BacktestResult,
    trades: list[BTTrade],
    equity_curve: list[tuple[str, float]],
    out_dir: Optional[Path] = None,
    label: str = "default",
) -> Path:
    out_dir = out_dir or settings.backtest_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    folder = out_dir / f"{stamp}_{label}"
    folder.mkdir()

    (folder / "summary.json").write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, default=str)
    )
    (folder / "trades.json").write_text(
        json.dumps([asdict(t) for t in trades], indent=2)
    )
    (folder / "equity.json").write_text(
        json.dumps([{"t": t, "equity": e} for t, e in equity_curve], indent=2)
    )
    return folder
