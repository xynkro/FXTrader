"""External macro data sources.

Currently only FRED. Uses the undocumented-but-stable public CSV
endpoint (no API key required, works for all series). Cached locally.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from .config import DATA_DIR


FRED_CACHE_DIR = DATA_DIR / "macro_cache"
FRED_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _bo_j_proxy(start: date, end: date) -> list[tuple[date, float]]:
    """Fallback when FRED's JP 10Y series is unavailable.

    Piecewise step function based on BoJ-regime documented public events.
    Coarse but defensible — JP 10Y has had limited movement under YCC
    until the 2022-2024 BoJ pivot.
    """
    bands = [
        (date(2010, 1, 1), 0.10),    # pre-NIRP
        (date(2016, 1, 29), -0.05),  # BoJ NIRP announced
        (date(2016, 9, 21), 0.00),   # YCC introduced; 10Y target = 0%
        (date(2022, 12, 20), 0.25),  # YCC band widened to ±0.5%
        (date(2023, 7, 28), 0.50),   # YCC band widened further
        (date(2023, 10, 31), 0.80),  # YCC effectively dismantled
        (date(2024, 3, 19), 0.85),   # NIRP exit; gradual rise
        (date(2024, 7, 31), 1.00),   # Hike to 0.25%
        (date(2025, 1, 24), 1.20),   # Further BoJ tightening
    ]
    out: list[tuple[date, float]] = []
    cur = start
    while cur <= end:
        last = bands[0][1]
        for b_date, b_val in bands:
            if cur >= b_date:
                last = b_val
        out.append((cur, last))
        cur += timedelta(days=1)
    return out


def _cache_path(series_id: str) -> Path:
    return FRED_CACHE_DIR / f"fred_{series_id}.json"


def fetch_fred_series(
    series_id: str, force_refresh: bool = False, max_age_hours: int = 24
) -> list[tuple[date, float]]:
    """Fetch a FRED series as a list of (date, value).

    Caches to disk for `max_age_hours`. The CSV endpoint requires no
    API key. For series we use:
      DGS10 — US 10-year Treasury constant maturity (daily)
      DGS2  — US 2-year Treasury (daily)
      IRLTLT01JPM — Japan long-term gov yield (monthly; we forward-fill)
      VIXCLS — CBOE VIX index (daily)
    """
    cache = _cache_path(series_id)
    if cache.exists() and not force_refresh:
        meta = json.loads(cache.read_text())
        fetched_at = datetime.fromisoformat(meta["fetched_at"])
        age = datetime.utcnow() - fetched_at
        if age < timedelta(hours=max_age_hours):
            return [
                (date.fromisoformat(d), float(v))
                for d, v in meta["data"]
            ]

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    rows: list[tuple[date, float]] = []
    for i, line in enumerate(r.text.splitlines()):
        if i == 0 or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            d = date.fromisoformat(parts[0].strip())
            v = float(parts[1].strip())
        except (ValueError, IndexError):
            continue
        rows.append((d, v))

    cache.write_text(
        json.dumps(
            {
                "fetched_at": datetime.utcnow().isoformat(),
                "series_id": series_id,
                "data": [[d.isoformat(), v] for d, v in rows],
            },
            indent=2,
        )
    )
    return rows


def forward_fill_to_daily(
    series: list[tuple[date, float]],
    start: date,
    end: date,
) -> dict[date, float]:
    """Forward-fill a (possibly monthly) series to daily."""
    if not series:
        return {}
    series = sorted(series, key=lambda x: x[0])
    out: dict[date, float] = {}
    series_idx = 0
    last_val: Optional[float] = None
    cur = start
    while cur <= end:
        # advance series cursor while next entry is on or before cur
        while (
            series_idx < len(series) and series[series_idx][0] <= cur
        ):
            last_val = series[series_idx][1]
            series_idx += 1
        if last_val is not None:
            out[cur] = last_val
        cur = cur + timedelta(days=1)
    return out


def build_macro_features(
    start: date, end: date,
) -> dict[date, dict]:
    """Return per-date macro feature dict for use during backtest.

    Keys per date:
      us10y_pct  — US 10Y Treasury yield (%)
      jp10y_pct  — Japan long-term yield (% — forward-filled monthly)
      yield_diff — us10y - jp10y (percentage points)
      vix        — CBOE VIX
    """
    us10y_raw = fetch_fred_series("DGS10")
    vix_raw = fetch_fred_series("VIXCLS")
    # Japan 10Y monthly — try the canonical OECD series. If the public
    # CSV endpoint doesn't have it (FRED restricts some), fall back to
    # a piecewise approximation based on the BoJ regime.
    try:
        jp10y_raw = fetch_fred_series("IRLTLT01JPM156N")
    except Exception:
        jp10y_raw = _bo_j_proxy(start, end)

    us10y = forward_fill_to_daily(us10y_raw, start, end)
    jp10y = forward_fill_to_daily(jp10y_raw, start, end)
    vix = forward_fill_to_daily(vix_raw, start, end)

    out: dict[date, dict] = {}
    cur = start
    while cur <= end:
        u = us10y.get(cur)
        j = jp10y.get(cur)
        v = vix.get(cur)
        if u is not None and j is not None and v is not None:
            out[cur] = {
                "us10y_pct": u,
                "jp10y_pct": j,
                "yield_diff": u - j,
                "vix": v,
            }
        cur = cur + timedelta(days=1)
    return out


if __name__ == "__main__":
    # smoke test
    from datetime import date
    feats = build_macro_features(date(2020, 1, 1), date(2020, 1, 10))
    for d in sorted(feats.keys()):
        f = feats[d]
        print(
            f"{d}  US10Y={f['us10y_pct']:.2f}  JP10Y={f['jp10y_pct']:.2f}  "
            f"diff={f['yield_diff']:+.2f}  VIX={f['vix']:.2f}"
        )
