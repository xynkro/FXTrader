"""H1 freshness check — does the deployed Pullback H1 default hold on
truly fresh 2014-2017 USD_JPY H1 data?

Aggregates the 12y M15 file into H1 bars (we never had 12y H1 data on
disk; this saves a separate download). Runs deployed default params on
2014-2017 (fresh — engine was tested on 2021-2026 only). Compares to
deployed baseline.

Decisive question: is the deployed H1 strategy a robust regime-spanning
edge, or also a regime-fitter like the M15 family?
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams, aggregate_to_h1


SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.4
EQUITY = 110_000.0


def load_m15(path):
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


def evaluate(candles, label):
    p = StrategyParams()  # DEFAULT params — same as deployed
    eval_fn = STRATEGIES["pullback"]
    r, _, _, diag = run_backtest(
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
    }


def fmt(s):
    return (f"  trades={s['trades']:>4d} ({s['trades_per_year']:>5.0f}/y)  "
            f"WR={s['win_rate_pct']:>5.1f}%  "
            f"CAGR={s['cagr_pct']:>+6.2f}%  "
            f"DD={s['max_dd_pct']:>5.2f}%  "
            f"Sharpe={s['sharpe']:>+5.2f}  "
            f"PF={s['profit_factor']:.2f}")


def main():
    print("=" * 78)
    print("  H1 FRESHNESS CHECK — does the deployed Pullback hold on 2014-2017?")
    print("=" * 78)
    print()

    m15_path = settings.historical_dir / "USD_JPY_M15_4380d.json"
    if not m15_path.exists():
        print(f"missing {m15_path}")
        return 2

    print(f"Loading {m15_path.name} (M15 12y) and aggregating → H1…")
    m15_full = load_m15(m15_path)
    h1_full = aggregate_to_h1(m15_full)
    print(f"  M15: {len(m15_full):,} bars  →  H1: {len(h1_full):,} bars")
    print(f"  H1 range: {h1_full[0].time.date()} → {h1_full[-1].time.date()}")
    print()

    # === Test windows ===
    fresh_start = datetime(2014, 5, 1, tzinfo=timezone.utc)
    fresh_end   = datetime(2017, 5, 1, tzinfo=timezone.utc)
    deployed_start = datetime(2021, 5, 1, tzinfo=timezone.utc)
    deployed_end   = datetime(2026, 5, 1, tzinfo=timezone.utc)

    fresh = slice_candles(h1_full, fresh_start, fresh_end)
    deployed = slice_candles(h1_full, deployed_start, deployed_end)

    print(f"  Fresh window   (2014-2017): {len(fresh):,} bars")
    print(f"  Deployed test  (2021-2026): {len(deployed):,} bars (sanity reference)")
    print()

    print("=== FRESH (2014-2017, never previously tested on H1) ===")
    f = evaluate(fresh, "fresh_2014_2017")
    print(fmt(f))
    print()

    print("=== DEPLOYED REFERENCE (2021-2026) ===")
    d = evaluate(deployed, "deployed_2021_2026")
    print(fmt(d))
    print()

    print("=== Yearly breakdown (fresh window) ===")
    for y in range(2014, 2017):
        slice_start = datetime(y, 5, 1, tzinfo=timezone.utc)
        slice_end = datetime(y + 1, 5, 1, tzinfo=timezone.utc)
        candles = slice_candles(h1_full, slice_start, slice_end)
        if not candles:
            continue
        r = evaluate(candles, f"{y}_{y+1}")
        print(f"  {y}-05 → {y+1}-05:  " + fmt(r))
    print()

    # === Verdict ===
    print("=" * 78)
    print("  VERDICT")
    print("=" * 78)
    sharpe_gap = abs(f["sharpe"] - d["sharpe"])
    if f["sharpe"] >= 0.4 and f["expectancy_pct"] > 0:
        print(f"  H1 PASSES freshness — Sharpe {f['sharpe']:.2f} on 2014-2017,")
        print(f"  expectancy +{f['expectancy_pct']:.4f}%/trade. Live strategy")
        print(f"  is robust across regimes, not a recency-only fitter.")
        verdict = "ROBUST"
    elif f["sharpe"] > 0 and f["expectancy_pct"] > 0:
        print(f"  H1 WEAK PASS — Sharpe {f['sharpe']:.2f} positive but below")
        print(f"  the expected ~0.7. Live strategy works in 2014-2017 but at")
        print(f"  weaker level than 2021-2026. Mild regime sensitivity.")
        verdict = "WEAK_PASS"
    else:
        print(f"  H1 FAILS freshness — Sharpe {f['sharpe']:.2f}, expectancy")
        print(f"  {f['expectancy_pct']:+.4f}%/trade. Deployed strategy is also")
        print(f"  regime-dependent. CRITICAL: the live demo is now riskier than")
        print(f"  we thought; the +2.20% CAGR on 2021-2026 may not be edge.")
        verdict = "ALSO_REGIME_FRAGILE"
    print(f"\n  Sharpe gap (deployed → fresh): {d['sharpe']:.2f} → {f['sharpe']:.2f}  "
          f"(Δ={d['sharpe']-f['sharpe']:+.2f})")
    print("=" * 78)

    out = {
        "fresh_window": [fresh_start.isoformat(), fresh_end.isoformat()],
        "deployed_window": [deployed_start.isoformat(), deployed_end.isoformat()],
        "fresh_metrics": f,
        "deployed_metrics": d,
        "verdict": verdict,
    }
    out_path = settings.backtest_dir / "h1_freshness_check.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
