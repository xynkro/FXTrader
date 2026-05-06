"""Pre-registered out-of-distribution validation for the Pullback M15 v2
candidate. See docs/pullback-m15-v2-candidate.md.

Tests:
    1. USD_JPY M15 2017-05 → 2021-05 (truly fresh, never seen)
    2. EUR_USD M15 2017-05 → 2021-05 (cross-instrument)
    3. Year-by-year breakdown of Test 1 (cross-window consistency)

The bars are LOCKED in the spec doc and not modifiable here.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams


SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.4
EQUITY = 110_000.0

# Candidate parameters — LOCKED in spec doc.
CANDIDATE = {
    "sma_long": 200,
    "sma_short": 50,
    "pullback_lookback": 5,
    "trend_slope_lookback": 20,
    "atr_period": 14,
    "stop_atr_mult": 3.0,
    "min_atr_pips": 3.0,
}

# Test window — LOCKED.
START_UTC = datetime(2017, 5, 1, tzinfo=timezone.utc)
END_UTC   = datetime(2021, 5, 1, tzinfo=timezone.utc)

# Pre-registered bars from the spec doc.
BARS = {
    "USD_JPY_sharpe_min":  ("A", 0.50),
    "USD_JPY_cagr_min":    ("B", 1.5),
    "USD_JPY_max_dd":      ("C", 15.0),
    "USD_JPY_trades_min":  ("D", 200),  # per year
    "USD_JPY_pf_min":      ("E", 1.05),
    "EUR_USD_sharpe_min":  ("F", 0.30),
    "EUR_USD_cagr_min":    ("G", 0.5),
    "EUR_USD_pf_min":      ("H", 1.0),
    "yearly_pos_count":    ("I", 3),  # 3 of 4 years positive
    "yearly_sharpe_range": ("J", 1.5),
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


def slice_candles(candles: list[Candle], start, end) -> list[Candle]:
    return [c for c in candles if start <= c.time < end]


def annualised(start, end, eq0, eq1):
    seconds = (end - start).total_seconds()
    years = max(seconds / (365.25 * 24 * 3600.0), 1e-6)
    if eq1 / eq0 <= 0:
        return -100.0
    return ((eq1 / eq0) ** (1.0 / years) - 1.0) * 100.0


def evaluate(candles: list[Candle], label: str, instrument: str = "USD_JPY") -> dict:
    p = replace(StrategyParams(), **CANDIDATE)
    eval_fn = STRATEGIES["pullback"]
    r, trades, _, diag = run_backtest(
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
    return {
        "label": label,
        "trades": r.trades,
        "trades_per_year": r.trades / max(n_years, 1e-6),
        "win_rate_pct": r.win_rate,
        "expectancy_pct": r.expectancy_pct,
        "total_return_pct": r.total_return_pct,
        "cagr_pct": cagr,
        "max_dd_pct": r.max_drawdown_pct,
        "sharpe": r.sharpe,
        "profit_factor": r.profit_factor,
        "yearly": diag.get("yearly", {}),
        "n_bars": len(candles),
        "start": candles[0].time.isoformat(),
        "end": candles[-1].time.isoformat(),
    }


def fmt(s: dict) -> str:
    return (
        f"  trades={s['trades']:>4d} ({s['trades_per_year']:.0f}/y)  "
        f"WR={s['win_rate_pct']:>5.1f}%  "
        f"CAGR={s['cagr_pct']:>+6.2f}%  "
        f"DD={s['max_dd_pct']:>5.2f}%  "
        f"Sharpe={s['sharpe']:>+5.2f}  "
        f"PF={s['profit_factor']:.2f}"
    )


def check_bar(label: str, value: float, op: str, threshold: float) -> tuple[bool, str]:
    """op: 'ge' (≥) or 'le' (≤)."""
    if op == "ge":
        ok = value >= threshold
        sym = "≥"
    else:
        ok = value <= threshold
        sym = "≤"
    status = "PASS" if ok else "FAIL"
    return ok, f"  [{label}] {status}  value={value:.2f}  bar: {sym}{threshold:.2f}"


def main() -> int:
    print("=" * 78)
    print("  Pullback M15 v2 candidate — pre-registered validation")
    print(f"  Window: {START_UTC.date()} → {END_UTC.date()}  (truly fresh, "
          f"never seen by optimizer)")
    print("=" * 78)
    print()

    print("Loading data files…")
    usd_path = settings.historical_dir / "USD_JPY_M15_3287d.json"
    eur_path = settings.historical_dir / "EUR_USD_M15_3287d.json"
    if not usd_path.exists() or not eur_path.exists():
        print(f"  Missing one of:\n    {usd_path}\n    {eur_path}")
        return 2
    usd_full = load_candles(usd_path)
    eur_full = load_candles(eur_path)
    print(f"  USD_JPY M15: {len(usd_full):,} bars total, "
          f"{usd_full[0].time.date()} → {usd_full[-1].time.date()}")
    print(f"  EUR_USD M15: {len(eur_full):,} bars total, "
          f"{eur_full[0].time.date()} → {eur_full[-1].time.date()}")

    usd_test = slice_candles(usd_full, START_UTC, END_UTC)
    eur_test = slice_candles(eur_full, START_UTC, END_UTC)
    print(f"  USD_JPY sliced: {len(usd_test):,} bars  "
          f"{usd_test[0].time.date()} → {usd_test[-1].time.date()}")
    print(f"  EUR_USD sliced: {len(eur_test):,} bars  "
          f"{eur_test[0].time.date()} → {eur_test[-1].time.date()}")
    print()

    print(f"Candidate parameters: {CANDIDATE}\n")

    # === Test 1: USD_JPY 2017-2021 ===
    print("=== Test 1: USD_JPY M15 2017-05 → 2021-05 (fresh) ===")
    t1 = evaluate(usd_test, "USD_JPY_2017_2021", instrument="USD_JPY")
    print(fmt(t1))
    print()

    # === Test 2: EUR_USD 2017-2021 ===
    print("=== Test 2: EUR_USD M15 2017-05 → 2021-05 (cross-instrument) ===")
    t2 = evaluate(eur_test, "EUR_USD_2017_2021", instrument="EUR_USD")
    print(fmt(t2))
    print()

    # === Test 3: yearly breakdown of Test 1 ===
    print("=== Test 3: USD_JPY year-by-year breakdown ===")
    yearly_results = []
    for y in range(2017, 2021):
        slice_start = datetime(y, 5, 1, tzinfo=timezone.utc)
        slice_end = datetime(y + 1, 5, 1, tzinfo=timezone.utc)
        candles = slice_candles(usd_full, slice_start, slice_end)
        if not candles:
            continue
        r = evaluate(candles, f"USD_JPY_{y}_{y+1}")
        yearly_results.append(r)
        print(f"  {y}-05 → {y+1}-05:  " + fmt(r))
    print()

    # === Apply bars ===
    print("=" * 78)
    print("  PRE-REGISTERED BAR EVALUATION")
    print("=" * 78)

    bar_results = []

    ok, msg = check_bar("A", t1["sharpe"], "ge", BARS["USD_JPY_sharpe_min"][1])
    print(msg); bar_results.append(("A: USD_JPY Sharpe", ok))

    ok, msg = check_bar("B", t1["cagr_pct"], "ge", BARS["USD_JPY_cagr_min"][1])
    print(msg); bar_results.append(("B: USD_JPY CAGR", ok))

    ok, msg = check_bar("C", t1["max_dd_pct"], "le", BARS["USD_JPY_max_dd"][1])
    print(msg); bar_results.append(("C: USD_JPY max DD", ok))

    ok, msg = check_bar("D", t1["trades_per_year"], "ge", BARS["USD_JPY_trades_min"][1])
    print(msg); bar_results.append(("D: USD_JPY trades/yr", ok))

    ok, msg = check_bar("E", t1["profit_factor"], "ge", BARS["USD_JPY_pf_min"][1])
    print(msg); bar_results.append(("E: USD_JPY PF", ok))

    ok, msg = check_bar("F", t2["sharpe"], "ge", BARS["EUR_USD_sharpe_min"][1])
    print(msg); bar_results.append(("F: EUR_USD Sharpe", ok))

    ok, msg = check_bar("G", t2["cagr_pct"], "ge", BARS["EUR_USD_cagr_min"][1])
    print(msg); bar_results.append(("G: EUR_USD CAGR", ok))

    ok, msg = check_bar("H", t2["profit_factor"], "ge", BARS["EUR_USD_pf_min"][1])
    print(msg); bar_results.append(("H: EUR_USD PF", ok))

    pos_years = sum(1 for r in yearly_results if r["expectancy_pct"] > 0)
    ok, msg = check_bar("I", pos_years, "ge", BARS["yearly_pos_count"][1])
    print(msg); bar_results.append(("I: positive years", ok))

    if yearly_results:
        sharpes = [r["sharpe"] for r in yearly_results]
        sharpe_range = max(sharpes) - min(sharpes)
        ok, msg = check_bar("J", sharpe_range, "le", BARS["yearly_sharpe_range"][1])
        print(msg); bar_results.append(("J: yearly Sharpe range", ok))
    else:
        bar_results.append(("J: yearly Sharpe range", False))
        print("  [J] FAIL  no yearly data")

    print()
    n_pass = sum(1 for _, ok in bar_results if ok)
    print(f"  TOTAL: {n_pass}/{len(bar_results)} bars passed")

    # === Decision ===
    print()
    print("=" * 78)
    if n_pass == len(bar_results):
        print("  VERDICT: ALL BARS PASSED — candidate ADVANCES to v2 status.")
        print("  Eligible for separate pre-registered demo cycle AFTER current")
        print("  Pullback H1 demo concludes. NOT swapped live now.")
        verdict = "ADVANCED"
    else:
        failed = [name for name, ok in bar_results if not ok]
        print(f"  VERDICT: KILLED — failed {len(failed)} bar(s):")
        for name in failed:
            print(f"    • {name}")
        print("  Candidate is not pursued further. Logged for institutional memory.")
        verdict = "KILLED"
    print("=" * 78)

    out = {
        "spec": "docs/pullback-m15-v2-candidate.md",
        "candidate_params": CANDIDATE,
        "test_window": [START_UTC.isoformat(), END_UTC.isoformat()],
        "spread_pips": SPREAD_PIPS,
        "slippage_pips": SLIPPAGE_PIPS,
        "test1_usd_jpy": t1,
        "test2_eur_usd": t2,
        "yearly_breakdown": yearly_results,
        "bar_results": [{"name": n, "passed": ok} for n, ok in bar_results],
        "n_passed": n_pass,
        "n_total": len(bar_results),
        "verdict": verdict,
    }
    out_path = settings.backtest_dir / "pullback_m15_v2_validation.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")

    return 0 if verdict == "ADVANCED" else 1


if __name__ == "__main__":
    sys.exit(main())
