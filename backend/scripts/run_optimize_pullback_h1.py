"""Walk-forward parameter optimization for Pullback on USD_JPY H1.

Mirror of run_optimize_pullback_m15.py but on H1 data (5y, 31k bars).
Methodology: optimize on oldest 80% (IS), evaluate on held-out 20% (OOS),
report the IS→OOS gap as the data-mining tax.

Same friction, same equity, same evaluation rules as the deployed engine.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from datetime import datetime
from itertools import product
from pathlib import Path

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams


SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.4
EQUITY = 110_000.0

# Grid sized for H1 — sma_long values cluster around the deployed 100,
# but with reasonable span. Same total dimensionality as the M15 grid
# so the search space is comparable.
GRID = {
    "sma_long":             [50, 75, 100, 150, 200],
    "sma_short":            [10, 15, 20, 30],
    "pullback_lookback":    [2, 3, 5],
    "trend_slope_lookback": [10, 20],
    "atr_period":           [14, 21],
    "stop_atr_mult":        [1.5, 2.0, 2.5, 3.0],
    "min_atr_pips":         [1.0, 3.0, 5.0],
}


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


def annualised(start, end, eq0, eq1):
    seconds = (end - start).total_seconds()
    years = max(seconds / (365.25 * 24 * 3600.0), 1e-6)
    if eq1 / eq0 <= 0:
        return -100.0
    return ((eq1 / eq0) ** (1.0 / years) - 1.0) * 100.0


def evaluate(candles: list[Candle], params: StrategyParams) -> dict:
    eval_fn = STRATEGIES["pullback"]
    r, _, _, _ = run_backtest(
        candles, starting_equity=EQUITY, params=params,
        spread_pips=SPREAD_PIPS, slippage_pips=SLIPPAGE_PIPS,
        evaluate_fn=eval_fn,
        signal_in_session_only=True,
        force_close_at_session_end=False,
        macro_features=None,
    )
    cagr = annualised(candles[0].time, candles[-1].time,
                      r.starting_equity, r.final_equity)
    return {
        "trades": r.trades,
        "win_rate_pct": round(r.win_rate, 1),
        "expectancy_pct": round(r.expectancy_pct, 4),
        "cagr_pct": round(cagr, 2),
        "max_dd_pct": round(r.max_drawdown_pct, 2),
        "sharpe": round(r.sharpe, 2),
        "profit_factor": round(r.profit_factor, 2),
    }


def main() -> int:
    path = settings.historical_dir / "USD_JPY_H1_1825d.json"
    if not path.exists():
        print(f"missing {path}")
        return 2
    print(f"Loading {path.name}…")
    candles = load_candles(path)
    print(f"  {len(candles):,} bars  "
          f"{candles[0].time.date()} → {candles[-1].time.date()}\n")

    n = len(candles)
    split = int(n * 0.80)
    is_candles = candles[:split]
    oos_candles = candles[split:]

    is_years = (is_candles[-1].time - is_candles[0].time).total_seconds() / (365.25 * 86400.0)
    oos_years = (oos_candles[-1].time - oos_candles[0].time).total_seconds() / (365.25 * 86400.0)
    print(f"  IS  : {len(is_candles):,} bars, "
          f"{is_candles[0].time.date()} → {is_candles[-1].time.date()}  ({is_years:.2f}y)")
    print(f"  OOS : {len(oos_candles):,} bars, "
          f"{oos_candles[0].time.date()} → {oos_candles[-1].time.date()}  ({oos_years:.2f}y)")
    print(f"  Held-out OOS is INVISIBLE to the optimizer.\n")

    p_default = StrategyParams()

    print("=== Baseline (default Pullback params) ===")
    base_is = evaluate(is_candles, p_default)
    base_oos = evaluate(oos_candles, p_default)
    print(f"  IS : {base_is}")
    print(f"  OOS: {base_oos}\n")

    print("=== Sweep on IS only ===")
    keys = list(GRID.keys())
    grid_values = [GRID[k] for k in keys]
    total_combos = 1
    for v in grid_values:
        total_combos *= len(v)
    print(f"  {total_combos} parameter combinations to evaluate on IS…")

    results: list[dict] = []
    seen = 0
    for combo in product(*grid_values):
        params = replace(p_default, **dict(zip(keys, combo)))
        try:
            m = evaluate(is_candles, params)
        except Exception:
            seen += 1
            continue
        seen += 1
        if m["trades"] < 50:  # H1 has fewer trades than M15 — lower floor
            continue
        results.append({"params": dict(zip(keys, combo)), "is_metrics": m})
        if seen % 100 == 0:
            print(f"    progress {seen}/{total_combos}…")
    print(f"  {len(results):,} viable combos (≥50 trades) of {total_combos}\n")

    K = 10
    results.sort(key=lambda r: r["is_metrics"]["sharpe"], reverse=True)
    top = results[:K]

    print(f"=== Top-{K} parameter sets by IS Sharpe — and their OOS reality ===\n")
    print(f"  {'rank':4s} {'IS Sharpe':>9s} {'IS CAGR':>8s} {'IS DD':>7s}  "
          f"{'OOS Sharpe':>10s} {'OOS CAGR':>9s} {'OOS DD':>8s}  "
          f"{'IS→OOS Δ':>10s}  params")
    print(f"  {'-'*4} {'-'*9} {'-'*8} {'-'*7}  {'-'*10} {'-'*9} {'-'*8}  {'-'*10}  ------")

    final_rows = []
    for i, r in enumerate(top, 1):
        params = replace(p_default, **r["params"])
        oos_m = evaluate(oos_candles, params)
        is_m = r["is_metrics"]
        delta_sharpe = round(is_m["sharpe"] - oos_m["sharpe"], 2)
        final_rows.append({
            "rank": i,
            "params": r["params"],
            "is": is_m,
            "oos": oos_m,
            "is_oos_sharpe_delta": delta_sharpe,
        })
        params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
        print(f"  {i:>4d} {is_m['sharpe']:>+9.2f} "
              f"{is_m['cagr_pct']:>+7.2f}% {is_m['max_dd_pct']:>6.2f}%  "
              f"{oos_m['sharpe']:>+10.2f} {oos_m['cagr_pct']:>+8.2f}% {oos_m['max_dd_pct']:>7.2f}%  "
              f"{delta_sharpe:>+9.2f}   {params_str[:60]}")

    print()
    print("=== Population stats ===")
    median_is_sharpe = sorted([r["is_metrics"]["sharpe"] for r in results])[len(results) // 2]
    print(f"  Total viable combos      : {len(results)} of {total_combos}")
    print(f"  Median IS Sharpe         : {median_is_sharpe}")
    print(f"  Default IS Sharpe        : {base_is['sharpe']}")
    print(f"  Default OOS Sharpe       : {base_oos['sharpe']}")
    print(f"  Best IS Sharpe found     : {top[0]['is_metrics']['sharpe']}")
    print(f"  Best's OOS Sharpe        : {final_rows[0]['oos']['sharpe']}")

    out = {
        "strategy": "pullback",
        "instrument": "USD_JPY",
        "granularity": "H1",
        "spread_pips": SPREAD_PIPS,
        "slippage_pips": SLIPPAGE_PIPS,
        "is_window": [is_candles[0].time.isoformat(), is_candles[-1].time.isoformat()],
        "oos_window": [oos_candles[0].time.isoformat(), oos_candles[-1].time.isoformat()],
        "default_params": asdict(p_default),
        "default_is": base_is,
        "default_oos": base_oos,
        "viable_combos": len(results),
        "total_combos": total_combos,
        "topk_by_is_sharpe": final_rows,
    }
    out_path = settings.backtest_dir / "pullback_h1_optimization.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
