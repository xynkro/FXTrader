"""Walk-forward stability test (Robustness Pack — Test 2).

Splits the input series into rolling fixed-length windows stepped forward
in time and runs the strategy on each window as a standalone backtest.
No parameter refitting per window — this measures pure consistency, not
adaptive optimization.

Pre-registered pass criteria (per docs/robustness-pack-spec.md):
  - >=70% of windows show positive expectancy (>=10 of 14 for default config)
  - Median PF across windows >= 1.05
  - No single window contributes >50% of cumulative across-windows P&L

Usage:
  python -m scripts.walk_forward --days 1825 --instrument USD_JPY \
      --granularity H1 --strategy pullback --label robust_T2 \
      [--no-session-close]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams


def load_candles(path: Path) -> list[Candle]:
    raw = json.loads(path.read_text())
    return [
        Candle(
            time=datetime.fromisoformat(c["time"]),
            open=c["open"], high=c["high"],
            low=c["low"], close=c["close"],
            volume=c["volume"],
        )
        for c in raw
    ]


def make_windows(candles: list[Candle], window_months: int, step_months: int):
    """Yield (start, end, sliced_candles) for each rolling window."""
    if not candles:
        return
    first = candles[0].time
    last = candles[-1].time
    one_month = timedelta(days=30)  # approximate; fine for windowing
    start = first
    while start + window_months * one_month <= last + timedelta(days=15):
        end = start + window_months * one_month
        sliced = [c for c in candles if start <= c.time < end]
        if len(sliced) > 100:        # skip tiny windows
            yield start, end, sliced
        start = start + step_months * one_month


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1825)
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--instrument", default=None)
    ap.add_argument("--granularity", default=None)
    ap.add_argument("--spread-pips", type=float, default=0.5)
    ap.add_argument("--slippage-pips", type=float, default=0.2)
    ap.add_argument("--strategy", choices=sorted(STRATEGIES.keys()),
                    default="pullback")
    ap.add_argument("--label", default="walkforward")
    ap.add_argument("--window-months", type=int, default=12)
    ap.add_argument("--step-months", type=int, default=3)
    ap.add_argument("--no-session-close", action="store_true")
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

    candles = load_candles(path)
    eval_fn = STRATEGIES[args.strategy]

    line = "=" * 78
    label = f"{args.strategy} {'(no-session-close)' if args.no_session_close else '(default)'}"
    print(line)
    print(f"  Walk-forward — {instrument} {granularity}  strategy={label}")
    print(f"  Window={args.window_months}mo step={args.step_months}mo "
          f"costs spread={args.spread_pips}p slip={args.slippage_pips}p")
    print(line)

    rows = []
    for start, end, sliced in make_windows(candles, args.window_months,
                                            args.step_months):
        result, trades, eq, diag = run_backtest(
            sliced, starting_equity=args.equity, params=StrategyParams(),
            spread_pips=args.spread_pips, slippage_pips=args.slippage_pips,
            evaluate_fn=eval_fn,
            force_close_at_session_end=not args.no_session_close,
        )
        rows.append({
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "trades": result.trades,
            "wins": result.wins,
            "losses": result.losses,
            "win_rate": result.win_rate,
            "expectancy": result.expectancy_pct,
            "pf": result.profit_factor,
            "total_return": result.total_return_pct,
            "max_dd": result.max_drawdown_pct,
            "pnl_dollars": result.final_equity - result.starting_equity,
        })

    # ---- per-window table ----
    print(f"  {'window':<25} {'trades':>6} {'WR':>6} {'PF':>5} "
          f"{'exp%':>7} {'ret%':>7} {'DD%':>6} {'P&L$':>10}")
    print(f"  {'-'*25} {'-'*6} {'-'*6} {'-'*5} {'-'*7} {'-'*7} {'-'*6} {'-'*10}")
    for r in rows:
        pf_str = f"{r['pf']:.2f}" if r['pf'] != float("inf") else "inf"
        print(f"  {r['start']} → {r['end']:<10} "
              f"{r['trades']:>6} {r['win_rate']:>5.1f}% "
              f"{pf_str:>5} {r['expectancy']:>+7.4f} "
              f"{r['total_return']:>+7.2f} {r['max_dd']:>6.2f} "
              f"{r['pnl_dollars']:>+10.2f}")

    # ---- aggregates ----
    n_windows = len(rows)
    if n_windows == 0:
        print("\nNo windows produced.")
        return 0

    pos_exp = sum(1 for r in rows if r["expectancy"] > 0)
    pfs = [r["pf"] for r in rows if r["pf"] not in (float("inf"), 0)]
    med_pf = statistics.median(pfs) if pfs else 0.0
    pnls = [r["pnl_dollars"] for r in rows]
    cumulative = sum(pnls)
    max_single = max(abs(p) for p in pnls) if pnls else 0.0
    biggest_share = (
        100.0 * max_single / abs(cumulative) if cumulative != 0 else float("inf")
    )

    print("\n--- Aggregates ---")
    print(f"  Windows                : {n_windows}")
    print(f"  Positive-expectancy    : {pos_exp}/{n_windows} "
          f"({100*pos_exp/n_windows:.0f}%)  [pass bar: ≥70%]")
    print(f"  Median PF              : {med_pf:.3f}  [pass bar: ≥1.05]")
    print(f"  Cumulative P&L (sum)   : ${cumulative:+,.2f}")
    print(f"  Biggest window |P&L|   : ${max_single:,.2f}  ({biggest_share:.1f}% "
          f"of cumulative)  [fail if >50%]")

    # ---- diagnosis ----
    print()
    msgs = []
    pct_pos = 100.0 * pos_exp / n_windows
    if pct_pos < 70:
        msgs.append(
            f"FAIL positive-expectancy windows: {pct_pos:.0f}% < 70%."
        )
    if med_pf < 1.05:
        msgs.append(f"FAIL median PF: {med_pf:.3f} < 1.05.")
    if biggest_share > 50:
        msgs.append(
            f"FAIL concentration: biggest window = {biggest_share:.0f}% "
            "of cumulative P&L (>50%)."
        )
    if not msgs:
        msgs.append(
            f"PASS walk-forward: {pos_exp}/{n_windows} positive, median "
            f"PF={med_pf:.3f}, biggest share={biggest_share:.0f}%."
        )

    print("=" * 78)
    print("DIAGNOSIS")
    print("=" * 78)
    for m in msgs:
        print(f"  • {m}")
    print("=" * 78)

    # save artifacts
    out_dir = settings.backtest_dir / f"{args.label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "windows.json").write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
