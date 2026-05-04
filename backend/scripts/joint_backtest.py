"""Two-strategy joint backtest with formal risk budget split + conflict
resolution, used to test whether combining a validated edge (Pullback)
with a borderline edge (Liquidity Sweep) produces real diversification
versus dilution.

Pre-registered rules (locked before this run):

1. **Risk budget split:** strategy A gets `risk_a%`, strategy B gets
   `risk_b%`. Each independently sized via the engine's account-currency-
   aware position_size formula at signal time.
2. **Concurrency cap:** max 1 concurrent position PER STRATEGY (so up to
   2 simultaneous trades total, but never 2 by the same strategy).
3. **Signal conflict resolution:** if both strategies fire in the SAME
   bar, the strategy named in `priority_strategy` wins; the other is
   skipped (logged as `skipped_by_priority`). This avoids same-bar
   double-counting and prevents directionally-opposite simultaneous
   opens that would just pay spread for nothing.
4. **No session-end forced close** (matches the validated configuration
   from the robustness pack).
5. **Each strategy's cooldown is independent** — a Pullback stop-out
   doesn't put Sweep on cooldown.

Output is a comparison report plus per-strategy + joint trade lists.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from app.backtest import _apply_costs, BTTrade
from app.config import settings
from app.models import Candle, Side
from app.strategy import (
    STRATEGIES,
    StrategyParams,
    StrategyState,
    in_session,
    is_jpy_quote,
    pip_size,
    position_size,
)


# ----------------------------------------------------------------------
#  Joint backtester
# ----------------------------------------------------------------------
@dataclass
class StrategyLane:
    """Per-strategy state inside the joint backtester."""
    name: str
    eval_fn: Callable
    risk_pct: float                 # e.g. 0.25 for 0.25% per trade
    state: StrategyState = field(default_factory=StrategyState)
    pending_signal: Optional[object] = None
    open_trade: Optional[dict] = None
    trades: list = field(default_factory=list)
    skips: dict = field(default_factory=dict)


def _size_with_risk(
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float,
    instrument: Optional[str] = None,
    max_leverage: float = 30.0,
) -> tuple[int, bool]:
    """Position sizing for the joint test — same formula as position_size()
    but with an explicit risk_pct override (instead of reading
    settings.RISK_PER_TRADE_PCT)."""
    inst = instrument or settings.INSTRUMENT
    risk_acct = equity * (risk_pct / 100.0)
    distance = abs(entry - stop)
    if distance <= 0 or entry <= 0:
        return 0, False
    q2a = (1.0 / entry) if is_jpy_quote(inst) else 1.0
    risk_per_unit = distance * q2a
    if risk_per_unit <= 0:
        return 0, False
    risk_units = int(risk_acct / risk_per_unit)
    notional_per_unit = entry * q2a
    max_units = (
        int(max_leverage * equity / notional_per_unit)
        if notional_per_unit > 0 else 0
    )
    if risk_units > max_units:
        return max_units, True
    return max(risk_units, 0), False


def _close_lane_trade(
    lane: StrategyLane,
    exit_price: float,
    exit_time: datetime,
    reason: str,
    cumulative_equity: float,
) -> float:
    ot = lane.open_trade
    side = ot["side"]
    units = ot["units"]
    entry_px = ot["entry_price"]
    initial_stop = ot["initial_stop"]
    final_stop = ot["stop"]

    if side == Side.LONG:
        gross_quote = (exit_price - entry_px) * units
    else:
        gross_quote = (entry_px - exit_price) * units
    if is_jpy_quote(settings.INSTRUMENT):
        gross = gross_quote / exit_price
        planned_risk = abs(entry_px - initial_stop) * units / entry_px
    else:
        gross = gross_quote
        planned_risk = abs(entry_px - initial_stop) * units
    r_mult = gross / planned_risk if planned_risk > 0 else 0.0
    pnl_pct = 100.0 * gross / ot["equity_at_entry"]

    lane.trades.append(BTTrade(
        entry_time=ot["entry_time"].isoformat(),
        exit_time=exit_time.isoformat(),
        side=side.value,
        units=units,
        entry_price=entry_px,
        exit_price=exit_price,
        initial_stop=initial_stop,
        final_stop=final_stop,
        atr_at_entry=ot["atr_at_entry"],
        pnl=gross,
        pnl_pct=pnl_pct,
        r_multiple=r_mult,
        bars_held=ot["bars_held"],
        leverage_capped=ot["leverage_capped"],
        exit_reason=reason,
        reason=ot["reason"],
    ))
    return cumulative_equity + gross


def _record_skip(lane: StrategyLane, key: str) -> None:
    k = f"skip_{key}"
    lane.skips[k] = lane.skips.get(k, 0) + 1


def run_joint_backtest(
    candles: list[Candle],
    starting_equity: float,
    spread_pips: float,
    slippage_pips: float,
    eval_fn_a: Callable, name_a: str, risk_a: float,
    eval_fn_b: Callable, name_b: str, risk_b: float,
    priority_strategy: str,
    params: Optional[StrategyParams] = None,
) -> dict:
    if not candles:
        raise ValueError("no candles supplied")

    p = params or StrategyParams()
    lane_a = StrategyLane(
        name=name_a, eval_fn=eval_fn_a, risk_pct=risk_a,
        state=StrategyState(params=p),
    )
    lane_b = StrategyLane(
        name=name_b, eval_fn=eval_fn_b, risk_pct=risk_b,
        state=StrategyState(params=p),
    )
    lanes = [lane_a, lane_b]

    equity = starting_equity
    equity_curve = [(candles[0].time.isoformat(), equity)]
    overlap_count = 0          # # of bars where BOTH strategies fired
    priority_skips = 0          # # of times priority rule suppressed a signal

    for bar in candles:
        # === per-lane lifecycle ===
        for lane in lanes:
            ot = lane.open_trade

            # 1. Activate scheduled trail update from prior bar
            if ot is not None and ot.get("next_stop") is not None:
                ot["stop"] = ot["next_stop"]
                ot["next_stop"] = None

            # 2. Stop-out check
            exited_by_stop = False
            if ot is not None:
                side = ot["side"]
                stop = ot["stop"]
                hit = bar.low <= stop if side == Side.LONG else bar.high >= stop
                if hit:
                    exit_price = _apply_costs(
                        side, stop, "exit", spread_pips, slippage_pips
                    )
                    label = "trailing_stop" if ot.get("trailed") else "initial_stop"
                    equity = _close_lane_trade(
                        lane, exit_price, bar.time, label, equity
                    )
                    equity_curve.append((bar.time.isoformat(), equity))
                    if side == Side.LONG:
                        lane.state.long_cooldown = lane.state.params.cooldown_bars
                    else:
                        lane.state.short_cooldown = lane.state.params.cooldown_bars
                    lane.open_trade = None
                    exited_by_stop = True

            # 3. Activate pending entry at this bar's open
            if lane.open_trade is None and lane.pending_signal is not None:
                sig = lane.pending_signal
                # Skip pending if this bar is OOS (signal-bar was at session edge)
                if not in_session(bar.time):
                    lane.pending_signal = None
                else:
                    fill_price = _apply_costs(
                        sig.side, bar.open, "entry", spread_pips, slippage_pips
                    )
                    stop_dist_sig = sig.stop_distance
                    if sig.side == Side.LONG:
                        initial_stop = fill_price - stop_dist_sig
                    else:
                        initial_stop = fill_price + stop_dist_sig
                    units, capped = _size_with_risk(
                        equity, fill_price, initial_stop,
                        risk_pct=lane.risk_pct,
                    )
                    if units > 0:
                        lane.open_trade = {
                            "side": sig.side,
                            "entry_time": bar.time,
                            "entry_price": fill_price,
                            "initial_stop": initial_stop,
                            "stop": initial_stop,
                            "next_stop": None,
                            "atr_at_entry": sig.atr,
                            "stop_distance": stop_dist_sig,
                            "units": units,
                            "leverage_capped": capped,
                            "equity_at_entry": equity,
                            "ext": bar.high if sig.side == Side.LONG else bar.low,
                            "bars_held": 0,
                            "reason": sig.reason,
                            "trailed": False,
                        }
                    lane.pending_signal = None

            # 4. Update trail extreme + bars_held
            ot = lane.open_trade
            if ot is not None:
                if ot["side"] == Side.LONG:
                    ot["ext"] = max(ot["ext"], bar.high)
                else:
                    ot["ext"] = min(ot["ext"], bar.low)
                ot["bars_held"] += 1

            # 5. (No session-end forced close — matches validated config)

            # 6. Add bar to state, decrement cooldowns
            lane.state.add(bar)
            lane.state.decrement_cooldowns()

        # === 7. Signal evaluation with conflict resolution ===
        # Evaluate both lanes when their lane is flat AND in-session.
        sigs = {}
        for lane in lanes:
            if lane.open_trade is None and lane.pending_signal is None and in_session(bar.time):
                s = lane.eval_fn(lane.state, equity, diagnostics=lane.skips)
                if s is not None:
                    sigs[lane.name] = s

        # Apply priority rule: if both fired this bar, only priority wins
        if len(sigs) == 2:
            overlap_count += 1
            losers = [n for n in sigs if n != priority_strategy]
            for losing_name in losers:
                priority_skips += 1
                losing_lane = lane_a if losing_name == lane_a.name else lane_b
                _record_skip(losing_lane, "skipped_by_priority")
                sigs.pop(losing_name)

        # Stash surviving signals as pending for next bar's open fill
        for lane in lanes:
            if lane.name in sigs:
                lane.pending_signal = sigs[lane.name]

        # 8. Compute next-bar trail stop per open trade
        for lane in lanes:
            ot = lane.open_trade
            if ot is None:
                continue
            stop_dist = ot["stop_distance"]
            ext = ot["ext"]
            if ot["side"] == Side.LONG:
                trail = ext - stop_dist
                if trail > ot["stop"]:
                    ot["next_stop"] = trail
                    ot["trailed"] = True
            else:
                trail = ext + stop_dist
                if trail < ot["stop"]:
                    ot["next_stop"] = trail
                    ot["trailed"] = True

    # Close dangling trades at last bar's close
    for lane in lanes:
        if lane.open_trade is not None:
            side = lane.open_trade["side"]
            exit_price = _apply_costs(
                side, candles[-1].close, "exit", spread_pips, slippage_pips
            )
            equity = _close_lane_trade(
                lane, exit_price, candles[-1].time, "forced_eod", equity
            )
            equity_curve.append((candles[-1].time.isoformat(), equity))

    return {
        "equity_curve": equity_curve,
        "starting_equity": starting_equity,
        "final_equity": equity,
        "lane_a_name": lane_a.name,
        "lane_a_trades": lane_a.trades,
        "lane_a_skips": lane_a.skips,
        "lane_b_name": lane_b.name,
        "lane_b_trades": lane_b.trades,
        "lane_b_skips": lane_b.skips,
        "overlap_count": overlap_count,
        "priority_skips": priority_skips,
        "candles": len(candles),
        "start": candles[0].time,
        "end": candles[-1].time,
    }


# ----------------------------------------------------------------------
#  Stats + reporting
# ----------------------------------------------------------------------
def lane_stats(trades: list[BTTrade], starting_equity: float) -> dict:
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "expectancy_pct": 0.0, "pf": 0.0, "max_dd_pct": 0.0,
            "total_return_pct": 0.0, "avg_dur": 0.0, "median_dur": 0.0,
        }
    pnls = np.array([t.pnl for t in trades])
    pcts = np.array([t.pnl_pct for t in trades])
    wins = int((pnls > 0).sum()); losses = int((pnls <= 0).sum())
    durations = [t.bars_held for t in trades]
    cumeq = starting_equity + pnls.cumsum()
    peaks = np.maximum.accumulate(np.concatenate([[starting_equity], cumeq]))
    eq = np.concatenate([[starting_equity], cumeq])
    dd = (peaks - eq) / peaks
    gross_win = float(pnls[pnls > 0].sum())
    gross_loss = float(-pnls[pnls < 0].sum())
    return {
        "trades": len(trades),
        "wins": wins, "losses": losses,
        "win_rate": 100.0 * wins / len(trades),
        "expectancy_pct": float(pcts.mean()),
        "pf": gross_win / gross_loss if gross_loss > 0 else float("inf"),
        "max_dd_pct": float(dd.max() * 100.0),
        "total_return_pct": 100.0 * float(pnls.sum()) / starting_equity,
        "avg_dur": float(np.mean(durations)),
        "median_dur": float(np.median(durations)),
    }


def joint_stats(
    equity_curve: list, starting_equity: float, final_equity: float
) -> dict:
    eq = np.array([e for _, e in equity_curve])
    peaks = np.maximum.accumulate(eq)
    dd = (peaks - eq) / peaks
    return {
        "total_return_pct": 100.0 * (final_equity - starting_equity) / starting_equity,
        "max_dd_pct": float(dd.max() * 100.0) if len(dd) else 0.0,
        "final_equity": final_equity,
    }


def yearly_breakdown(trades: list[BTTrade]) -> dict:
    out: dict = defaultdict(lambda: {"pnl": 0.0, "n": 0})
    for t in trades:
        y = datetime.fromisoformat(t.exit_time).strftime("%Y")
        out[y]["pnl"] += t.pnl
        out[y]["n"] += 1
    return {k: dict(v) for k, v in out.items()}


def annualised_return(total_pct: float, days: int) -> float:
    if days <= 0:
        return 0.0
    years = days / 365.0
    if years <= 0:
        return 0.0
    return ((1 + total_pct / 100.0) ** (1.0 / years) - 1.0) * 100.0


def returns_correlation(
    a_trades: list[BTTrade], b_trades: list[BTTrade]
) -> dict:
    """Per-month aggregated P&L correlation. We aggregate by year-month
    so isolated trades in different months don't artificially align."""
    months_a: dict = defaultdict(float)
    months_b: dict = defaultdict(float)
    for t in a_trades:
        m = datetime.fromisoformat(t.exit_time).strftime("%Y-%m")
        months_a[m] += t.pnl
    for t in b_trades:
        m = datetime.fromisoformat(t.exit_time).strftime("%Y-%m")
        months_b[m] += t.pnl
    common = sorted(set(months_a.keys()) & set(months_b.keys()))
    if len(common) < 5:
        return {"n_months": len(common), "corr_full": None,
                "corr_2022_2023": None, "corr_2024_2025": None}
    a = np.array([months_a[m] for m in common])
    b = np.array([months_b[m] for m in common])
    full = float(np.corrcoef(a, b)[0, 1])

    def by_period(prefix_set: set) -> Optional[float]:
        pairs = [(months_a[m], months_b[m])
                 for m in common if m[:4] in prefix_set]
        if len(pairs) < 5:
            return None
        aa = np.array([x[0] for x in pairs])
        bb = np.array([x[1] for x in pairs])
        return float(np.corrcoef(aa, bb)[0, 1])

    return {
        "n_months": len(common),
        "corr_full": full,
        "corr_2022_2023": by_period({"2022", "2023"}),
        "corr_2024_2025": by_period({"2024", "2025"}),
    }


