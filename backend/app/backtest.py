"""Bar-by-bar backtester for v1-B trend-follower with strict execution semantics.

Locked semantics (verified against the v1-B plan):

1. Signal computed on close of bar t. Entry filled at OPEN of bar t+1 with
   spread/slippage applied. Stop computed from t+1 fill price using
   ATR FROZEN at signal bar (sig.atr).

2. Stop-out check uses the stop active for that bar (set at end of previous
   bar). Trail update for bar t becomes active at bar t+1 — never
   retroactively protects bar t. (No lookahead.)

3. Cooldown applies after stop-out only (initial OR trailed). NOT after
   session-end forced exit.

4. Session-end exit: if open trade and current bar is OOS, close at this
   bar's open with costs (the boundary bar = "17:00 close" mark).

5. Sizing safeguards:
   - MIN_STOP_PIPS already filtered at signal time (in strategy.evaluate)
   - MAX_LEVERAGE caps units; counted as `leverage_cap_binds`

Reports: per-trade list w/ bars_held, equity curve, skip counts, monthly P&L,
top-5 winner concentration, friction shock (via spread/slippage args).
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from .config import settings
from .models import BacktestResult, Candle, Side
from typing import Callable

from .strategy import (
    StrategyParams,
    StrategyState,
    evaluate as evaluate_default,
    in_session,
    is_jpy_quote,
    pip_size,
    position_size,
)


@dataclass
class BTTrade:
    entry_time: str
    exit_time: str
    side: str
    units: int
    entry_price: float
    exit_price: float
    initial_stop: float
    final_stop: float
    atr_at_entry: float
    pnl: float
    pnl_pct: float
    r_multiple: float
    bars_held: int
    leverage_capped: bool
    exit_reason: str
    reason: str


@dataclass
class BTDiagnostics:
    leverage_cap_attempts: int = 0
    leverage_cap_binds: int = 0
    session_end_closes: int = 0
    skips: dict = field(default_factory=dict)


def _apply_costs(
    side: Side,
    price: float,
    action: str,
    spread_pips: float,
    slippage_pips: float,
) -> float:
    """Add round-trip half-spread + slippage to the trader's detriment."""
    cost = (spread_pips / 2.0 + slippage_pips) * pip_size(settings.INSTRUMENT)
    if action == "entry":
        return price + cost if side == Side.LONG else price - cost
    return price - cost if side == Side.LONG else price + cost


