"""Self-audit script after Caspar's red-team challenge:
  1. TV-B on M5/M15/H1 USD_JPY — closes the frame-lock gap
  2. TV-A on EUR/USD + GBP/USD — pairs where Pullback fails (mean-reversion territory)
  3. 50/50 portfolio sim: Pullback + TV-B on USD/JPY — the ensemble Sharpe question

Output: docs/self-audit-2026-05-06.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams


SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.4
EQUITY = 110_000.0


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


def daily_returns(equity_curve):
    by_day = {}
    for ts, eq in equity_curve:
        by_day[ts[:10]] = eq
    dates = sorted(by_day.keys())
    eqs = [by_day[d] for d in dates]
    rets = [
        np.log(eqs[i] / eqs[i - 1]) if eqs[i - 1] > 0 else 0.0
        for i in range(1, len(eqs))
    ]
    return dates[1:], eqs[1:], rets


def run_one(candles, strategy: str, instrument: str, session: bool = True) -> dict:
    p = StrategyParams()
    eval_fn = STRATEGIES[strategy]
    r, _, eq, _ = run_backtest(
        candles, starting_equity=EQUITY, params=p,
        spread_pips=SPREAD_PIPS, slippage_pips=SLIPPAGE_PIPS,
        evaluate_fn=eval_fn,
        signal_in_session_only=session,
        force_close_at_session_end=False,
        macro_features=None,
        instrument=instrument,
    )
    cagr = annualised(candles[0].time, candles[-1].time,
                      r.starting_equity, r.final_equity)
    n_years = (candles[-1].time - candles[0].time).total_seconds() / (365.25 * 86400.0)
    return {
        "trades": r.trades,
        "trades_per_year": r.trades / max(n_years, 1e-6),
        "win_rate": r.win_rate,
        "cagr_pct": cagr,
        "max_dd_pct": r.max_drawdown_pct,
        "sharpe": r.sharpe,
        "profit_factor": r.profit_factor,
        "expectancy_pct": r.expectancy_pct,
        "_eq_curve": eq,
    }


def fmt(s):
    return (f"trades={s['trades']:>4d} ({s['trades_per_year']:>5.0f}/y)  "
            f"WR={s['win_rate']:>4.1f}%  "
            f"CAGR={s['cagr_pct']:>+6.2f}%  "
            f"DD={s['max_dd_pct']:>5.2f}%  "
            f"Sharpe={s['sharpe']:>+5.2f}  "
            f"PF={s['profit_factor']:.2f}")


def main():
    print("=" * 100)
    print("  SELF-AUDIT — closing frame-lock + instrument-lock gaps")
    print("=" * 100)

    # ===== TEST 1: TV-B across timeframes on USD/JPY =====
    print("\n\n##### TEST 1: TV-B (smoothed-RSI L/S) across timeframes — USD/JPY #####\n")

    test1_results = {}
    for tf, fname in [
        ("H1 5y",  "USD_JPY_H1_1825d.json"),
        ("M15 5y", "USD_JPY_M15_1825d.json"),
        ("M15 1y", "USD_JPY_M15_365d.json"),
        ("M5 1y",  "USD_JPY_M5_365d.json"),
    ]:
        path = settings.historical_dir / fname
        if not path.exists():
            print(f"  {tf}: missing {fname}")
            continue
        candles = load_candles(path)
        print(f"  -- USD/JPY {tf} ({len(candles):,} bars) --")
        # Pullback baseline
        p_res = run_one(candles, "pullback", "USD_JPY", session=True)
        # TV-B
        tv_res = run_one(candles, "tv_fx_master_longshort", "USD_JPY", session=True)
        print(f"     pullback : {fmt(p_res)}")
        print(f"     TV-B     : {fmt(tv_res)}")
        test1_results[tf] = {"pullback": p_res, "tv_b": tv_res}

    # ===== TEST 2: TV-A on EUR/USD + GBP/USD (pairs Pullback fails) =====
    print("\n\n##### TEST 2: TV-A (BB mean-reversion + ADX-fall) — non-JPY majors #####\n")

    test2_results = {}
    for instr in ["EUR_USD", "GBP_USD"]:
        path = settings.historical_dir / f"{instr}_H1_1825d.json"
        if not path.exists():
            print(f"  {instr}: missing data")
            continue
        candles = load_candles(path)
        print(f"  -- {instr} H1 5y ({len(candles):,} bars) --")
        p_res = run_one(candles, "pullback", instr, session=True)
        tva_res = run_one(candles, "tv_forex_master_v4", instr, session=True)
        tvb_res = run_one(candles, "tv_fx_master_longshort", instr, session=True)
        print(f"     pullback : {fmt(p_res)}   (Pullback fails non-JPY, expected)")
        print(f"     TV-A     : {fmt(tva_res)}")
        print(f"     TV-B     : {fmt(tvb_res)}")
        test2_results[instr] = {"pullback": p_res, "tv_a": tva_res, "tv_b": tvb_res}

    # ===== TEST 3: 50/50 portfolio Pullback + TV-B on USD/JPY =====
    print("\n\n##### TEST 3: 50/50 portfolio sim — Pullback + TV-B on USD/JPY H1 5y #####\n")

    candles = load_candles(settings.historical_dir / "USD_JPY_H1_1825d.json")
    p_res = run_one(candles, "pullback", "USD_JPY", session=True)
    tvb_res = run_one(candles, "tv_fx_master_longshort", "USD_JPY", session=True)

    # Combine equity curves: 50/50 weighted, normalized to start from EQUITY
    # combined_eq(t) = 0.5 * eq_p(t) + 0.5 * eq_b(t)  (both start at EQUITY)
    p_dates, p_eqs, p_rets = daily_returns(p_res["_eq_curve"])
    b_dates, b_eqs, b_rets = daily_returns(tvb_res["_eq_curve"])
    common_dates = sorted(set(p_dates) & set(b_dates))
    p_eq_dict = dict(zip(p_dates, p_eqs))
    b_eq_dict = dict(zip(b_dates, b_eqs))
    combined_eq = [0.5 * p_eq_dict[d] + 0.5 * b_eq_dict[d] for d in common_dates]
    combined_rets = [
        np.log(combined_eq[i] / combined_eq[i - 1]) if combined_eq[i - 1] > 0 else 0.0
        for i in range(1, len(combined_eq))
    ]
    combined_eq_start = combined_eq[0] if combined_eq else EQUITY
    combined_eq_end = combined_eq[-1] if combined_eq else EQUITY

    n_years = (candles[-1].time - candles[0].time).total_seconds() / (365.25 * 86400.0)
    combined_cagr = annualised(candles[0].time, candles[-1].time,
                                combined_eq_start, combined_eq_end)

    rets_arr = np.array(combined_rets)
    if rets_arr.std() > 0:
        # Sharpe from daily returns
        combined_sharpe = float(rets_arr.mean() / rets_arr.std() * np.sqrt(252))
    else:
        combined_sharpe = 0.0

    # Max DD from combined equity curve
    eq_arr = np.array(combined_eq)
    peaks = np.maximum.accumulate(eq_arr)
    dd = (peaks - eq_arr) / peaks
    combined_max_dd = float(dd.max() * 100.0) if len(dd) else 0.0

    # Per-strategy stats from same daily returns
    p_rets_arr = np.array([p_rets[p_dates.index(d)] if d in p_dates else 0.0 for d in common_dates[1:]])
    b_rets_arr = np.array([b_rets[b_dates.index(d)] if d in b_dates else 0.0 for d in common_dates[1:]])

    print(f"  Pullback alone : CAGR={p_res['cagr_pct']:+.2f}%  "
          f"DD={p_res['max_dd_pct']:.2f}%  Sharpe={p_res['sharpe']:+.2f}  "
          f"PF={p_res['profit_factor']:.2f}")
    print(f"  TV-B alone     : CAGR={tvb_res['cagr_pct']:+.2f}%  "
          f"DD={tvb_res['max_dd_pct']:.2f}%  Sharpe={tvb_res['sharpe']:+.2f}  "
          f"PF={tvb_res['profit_factor']:.2f}")
    print(f"  50/50 PORTFOLIO: CAGR={combined_cagr:+.2f}%  "
          f"DD={combined_max_dd:.2f}%  Sharpe={combined_sharpe:+.2f}  "
          f"(combined daily returns)")

    rho = float(np.corrcoef(p_rets_arr, b_rets_arr)[0, 1]) if len(p_rets_arr) > 30 else float("nan")
    print(f"\n  Daily return correlation: {rho:+.3f}")

    # Diversification ratio
    pullback_vol = p_rets_arr.std() if p_rets_arr.std() > 0 else 1e-9
    combined_vol = rets_arr.std() if rets_arr.std() > 0 else 1e-9
    vol_reduction = 1.0 - (combined_vol / pullback_vol)
    print(f"  Combined vol / Pullback vol: {combined_vol/pullback_vol:.3f}  "
          f"({vol_reduction*100:+.1f}% vol reduction)")

    # Sharpe improvement?
    sharpe_delta = combined_sharpe - p_res["sharpe"]
    print(f"  Sharpe Δ: {sharpe_delta:+.3f} ({'IMPROVED' if sharpe_delta > 0 else 'WORSE'})")

    # Save JSON
    out = {
        "test1_tv_b_timeframes": {
            tf: {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                 for k, v in r.items()}
            for tf, r in test1_results.items()
        },
        "test2_tv_a_non_jpy": {
            instr: {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                    for k, v in r.items()}
            for instr, r in test2_results.items()
        },
        "test3_portfolio_50_50": {
            "pullback_alone": {k: v for k, v in p_res.items() if not k.startswith("_")},
            "tv_b_alone": {k: v for k, v in tvb_res.items() if not k.startswith("_")},
            "combined_cagr_pct": combined_cagr,
            "combined_max_dd_pct": combined_max_dd,
            "combined_sharpe": combined_sharpe,
            "daily_correlation": rho,
            "vol_reduction_pct": vol_reduction * 100,
            "sharpe_delta": sharpe_delta,
        },
    }
    out_path = settings.backtest_dir / "self_audit_2026_05_06.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