def fmt_pct(x: float, plus: bool = True) -> str:
    s = "+" if plus and x >= 0 else ""
    return f"{s}{x:.2f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1825)
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--instrument", default=None)
    ap.add_argument("--granularity", default=None)
    ap.add_argument("--spread-pips", type=float, default=0.5)
    ap.add_argument("--slippage-pips", type=float, default=0.2)
    ap.add_argument("--strategy-a", default="pullback")
    ap.add_argument("--strategy-b", default="liquidity_sweep")
    ap.add_argument("--risk-a", type=float, default=0.25)
    ap.add_argument("--risk-b", type=float, default=0.25)
    ap.add_argument("--priority", default="pullback")
    args = ap.parse_args()

    if args.instrument:
        settings.INSTRUMENT = args.instrument
    if args.granularity:
        settings.GRANULARITY = args.granularity

    instrument = settings.INSTRUMENT
    granularity = settings.GRANULARITY
    fname = f"{instrument}_{granularity}_{args.days}d.json"
    path = settings.historical_dir / fname
    if not path.exists():
        print(f"missing {path}", file=sys.stderr)
        return 2

    raw = json.loads(path.read_text())
    candles = [
        Candle(
            time=datetime.fromisoformat(c["time"]),
            open=c["open"], high=c["high"],
            low=c["low"], close=c["close"],
            volume=c["volume"],
        )
        for c in raw
    ]

    eval_a = STRATEGIES[args.strategy_a]
    eval_b = STRATEGIES[args.strategy_b]

    line = "=" * 78

    # --- Pullback alone (full risk budget = 0.5%) ---
    settings.RISK_PER_TRADE_PCT = 0.5
    from app.backtest import run_backtest
    alone_default, alone_t, alone_eq, alone_d = run_backtest(
        candles, starting_equity=args.equity, params=StrategyParams(),
        spread_pips=args.spread_pips, slippage_pips=args.slippage_pips,
        evaluate_fn=eval_a, force_close_at_session_end=False,
    )
    alone_friction, alone_t_fr, alone_eq_fr, alone_d_fr = run_backtest(
        candles, starting_equity=args.equity, params=StrategyParams(),
        spread_pips=2.0 * args.spread_pips,
        slippage_pips=2.0 * args.slippage_pips,
        evaluate_fn=eval_a, force_close_at_session_end=False,
    )

    # --- Joint at default friction ---
    joint_def = run_joint_backtest(
        candles, args.equity, args.spread_pips, args.slippage_pips,
        eval_a, args.strategy_a, args.risk_a,
        eval_b, args.strategy_b, args.risk_b,
        priority_strategy=args.priority,
    )
    a_def_stats = lane_stats(joint_def["lane_a_trades"], args.equity)
    b_def_stats = lane_stats(joint_def["lane_b_trades"], args.equity)
    j_def_stats = joint_stats(joint_def["equity_curve"], args.equity,
                               joint_def["final_equity"])
    corr_def = returns_correlation(
        joint_def["lane_a_trades"], joint_def["lane_b_trades"]
    )

    # --- Joint at 2x friction ---
    joint_fr = run_joint_backtest(
        candles, args.equity,
        2.0 * args.spread_pips, 2.0 * args.slippage_pips,
        eval_a, args.strategy_a, args.risk_a,
        eval_b, args.strategy_b, args.risk_b,
        priority_strategy=args.priority,
    )
    a_fr_stats = lane_stats(joint_fr["lane_a_trades"], args.equity)
    b_fr_stats = lane_stats(joint_fr["lane_b_trades"], args.equity)
    j_fr_stats = joint_stats(joint_fr["equity_curve"], args.equity,
                              joint_fr["final_equity"])

    days = (candles[-1].time - candles[0].time).days

    # ----------------- Report -----------------
    print(line)
    print(f"  JOINT BACKTEST — {instrument} {granularity}, {days} days")
    print(f"  A = {args.strategy_a} (priority, risk {args.risk_a}%)")
    print(f"  B = {args.strategy_b} (risk {args.risk_b}%)")
    print(f"  Costs: spread={args.spread_pips}p slip={args.slippage_pips}p")
    print(line)

    # === SOLO BASELINE ===
    print("\n--- BASELINE: Pullback alone (risk 0.5%) ---")
    print(f"  Default friction : trades={alone_default.trades}  "
          f"PF={alone_default.profit_factor:.2f}  "
          f"return={alone_default.total_return_pct:+.2f}%  "
          f"DD={alone_default.max_drawdown_pct:.2f}%  "
          f"ann={annualised_return(alone_default.total_return_pct, days):.2f}%")
    print(f"  2x friction      : trades={alone_friction.trades}  "
          f"PF={alone_friction.profit_factor:.2f}  "
          f"return={alone_friction.total_return_pct:+.2f}%  "
          f"DD={alone_friction.max_drawdown_pct:.2f}%  "
          f"ann={annualised_return(alone_friction.total_return_pct, days):.2f}%")

    # === COMBO at default friction ===
    print("\n--- COMBO: Pullback (0.25%) + Sweep (0.25%) ---")
    print(f"  Lane A ({args.strategy_a:>15}): trades={a_def_stats['trades']:>4}  "
          f"PF={a_def_stats['pf']:.2f}  "
          f"return={a_def_stats['total_return_pct']:+.2f}%  "
          f"win%={a_def_stats['win_rate']:.1f}  "
          f"avg_dur={a_def_stats['avg_dur']:.1f}")
    print(f"  Lane B ({args.strategy_b:>15}): trades={b_def_stats['trades']:>4}  "
          f"PF={b_def_stats['pf']:.2f}  "
          f"return={b_def_stats['total_return_pct']:+.2f}%  "
          f"win%={b_def_stats['win_rate']:.1f}  "
          f"avg_dur={b_def_stats['avg_dur']:.1f}")
    print(f"  Joint (default)  : trades={a_def_stats['trades']+b_def_stats['trades']}  "
          f"return={j_def_stats['total_return_pct']:+.2f}%  "
          f"DD={j_def_stats['max_dd_pct']:.2f}%  "
          f"ann={annualised_return(j_def_stats['total_return_pct'], days):.2f}%")

    # === COMBO at 2x friction ===
    print("\n--- COMBO at 2x friction (the binding test) ---")
    print(f"  Lane A ({args.strategy_a:>15}): PF={a_fr_stats['pf']:.2f}  "
          f"return={a_fr_stats['total_return_pct']:+.2f}%")
    print(f"  Lane B ({args.strategy_b:>15}): PF={b_fr_stats['pf']:.2f}  "
          f"return={b_fr_stats['total_return_pct']:+.2f}%")
    print(f"  Joint (2x)       : return={j_fr_stats['total_return_pct']:+.2f}%  "
          f"DD={j_fr_stats['max_dd_pct']:.2f}%  "
          f"ann={annualised_return(j_fr_stats['total_return_pct'], days):.2f}%")

    # === Overlap & priority rule activity ===
    print("\n--- Signal interaction ---")
    print(f"  Bars where BOTH lanes fired: {joint_def['overlap_count']}")
    print(f"  Suppressed by priority rule  : {joint_def['priority_skips']}")
    a_solo = alone_default.trades
    a_combo = a_def_stats['trades']
    print(f"  {args.strategy_a} trade count: solo={a_solo}, in combo={a_combo}  "
          f"(delta={a_combo - a_solo:+d}; loss to crowding/risk_split)")

    # === Correlation ===
    print("\n--- Lane return correlation (per-month P&L) ---")
    print(f"  Months where both produced trades: {corr_def['n_months']}")
    if corr_def['corr_full'] is not None:
        print(f"  Full sample : {corr_def['corr_full']:+.3f}")
    if corr_def['corr_2022_2023'] is not None:
        print(f"  2022–2023   : {corr_def['corr_2022_2023']:+.3f}")
    if corr_def['corr_2024_2025'] is not None:
        print(f"  2024–2025   : {corr_def['corr_2024_2025']:+.3f}")

    # === Yearly breakdown (joint) ===
    print("\n--- Yearly P&L (combined lanes, default friction) ---")
    yearly_a = yearly_breakdown(joint_def["lane_a_trades"])
    yearly_b = yearly_breakdown(joint_def["lane_b_trades"])
    all_years = sorted(set(yearly_a.keys()) | set(yearly_b.keys()))
    for y in all_years:
        a = yearly_a.get(y, {"pnl": 0, "n": 0})
        b = yearly_b.get(y, {"pnl": 0, "n": 0})
        total = a["pnl"] + b["pnl"]
        print(f"  {y}: combined ${total:+,.2f}  "
              f"[A {a['n']}t ${a['pnl']:+,.2f}, "
              f"B {b['n']}t ${b['pnl']:+,.2f}]")

    # === DECISION ===
    print("\n" + line)
    print("DECISION (vs pre-registered bar)")
    print(line)

    alone_ann = annualised_return(alone_friction.total_return_pct, days)
    combo_ann = annualised_return(j_fr_stats["total_return_pct"], days)
    rel_uplift = (
        100.0 * (combo_ann - alone_ann) / abs(alone_ann)
        if alone_ann != 0 else 0.0
    )
    dd_change = j_fr_stats["max_dd_pct"] - alone_friction.max_drawdown_pct

    print(f"  Pullback-alone friction-shocked annualised : {alone_ann:.2f}%")
    print(f"  Joint friction-shocked annualised          : {combo_ann:.2f}%")
    print(f"  Relative uplift                            : {rel_uplift:+.1f}%")
    print(f"  Max DD: alone {alone_friction.max_drawdown_pct:.2f}% → "
          f"combo {j_fr_stats['max_dd_pct']:.2f}% (Δ {dd_change:+.2f} pp)")

    bar_uplift = 15.0
    pass_uplift = rel_uplift >= bar_uplift
    pass_dd = dd_change <= 1.0      # combo not materially worse
    if pass_uplift and pass_dd:
        verdict = "PASS — combo clears 15% uplift bar AND DD not worse"
    elif rel_uplift > 0 and dd_change < 0:
        verdict = (
            f"BORDERLINE — uplift {rel_uplift:+.1f}% < 15% bar but "
            "DD reduced; trade-off, not free win"
        )
    else:
        verdict = (
            "FAIL — combo does not meaningfully improve on alone. "
            "Operational complexity not justified."
        )
    print(f"  Verdict                                    : {verdict}")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