def run_backtest(
    candles: list[Candle],
    starting_equity: float = 10_000.0,
    params: Optional[StrategyParams] = None,
    spread_pips: float = 0.5,
    slippage_pips: float = 0.2,
    session_filter: bool = True,
    evaluate_fn: Optional[Callable] = None,
) -> tuple[BacktestResult, list[BTTrade], list[tuple[str, float]], dict]:
    if not candles:
        raise ValueError("no candles supplied")

    p = params or StrategyParams()
    state = StrategyState(params=p)
    eval_fn = evaluate_fn or evaluate_default
    diag = BTDiagnostics()
    trades: list[BTTrade] = []
    equity_curve: list[tuple[str, float]] = [
        (candles[0].time.isoformat(), starting_equity)
    ]
    equity = starting_equity

    pending_signal = None
    open_trade: Optional[dict] = None

    for bar in candles:
        # --- 1. Activate any trail update planned for this bar ---
        if open_trade is not None and open_trade.get("next_stop") is not None:
            open_trade["stop"] = open_trade["next_stop"]
            open_trade["next_stop"] = None

        # --- 2. Stop-out check using the active stop ---
        exited_by_stop = False
        if open_trade is not None:
            side = open_trade["side"]
            stop = open_trade["stop"]
            stop_hit = (
                bar.low <= stop if side == Side.LONG else bar.high >= stop
            )
            if stop_hit:
                exit_price = _apply_costs(
                    side, stop, "exit", spread_pips, slippage_pips
                )
                stop_label = (
                    "trailing_stop" if open_trade.get("trailed", False)
                    else "initial_stop"
                )
                equity = _close_trade(
                    open_trade, exit_price, bar.time, stop_label,
                    trades, equity_curve, equity,
                )
                state.trip_cooldown(side)   # cooldown ONLY after stop-out
                open_trade = None
                exited_by_stop = True

        # --- 3. Activate pending entry at this bar's open ---
        if open_trade is None and pending_signal is not None:
            sig = pending_signal
            if session_filter and not in_session(bar.time):
                # next bar after a session-edge signal → discard
                pending_signal = None
            else:
                fill_price = _apply_costs(
                    sig.side, bar.open, "entry", spread_pips, slippage_pips
                )
                stop_distance = sig.stop_distance
                # Recompute stop from actual fill (locked semantic)
                if sig.side == Side.LONG:
                    initial_stop = fill_price - stop_distance
                else:
                    initial_stop = fill_price + stop_distance
                units, capped = position_size(
                    equity, fill_price, initial_stop, p.max_leverage
                )
                diag.leverage_cap_attempts += 1
                if capped:
                    diag.leverage_cap_binds += 1
                if units > 0:
                    open_trade = {
                        "side": sig.side,
                        "entry_time": bar.time,
                        "entry_price": fill_price,
                        "initial_stop": initial_stop,
                        "stop": initial_stop,
                        "next_stop": None,
                        "atr_at_entry": sig.atr,
                        "stop_distance": stop_distance,
                        "units": units,
                        "leverage_capped": capped,
                        "equity_at_entry": equity,
                        "ext": bar.high if sig.side == Side.LONG else bar.low,
                        "bars_held": 0,
                        "reason": sig.reason,
                    }
                pending_signal = None

        # --- 4. Update trail extreme + bars_held ---
        if open_trade is not None:
            if open_trade["side"] == Side.LONG:
                open_trade["ext"] = max(open_trade["ext"], bar.high)
            else:
                open_trade["ext"] = min(open_trade["ext"], bar.low)
            open_trade["bars_held"] += 1

        # --- 5. Session-end forced exit (no cooldown) ---
        if (
            open_trade is not None
            and not exited_by_stop
            and session_filter
            and not in_session(bar.time)
        ):
            side = open_trade["side"]
            exit_price = _apply_costs(
                side, bar.open, "exit", spread_pips, slippage_pips
            )
            equity = _close_trade(
                open_trade, exit_price, bar.time, "session_end",
                trades, equity_curve, equity,
            )
            diag.session_end_closes += 1
            open_trade = None

        # --- 6. Add bar to strategy state, decrement cooldowns ---
        state.add(bar)
        state.decrement_cooldowns()

        # --- 7. Evaluate signal if flat AND in-session AND no pending ---
        if (
            open_trade is None
            and pending_signal is None
            and (not session_filter or in_session(bar.time))
        ):
            sig = eval_fn(state, equity, diagnostics=diag.skips)
            if sig is not None:
                pending_signal = sig

        # --- 8. Compute next-bar trail stop (active at bar t+1) ---
        if open_trade is not None:
            stop_dist = open_trade["stop_distance"]
            ext = open_trade["ext"]
            if open_trade["side"] == Side.LONG:
                trail = ext - stop_dist
                if trail > open_trade["stop"]:
                    open_trade["next_stop"] = trail
                    open_trade["trailed"] = True
            else:
                trail = ext + stop_dist
                if trail < open_trade["stop"]:
                    open_trade["next_stop"] = trail
                    open_trade["trailed"] = True

    # Close dangling trade at last bar's close
    if open_trade is not None:
        side = open_trade["side"]
        exit_price = _apply_costs(
            side, candles[-1].close, "exit", spread_pips, slippage_pips
        )
        equity = _close_trade(
            open_trade, exit_price, candles[-1].time, "forced_eod",
            trades, equity_curve, equity,
        )

    summary = _summarize(candles, trades, equity_curve, starting_equity, equity)
    diagnostics = _diagnostics_dict(diag, trades, spread_pips, slippage_pips)
    return summary, trades, equity_curve, diagnostics


def _close_trade(
    open_trade: dict, exit_price: float, exit_time: datetime, reason: str,
    trades: list[BTTrade], equity_curve: list[tuple[str, float]], equity: float,
) -> float:
    side = open_trade["side"]
    units = open_trade["units"]
    entry_px = open_trade["entry_price"]
    initial_stop = open_trade["initial_stop"]
    final_stop = open_trade["stop"]
    if side == Side.LONG:
        gross_quote = (exit_price - entry_px) * units
    else:
        gross_quote = (entry_px - exit_price) * units
    # Convert to USD if quote currency is JPY (account currency is USD).
    if is_jpy_quote(settings.INSTRUMENT):
        gross = gross_quote / exit_price
        planned_risk = abs(entry_px - initial_stop) * units / entry_px
    else:
        gross = gross_quote
        planned_risk = abs(entry_px - initial_stop) * units
    r_mult = gross / planned_risk if planned_risk > 0 else 0.0
    pnl_pct = 100.0 * gross / open_trade["equity_at_entry"]
    new_equity = equity + gross
    trades.append(
        BTTrade(
            entry_time=open_trade["entry_time"].isoformat(),
            exit_time=exit_time.isoformat(),
            side=side.value,
            units=units,
            entry_price=entry_px,
            exit_price=exit_price,
            initial_stop=initial_stop,
            final_stop=final_stop,
            atr_at_entry=open_trade["atr_at_entry"],
            pnl=gross,
            pnl_pct=pnl_pct,
            r_multiple=r_mult,
            bars_held=open_trade["bars_held"],
            leverage_capped=open_trade["leverage_capped"],
            exit_reason=reason,
            reason=open_trade["reason"],
        )
    )
    equity_curve.append((exit_time.isoformat(), new_equity))
    return new_equity


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
            start=candles[0].time, end=candles[-1].time,
            instrument=settings.INSTRUMENT, bars=len(candles),
            trades=0, wins=0, losses=0, win_rate=0.0, avg_r=0.0,
            expectancy_pct=0.0, total_return_pct=0.0,
            max_drawdown_pct=0.0, sharpe=0.0, profit_factor=0.0,
            final_equity=final_equity, starting_equity=starting_equity,
        )

    pnls = np.array([t.pnl for t in trades])
    rs   = np.array([t.r_multiple for t in trades])
    pcts = np.array([t.pnl_pct for t in trades])

    wins = int((pnls > 0).sum())
    losses = int((pnls <= 0).sum())
    win_rate = 100.0 * wins / n
    avg_r = float(rs.mean())
    expectancy_pct = float(pcts.mean())
    total_ret = 100.0 * (final_equity - starting_equity) / starting_equity

    eq = np.array([e for _, e in equity_curve])
    peaks = np.maximum.accumulate(eq)
    dd = (peaks - eq) / peaks
    max_dd = float(dd.max() * 100.0) if len(dd) else 0.0

    days = max((candles[-1].time - candles[0].time).days, 1)
    trades_per_year = n * (365.0 / days)
    if pcts.std(ddof=0) > 0:
        sharpe = float(pcts.mean() / pcts.std(ddof=0) * math.sqrt(trades_per_year))
    else:
        sharpe = 0.0

    gross_win = float(pnls[pnls > 0].sum())
    gross_loss = float(-pnls[pnls < 0].sum())
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    return BacktestResult(
        start=candles[0].time, end=candles[-1].time,
        instrument=settings.INSTRUMENT, bars=len(candles),
        trades=n, wins=wins, losses=losses, win_rate=win_rate,
        avg_r=avg_r, expectancy_pct=expectancy_pct,
        total_return_pct=total_ret, max_drawdown_pct=max_dd,
        sharpe=sharpe, profit_factor=pf,
        final_equity=final_equity, starting_equity=starting_equity,
    )


