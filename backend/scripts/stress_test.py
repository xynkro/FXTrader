"""Cross-instrument stress test: do our top strategies generalize, or
are we frame-locked to USD/JPY H1?

For each (strategy, instrument) pair: run 5y backtest with same engine,
same friction (default + 2x), same protocol (no-session-close as
validated). Output a heatmap-style table.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams


STRATEGIES_TO_TEST = ["pullback", "donchian", "liquidity_sweep", "engulfing_pivot"]
INSTRUMENTS_TO_TEST = ["USD_JPY", "EUR_USD", "GBP_USD", "GBP_JPY", "AUD_USD"]


def load_candles(instrument: str, granularity: str, days: int) -> list[Candle]:
    fname = f"{instrument}_{granularity}_{days}d.json"
    path = settings.historical_dir / fname
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


def annualised(total_pct: float, days: int) -> float:
    if days <= 0:
        return 0.0
    years = days / 365.0
    if years <= 0 or 1 + total_pct / 100.0 <= 0:
        return 0.0
    return ((1 + total_pct / 100.0) ** (1.0 / years) - 1.0) * 100.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1825)
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--in-sample-pct", type=int, default=80)
    args = ap.parse_args()

    cells: dict = {}      # cells[(strategy, instrument)] = result dict

    for instrument in INSTRUMENTS_TO_TEST:
        try:
            candles = load_candles(instrument, "H1", args.days)
        except FileNotFoundError:
            print(f"missing data for {instrument}", file=sys.stderr)
            continue

        # Set the right pip / quote conversion for this instrument
        settings.INSTRUMENT = instrument

        n = len(candles)
        split = int(n * args.in_sample_pct / 100)
        is_candles = candles[:split]
        oos_candles = candles[split:]
        days = (candles[-1].time - candles[0].time).days

        for strategy in STRATEGIES_TO_TEST:
            eval_fn = STRATEGIES[strategy]
            try:
                is_r, _, _, _ = run_backtest(
                    is_candles, starting_equity=args.equity,
                    params=StrategyParams(),
                    spread_pips=0.5, slippage_pips=0.2,
                    evaluate_fn=eval_fn,
                    force_close_at_session_end=False,
                )
                oos_r, _, _, _ = run_backtest(
                    oos_candles, starting_equity=args.equity,
                    params=StrategyParams(),
                    spread_pips=0.5, slippage_pips=0.2,
                    evaluate_fn=eval_fn,
                    force_close_at_session_end=False,
                )
                fr_r, _, _, _ = run_backtest(
                    candles, starting_equity=args.equity,
                    params=StrategyParams(),
                    spread_pips=1.0, slippage_pips=0.4,
                    evaluate_fn=eval_fn,
                    force_close_at_session_end=False,
                )
            except Exception as e:
                cells[(strategy, instrument)] = {"error": str(e)[:50]}
                print(f"  ERROR {strategy}/{instrument}: {e}", file=sys.stderr)
                continue

            cells[(strategy, instrument)] = {
                "trades": fr_r.trades,
                "is_pf": is_r.profit_factor,
                "oos_pf": oos_r.profit_factor,
                "fr_pf": fr_r.profit_factor,
                "is_ret": is_r.total_return_pct,
                "oos_ret": oos_r.total_return_pct,
                "fr_ret": fr_r.total_return_pct,
                "fr_ann": annualised(fr_r.total_return_pct, days),
                "fr_dd": fr_r.max_drawdown_pct,
                "is_n": is_r.trades, "oos_n": oos_r.trades,
            }
            print(
                f"  {strategy:<16} {instrument:<8} "
                f"IS PF={is_r.profit_factor:.2f}  "
                f"OOS PF={oos_r.profit_factor:.2f}  "
                f"FR PF={fr_r.profit_factor:.2f}  "
                f"FR ret={fr_r.total_return_pct:+.1f}%  "
                f"FR ann={annualised(fr_r.total_return_pct, days):.2f}%"
            )

    # ---- summary table ----
    print()
    print("=" * 96)
    print("  STRESS TEST — friction-shocked annualised return (%)")
    print("=" * 96)
    header = f"{'STRATEGY':<18}" + "".join(f"{i:>10}" for i in INSTRUMENTS_TO_TEST) + f"{'WINS':>8}"
    print(header)
    print("-" * len(header))
    wins_per_strat: dict = {s: 0 for s in STRATEGIES_TO_TEST}
    for s in STRATEGIES_TO_TEST:
        row = f"{s:<18}"
        for inst in INSTRUMENTS_TO_TEST:
            cell = cells.get((s, inst), {})
            if "error" in cell:
                row += f"{'ERR':>10}"
            elif not cell:
                row += f"{'—':>10}"
            else:
                row += f"{cell['fr_ann']:>+9.2f}%"
                if cell["fr_ann"] > 0:
                    wins_per_strat[s] += 1
        row += f"{wins_per_strat[s]:>5}/{len(INSTRUMENTS_TO_TEST)}"
        print(row)

    # ---- friction PF table ----
    print()
    print("=" * 96)
    print("  STRESS TEST — friction-shocked PF (>=1.0 = survives 2x costs)")
    print("=" * 96)
    print(header)
    print("-" * len(header))
    pass_per_strat: dict = {s: 0 for s in STRATEGIES_TO_TEST}
    for s in STRATEGIES_TO_TEST:
        row = f"{s:<18}"
        for inst in INSTRUMENTS_TO_TEST:
            cell = cells.get((s, inst), {})
            if not cell or "error" in cell:
                row += f"{'—':>10}"
            else:
                pf = cell["fr_pf"]
                marker = "✓" if pf >= 1.0 else "✗"
                row += f"{marker} {pf:>6.2f}  "
                if pf >= 1.0:
                    pass_per_strat[s] += 1
        row += f"{pass_per_strat[s]:>5}/{len(INSTRUMENTS_TO_TEST)}"
        print(row)

    # ---- per-instrument winner ----
    print()
    print("=" * 96)
    print("  PER-INSTRUMENT WINNER (highest friction-shocked annualised)")
    print("=" * 96)
    for inst in INSTRUMENTS_TO_TEST:
        candidates = []
        for s in STRATEGIES_TO_TEST:
            cell = cells.get((s, inst), {})
            if not cell or "error" in cell:
                continue
            candidates.append((cell["fr_ann"], cell["fr_pf"], s))
        if not candidates:
            print(f"  {inst:<10}: no data")
            continue
        candidates.sort(reverse=True)
        top = candidates[0]
        print(f"  {inst:<10}: {top[2]:<18} ann={top[0]:+.2f}%  PF={top[1]:.2f}")

    # save raw
    out_path = settings.backtest_dir / "stress_test_summary.json"
    save_data = {
        f"{s}|{i}": v for (s, i), v in cells.items()
    }
    out_path.write_text(json.dumps(save_data, indent=2, default=str))
    print(f"\nRaw cells saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
