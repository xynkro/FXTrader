"""Focused 5y comparison: liquidity_sweep on M15 vs pullback on H1.

Both run on USD_JPY, same friction-shocked execution costs (1.0 pip
spread, 0.4 pip slippage), same starting equity, no forced session-end
close, IS/OOS split (80/20).

The 1y M15 liquidity_sweep result showed +5.03% CAGR / Sharpe 0.96 /
PF 1.16 on 304 trades. This is the falsification test: does that
result hold across 5y or wash out as noise?
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


def run(strategy: str, candles: list[Candle], label: str, equity: float = 110_000.0) -> dict:
    eval_fn = STRATEGIES[strategy]
    p = StrategyParams()
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
    yearly = diag.get("yearly", {})
    return {
        "label": label,
        "strategy": strategy,
        "trades": r.trades,
        "wins": r.wins,
        "losses": r.losses,
        "win_rate_pct": r.win_rate,
        "avg_r": r.avg_r,
        "expectancy_pct": r.expectancy_pct,
        "total_return_pct": r.total_return_pct,
        "cagr_pct": cagr,
        "max_dd_pct": r.max_drawdown_pct,
        "sharpe": r.sharpe,
        "profit_factor": r.profit_factor,
        "starting_equity": r.starting_equity,
        "final_equity": r.final_equity,
        "avg_bars_held": diag.get("avg_bars_held", 0),
        "avg_stop_pips": diag.get("avg_stop_distance_pips", 0),
        "yearly": yearly,
    }


def fmt(stat: dict) -> str:
    return "\n".join([
        f"  Trades        : {stat['trades']:,}  (W:{stat['wins']} / L:{stat['losses']})",
        f"  Win rate      : {stat['win_rate_pct']:.2f}%",
        f"  Avg R         : {stat['avg_r']:+.3f}",
        f"  Expectancy    : {stat['expectancy_pct']:+.4f}% / trade",
        f"  Total return  : {stat['total_return_pct']:+.2f}%",
        f"  CAGR          : {stat['cagr_pct']:+.2f}%",
        f"  Max DD        : {stat['max_dd_pct']:.2f}%",
        f"  Sharpe        : {stat['sharpe']:+.2f}",
        f"  Profit factor : {stat['profit_factor']:.2f}",
        f"  Final equity  : ${stat['final_equity']:,.2f}  (start ${stat['starting_equity']:,.2f})",
        f"  Avg duration  : {stat['avg_bars_held']:.1f} bars",
        f"  Avg stop      : {stat['avg_stop_pips']:.1f} pips",
    ])


def split_is_oos(candles: list[Candle], pct: int = 80) -> tuple[list[Candle], list[Candle]]:
    n = len(candles)
    split = int(n * pct / 100)
    return candles[:split], candles[split:]


def main():
    print("=" * 78)
    print("  liquidity_sweep M15 (5y) vs pullback H1 (5y) — falsification test")
    print(f"  USD_JPY, friction-shocked (spread {SPREAD_PIPS}p + slip {SLIPPAGE_PIPS}p)")
    print(f"  Same starting equity, no forced session-end close")
    print("=" * 78)
    print()

    h1 = settings.historical_dir / "USD_JPY_H1_1825d.json"
    m15 = settings.historical_dir / "USD_JPY_M15_1825d.json"

    print("Loading data…")
    h1_candles = load_candles(h1)
    m15_candles = load_candles(m15)
    print(f"  H1 : {len(h1_candles):,} bars  "
          f"{h1_candles[0].time.date()} → {h1_candles[-1].time.date()}")
    print(f"  M15: {len(m15_candles):,} bars  "
          f"{m15_candles[0].time.date()} → {m15_candles[-1].time.date()}")
    print()

    # === Pullback H1 (full + IS/OOS) ===
    print("--- PULLBACK on H1 (5y, full sample) ---")
    p_full = run("pullback", h1_candles, "pullback_H1_full")
    print(fmt(p_full))
    print()

    h1_is, h1_oos = split_is_oos(h1_candles, 80)
    p_is = run("pullback", h1_is, "pullback_H1_IS")
    p_oos = run("pullback", h1_oos, "pullback_H1_OOS")
    print("  IS/OOS split (80/20):")
    print(f"    IS  exp={p_is['expectancy_pct']:+.4f}%  PF={p_is['profit_factor']:.2f}  "
          f"WR={p_is['win_rate_pct']:.1f}%  CAGR={p_is['cagr_pct']:+.2f}%")
    print(f"    OOS exp={p_oos['expectancy_pct']:+.4f}%  PF={p_oos['profit_factor']:.2f}  "
          f"WR={p_oos['win_rate_pct']:.1f}%  CAGR={p_oos['cagr_pct']:+.2f}%")
    print()

    # === Liquidity_sweep M15 (full + IS/OOS) ===
    print("--- LIQUIDITY_SWEEP on M15 (5y, full sample) ---")
    l_full = run("liquidity_sweep", m15_candles, "liquidity_sweep_M15_full")
    print(fmt(l_full))
    print()

    m15_is, m15_oos = split_is_oos(m15_candles, 80)
    l_is = run("liquidity_sweep", m15_is, "liquidity_sweep_M15_IS")
    l_oos = run("liquidity_sweep", m15_oos, "liquidity_sweep_M15_OOS")
    print("  IS/OOS split (80/20):")
    print(f"    IS  exp={l_is['expectancy_pct']:+.4f}%  PF={l_is['profit_factor']:.2f}  "
          f"WR={l_is['win_rate_pct']:.1f}%  CAGR={l_is['cagr_pct']:+.2f}%")
    print(f"    OOS exp={l_oos['expectancy_pct']:+.4f}%  PF={l_oos['profit_factor']:.2f}  "
          f"WR={l_oos['win_rate_pct']:.1f}%  CAGR={l_oos['cagr_pct']:+.2f}%")
    print()

    # === Yearly breakdowns ===
    print("--- Yearly P&L (USD, full sample) ---")
    print(f"  {'Year':6s} {'pullback H1':>16s}   {'liquidity_sweep M15':>22s}")
    years = sorted(set(p_full["yearly"].keys()) | set(l_full["yearly"].keys()))
    for y in years:
        py = p_full["yearly"].get(y, {"pnl": 0, "trades": 0, "wins": 0, "losses": 0})
        ly = l_full["yearly"].get(y, {"pnl": 0, "trades": 0, "wins": 0, "losses": 0})
        pwr = (100.0 * py["wins"] / py["trades"]) if py["trades"] else 0.0
        lwr = (100.0 * ly["wins"] / ly["trades"]) if ly["trades"] else 0.0
        print(f"  {y:6s}  ${py['pnl']:>+10,.0f} (n={py['trades']:>3d}, {pwr:>4.1f}%)   "
              f"${ly['pnl']:>+10,.0f} (n={ly['trades']:>4d}, {lwr:>4.1f}%)")

    out = {
        "spread_pips": SPREAD_PIPS,
        "slippage_pips": SLIPPAGE_PIPS,
        "pullback_H1_full": p_full,
        "pullback_H1_IS": p_is,
        "pullback_H1_OOS": p_oos,
        "liquidity_sweep_M15_full": l_full,
        "liquidity_sweep_M15_IS": l_is,
        "liquidity_sweep_M15_OOS": l_oos,
    }
    out_path = settings.backtest_dir / "liquidity_sweep_5y_focus.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  Saved JSON: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
