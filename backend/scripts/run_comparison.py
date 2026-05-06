"""Cross-strategy / cross-timeframe comparison: how do scalping variants
look against the deployed Pullback?

Runs each strategy in STRATEGIES against the same instrument across
multiple timeframes, with identical friction-shocked execution costs
(1.0 pip spread, 0.4 pip slippage = 2× retail FX defaults). Reports
the headline metrics in a single table.

NOTE: this is a DISPLAY tool. The output is for comparison only —
selecting a "winner" from this table and shipping it on already-seen
data is the canonical overfitting trap, and the deployed Pullback
strategy is locked for the current evaluation window.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams


SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.4

# Strategies grouped by character — for the printed table.
STRATEGY_GROUPS = {
    "trend": ["donchian", "pullback"],
    "scalp": ["zscore", "session_vwap", "bb_squeeze", "volsqueeze",
              "liquidity_sweep", "engulfing_pivot"],
}
ALL_STRATS = STRATEGY_GROUPS["trend"] + STRATEGY_GROUPS["scalp"]

# Timeframe → (filename suffix, label)
TIMEFRAMES = [
    ("H1_1825d", "H1 (5y)"),
    ("M15_365d", "M15 (1y)"),
    ("M5_365d",  "M5 (1y)"),
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


def annualised(start_dt: datetime, end_dt: datetime, eq0: float, eq1: float) -> float:
    seconds = (end_dt - start_dt).total_seconds()
    years = max(seconds / (365.25 * 24 * 3600.0), 1e-6)
    if eq1 / eq0 <= 0:
        return -100.0
    return ((eq1 / eq0) ** (1.0 / years) - 1.0) * 100.0


def run_one(strategy: str, candles: list[Candle], equity: float = 10_000.0) -> dict | None:
    eval_fn = STRATEGIES[strategy]
    p = StrategyParams()
    try:
        r, trades, _, diag = run_backtest(
            candles, starting_equity=equity, params=p,
            spread_pips=SPREAD_PIPS, slippage_pips=SLIPPAGE_PIPS,
            evaluate_fn=eval_fn,
            signal_in_session_only=True,
            force_close_at_session_end=False,
            macro_features=None,
        )
        cagr = annualised(candles[0].time, candles[-1].time,
                          r.starting_equity, r.final_equity)
        return {
            "strategy": strategy,
            "trades": r.trades,
            "trades_per_year": round(r.trades / max(
                (candles[-1].time - candles[0].time).total_seconds() / (365.25 * 86400.0),
                1e-6
            ), 1),
            "win_rate_pct": round(r.win_rate, 1),
            "avg_r": round(r.avg_r, 3),
            "expectancy_pct": round(r.expectancy_pct, 4),
            "cagr_pct": round(cagr, 2),
            "max_dd_pct": round(r.max_drawdown_pct, 2),
            "sharpe": round(r.sharpe, 2),
            "profit_factor": round(r.profit_factor, 2),
            "avg_bars_held": round(diag.get("avg_bars_held", 0.0), 1),
            "session_end_closes": diag.get("session_end_closes", 0),
        }
    except Exception as e:
        return {"strategy": strategy, "error": str(e)}


def fmt_row(s: str, m: dict, group: str) -> str:
    if "error" in m:
        return f"  {s:18s} ERROR: {m['error'][:60]}"
    n = m["trades"]
    if n == 0:
        return (f"  {group:5s} {s:18s} {n:>5d}     —     —     —     —     —     —     —     —")
    return (
        f"  {group:5s} {s:18s} "
        f"{n:>5d} "
        f"{m['trades_per_year']:>6.1f}/y "
        f"{m['win_rate_pct']:>5.1f}% "
        f"{m['avg_r']:>+6.3f}R "
        f"{m['cagr_pct']:>+7.2f}% "
        f"{m['max_dd_pct']:>6.2f}% "
        f"{m['sharpe']:>+6.2f} "
        f"{m['profit_factor']:>5.2f} "
        f"{m['avg_bars_held']:>5.1f}b"
    )


def main() -> int:
    instrument = "USD_JPY"
    print(f"\n{'='*100}")
    print(f"  CROSS-STRATEGY / CROSS-TIMEFRAME COMPARISON  —  {instrument}")
    print(f"  Friction: spread {SPREAD_PIPS}p + slippage {SLIPPAGE_PIPS}p (2× retail FX) — same as deployed")
    print(f"  Session: in-session signals only, no forced session-end close (matches deployed engine)")
    print(f"{'='*100}\n")

    out_for_pwa: dict = {
        "instrument": instrument,
        "spread_pips": SPREAD_PIPS,
        "slippage_pips": SLIPPAGE_PIPS,
        "generated_at": datetime.utcnow().isoformat() + "+00:00",
        "results_by_timeframe": {},
    }

    for suffix, label in TIMEFRAMES:
        path = settings.historical_dir / f"{instrument}_{suffix}.json"
        if not path.exists():
            print(f"  -- {label}: missing {path.name}, skipping --\n")
            continue

        candles = load_candles(path)
        n_years = (candles[-1].time - candles[0].time).total_seconds() / (365.25 * 86400.0)

        print(f"  -- {label}  {len(candles):,} bars  "
              f"{candles[0].time.date()} → {candles[-1].time.date()}  "
              f"({n_years:.2f}y) --")
        print(f"  {'group':5s} {'strategy':18s} {'trades':>5s}  {'rate':>7s}  {'WR':>6s} "
              f"{'avgR':>7s} {'CAGR':>8s} {'maxDD':>7s} {'Sharp':>7s} {'PF':>5s} {'dur':>6s}")
        print(f"  {'-'*5}  {'-'*18}  {'-'*5}  {'-'*7}  {'-'*6} {'-'*7} {'-'*8} {'-'*7} {'-'*7} {'-'*5} {'-'*6}")

        tf_results = {}
        for group_name, strats in STRATEGY_GROUPS.items():
            for s in strats:
                m = run_one(s, candles)
                tf_results[s] = m
                print(fmt_row(s, m, group_name))
            print()

        out_for_pwa["results_by_timeframe"][label] = {
            "bars": len(candles),
            "start": candles[0].time.isoformat(),
            "end": candles[-1].time.isoformat(),
            "results": tf_results,
        }

    out_path = settings.backtest_dir / "comparison.json"
    out_path.write_text(json.dumps(out_for_pwa, indent=2))
    print(f"\n  Saved JSON: {out_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
