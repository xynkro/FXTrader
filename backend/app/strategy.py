"""Donchian breakout intraday trend-follower for EUR/USD M5.

v1-B locked semantics:

- Signal computed on bar t close. Entry executed at bar t+1 open
  (backtest enforces strictly; live engine approximates with t-close fill).
- Stop & trail: entry-anchored chandelier. ATR(14) frozen at signal bar.
  Initial stop = entry ± K * ATR. Trail = max(prior_stop, ext - K*ATR_entry)
  for long; mirror for short. New trail activates ONE BAR LATER.
- Cooldown: same-direction lockout for `cooldown_bars` after stop-out.
  No cooldown after session-end exit.
- Session: configured UTC window (default 07:00-17:00 in .env).
- Sizing safeguards:
    MIN_STOP_PIPS: skip signal if K*ATR < 5 pips
    MAX_LEVERAGE: cap units at max_leverage * equity / price
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Optional

import numpy as np

from .config import settings
from .models import Candle, Side, Signal


# Default pip size for the configured instrument. Use pip_size(instrument)
# at call sites to support JPY pairs (pip = 0.01) without changing callers.
PIP = 0.0001  # legacy alias, EUR/USD style


def pip_size(instrument: str) -> float:
    """Return one pip in price units for the given instrument."""
    return 0.01 if "JPY" in instrument else 0.0001


def is_jpy_quote(instrument: str) -> bool:
    """True if the quote currency is JPY (e.g. USD_JPY, EUR_JPY)."""
    return instrument.endswith("_JPY")


# --- indicators ----------------------------------------------------------
def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    """True Range avg over `period`. Returns nan if not enough data."""
    if len(closes) < period + 1:
        return float("nan")
    prev_close = closes[-period - 1 : -1]
    h = highs[-period:]
    l = lows[-period:]
    tr = np.maximum.reduce([h - l, np.abs(h - prev_close), np.abs(l - prev_close)])
    return float(tr.mean())


# --- session -------------------------------------------------------------
def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_session(dt: datetime) -> bool:
    dt = dt.astimezone(timezone.utc)
    start = _parse_hhmm(settings.SESSION_START_UTC)
    end = _parse_hhmm(settings.SESSION_END_UTC)
    t = dt.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end


# --- params + state ------------------------------------------------------
@dataclass
class StrategyParams:
    donchian_period: int = 20
    atr_period: int = 14
    stop_atr_mult: float = 2.0          # K
    min_atr_pips: float = 3.0
    min_stop_pips: float = 5.0
    max_leverage: float = 30.0
    cooldown_bars: int = 20             # = donchian_period by default


@dataclass
class StrategyState:
    params: StrategyParams = field(default_factory=StrategyParams)
    candles: deque = field(default_factory=lambda: deque(maxlen=200))
    long_cooldown: int = 0
    short_cooldown: int = 0

    def add(self, c: Candle) -> None:
        if self.candles and self.candles[-1].time == c.time:
            return
        self.candles.append(c)

    def decrement_cooldowns(self) -> None:
        self.long_cooldown = max(0, self.long_cooldown - 1)
        self.short_cooldown = max(0, self.short_cooldown - 1)

    def trip_cooldown(self, side: Side) -> None:
        if side == Side.LONG:
            self.long_cooldown = self.params.cooldown_bars
        else:
            self.short_cooldown = self.params.cooldown_bars

    def warm(self) -> bool:
        return len(self.candles) >= max(
            self.params.donchian_period + 1,
            self.params.atr_period + 1,
        )


# --- sizing --------------------------------------------------------------
def position_size(
    equity: float,
    entry: float,
    stop: float,
    max_leverage: float = 30.0,
    instrument: Optional[str] = None,
) -> tuple[int, bool]:
    """Return (units, leverage_capped). units >= 0.

    USD account assumed. Two cases:
      - quote = USD (e.g. EUR_USD): 1 unit = 1 EUR; P&L in USD = units × Δprice.
        size: units = risk_$ / |entry - stop|; leverage cap: units × entry ≤ L × equity.
      - quote = JPY (e.g. USD_JPY): 1 unit = 1 USD; P&L in JPY = units × Δprice;
        ≈ converted by /entry. So |entry - stop| / entry ≈ % change ≈ USD-risk per
        unit. size: units = risk_$ × entry / |entry - stop|; notional in USD = units;
        leverage cap: units ≤ L × equity.
    """
    inst = instrument or settings.INSTRUMENT
    risk_dollars = equity * (settings.RISK_PER_TRADE_PCT / 100.0)
    distance = abs(entry - stop)
    if distance <= 0 or entry <= 0:
        return 0, False

    if is_jpy_quote(inst):
        risk_units = int(risk_dollars * entry / distance)
        max_units = int(max_leverage * equity)
    else:
        risk_units = int(risk_dollars / distance)
        max_units = int(max_leverage * equity / entry)

    if risk_units > max_units:
        return max_units, True
    return max(risk_units, 0), False


# --- signal --------------------------------------------------------------
def evaluate(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    """Generate a signal at bar t close. Caller fills at bar t+1 open.

    `equity` kept for API compat; not used. If `diagnostics` dict is passed,
    reasons for skipping (warmup, atr_min, min_stop, cooldown_*) are tallied.
    """
    def skip(key: str) -> None:
        if diagnostics is not None:
            k = f"skip_{key}"
            diagnostics[k] = diagnostics.get(k, 0) + 1
        return None

    if not state.warm():
        return skip("warmup")

    candles = list(state.candles)
    last = candles[-1]

    if not in_session(last.time):
        return skip("out_of_session")

    p = state.params
    closes = np.array([c.close for c in candles], dtype=float)
    highs  = np.array([c.high  for c in candles], dtype=float)
    lows   = np.array([c.low   for c in candles], dtype=float)

    a = atr(highs, lows, closes, p.atr_period)
    if np.isnan(a):
        return skip("warmup")

    pip = pip_size(settings.INSTRUMENT)
    atr_pips = a / pip
    if atr_pips < p.min_atr_pips:
        return skip("atr_below_min")

    stop_distance = p.stop_atr_mult * a
    if stop_distance < p.min_stop_pips * pip:
        return skip("stop_below_min")

    n = p.donchian_period
    if len(closes) < n + 1:
        return skip("warmup")
    # Donchian channel: high/low of the previous N CLOSED bars (excludes current)
    prev_high = float(highs[-n - 1 : -1].max())
    prev_low  = float(lows[ -n - 1 : -1].min())

    # LONG breakout
    if last.close > prev_high:
        if state.long_cooldown > 0:
            return skip("cooldown_long")
        return Signal(
            time=last.time,
            side=Side.LONG,
            entry=last.close,
            stop=last.close - stop_distance,
            target=None,
            atr=a,
            stop_distance=stop_distance,
            reason=f"long_breakout N{n} ATR{atr_pips:.1f}p prev_hi={prev_high:.5f}",
        )
    # SHORT breakout
    if last.close < prev_low:
        if state.short_cooldown > 0:
            return skip("cooldown_short")
        return Signal(
            time=last.time,
            side=Side.SHORT,
            entry=last.close,
            stop=last.close + stop_distance,
            target=None,
            atr=a,
            stop_distance=stop_distance,
            reason=f"short_breakout N{n} ATR{atr_pips:.1f}p prev_lo={prev_low:.5f}",
        )

    return skip("no_breakout")
