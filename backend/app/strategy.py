"""EUR/USD M5 mean-reversion strategy.

Logic in plain English:
    - Trade only during the configured session window (default: London-NY
      overlap, 12:00-16:00 UTC), where EUR/USD spreads are tightest and
      mean-reverting microstructure is strongest.
    - Skip when ADX(14) >= 25 — strong trends crush mean reversion.
    - Long when the candle close pierces the lower Bollinger Band
      (20, 2.0σ) AND the previous close was inside the bands.
    - Short: mirror image at the upper band.
    - Stop: 1.5 × ATR(14) from entry.
    - Target: midline of the bands, OR 1.5 × ATR profit, whichever is
      closer (we want the mean, not a moonshot).
    - Position size: solve for units such that a stop-out costs exactly
      RISK_PER_TRADE_PCT of current equity.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Optional

import numpy as np

from .config import settings
from .models import Candle, Side, Signal


# --- indicators ----------------------------------------------------------
def sma(arr: np.ndarray, period: int) -> float:
    if len(arr) < period:
        return float("nan")
    return float(arr[-period:].mean())


def std(arr: np.ndarray, period: int) -> float:
    if len(arr) < period:
        return float("nan")
    return float(arr[-period:].std(ddof=0))


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    if len(closes) < period + 1:
        return float("nan")
    prev_close = closes[-period - 1 : -1]
    h = highs[-period:]
    l = lows[-period:]
    tr = np.maximum.reduce(
        [h - l, np.abs(h - prev_close), np.abs(l - prev_close)]
    )
    return float(tr.mean())


def adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
) -> float:
    """Wilder's ADX. Returns nan if not enough data."""
    n = len(closes)
    if n < period * 2 + 1:
        return float("nan")

    up = highs[1:] - highs[:-1]
    dn = lows[:-1] - lows[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)

    prev_c = closes[:-1]
    h = highs[1:]
    l = lows[1:]
    tr = np.maximum.reduce(
        [h - l, np.abs(h - prev_c), np.abs(l - prev_c)]
    )

    # Wilder smoothing
    def smooth(x: np.ndarray) -> np.ndarray:
        out = np.zeros_like(x)
        out[period - 1] = x[:period].sum()
        for i in range(period, len(x)):
            out[i] = out[i - 1] - out[i - 1] / period + x[i]
        return out

    tr_s = smooth(tr)
    plus_s = smooth(plus_dm)
    minus_s = smooth(minus_dm)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * plus_s / np.where(tr_s == 0, np.nan, tr_s)
        minus_di = 100.0 * minus_s / np.where(tr_s == 0, np.nan, tr_s)
        dx = 100.0 * np.abs(plus_di - minus_di) / np.where(
            (plus_di + minus_di) == 0, np.nan, (plus_di + minus_di)
        )

    dx = dx[~np.isnan(dx)]
    if len(dx) < period:
        return float("nan")
    # Final ADX = Wilder average of DX
    adx_val = dx[-period:].mean()
    return float(adx_val)


# --- strategy ------------------------------------------------------------
@dataclass
class StrategyParams:
    bb_period: int = 20
    bb_mult: float = 2.0
    atr_period: int = 14
    adx_period: int = 14
    adx_max: float = 25.0           # skip when trend is stronger than this
    stop_atr_mult: float = 1.5
    target_atr_mult: float = 1.5    # cap on profit target
    min_atr_pips: float = 3.0       # skip dead markets
    max_atr_pips: float = 25.0      # skip wild markets


@dataclass
class StrategyState:
    """Maintains a rolling window of candles needed for indicator math."""
    params: StrategyParams = field(default_factory=StrategyParams)
    candles: deque[Candle] = field(default_factory=lambda: deque(maxlen=200))

    def add(self, c: Candle) -> None:
        # Idempotent: don't double-add the same bar.
        if self.candles and self.candles[-1].time == c.time:
            return
        self.candles.append(c)

    def warm(self) -> bool:
        return len(self.candles) >= max(self.params.bb_period + 1,
                                        self.params.atr_period + 1,
                                        self.params.adx_period * 2 + 1)


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_session(dt: datetime) -> bool:
    """True if `dt` (any tz) is within the configured UTC session window."""
    dt = dt.astimezone(timezone.utc)
    start = _parse_hhmm(settings.SESSION_START_UTC)
    end = _parse_hhmm(settings.SESSION_END_UTC)
    t = dt.time()
    if start <= end:
        return start <= t < end
    # window crosses midnight
    return t >= start or t < end


def position_size(equity: float, entry: float, stop: float) -> int:
    """Solve units for EUR/USD with USD account currency.

    For EUR/USD, 1 unit moves the account by `price_distance` USD per unit.
    So units = risk_dollars / abs(entry - stop).
    """
    risk_dollars = equity * (settings.RISK_PER_TRADE_PCT / 100.0)
    distance = abs(entry - stop)
    if distance <= 0:
        return 0
    units = int(risk_dollars / distance)
    # OANDA practical floor — too few units becomes meaningless
    return max(units, 0)


def evaluate(state: StrategyState, equity: float) -> Optional[Signal]:
    """Look at the latest closed candle and emit a Signal, or None."""
    if not state.warm():
        return None

    candles = list(state.candles)
    last = candles[-1]
    prev = candles[-2]

    if not in_session(last.time):
        return None

    closes = np.array([c.close for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)

    p = state.params
    mid = sma(closes, p.bb_period)
    sd = std(closes, p.bb_period)
    upper = mid + p.bb_mult * sd
    lower = mid - p.bb_mult * sd

    a = atr(highs, lows, closes, p.atr_period)
    if np.isnan(a) or np.isnan(mid):
        return None

    atr_pips = a * 10000.0
    if atr_pips < p.min_atr_pips or atr_pips > p.max_atr_pips:
        return None

    adx_val = adx(highs, lows, closes, p.adx_period)
    if not np.isnan(adx_val) and adx_val >= p.adx_max:
        return None

    # Long: this close < lower band, prev close inside bands
    if last.close < lower and lower < prev.close < upper:
        entry = last.close
        stop = entry - p.stop_atr_mult * a
        # target: closer of (mid) or (entry + target_atr_mult*ATR)
        atr_target = entry + p.target_atr_mult * a
        target = min(mid, atr_target)
        if target <= entry:  # don't enter if target isn't above entry
            return None
        return Signal(
            time=last.time,
            side=Side.LONG,
            entry=entry,
            stop=stop,
            target=target,
            atr=a,
            reason=f"long_meanrev BB[{lower:.5f}] ATR{atr_pips:.1f}p ADX{adx_val:.1f}",
        )

    # Short: this close > upper band, prev close inside bands
    if last.close > upper and lower < prev.close < upper:
        entry = last.close
        stop = entry + p.stop_atr_mult * a
        atr_target = entry - p.target_atr_mult * a
        target = max(mid, atr_target)
        if target >= entry:
            return None
        return Signal(
            time=last.time,
            side=Side.SHORT,
            entry=entry,
            stop=stop,
            target=target,
            atr=a,
            reason=f"short_meanrev BB[{upper:.5f}] ATR{atr_pips:.1f}p ADX{adx_val:.1f}",
        )

    return None
