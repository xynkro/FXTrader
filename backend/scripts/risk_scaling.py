"""Quick what-if: how do backtest stats scale as RISK_PER_TRADE_PCT goes
from 0.25% to 5%?

Same strategy, same parameters, same data window, same friction. Only
the risk-fraction setting changes. This isolates the pure-leverage
effect from any edge change.

Note: the deployed engine's daily loss limit (-2% kill switch) is NOT
modeled here — the backtest doesn't honor it because in production a
trip just means the engine stops trading until manual reset. So the
high-risk lines here describe what the *math* would do; in real life
the kill switch trips on the first losing day at 5% risk.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.backtest import run_backtest
from app.config import settings
from app.models import Candle
from app.strategy import STRATEGIES, StrategyParams


SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 0.4
RISK_LEVELS = [0.25, 0.5, 1.0, 2.5, 5.0]


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


def main():
    fname = f"{settings.INSTRUMENT}_{settings.GRANULARITY}_1825d.json"
    candles = load_candles(settings.historical_dir / fname)
    print(f"Loaded {len(candles):,} bars  "
          f"{candles[0].time.date()} -> {candles[-1].time.date()}\n")

    eval_fn = STRATEGIES["pullback"]
    p = StrategyParams()

    print(f"{'risk%':>6} | {'trades':>6} {'lev_cap':>8} | "
          f"{'CAGR':>8} {'Sharpe':>7} {'maxDD':>7} {'PF':>5} {'finEq':>10}")
    print("-" * 80)

    rows = []
    for r in RISK_LEVELS:
        # Override settings.RISK_PER_TRADE_PCT for this run only.
        prev = settings.RISK_PER_TRADE_PCT
        settings.RISK_PER_TRADE_PCT = r
        try:
            res, trades, _, diag = run_backtest(
                candles, starting_equity=10_000.0, params=p,
                spread_pips=SPREAD_PIPS, slippage_pips=SLIPPAGE_PIPS,
                evaluate_fn=eval_fn,
                signal_in_session_only=True,
                force_close_at_session_end=False,
                macro_features=None,
            )
            cagr = annualised(candles[0].time, candles[-1].time,
                              res.starting_equity, res.final_equity)
            lev_attempts = diag.get("leverage_cap_attempts", 0)
            lev_binds = diag.get("leverage_cap_binds", 0)
            lev_pct = (100.0 * lev_binds / lev_attempts) if lev_attempts else 0.0
            rows.append({
                "risk_pct": r,
                "trades": res.trades,
                "lev_cap_pct": lev_pct,
                "cagr_pct": cagr,
                "sharpe": res.sharpe,
                "max_dd_pct": res.max_drawdown_pct,
                "profit_factor": res.profit_factor,
                "final_equity": res.final_equity,
            })
            print(f"{r:>5.2f}% | {res.trades:>6d} {lev_pct:>7.1f}% | "
                  f"{cagr:>+7.2f}% {res.sharpe:>+7.2f} "
                  f"{res.max_drawdown_pct:>6.2f}% {res.profit_factor:>5.2f} "
                  f"${res.final_equity:>9,.0f}")
        finally:
            settings.RISK_PER_TRADE_PCT = prev

    print()
    print("Notes:")
    print(" * Sharpe is roughly constant — risk just scales return and DD")
    print("   together; it's pure leverage, not more edge.")
    print(" * lev_cap = % of trade signals where the engine's 30:1 leverage")
    print("   cap binds. When it binds, you get LESS than the requested risk.")
    print(" * The deployed -2% daily kill switch is NOT modeled — at 5%")
    print("   risk, ONE stop-out trips it. In production the engine would")
    print("   shut off on the first losing day.")


if __name__ == "__main__":
    main()
