"""Cross-instrument generalization test for the deployed Pullback H1.

Question: does the live strategy's edge generalize across instruments,
or is it specifically a USD/JPY (BoJ-driven trend) edge?

Method: Pullback H1 with DEPLOYED DEFAULT parameters (no optimization,
no per-instrument tweaking), friction-shocked, run on every H1 5y file
available. Group by instrument family for interpretation.

This test became valid TODAY after the pip_size() bug fix — previously
non-USD_JPY runs silently broke the min_atr_pips floor.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams, pip_size


SPREAD_PIPS = 1.0    # 2× retail FX default
SLIPPAGE_PIPS = 0.4
EQUITY = 110_000.0

INSTRUMENTS = [
    "USD_JPY",   # deployed reference
    "GBP_JPY",   # other JPY pair
    "EUR_USD",   # major non-JPY
    "GBP_USD",   # major non-JPY
    "AUD_USD",   # commodity-correlated major
    "XAU_USD",   # gold (different asset class — sanity check)
]


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


def evaluate(candles, instrument):
    p = StrategyParams()  # DEFAULTS only
    eval_fn = STRATEGIES["pullback"]
    r, _, _, diag = run_backtest(
        candles, starting_equity=EQUITY, params=p,
        spread_pips=SPREAD_PIPS, slippage_pips=SLIPPAGE_PIPS,
        evaluate_fn=eval_fn,
        signal_in_session_only=True,
        force_close_at_session_end=False,
        macro_features=None,
        instrument=instrument,
    )
    cagr = annualised(candles[0].time, candles[-1].time,
                      r.starting_equity, r.final_equity)
    n_years = (candles[-1].time - candles[0].time).total_seconds() / (365.25 * 86400.0)
    pip = pip_size(instrument)
    return {
        "instrument": instrument,
        "pip_size": pip,
        "trades": r.trades,
        "trades_per_year": r.trades / max(n_years, 1e-6),
        "win_rate_pct": r.win_rate,
        "cagr_pct": cagr,
        "max_dd_pct": r.max_drawdown_pct,
        "sharpe": r.sharpe,
        "profit_factor": r.profit_factor,
        "expectancy_pct": r.expectancy_pct,
        "avg_stop_pips": diag.get("avg_stop_distance_pips", 0),
    }


def main():
    print("=" * 90)
    print("  Cross-instrument generalization — deployed Pullback H1 defaults")
    print("  Same params (sma_long=100, sma_short=20, K=2.0, etc.). Same friction.")
    print(f"  Friction: {SPREAD_PIPS}p spread + {SLIPPAGE_PIPS}p slippage (2× retail)")
    print("=" * 90)
    print()

    results = []
    print(f"  {'instrument':12s}  {'trades':>6s}  {'rate':>7s}  {'WR':>6s}  "
          f"{'CAGR':>7s}  {'maxDD':>7s}  {'Sharpe':>7s}  {'PF':>5s}  {'avgStop':>8s}")
    print("  " + "-" * 86)

    for instr in INSTRUMENTS:
        path = settings.historical_dir / f"{instr}_H1_1825d.json"
        if not path.exists():
            print(f"  {instr:12s}  MISSING DATA")
            continue
        candles = load_candles(path)
        m = evaluate(candles, instr)
        results.append(m)
        print(f"  {m['instrument']:12s}  {m['trades']:>6d}  "
              f"{m['trades_per_year']:>5.0f}/y  "
              f"{m['win_rate_pct']:>5.1f}%  "
              f"{m['cagr_pct']:>+6.2f}%  "
              f"{m['max_dd_pct']:>6.2f}%  "
              f"{m['sharpe']:>+6.2f}  "
              f"{m['profit_factor']:>5.2f}  "
              f"{m['avg_stop_pips']:>6.1f}p")

    print()
    print("=" * 90)
    print("  ANALYSIS")
    print("=" * 90)

    pos_sharpe = [r for r in results if r["sharpe"] > 0]
    pos_cagr = [r for r in results if r["cagr_pct"] > 0]
    print(f"  Instruments with positive Sharpe: {len(pos_sharpe)} of {len(results)}")
    print(f"  Instruments with positive CAGR  : {len(pos_cagr)} of {len(results)}")
    print()

    jpy = [r for r in results if "JPY" in r["instrument"]]
    non_jpy_fx = [r for r in results
                  if "JPY" not in r["instrument"] and "XAU" not in r["instrument"]]
    if jpy and non_jpy_fx:
        avg_jpy_sharpe = sum(r["sharpe"] for r in jpy) / len(jpy)
        avg_non_jpy_sharpe = sum(r["sharpe"] for r in non_jpy_fx) / len(non_jpy_fx)
        print(f"  Avg Sharpe — JPY pairs    ({len(jpy)} instr): {avg_jpy_sharpe:+.2f}")
        print(f"  Avg Sharpe — non-JPY FX   ({len(non_jpy_fx)} instr): {avg_non_jpy_sharpe:+.2f}")
        print()

    if len(pos_sharpe) >= 4:
        verdict = "GENERALIZES — broad-FX edge"
        print(f"  VERDICT: {verdict}")
        print(f"  Positive Sharpe on ≥4 of 6 instruments. Strategy class has")
        print(f"  cross-instrument validity — not a USD/JPY-specific edge.")
    elif len(pos_sharpe) >= 2:
        verdict = "PARTIAL — works on a subset"
        print(f"  VERDICT: {verdict}")
        print(f"  Positive Sharpe on {len(pos_sharpe)} of 6. Family-specific edge,")
        print(f"  not universal. Useful info for v4 cross-instrument deployment.")
    else:
        verdict = "USD/JPY-SPECIFIC — does not generalize"
        print(f"  VERDICT: {verdict}")
        print(f"  Positive Sharpe on only {len(pos_sharpe)} of 6. Deployed strategy")
        print(f"  is essentially a USD/JPY edge. Other instruments need different")
        print(f"  strategies — likely the M15 family failures had instrument-specific")
        print(f"  echoes here.")

    out = {
        "spread_pips": SPREAD_PIPS,
        "slippage_pips": SLIPPAGE_PIPS,
        "verdict": verdict,
        "results": results,
    }
    out_path = settings.backtest_dir / "cross_instrument_check.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
