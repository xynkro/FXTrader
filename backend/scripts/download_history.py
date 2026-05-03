"""Download historical M5 candles from OANDA in chunks (5000-bar limit per
request) and persist to a single JSON file under backend/data/historical/."""
from __future__ import annotations

import argparse
import json
import sys
import time as time_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.oanda_client import OandaClient, OandaError


GRANULARITY_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D": 1440,
}


def chunk_ranges(start: datetime, end: datetime, gran_minutes: int, max_bars: int = 4500):
    span = timedelta(minutes=gran_minutes * max_bars)
    cur = start
    while cur < end:
        nxt = min(cur + span, end)
        yield cur, nxt
        cur = nxt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365,
                    help="how many days back from now to fetch")
    ap.add_argument("--instrument", default=None)
    ap.add_argument("--granularity", default=None)
    args = ap.parse_args()

    instrument = args.instrument or settings.INSTRUMENT
    granularity = args.granularity or settings.GRANULARITY
    if granularity not in GRANULARITY_MINUTES:
        print(f"unsupported granularity {granularity}", file=sys.stderr)
        return 2

    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(days=args.days)
    out = settings.historical_dir / f"{instrument}_{granularity}_{args.days}d.json"

    try:
        client = OandaClient()
    except OandaError as e:
        print(f"OANDA init failed: {e}", file=sys.stderr)
        print("Did you set OANDA_API_KEY in .env?", file=sys.stderr)
        return 3

    all_candles: list[dict] = []
    print(f"Fetching {instrument} {granularity} from {start} to {end}")
    for chunk_start, chunk_end in chunk_ranges(
        start, end, GRANULARITY_MINUTES[granularity]
    ):
        for attempt in range(3):
            try:
                candles = client._candles_sync(
                    instrument=instrument,
                    granularity=granularity,
                    from_time=chunk_start,
                    to_time=chunk_end,
                )
                break
            except OandaError as e:
                if attempt == 2:
                    print(f"failed chunk {chunk_start} - {chunk_end}: {e}",
                          file=sys.stderr)
                    candles = []
                    break
                time_mod.sleep(1.5 ** attempt)
        all_candles.extend(
            {
                "time": c.time.isoformat(),
                "open": c.open, "high": c.high,
                "low": c.low, "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        )
        print(f"  {chunk_start.date()} → {chunk_end.date()}  total={len(all_candles)}")
        time_mod.sleep(0.15)  # be polite

    # Dedupe by timestamp + sort
    seen: dict[str, dict] = {}
    for c in all_candles:
        seen[c["time"]] = c
    final = [seen[k] for k in sorted(seen.keys())]
    out.write_text(json.dumps(final))
    print(f"\nWrote {len(final)} candles to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