def _diagnostics_dict(
    diag: BTDiagnostics,
    trades: list[BTTrade],
    spread_pips: float,
    slippage_pips: float,
) -> dict:
    durations = [t.bars_held for t in trades]
    avg_dur = float(np.mean(durations)) if durations else 0.0
    median_dur = float(np.median(durations)) if durations else 0.0

    pnls_sorted = sorted([t.pnl for t in trades], reverse=True)
    gross_profit = sum(p for p in pnls_sorted if p > 0)
    top5_sum = sum(p for p in pnls_sorted[:5] if p > 0)
    top5_pct = (100.0 * top5_sum / gross_profit) if gross_profit > 0 else 0.0

    monthly: dict[str, float] = defaultdict(float)
    yearly: dict[str, dict] = defaultdict(
        lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
    )
    for t in trades:
        ex = datetime.fromisoformat(t.exit_time)
        monthly[ex.strftime("%Y-%m")] += t.pnl
        y = ex.strftime("%Y")
        yearly[y]["pnl"] += t.pnl
        yearly[y]["trades"] += 1
        if t.pnl > 0:
            yearly[y]["wins"] += 1
        else:
            yearly[y]["losses"] += 1

    exit_reasons: dict[str, int] = defaultdict(int)
    for t in trades:
        exit_reasons[t.exit_reason] += 1

    # Friction tax metric: round-trip cost as % of initial stop distance.
    cost_pips_round_trip = spread_pips + 2.0 * slippage_pips
    pip_units = pip_size(settings.INSTRUMENT)
    stop_dists_pips = [
        abs(t.entry_price - t.initial_stop) / pip_units for t in trades
    ]
    avg_stop_pips = float(np.mean(stop_dists_pips)) if stop_dists_pips else 0.0
    if stop_dists_pips:
        per_trade_pcts = [
            100.0 * cost_pips_round_trip / d for d in stop_dists_pips if d > 0
        ]
        cost_pct_of_stop = float(np.mean(per_trade_pcts)) if per_trade_pcts else 0.0
    else:
        cost_pct_of_stop = 0.0

    return {
        "session_end_closes": diag.session_end_closes,
        "leverage_cap_attempts": diag.leverage_cap_attempts,
        "leverage_cap_binds": diag.leverage_cap_binds,
        "leverage_cap_pct": (
            100.0 * diag.leverage_cap_binds / diag.leverage_cap_attempts
            if diag.leverage_cap_attempts > 0 else 0.0
        ),
        "avg_bars_held": avg_dur,
        "median_bars_held": median_dur,
        "top5_winner_concentration_pct": top5_pct,
        "monthly_pnl": dict(monthly),
        "yearly": {y: dict(d) for y, d in yearly.items()},
        "skips": dict(diag.skips),
        "exit_reasons": dict(exit_reasons),
        "cost_pips_round_trip": cost_pips_round_trip,
        "avg_stop_distance_pips": avg_stop_pips,
        "cost_pct_of_stop": cost_pct_of_stop,
    }


def save_results(
    result: BacktestResult,
    trades: list[BTTrade],
    equity_curve: list[tuple[str, float]],
    diagnostics: dict,
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
    (folder / "diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, default=str)
    )
    return folder
