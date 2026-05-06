"""Pre-computed parameter sensitivity sweep for the deployed Pullback strategy.

A read-only diagnostic for the PWA. For each strategy parameter, sweeps a
range of values around the deployed default, runs a friction-shocked
backtest at each point, records headline metrics. Output is a JSON file
consumed by the /api/sensitivity endpoint and rendered as static curves
in the PWA's Strategy tab.

Purpose: lets the user see whether the deployed parameter sits on a broad
plateau (= robust edge) or a sharp peak (= overfit / fragile). It does NOT
recommend changes, and the PWA renders the data without any "apply this
value" workflow. Diagnostic, not actuator.

Why this matters: cherry-picking the "best" parameter value from a sweep
on already-seen historical data is the textbook backtest-overfitting
trap. So the dashboard is intentionally lossy — it shows you the SHAPE,
not a "winner".

Run with:
    cd backend && python -m scripts.run_sensitivity
"""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams


# Friction-shocked: matches the cost regime the original 4.7% number was
# computed under (2× of FX defaults).
SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.4

# Sweep grids. The deployed value is included in each list and falls
# roughly in the middle. Span is wide enough to see plateau vs peak,
# tight enough that the sweep finishes in reasonable time.
SWEEPS: dict[str, list] = {
    "sma_long":             [50, 70, 85, 100, 115, 130, 150, 175, 200],
    "sma_short":            [10, 14, 17, 20, 24, 28, 35, 40],
    "pullback_lookback":    [1, 2, 3, 4, 5, 6, 8],
    "trend_slope_lookback": [5, 7, 10, 12, 15, 20, 25],
    "atr_period":           [7, 10, 14, 18, 22, 28],
    "stop_atr_mult":        [1.0, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 3.5],
    "min_atr_pips":         [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0],
    "min_stop_pips":        [2.0, 3.5, 5.0, 6.5, 8.0, 10.0],
    "cooldown_bars":        [5, 10, 15, 20, 25, 30, 40, 60],
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


def annualised_return(start_dt: datetime, end_dt: datetime,
                      starting_equity: float, final_equity: float) -> float:
    """CAGR-style annualisation. Uses calendar years between first and last
    bar — close enough for our diagnostic purposes."""
    if final_equity <= 0 or starting_equity <= 0:
        return 0.0
    seconds = (end_dt - start_dt).total_seconds()
    years = max(seconds / (365.25 * 24 * 3600.0), 1e-6)
    if final_equity / starting_equity <= 0:
        return 0.0
    return ((final_equity / starting_equity) ** (1.0 / years) - 1.0) * 100.0


def metrics_for(candles: list[Candle], params: StrategyParams,
                equity: float = 10_000.0) -> dict:
    eval_fn = STRATEGIES["pullback"]
    # Match the DEPLOYED engine's semantics:
    #   signals only fire inside the session window,
    #   but trades that opened in-session are allowed to hold across the
    #   boundary until their stop is hit (no forced session-end close).
    # The pre-registered protocol's 4.7% friction-shocked CAGR was
    # measured under exactly these rules (Test 1 of the robustness pack).
    r, trades, _, _ = run_backtest(
        candles, starting_equity=equity, params=params,
        spread_pips=SPREAD_PIPS, slippage_pips=SLIPPAGE_PIPS,
        evaluate_fn=eval_fn,
        signal_in_session_only=True,
        force_close_at_session_end=False,
        macro_features=None,
    )
    cagr = annualised_return(
        candles[0].time, candles[-1].time, r.starting_equity, r.final_equity
    )
    return {
        "trades": r.trades,
        "win_rate_pct": round(r.win_rate, 2),
        "expectancy_pct": round(r.expectancy_pct, 4),
        "total_return_pct": round(r.total_return_pct, 2),
        "cagr_pct": round(cagr, 2),
        "max_dd_pct": round(r.max_drawdown_pct, 2),
        "sharpe": round(r.sharpe, 2),
        "profit_factor": round(r.profit_factor, 2),
        "avg_r": round(r.avg_r, 3),
    }


def run_sweep(candles: list[Candle], p_default: StrategyParams,
              sweeps: dict[str, list]) -> dict:
    out: dict = {}
    for pname, values in sweeps.items():
        results = []
        print(f"\n  -- sweeping {pname} --")
        for v in values:
            p = replace(p_default, **{pname: v})
            try:
                m = metrics_for(candles, p)
                marker = " *deployed*" if v == getattr(p_default, pname) else ""
                print(f"    {pname}={v}: trades={m['trades']:3d}  "
                      f"CAGR={m['cagr_pct']:+5.2f}%  Sharpe={m['sharpe']:+.2f}  "
                      f"DD={m['max_dd_pct']:.2f}%  WR={m['win_rate_pct']:.1f}%"
                      f"{marker}")
            except Exception as e:
                m = {"error": str(e)}
                print(f"    {pname}={v}: ERROR {e}")
            results.append({"value": v, "metrics": m})
        out[pname] = {
            "deployed_value": getattr(p_default, pname),
            "values": values,
            "results": results,
        }
    return out


def main() -> int:
    fname = f"{settings.INSTRUMENT}_{settings.GRANULARITY}_1825d.json"
    path = settings.historical_dir / fname
    if not path.exists():
        print(f"missing {path}")
        return 2

    print(f"Loading {path.name}…")
    candles = load_candles(path)
    print(f"  {len(candles):,} bars  "
          f"{candles[0].time.date()} → {candles[-1].time.date()}")

    p_default = StrategyParams()

    print("\n=== Baseline (deployed params, friction-shocked) ===")
    base = metrics_for(candles, p_default)
    print(f"  trades={base['trades']}  CAGR={base['cagr_pct']:+.2f}%  "
          f"Sharpe={base['sharpe']:+.2f}  DD={base['max_dd_pct']:.2f}%  "
          f"WR={base['win_rate_pct']:.1f}%  PF={base['profit_factor']:.2f}")

    print("\n=== Sensitivity sweep ===")
    sweeps = run_sweep(candles, p_default, SWEEPS)

    out_path = settings.backtest_dir / "sensitivity_pullback.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "pullback",
        "instrument": settings.INSTRUMENT,
        "granularity": settings.GRANULARITY,
        "data_window_bars": len(candles),
        "data_window_start": candles[0].time.isoformat(),
        "data_window_end": candles[-1].time.isoformat(),
        "spread_pips": SPREAD_PIPS,
        "slippage_pips": SLIPPAGE_PIPS,
        "deployed_params": asdict(p_default),
        "baseline_metrics": base,
        "sweeps": sweeps,
        "disclaimer": (
            "This is a one-factor sensitivity sweep on already-seen "
            "historical data. It is a DIAGNOSTIC for fragility, not a "
            "basis for picking 'better' parameter values. Selecting the "
            "value with the highest CAGR from this output is data mining "
            "and will overfit. The deployed parameters are locked for "
            "the current evaluation window."
        ),
    }, indent=2))
    print(f"\nSaved {out_path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
