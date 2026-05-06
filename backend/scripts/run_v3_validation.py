"""V3 — Pullback M15 with restart confirmation, pre-registered fresh-data validation.

Spec: docs/pullback-m15-v3-research-plan.md (Variant 3).
Bars 3A through 3G are LOCKED in that document.

Test window: USD_JPY M15 2014-05-01 → 2017-05-01 (same fresh window as V1
test, never touched by any optimization).

Confirmation rule: signal bar's high (long) or low (short) must break the
prior bar's same. One specific mechanism, not a knob hunt.
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

CANDIDATE_PARAMS = {
    "sma_long": 200,
    "sma_short": 50,
    "pullback_lookback": 5,
    "trend_slope_lookback": 20,
    "atr_period": 14,
    "stop_atr_mult": 3.0,
    "min_atr_pips": 3.0,
}

START_UTC = datetime(2014, 5, 1, tzinfo=timezone.utc)
END_UTC   = datetime(2017, 5, 1, tzinfo=timezone.utc)

# V3 pre-registered bars (higher than V1 because confirmation should help).
BARS = {
    "3A": ("Sharpe ≥ 0.55",          "sharpe",         "ge", 0.55),
    "3B": ("CAGR ≥ +1.5%",           "cagr_pct",       "ge", 1.5),
    "3C": ("PF ≥ 1.15",              "profit_factor",  "ge", 1.15),
    "3D": ("Win rate ≥ 38%",         "win_rate_pct",   "ge", 38.0),
    "3E": ("Max DD ≤ 10%",           "max_dd_pct",     "le", 10.0),
    "3G": ("Trades/yr ≥ 80",         "trades_per_year","ge", 80),
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


def slice_candles(candles, start, end):
    return [c for c in candles if start <= c.time < end]


def annualised(start, end, eq0, eq1):
    seconds = (end - start).total_seconds()
    years = max(seconds / (365.25 * 24 * 3600.0), 1e-6)
    if eq1 / eq0 <= 0:
        return -100.0
    return ((eq1 / eq0) ** (1.0 / years) - 1.0) * 100.0


def evaluate(candles, strategy: str, label: str) -> dict:
    p = replace(StrategyParams(), **CANDIDATE_PARAMS)
    eval_fn = STRATEGIES[strategy]
    r, trades, _, diag = run_backtest(
        candles, starting_equity=EQUITY, params=p,
        spread_pips=SPREAD_PIPS, slippage_pips=SLIPPAGE_PIPS,
        evaluate_fn=eval_fn,
        signal_in_session_only=True,
        force_close_at_session_end=False,
        macro_features=None,
        instrument="USD_JPY",
    )
    cagr = annualised(candles[0].time, candles[-1].time,
                      r.starting_equity, r.final_equity)
    n_years = (candles[-1].time - candles[0].time).total_seconds() / (365.25 * 86400.0)
    return {
        "label": label, "strategy": strategy,
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
        "skips": diag.get("skips", {}),
    }


def fmt(s):
    return (f"  trades={s['trades']:>4d} ({s['trades_per_year']:>5.0f}/y)  "
            f"WR={s['win_rate_pct']:>5.1f}%  "
            f"CAGR={s['cagr_pct']:>+6.2f}%  "
            f"DD={s['max_dd_pct']:>5.2f}%  "
            f"Sharpe={s['sharpe']:>+5.2f}  "
            f"PF={s['profit_factor']:.2f}")


def check_bar(label, desc, value, op, threshold):
    if op == "ge":
        ok = value >= threshold
        sym = "≥"
    else:
        ok = value <= threshold
        sym = "≤"
    status = "PASS" if ok else "FAIL"
    return ok, f"  [{label}] {status}  {desc}  →  value={value:.2f}  bar: {sym}{threshold}"


def main():
    print("=" * 78)
    print("  V3 — Pullback M15 with restart confirmation")
    print(f"  Window: {START_UTC.date()} → {END_UTC.date()}  (truly fresh)")
    print(f"  Friction: {SPREAD_PIPS}p spread + {SLIPPAGE_PIPS}p slippage")
    print(f"  Confirmation rule: bar's high>prevH (long) / low<prevL (short)")
    print("=" * 78)
    print()

    path = settings.historical_dir / "USD_JPY_M15_4380d.json"
    if not path.exists():
        print(f"missing {path}")
        return 2

    full = load_candles(path)
    test = slice_candles(full, START_UTC, END_UTC)
    print(f"  {len(test):,} bars in window  "
          f"{test[0].time.date()} → {test[-1].time.date()}\n")

    print("=== V3: Pullback M15 + restart confirmation ===")
    v3 = evaluate(test, "pullback_restart_conf", "V3_restart")
    print(fmt(v3))
    print()

    print("=== v2 baseline (no confirmation) — for falsification check ===")
    v2 = evaluate(test, "pullback", "v2_baseline")
    print(fmt(v2))
    print()

    print("=== V3 — yearly breakdown ===")
    yearly_results = []
    for y in range(2014, 2017):
        slice_start = datetime(y, 5, 1, tzinfo=timezone.utc)
        slice_end = datetime(y + 1, 5, 1, tzinfo=timezone.utc)
        candles = slice_candles(full, slice_start, slice_end)
        if not candles:
            continue
        r = evaluate(candles, "pullback_restart_conf", f"V3_{y}_{y+1}")
        yearly_results.append(r)
        print(f"  {y}-05 → {y+1}-05:  " + fmt(r))
    print()

    print("=" * 78)
    print("  PRE-REGISTERED BAR EVALUATION")
    print("=" * 78)

    bar_results = []
    for label, (desc, key, op, threshold) in BARS.items():
        ok, msg = check_bar(label, desc, v3[key], op, threshold)
        print(msg)
        bar_results.append((label, desc, ok))

    pos_years = sum(1 for r in yearly_results if r["expectancy_pct"] > 0)
    ok, msg = check_bar("3F", "Yearly positive count ≥ 2 of 3", pos_years, "ge", 2)
    print(msg)
    bar_results.append(("3F", "Yearly positive count", ok))

    print()
    print("=== Falsification trigger checks (informational) ===")
    if v3["win_rate_pct"] > v2["win_rate_pct"] and v3["expectancy_pct"] < v2["expectancy_pct"]:
        print(f"  ⚠ FALSIFICATION TRIGGER: WR up ({v3['win_rate_pct']:.1f}% vs "
              f"{v2['win_rate_pct']:.1f}%) but expectancy DOWN "
              f"({v3['expectancy_pct']:+.4f}% vs {v2['expectancy_pct']:+.4f}%)")
        print(f"     → Confirmation comes TOO LATE; gives away the move")
    if abs(v3["profit_factor"] - v2["profit_factor"]) < 0.02:
        print(f"  ⚠ FALSIFICATION TRIGGER: PF unchanged from v2 "
              f"({v3['profit_factor']:.2f} vs {v2['profit_factor']:.2f})")
        print(f"     → Confirmation isn't filtering bad setups, it's filtering both equally")
    if v3["sharpe"] <= v2["sharpe"]:
        print(f"  ⚠ V3 Sharpe ({v3['sharpe']:.2f}) NOT better than v2 ({v2['sharpe']:.2f}) "
              f"— confirmation didn't help")

    print()
    n_pass = sum(1 for _, _, ok in bar_results if ok)
    print(f"  TOTAL: {n_pass}/{len(bar_results)} bars passed")
    print()

    print("=" * 78)
    if n_pass == len(bar_results):
        print("  VERDICT: ALL BARS PASSED — V3 advances to v3 candidate pool.")
        print("  Eligible for separate pre-registered demo cycle AFTER current")
        print("  Pullback H1 demo concludes. NOT swapped live now.")
        verdict = "ADVANCED"
    else:
        failed = [f"{label}: {desc}" for label, desc, ok in bar_results if not ok]
        print(f"  VERDICT: V3 FAILED — {len(failed)} bar(s):")
        for f in failed:
            print(f"    • {f}")
        print()
        print("  V1 + V3 both failed → per v3 plan, M15 PULLBACK FAMILY DEAD.")
        print("  Document and pivot to a structurally different family.")
        verdict = "FAILED"
    print("=" * 78)

    out = {
        "spec": "docs/pullback-m15-v3-research-plan.md",
        "variant": "V3_restart_confirmation",
        "candidate_params": CANDIDATE_PARAMS,
        "test_window": [START_UTC.isoformat(), END_UTC.isoformat()],
        "spread_pips": SPREAD_PIPS,
        "slippage_pips": SLIPPAGE_PIPS,
        "v3_full": v3,
        "v2_baseline_full": v2,
        "yearly_breakdown": yearly_results,
        "bar_results": [
            {"label": label, "desc": desc, "passed": ok}
            for label, desc, ok in bar_results
        ],
        "n_passed": n_pass,
        "n_total": len(bar_results),
        "verdict": verdict,
    }
    out_path = settings.backtest_dir / "v3_restart_validation.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")
    return 0 if verdict == "ADVANCED" else 1


if __name__ == "__main__":
    sys.exit(main())
