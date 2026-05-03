"""Run the backtest against saved historical data, print stats, save results."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from app.backtest import run_backtest, save_results
from app.config import settings
from app.models import Candle
from app.strategy import StrategyParams


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--instrument", default=None)
    ap.add_argument("--granularity", default=None)
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--label", default="default")
    args = ap.parse_args()

    instrument = args.instrument or settings.INSTRUMENT
    granularity = args.granularity or settings.GRANULARITY
    fname = f"{instrument}_{granularity}_{args.days}d.json"
    path = settings.historical_dir / fname
    if not path.exists():
        print(f"missing data file {path}", file=sys.stderr)
        print(f"run: python -m scripts.download_history --days {args.days}",
              file=sys.stderr)
        return 2

    candles = load_candles(path)
    print(f"Loaded {len(candles)} candles "
          f"from {candles[0].time} to {candles[-1].time}")

    result, trades, curve = run_backtest(
        candles=candles,
        starting_equity=args.equity,
        params=StrategyParams(),
    )

    folder = save_results(result, trades, curve, label=args.label)

    print()
    print("=" * 60)
    print(f"  {result.instrument} backtest — saved to {folder.name}")
    print("=" * 60)
    print(f"  Period            : {result.start} → {result.end}")
    print(f"  Bars              : {result.bars:,}")
    print(f"  Trades            : {result.trades}  (W:{result.wins} / L:{result.losses})")
    print(f"  Win rate          : {result.win_rate:.2f}%")
    print(f"  Avg R-multiple    : {result.avg_r:+.3f}")
    print(f"  Expectancy/trade  : {result.expectancy_pct:+.3f}%")
    print(f"  Total return      : {result.total_return_pct:+.2f}%")
    print(f"  Max drawdown      : {result.max_drawdown_pct:.2f}%")
    print(f"  Sharpe (annual.)  : {result.sharpe:.2f}")
    print(f"  Profit factor     : {result.profit_factor:.2f}")
    print(f"  Final equity      : ${result.final_equity:,.2f}  "
          f"(start ${result.starting_equity:,.2f})")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
