"""V1 — Pullback M15 with H1 regime gate, pre-registered fresh-data validation.

Spec: docs/pullback-m15-v3-research-plan.md (Variant 1).
Bars 1A through 1G are LOCKED in that document.

Test window: USD_JPY M15 2014-05-01 → 2017-05-01 (3 years, truly fresh —
never seen by any prior optimization or validation cycle).

This script also runs the v2 candidate (without H1 gate) on the same fresh
window, to provide the bar-1G comparison ("Sharpe strictly better than v2").
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


# Same friction model as deployed engine and prior research.
SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.4
EQUITY = 110_000.0

# v2 candidate parameters — locked in v2 spec, inherited by V1
# (V1 only adds the H1 gate; doesn't change the M15 entry params).
CANDIDATE_PARAMS = {
    "sma_long": 200,
    "sma_short": 50,
    "pullback_lookback": 5,
    "trend_slope_lookback": 20,
    "atr_period": 14,
    "stop_atr_mult": 3.0,
    "min_atr_pips": 3.0,
}

# Test window — LOCKED in v3 plan.
START_UTC = datetime(2014, 5, 1, tzinfo=timezone.utc)
END_UTC   = datetime(2017, 5, 1, tzinfo=timezone.utc)

# Pre-registered bars (from v3 plan).
BARS = {
    "1A": ("Sharpe ≥ 0.50",   "sharpe",         "ge", 0.50),
    "1B": ("CAGR ≥ +1.5%",    "cagr_pct",       "ge", 1.5),
    "1C": ("PF ≥ 1.10",       "profit_factor",  "ge", 1.10),
    "1D": ("Max DD ≤ 12%",    "max_dd_pct",     "le", 12.0),
    "1F": ("Trades/yr ≥ 80",  "trades_per_year","ge", 80),
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


def evaluate(candles: list[Candle], strategy: str, label: str) -> dict:
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
        "label": label,
        "strategy": strategy,
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


def fmt(s: dict) -> str:
    return (
        f"  trades={s['trades']:>4d} ({s['trades_per_year']:>5.0f}/y)  "
        f"WR={s['win_rate_pct']:>5.1f}%  "
        f"CAGR={s['cagr_pct']:>+6.2f}%  "
        f"DD={s['max_dd_pct']:>5.2f}%  "
        f"Sharpe={s['sharpe']:>+5.2f}  "
        f"PF={s['profit_factor']:.2f}"
    )


def check_bar(label: str, desc: str, value: float, op: str, threshold: float) -> tuple[bool, str]:
    if op == "ge":
        ok = value >= threshold
        sym = "≥"
    else:
        ok = value <= threshold
        sym = "≤"
    status = "PASS" if ok else "FAIL"
    return ok, f"  [{label}] {status}  {desc}  →  value={value:.2f}  bar: {sym}{threshold}"


def main() -> int:
    print("=" * 78)
    print("  V1 — Pullback M15 with H1 regime gate")
    print(f"  Window: {START_UTC.date()} → {END_UTC.date()}  (truly fresh)")
    print(f"  Friction: {SPREAD_PIPS}p spread + {SLIPPAGE_PIPS}p slippage")
    print("=" * 78)
    print()

    path = settings.historical_dir / "USD_JPY_M15_4380d.json"
    if not path.exists():
        print(f"missing {path}")
        return 2

    print(f"Loading {path.name}…")
    full = load_candles(path)
    print(f"  {len(full):,} bars total, "
          f"{full[0].time.date()} → {full[-1].time.date()}")

    test = slice_candles(full, START_UTC, END_UTC)
    print(f"  Sliced to test window: {len(test):,} bars  "
          f"{test[0].time.date()} → {test[-1].time.date()}\n")

    print(f"Candidate parameters (inherited from v2): {CANDIDATE_PARAMS}\n")

    # === Run V1 (H1-gated) ===
    print("=== V1: Pullback M15 + H1 regime gate ===")
    v1 = evaluate(test, "pullback_h1_gated", "V1_h1gated")
    print(fmt(v1))
    print()

    # === Run v2 baseline (no gate) on same fresh window — for bar 1G ===
    print("=== v2 baseline (same params, no H1 gate) — for bar 1G comparison ===")
    v2 = evaluate(test, "pullback", "v2_baseline_on_fresh")
    print(fmt(v2))
    print()

    # === Yearly breakdown of V1 ===
    print("=== V1 — yearly breakdown ===")
    yearly_results = []
    for y in range(2014, 2017):
        slice_start = datetime(y, 5, 1, tzinfo=timezone.utc)
        slice_end = datetime(y + 1, 5, 1, tzinfo=timezone.utc)
        candles = slice_candles(full, slice_start, slice_end)
        if not candles:
            continue
        r = evaluate(candles, "pullback_h1_gated", f"V1_{y}_{y+1}")
        yearly_results.append(r)
        print(f"  {y}-05 → {y+1}-05:  " + fmt(r))
    print()

    # === Pre-registered bars ===
    print("=" * 78)
    print("  PRE-REGISTERED BAR EVALUATION")
    print("=" * 78)

    bar_results = []
    for label, (desc, key, op, threshold) in BARS.items():
        ok, msg = check_bar(label, desc, v1[key], op, threshold)
        print(msg)
        bar_results.append((label, desc, ok))

    # Bar 1E — yearly positive count
    pos_years = sum(1 for r in yearly_results if r["expectancy_pct"] > 0)
    ok, msg = check_bar("1E", "Yearly positive count ≥ 2 of 3", pos_years, "ge", 2)
    print(msg)
    bar_results.append(("1E", "Yearly positive count", ok))

    # Bar 1G — Sharpe vs v2 baseline
    sharpe_diff = v1["sharpe"] - v2["sharpe"]
    ok = v1["sharpe"] > v2["sharpe"]
    status = "PASS" if ok else "FAIL"
    print(f"  [1G] {status}  Sharpe vs v2 strictly better  →  V1={v1['sharpe']:.2f}, "
          f"v2={v2['sharpe']:.2f}, Δ={sharpe_diff:+.2f}")
    bar_results.append(("1G", "Sharpe vs v2 baseline", ok))

    # Falsification trigger checks (informational)
    print()
    print("=== Falsification triggers (informational) ===")
    if v1["trades_per_year"] < 50:
        print(f"  ⚠ Trade count collapsed (<50/y): {v1['trades_per_year']:.0f}/y — "
              f"filter is over-throttling")
    if v1["sharpe"] > v2["sharpe"] and v1["cagr_pct"] < v2["cagr_pct"]:
        print(f"  ⚠ Sharpe better but CAGR worse — improvement is from trading "
              f"less, not real edge")
    if v1["sharpe"] <= v2["sharpe"] and v1["sharpe"] >= 0.50:
        print(f"  ⚠ Numerical bars pass but Sharpe didn't improve over v2 — "
              f"H1 gate isn't actually adding value")

    print()
    n_pass = sum(1 for _, _, ok in bar_results if ok)
    print(f"  TOTAL: {n_pass}/{len(bar_results)} bars passed")
    print()

    # === Decision ===
    print("=" * 78)
    if n_pass == len(bar_results):
        print("  VERDICT: ALL BARS PASSED — V1 advances to v3 candidate pool.")
        print("  Eligible for separate pre-registered demo cycle AFTER current")
        print("  Pullback H1 demo concludes. NOT swapped live now.")
        verdict = "ADVANCED"
    else:
        failed = [f"{label}: {desc}" for label, desc, ok in bar_results if not ok]
        print(f"  VERDICT: V1 FAILED — {len(failed)} bar(s) failed:")
        for f in failed:
            print(f"    • {f}")
        print()
        print("  Next per v3 decision tree: Variant 3 (restart confirmation).")
        print("  M15 family branch-kill is one more failure away.")
        verdict = "FAILED"
    print("=" * 78)

    out = {
        "spec": "docs/pullback-m15-v3-research-plan.md",
        "variant": "V1_h1_regime_gate",
        "candidate_params": CANDIDATE_PARAMS,
        "test_window": [START_UTC.isoformat(), END_UTC.isoformat()],
        "spread_pips": SPREAD_PIPS,
        "slippage_pips": SLIPPAGE_PIPS,
        "v1_full": v1,
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
    out_path = settings.backtest_dir / "v1_h1_gate_validation.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")

    return 0 if verdict == "ADVANCED" else 1


if __name__ == "__main__":
    sys.exit(main())
