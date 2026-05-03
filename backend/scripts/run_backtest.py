"""Run the v1-B validation suite: in-sample, out-of-sample, friction shock,
report in the agreed order, then a short diagnosis."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from app.backtest import run_backtest, save_results
from app.config import settings
from app.models import Candle
from app.strategy import StrategyParams


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


def fmt_summary(label: str, r, diag: dict) -> str:
    return "\n".join([
        f"--- {label} ---",
        f"  Period      : {r.start} → {r.end}",
        f"  Bars        : {r.bars:,}",
        f"  Trades      : {r.trades}  W:{r.wins} / L:{r.losses}",
        f"  Win rate    : {r.win_rate:.2f}%",
        f"  Avg R       : {r.avg_r:+.3f}",
        f"  Expectancy  : {r.expectancy_pct:+.4f}% / trade",
        f"  Total return: {r.total_return_pct:+.2f}%",
        f"  Max DD      : {r.max_drawdown_pct:.2f}%",
        f"  Sharpe      : {r.sharpe:.2f}",
        f"  Profit fact : {r.profit_factor:.2f}",
        f"  Final eq    : ${r.final_equity:,.2f} (start ${r.starting_equity:,.2f})",
        f"  Avg dur     : {diag.get('avg_bars_held', 0):.1f} bars  "
        f"(median {diag.get('median_bars_held', 0):.0f})",
        f"  Avg stop    : {diag.get('avg_stop_distance_pips', 0):.1f} pips  "
        f"(round-trip cost {diag.get('cost_pips_round_trip', 0):.1f} pips = "
        f"{diag.get('cost_pct_of_stop', 0):.1f}% of stop)",
    ])


def diagnose(is_r, oos_r, fr_r, is_d, oos_d, fr_d) -> list[str]:
    msgs: list[str] = []

    is_pass_exp = is_r.expectancy_pct > 0
    is_pass_pf = is_r.profit_factor >= 1.1
    if not (is_pass_exp and is_pass_pf):
        msgs.append(
            f"FAIL IS gate — expectancy {is_r.expectancy_pct:+.4f}% (need >0), "
            f"PF {is_r.profit_factor:.2f} (need ≥1.1)."
        )

    if oos_r.trades < 30:
        msgs.append(
            f"OOS trade count {oos_r.trades} < 30 — comparison is noisy; "
            "treat as provisional."
        )

    def deg_pct(is_v: float, oos_v: float) -> float:
        if is_v == 0:
            return 0.0
        return 100.0 * (is_v - oos_v) / abs(is_v)

    deg_exp = deg_pct(is_r.expectancy_pct, oos_r.expectancy_pct)
    deg_pf = deg_pct(is_r.profit_factor, oos_r.profit_factor)
    dd_change = oos_r.max_drawdown_pct - is_r.max_drawdown_pct
    if deg_exp > 80 or deg_pf > 80:
        msgs.append(
            f"FAIL OOS degradation > 80% — exp_deg={deg_exp:.0f}%, "
            f"pf_deg={deg_pf:.0f}%, dd_change={dd_change:+.1f}pp."
        )

    if fr_r.profit_factor < 1.0:
        msgs.append(
            f"FAIL friction survival — PF after 2× costs = {fr_r.profit_factor:.2f}."
        )

    avg_dur = is_d.get("avg_bars_held", 0)
    if 0 < avg_dur < 3:
        msgs.append(
            f"Trades dying fast (avg {avg_dur:.1f} bars). Likely paying to "
            "probe breakouts, not harvesting trends."
        )

    sec = is_d.get("session_end_closes", 0)
    if is_r.trades > 0 and sec / is_r.trades > 0.5:
        msgs.append(
            f"{sec}/{is_r.trades} ({100 * sec / is_r.trades:.0f}%) closed by "
            "session-end forcing — intraday truncation dominates exits, "
            "thesis is half-tested. (Plan's prime suspect.)"
        )

    if not msgs:
        msgs.append(
            f"PASS all gates. IS exp={is_r.expectancy_pct:+.4f}%, "
            f"PF={is_r.profit_factor:.2f}; "
            f"OOS exp={oos_r.expectancy_pct:+.4f}%, PF={oos_r.profit_factor:.2f}; "
            f"friction PF={fr_r.profit_factor:.2f}."
        )
    return msgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--in-sample-pct", type=int, default=80)
    ap.add_argument("--label", default="v1B")
    args = ap.parse_args()

    instrument = settings.INSTRUMENT
    granularity = settings.GRANULARITY
    fname = f"{instrument}_{granularity}_{args.days}d.json"
    path = settings.historical_dir / fname
    if not path.exists():
        print(f"missing {path}", file=sys.stderr)
        print(f"run: python -m scripts.download_history --days {args.days}",
              file=sys.stderr)
        return 2

    candles = load_candles(path)
    n = len(candles)
    split = int(n * args.in_sample_pct / 100)
    print(f"Loaded {n:,} candles  IS={split:,}  OOS={n - split:,}\n")

    is_candles = candles[:split]
    oos_candles = candles[split:]

    is_result, is_trades, is_eq, is_diag = run_backtest(
        is_candles, starting_equity=args.equity, params=StrategyParams(),
    )
    oos_result, oos_trades, oos_eq, oos_diag = run_backtest(
        oos_candles, starting_equity=args.equity, params=StrategyParams(),
    )
    fr_result, fr_trades, fr_eq, fr_diag = run_backtest(
        candles, starting_equity=args.equity, params=StrategyParams(),
        spread_pips=1.0, slippage_pips=0.4,
    )

    save_results(is_result, is_trades, is_eq, is_diag, label=f"{args.label}_IS")
    save_results(oos_result, oos_trades, oos_eq, oos_diag, label=f"{args.label}_OOS")
    save_results(fr_result, fr_trades, fr_eq, fr_diag, label=f"{args.label}_FRICTION_2x")

    line = "=" * 68
    print(line)
    print(f"  v1-B Donchian breakout intraday — {instrument} {granularity}")
    print(line)

    # 1 + 2: IS / OOS full stats
    print(fmt_summary("IN-SAMPLE (80%)", is_result, is_diag))
    print()
    print(fmt_summary("OUT-OF-SAMPLE (20%)", oos_result, oos_diag))
    print()

    # 3: trade counts and skip counts
    print("--- Skip / safeguard counts ---")
    for label, r, d in [("IS", is_result, is_diag),
                        ("OOS", oos_result, oos_diag),
                        ("FULL+friction", fr_result, fr_diag)]:
        skips = ", ".join(
            f"{k.replace('skip_','')}={v}"
            for k, v in sorted(d.get("skips", {}).items())
        )
        print(
            f"  {label}: trades={r.trades}  "
            f"leverage_cap_binds={d.get('leverage_cap_binds', 0)}/"
            f"{d.get('leverage_cap_attempts', 0)} "
            f"({d.get('leverage_cap_pct', 0):.1f}%)  "
            f"session_end_closes={d.get('session_end_closes', 0)}"
        )
        if skips:
            print(f"        skips: {skips}")

    # 4: monthly P&L
    print("\n--- Monthly P&L (USD) ---")
    for label, d in [("IS", is_diag), ("OOS", oos_diag)]:
        mo = d.get("monthly_pnl", {})
        print(f"  {label}:")
        for k in sorted(mo.keys()):
            print(f"    {k}: ${mo[k]:+,.2f}")
        if not mo:
            print("    (no trades)")

    # 5: top-5 winner concentration
    print("\n--- Top-5 winner concentration ---")
    print(f"  IS : {is_diag.get('top5_winner_concentration_pct', 0):.1f}% of gross profit")
    print(f"  OOS: {oos_diag.get('top5_winner_concentration_pct', 0):.1f}% of gross profit")

    # 6: friction shock
    print()
    print(fmt_summary(
        "FRICTION SHOCK (full sample, 2× spread + 2× slippage)", fr_result, fr_diag
    ))
    print()

    # 7: diagnosis
    print(line)
    print("DIAGNOSIS")
    print(line)
    for m in diagnose(is_result, oos_result, fr_result,
                      is_diag, oos_diag, fr_diag):
        print(f"  • {m}")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
