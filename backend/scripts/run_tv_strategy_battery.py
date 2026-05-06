"""TV-imported strategies vs deployed Pullback — comparative battery.

3 strategies (pullback baseline + 2 TV-imported) × 3 JPY pairs × 2 session modes.
Friction-shocked. 5y H1 data. Pre-registered bars from
docs/tradingview-mcp-workflow.md applied at end.

Also computes return correlation between each TV strategy's daily equity
returns and Pullback's, to filter "redundant" strategies.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
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
INSTRUMENTS = ["USD_JPY", "GBP_JPY", "EUR_JPY"]
STRATEGY_LIST = [
    ("pullback",                "Pullback (deployed)"),
    ("tv_forex_master_v4",      "TV-A: Forex Master v4 (BB + ADX-fall)"),
    ("tv_fx_master_longshort",  "TV-B: FX Master L/S (smoothed-RSI)"),
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


def daily_returns(equity_curve: list[tuple[str, float]]) -> tuple[list[str], list[float]]:
    """Resample equity curve to daily, return (dates, log-returns)."""
    by_day: dict = {}
    for ts, eq in equity_curve:
        day = ts[:10]
        by_day[day] = eq  # last value of the day
    dates = sorted(by_day.keys())
    eqs = [by_day[d] for d in dates]
    returns = [
        np.log(eqs[i] / eqs[i - 1]) if eqs[i - 1] > 0 else 0.0
        for i in range(1, len(eqs))
    ]
    return dates[1:], returns


def run_one(candles, strategy: str, instrument: str, session: bool) -> dict:
    p = StrategyParams()
    eval_fn = STRATEGIES[strategy]
    r, trades, eq_curve, diag = run_backtest(
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
    dates, returns = daily_returns(eq_curve)
    return {
        "strategy": strategy, "instrument": instrument,
        "session_filter": session,
        "trades": r.trades,
        "trades_per_year": r.trades / max(n_years, 1e-6),
        "win_rate": r.win_rate,
        "expectancy_pct": r.expectancy_pct,
        "cagr_pct": cagr,
        "max_dd_pct": r.max_drawdown_pct,
        "sharpe": r.sharpe,
        "profit_factor": r.profit_factor,
        "exit_reasons": diag.get("exit_reasons", {}),
        "_daily_dates": dates,
        "_daily_returns": returns,
    }


def correlate(a: dict, b: dict) -> float:
    """Daily-return correlation between two backtest results, intersection of dates."""
    da = dict(zip(a["_daily_dates"], a["_daily_returns"]))
    db = dict(zip(b["_daily_dates"], b["_daily_returns"]))
    common = sorted(set(da) & set(db))
    if len(common) < 30:
        return float("nan")
    va = np.array([da[d] for d in common])
    vb = np.array([db[d] for d in common])
    if va.std() == 0 or vb.std() == 0:
        return float("nan")
    return float(np.corrcoef(va, vb)[0, 1])


def fmt_row(s: dict) -> str:
    return (
        f"{s['trades']:>4d} ({s['trades_per_year']:>4.0f}/y)  "
        f"WR={s['win_rate']:>4.1f}%  "
        f"CAGR={s['cagr_pct']:>+6.2f}%  "
        f"DD={s['max_dd_pct']:>5.2f}%  "
        f"Sharpe={s['sharpe']:>+5.2f}  "
        f"PF={s['profit_factor']:.2f}"
    )


def main() -> int:
    print("=" * 100)
    print("  TV STRATEGY BATTERY — 3 strategies × 3 JPY pairs × 2 session modes")
    print(f"  Friction: {SPREAD_PIPS}p spread + {SLIPPAGE_PIPS}p slip (2× retail)")
    print("=" * 100)
    print()

    results: dict = {}
    for instrument in INSTRUMENTS:
        path = settings.historical_dir / f"{instrument}_H1_1825d.json"
        if not path.exists():
            print(f"  ⚠ missing {path.name}")
            continue
        candles = load_candles(path)
        n_years = (candles[-1].time - candles[0].time).total_seconds() / (365.25 * 86400.0)
        print(f"\n  -- {instrument}: {len(candles):,} bars  "
              f"{candles[0].time.date()} → {candles[-1].time.date()}  ({n_years:.2f}y) --")

        for session in [True, False]:
            mode = "in-session only" if session else "24/5 (faithful)"
            print(f"\n     [{mode}]")
            print(f"     {'strategy':40s}  trades(rate)   WR     CAGR     DD     Sharpe   PF")
            print(f"     {'-'*40}  {'-'*12}  {'-'*5}  {'-'*7}  {'-'*5}  {'-'*7}  {'-'*4}")
            for skey, sname in STRATEGY_LIST:
                m = run_one(candles, skey, instrument, session)
                results[(skey, instrument, session)] = m
                print(f"     {sname:40s}  {fmt_row(m)}")

    # Correlation matrix: TV strategies vs Pullback (within same instrument + mode)
    print("\n\n" + "=" * 100)
    print("  RETURN CORRELATION (TV strategy vs Pullback baseline, daily, in-session mode)")
    print("=" * 100)
    print(f"  {'instrument':12s}  {'TV-A (Forex Master v4)':>26s}  {'TV-B (FX Master L/S)':>24s}")
    print(f"  {'-'*12}  {'-'*26}  {'-'*24}")
    for instrument in INSTRUMENTS:
        if (("pullback", instrument, True) not in results):
            continue
        baseline = results[("pullback", instrument, True)]
        c_a = correlate(baseline, results[("tv_forex_master_v4", instrument, True)])
        c_b = correlate(baseline, results[("tv_fx_master_longshort", instrument, True)])
        print(f"  {instrument:12s}  {c_a:>+26.3f}  {c_b:>+24.3f}")

    # Apply pre-registered bars (from docs/tradingview-mcp-workflow.md)
    # TV-A: Sharpe ≥ 0.40, TV-B: CAGR ≥ +1.0%, TV-C: PF ≥ 1.05,
    # TV-D: Max DD ≤ 12%, TV-E: trades/yr ≥ 30
    print("\n\n" + "=" * 100)
    print("  PRE-REGISTERED BARS (per workflow doc; applied to in-session mode)")
    print("=" * 100)
    print(f"  Bars: Sharpe ≥ 0.40, CAGR ≥ +1.0%, PF ≥ 1.05, MaxDD ≤ 12%, trades/yr ≥ 30")
    print(f"  TV-G: low correlation with Pullback (|ρ| ≤ 0.85) for diversification")
    print()
    print(f"  {'strategy + instrument':50s}  Pass?  {'reasons if fail':40s}")
    print(f"  {'-'*50}  {'-'*5}  {'-'*40}")
    for skey, sname in STRATEGY_LIST:
        if skey == "pullback":
            continue
        for instrument in INSTRUMENTS:
            m = results.get((skey, instrument, True))
            if not m:
                continue
            fails = []
            if m["sharpe"] < 0.40:           fails.append(f"Sharpe {m['sharpe']:.2f}<0.40")
            if m["cagr_pct"] < 1.0:          fails.append(f"CAGR {m['cagr_pct']:.2f}%<1.0%")
            if m["profit_factor"] < 1.05:    fails.append(f"PF {m['profit_factor']:.2f}<1.05")
            if m["max_dd_pct"] > 12.0:       fails.append(f"DD {m['max_dd_pct']:.2f}%>12%")
            if m["trades_per_year"] < 30:    fails.append(f"rate {m['trades_per_year']:.0f}/y<30")
            baseline = results.get(("pullback", instrument, True))
            if baseline:
                rho = correlate(baseline, m)
                if not np.isnan(rho) and abs(rho) > 0.85:
                    fails.append(f"|ρ| {abs(rho):.2f}>0.85")
            label = f"{skey} on {instrument}"
            verdict = "PASS" if not fails else "FAIL"
            print(f"  {label:50s}  {verdict:5s}  {('; '.join(fails))[:40]}")

    # Save JSON output (strip numpy arrays before JSON serialization)
    serial = {}
    for k, v in results.items():
        out = {x: y for x, y in v.items() if not x.startswith("_")}
        out["key"] = list(k)
        serial[f"{k[0]}__{k[1]}__{'session' if k[2] else 'no_session'}"] = out
    out_path = settings.backtest_dir / "tv_strategy_battery.json"
    out_path.write_text(json.dumps(serial, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
