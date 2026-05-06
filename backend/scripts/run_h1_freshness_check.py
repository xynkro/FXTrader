"""H1 freshness check — does deployed Pullback H1 default hold on
2014-2017 fresh data for a given instrument?

Usage:
    python -m scripts.run_h1_freshness_check                  # USD_JPY (default)
    python -m scripts.run_h1_freshness_check --instrument GBP_JPY

For USD_JPY, aggregates from existing M15 12y data. For other instruments,
expects the H1 12y file at backend/data/historical/{INSTR}_H1_4380d.json.

Decisive question: is the deployed-default Pullback strategy a robust
regime-spanning edge on this instrument, or only a regime-fitter?
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams, aggregate_to_h1


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


def get_h1_long_history(instrument: str) -> list[Candle]:
    """Return ~12y of H1 candles for the given instrument.

    Prefers a direct H1 4380d file; falls back to aggregating from
    M15 4380d if the H1 file isn't on disk.
    """
    h1_path = settings.historical_dir / f"{instrument}_H1_4380d.json"
    if h1_path.exists():
        return load_candles(h1_path)
    m15_path = settings.historical_dir / f"{instrument}_M15_4380d.json"
    if m15_path.exists():
        m15 = load_candles(m15_path)
        return aggregate_to_h1(m15)
    raise FileNotFoundError(
        f"No 12y data available for {instrument}. Need either "
        f"{instrument}_H1_4380d.json or {instrument}_M15_4380d.json."
    )


def slice_candles(candles, start, end):
    return [c for c in candles if start <= c.time < end]


def annualised(start, end, eq0, eq1):
    seconds = (end - start).total_seconds()
    years = max(seconds / (365.25 * 24 * 3600.0), 1e-6)
    if eq1 / eq0 <= 0:
        return -100.0
    return ((eq1 / eq0) ** (1.0 / years) - 1.0) * 100.0


def evaluate(candles, instrument, label):
    p = StrategyParams()  # DEFAULT params
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
    }


def fmt(s):
    return (f"  trades={s['trades']:>4d} ({s['trades_per_year']:>5.0f}/y)  "
            f"WR={s['win_rate_pct']:>5.1f}%  "
            f"CAGR={s['cagr_pct']:>+6.2f}%  "
            f"DD={s['max_dd_pct']:>5.2f}%  "
            f"Sharpe={s['sharpe']:>+5.2f}  "
            f"PF={s['profit_factor']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="USD_JPY")
    args = ap.parse_args()
    instr = args.instrument

    print("=" * 78)
    print(f"  H1 FRESHNESS CHECK — {instr}, deployed Pullback default")
    print("=" * 78)
    print()

    h1_full = get_h1_long_history(instr)
    print(f"  H1 series: {len(h1_full):,} bars  "
          f"{h1_full[0].time.date()} → {h1_full[-1].time.date()}\n")

    fresh_start = datetime(2014, 5, 1, tzinfo=timezone.utc)
    fresh_end   = datetime(2017, 5, 1, tzinfo=timezone.utc)
    deployed_start = datetime(2021, 5, 1, tzinfo=timezone.utc)
    deployed_end   = datetime(2026, 5, 1, tzinfo=timezone.utc)

    fresh = slice_candles(h1_full, fresh_start, fresh_end)
    deployed = slice_candles(h1_full, deployed_start, deployed_end)
    print(f"  Fresh window  (2014-2017): {len(fresh):,} bars")
    print(f"  Recent window (2021-2026): {len(deployed):,} bars\n")

    if len(fresh) < 100:
        print(f"  ⚠ Fresh window has only {len(fresh)} bars; data may not "
              f"reach back to 2014. Skipping.")
        return 1

    print("=== FRESH (2014-2017) ===")
    f = evaluate(fresh, instr, "fresh_2014_2017")
    print(fmt(f))
    print()

    print("=== RECENT (2021-2026) ===")
    d = evaluate(deployed, instr, "recent_2021_2026")
    print(fmt(d))
    print()

    print("=== Yearly breakdown — fresh window ===")
    yearly = []
    for y in range(2014, 2017):
        slice_start = datetime(y, 5, 1, tzinfo=timezone.utc)
        slice_end = datetime(y + 1, 5, 1, tzinfo=timezone.utc)
        candles = slice_candles(h1_full, slice_start, slice_end)
        if not candles:
            continue
        r = evaluate(candles, instr, f"{y}_{y+1}")
        yearly.append(r)
        print(f"  {y}-05 → {y+1}-05:  " + fmt(r))
    print()

    print("=" * 78)
    print("  VERDICT")
    print("=" * 78)
    if f["sharpe"] >= 0.4 and f["expectancy_pct"] > 0:
        print(f"  {instr} PASSES freshness — Sharpe {f['sharpe']:.2f}, "
              f"CAGR {f['cagr_pct']:+.2f}%. Robust across regimes.")
        verdict = "ROBUST"
    elif f["sharpe"] > 0 and f["expectancy_pct"] > 0:
        print(f"  {instr} WEAK PASS — Sharpe {f['sharpe']:.2f} positive but below ~0.4.")
        verdict = "WEAK_PASS"
    else:
        print(f"  {instr} FAILS freshness — Sharpe {f['sharpe']:.2f}, "
              f"expectancy {f['expectancy_pct']:+.4f}%/trade.")
        verdict = "FAILS"
    print(f"\n  Sharpe gap (recent → fresh): {d['sharpe']:.2f} → {f['sharpe']:.2f}  "
          f"(Δ={d['sharpe']-f['sharpe']:+.2f})")
    print("=" * 78)

    out = {
        "instrument": instr,
        "fresh_window": [fresh_start.isoformat(), fresh_end.isoformat()],
        "recent_window": [deployed_start.isoformat(), deployed_end.isoformat()],
        "fresh_metrics": f,
        "recent_metrics": d,
        "yearly_fresh": yearly,
        "verdict": verdict,
    }
    out_path = settings.backtest_dir / f"h1_freshness_{instr}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
