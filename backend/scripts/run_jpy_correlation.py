"""USD_JPY × GBP_JPY correlation analysis on H1 data.

Decisive question for v4 multi-instrument deployment: does running both
pairs at half-size each give meaningful diversification, or are they so
correlated that we're just doubling the same exposure?

Three views:
  1. Bar-to-bar return correlation (Pearson, on H1 closes)
  2. Rolling 30-day correlation to check stability
  3. Trade-level correlation: when USD/JPY signals long, what does GBP/JPY
     do during the same period? Practical diversification math.

If correlation is >0.85: not real diversification. If 0.5-0.85: partial.
If <0.5: meaningful.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from app.config import settings


def load_closes(path: Path) -> tuple[list[datetime], np.ndarray]:
    raw = json.loads(path.read_text())
    times = [datetime.fromisoformat(c["time"]) for c in raw]
    closes = np.array([c["close"] for c in raw], dtype=float)
    return times, closes


def main():
    print("=" * 80)
    print("  USD_JPY × GBP_JPY correlation analysis (H1, 5y)")
    print("=" * 80)
    print()

    usd_path = settings.historical_dir / "USD_JPY_H1_1825d.json"
    gbp_path = settings.historical_dir / "GBP_JPY_H1_1825d.json"

    usd_times, usd_closes = load_closes(usd_path)
    gbp_times, gbp_closes = load_closes(gbp_path)
    print(f"  USD_JPY: {len(usd_closes):,} bars  "
          f"{usd_times[0].date()} → {usd_times[-1].date()}")
    print(f"  GBP_JPY: {len(gbp_closes):,} bars  "
          f"{gbp_times[0].date()} → {gbp_times[-1].date()}")

    # Align by timestamp (take intersection)
    usd_idx = {t: i for i, t in enumerate(usd_times)}
    gbp_idx = {t: i for i, t in enumerate(gbp_times)}
    common = sorted(set(usd_idx.keys()) & set(gbp_idx.keys()))
    usd_aligned = np.array([usd_closes[usd_idx[t]] for t in common])
    gbp_aligned = np.array([gbp_closes[gbp_idx[t]] for t in common])
    print(f"  Aligned (intersection): {len(common):,} bars")
    print()

    # === 1. Bar-to-bar return correlation ===
    usd_ret = np.diff(np.log(usd_aligned))
    gbp_ret = np.diff(np.log(gbp_aligned))
    corr_returns = float(np.corrcoef(usd_ret, gbp_ret)[0, 1])

    # === 2. Daily aggregated returns ===
    times_arr = np.array([t.date() for t in common[1:]])
    daily_dates = sorted(set(times_arr))
    daily_usd = []
    daily_gbp = []
    for d in daily_dates:
        mask = times_arr == d
        if mask.sum() == 0:
            continue
        # Sum H1 log-returns within day to get daily log-return
        daily_usd.append(usd_ret[mask].sum())
        daily_gbp.append(gbp_ret[mask].sum())
    daily_usd_arr = np.array(daily_usd)
    daily_gbp_arr = np.array(daily_gbp)
    corr_daily = float(np.corrcoef(daily_usd_arr, daily_gbp_arr)[0, 1])

    # === 3. Rolling 30-day correlation ===
    win = 30
    rolling = []
    for i in range(win, len(daily_usd_arr)):
        u = daily_usd_arr[i - win : i]
        g = daily_gbp_arr[i - win : i]
        if u.std() > 0 and g.std() > 0:
            rolling.append(float(np.corrcoef(u, g)[0, 1]))
    rolling_arr = np.array(rolling)

    # === 4. Diversification quotient ===
    # If we hold equal $ in both, Var(portfolio) = 0.25*Var(A) + 0.25*Var(B) + 0.5*Cov(A,B)
    # vs holding 1 of either at full size = Var(A)
    # Diversification benefit = (Var(A) - Var(portfolio)) / Var(A)
    var_usd = float(daily_usd_arr.var())
    var_gbp = float(daily_gbp_arr.var())
    cov = float(np.cov(daily_usd_arr, daily_gbp_arr)[0, 1])
    var_portfolio = 0.25 * var_usd + 0.25 * var_gbp + 0.5 * cov
    div_benefit = (var_usd - var_portfolio) / var_usd if var_usd > 0 else 0.0
    portfolio_vol_reduction = 1.0 - np.sqrt(var_portfolio / var_usd) if var_usd > 0 else 0.0

    # === Output ===
    print("=== Correlation results ===")
    print(f"  Bar-to-bar (H1) returns          : {corr_returns:+.3f}")
    print(f"  Daily aggregated returns         : {corr_daily:+.3f}")
    print(f"  Rolling 30d corr — mean          : {rolling_arr.mean():+.3f}")
    print(f"  Rolling 30d corr — std           : {rolling_arr.std():.3f}")
    print(f"  Rolling 30d corr — min           : {rolling_arr.min():+.3f}")
    print(f"  Rolling 30d corr — max           : {rolling_arr.max():+.3f}")
    print(f"  Rolling 30d corr — % of windows >0.85 : "
          f"{100 * (rolling_arr > 0.85).mean():.1f}%")
    print(f"  Rolling 30d corr — % of windows <0.50 : "
          f"{100 * (rolling_arr < 0.50).mean():.1f}%")
    print()

    print("=== 50/50 portfolio diversification math ===")
    print(f"  Daily variance USD_JPY           : {var_usd:.6f}")
    print(f"  Daily variance GBP_JPY           : {var_gbp:.6f}")
    print(f"  Covariance                       : {cov:.6f}")
    print(f"  Portfolio variance (50/50, full size on each):")
    print(f"     Var(p) = 0.25·Var(A) + 0.25·Var(B) + 0.5·Cov  = {var_portfolio:.6f}")
    print(f"  Diversification benefit (variance reduction): {100*div_benefit:+.1f}%")
    print(f"  Diversification benefit (vol reduction)     : {100*portfolio_vol_reduction:+.1f}%")
    print()

    print("=" * 80)
    print("  VERDICT")
    print("=" * 80)
    if corr_daily > 0.85:
        verdict = "HIGHLY CORRELATED — not real diversification"
        msg = (f"Daily correlation {corr_daily:.2f} > 0.85. Running both pairs at\n"
               f"  full size = doubling JPY-axis exposure with extra friction.\n"
               f"  Half-size on each gives only ~{100*portfolio_vol_reduction:.1f}% vol reduction\n"
               f"  vs single-instrument full size. Diversification claim FAILS.")
    elif corr_daily > 0.65:
        verdict = "PARTIALLY CORRELATED — marginal diversification"
        msg = (f"Daily correlation {corr_daily:.2f} sits in the 0.65-0.85 range.\n"
               f"  Half-size on each gives ~{100*portfolio_vol_reduction:.1f}% vol reduction —\n"
               f"  modest benefit. Worth doing if engineering cost is reasonable;\n"
               f"  expect Sharpe to improve by ~{(1/(1-portfolio_vol_reduction)-1)*100:.0f}% via vol reduction\n"
               f"  rather than excess return.")
    else:
        verdict = "MEANINGFUL DIVERSIFICATION — pursue"
        msg = (f"Daily correlation {corr_daily:.2f} < 0.65. Half-size on each\n"
               f"  gives ~{100*portfolio_vol_reduction:.1f}% vol reduction, which is real.\n"
               f"  Two-pair portfolio is a legitimate v4 candidate.")
    print(f"  {verdict}")
    print()
    print(f"  {msg}")

    out = {
        "instruments": ["USD_JPY", "GBP_JPY"],
        "n_aligned_bars": len(common),
        "correlation": {
            "bar_to_bar_h1_returns": corr_returns,
            "daily_returns": corr_daily,
            "rolling_30d_mean": float(rolling_arr.mean()),
            "rolling_30d_std": float(rolling_arr.std()),
            "rolling_30d_min": float(rolling_arr.min()),
            "rolling_30d_max": float(rolling_arr.max()),
            "rolling_pct_above_0_85": float(100 * (rolling_arr > 0.85).mean()),
            "rolling_pct_below_0_50": float(100 * (rolling_arr < 0.50).mean()),
        },
        "diversification": {
            "daily_var_usd": var_usd,
            "daily_var_gbp": var_gbp,
            "covariance": cov,
            "portfolio_50_50_full_size_var": var_portfolio,
            "var_reduction_pct": float(100 * div_benefit),
            "vol_reduction_pct": float(100 * portfolio_vol_reduction),
        },
        "verdict": verdict,
    }
    out_path = settings.backtest_dir / "jpy_correlation.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
