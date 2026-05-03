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
    """Return one pip in price units for the given instrument.

    Conventions:
    - Major FX (EUR/USD, GBP/USD, USD/CAD, ...): 0.0001 (4th decimal)
    - JPY pairs:                                  0.01   (2nd decimal)
    - Gold (XAU/USD), silver (XAG/USD):           0.10   (10 cents/oz)
    - Crypto (BTC/USD, ETH/USD):                  1.0    (1 dollar)
    """
    if "JPY" in instrument:
        return 0.01
    base = instrument.split("_")[0] if "_" in instrument else instrument
    if base in ("XAU", "XAG"):
        return 0.10
    if base in ("BTC", "ETH", "LTC", "XRP"):
        return 1.0
    return 0.0001


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
    # shared across all classes
    atr_period: int = 14
    stop_atr_mult: float = 2.0          # K
    min_atr_pips: float = 3.0
    min_stop_pips: float = 5.0
    max_leverage: float = 30.0
    cooldown_bars: int = 20

    # Class A — Donchian
    donchian_period: int = 20

    # Class B — Pullback-in-trend
    sma_long: int = 100
    sma_short: int = 20
    pullback_lookback: int = 3       # bars in which low/high must touch SMA_short
    trend_slope_lookback: int = 10   # how far back to measure SMA_long slope

    # Class C — Volatility compression -> expansion
    bb_period: int = 20
    bb_mult: float = 2.0
    compression_lookback: int = 100  # window for percentile rank of BB width
    compression_pct: float = 30.0    # below this percentile = compressed


@dataclass
class StrategyState:
    params: StrategyParams = field(default_factory=StrategyParams)
    # Bigger window so pullback (sma_long=100) and compression (lookback=100)
    # have full warmup history available.
    candles: deque = field(default_factory=lambda: deque(maxlen=300))
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

    def warm(self, min_bars: int) -> bool:
        return len(self.candles) >= min_bars


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


# --- shared signal preamble ---------------------------------------------
def _preamble(
    state: StrategyState,
    diagnostics: Optional[dict],
    min_warmup: int,
):
    """Common gate checks. Returns either a tuple (candles, p, closes, highs,
    lows, atr_value, stop_distance, pip, last) ready for evaluation, or
    a `None` from `skip(...)` already recorded in diagnostics."""
    def skip(key: str):
        if diagnostics is not None:
            k = f"skip_{key}"
            diagnostics[k] = diagnostics.get(k, 0) + 1
        return None

    if not state.warm(min_warmup):
        return skip("warmup"), None
    candles = list(state.candles)
    last = candles[-1]
    if not in_session(last.time):
        return skip("out_of_session"), None

    p = state.params
    closes = np.array([c.close for c in candles], dtype=float)
    highs  = np.array([c.high  for c in candles], dtype=float)
    lows   = np.array([c.low   for c in candles], dtype=float)

    a = atr(highs, lows, closes, p.atr_period)
    if np.isnan(a):
        return skip("warmup"), None
    pip = pip_size(settings.INSTRUMENT)
    atr_pips = a / pip
    if atr_pips < p.min_atr_pips:
        return skip("atr_below_min"), None
    stop_distance = p.stop_atr_mult * a
    if stop_distance < p.min_stop_pips * pip:
        return skip("stop_below_min"), None

    return None, dict(
        candles=candles, p=p, last=last, closes=closes, highs=highs, lows=lows,
        atr=a, atr_pips=atr_pips, pip=pip, stop_distance=stop_distance,
    )


def _record_skip(diagnostics: Optional[dict], key: str) -> None:
    if diagnostics is not None:
        k = f"skip_{key}"
        diagnostics[k] = diagnostics.get(k, 0) + 1


# --- Class A: Donchian breakout -----------------------------------------
def evaluate_donchian(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    p = state.params
    pre_skip, ctx = _preamble(state, diagnostics,
                               min_warmup=max(p.donchian_period + 1,
                                              p.atr_period + 1))
    if ctx is None:
        return pre_skip

    last = ctx["last"]
    highs, lows = ctx["highs"], ctx["lows"]
    a = ctx["atr"]; atr_pips = ctx["atr_pips"]; stop_distance = ctx["stop_distance"]

    n = p.donchian_period
    prev_high = float(highs[-n - 1 : -1].max())
    prev_low  = float(lows[ -n - 1 : -1].min())

    if last.close > prev_high:
        if state.long_cooldown > 0:
            _record_skip(diagnostics, "cooldown_long"); return None
        return Signal(
            time=last.time, side=Side.LONG, entry=last.close,
            stop=last.close - stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"donchian_long N{n} ATR{atr_pips:.1f}p hi={prev_high:.5f}",
        )
    if last.close < prev_low:
        if state.short_cooldown > 0:
            _record_skip(diagnostics, "cooldown_short"); return None
        return Signal(
            time=last.time, side=Side.SHORT, entry=last.close,
            stop=last.close + stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"donchian_short N{n} ATR{atr_pips:.1f}p lo={prev_low:.5f}",
        )
    _record_skip(diagnostics, "no_breakout"); return None


# --- Class B: Pullback-in-trend -----------------------------------------
def evaluate_pullback(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    p = state.params
    pre_skip, ctx = _preamble(
        state, diagnostics,
        min_warmup=max(p.sma_long + p.trend_slope_lookback,
                       p.atr_period + 1, p.pullback_lookback + 1),
    )
    if ctx is None:
        return pre_skip

    last = ctx["last"]
    closes, highs, lows = ctx["closes"], ctx["highs"], ctx["lows"]
    a = ctx["atr"]; atr_pips = ctx["atr_pips"]; stop_distance = ctx["stop_distance"]

    sma_long_now = float(closes[-p.sma_long:].mean())
    sma_long_prev = float(
        closes[-p.sma_long - p.trend_slope_lookback : -p.trend_slope_lookback].mean()
    )
    sma_short_now = float(closes[-p.sma_short:].mean())

    # Recent pullback window: last `pullback_lookback` bars (excluding current)
    lb = p.pullback_lookback
    sma_short_window = []
    for i in range(1, lb + 1):
        sma_short_at_i = float(closes[-p.sma_short - i : -i].mean()) if i > 0 else sma_short_now
        sma_short_window.append(sma_short_at_i)

    recent_lows = lows[-lb - 1 : -1]
    recent_highs = highs[-lb - 1 : -1]
    long_pullback_touched = any(
        recent_lows[k] <= sma_short_window[lb - 1 - k] for k in range(lb)
    )
    short_pullback_touched = any(
        recent_highs[k] >= sma_short_window[lb - 1 - k] for k in range(lb)
    )

    up_trend = last.close > sma_long_now and sma_long_now > sma_long_prev
    down_trend = last.close < sma_long_now and sma_long_now < sma_long_prev

    if up_trend and last.close > sma_short_now and long_pullback_touched:
        if state.long_cooldown > 0:
            _record_skip(diagnostics, "cooldown_long"); return None
        return Signal(
            time=last.time, side=Side.LONG, entry=last.close,
            stop=last.close - stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=(
                f"pullback_long sma_l={sma_long_now:.5f} sma_s={sma_short_now:.5f} "
                f"ATR{atr_pips:.1f}p"
            ),
        )
    if down_trend and last.close < sma_short_now and short_pullback_touched:
        if state.short_cooldown > 0:
            _record_skip(diagnostics, "cooldown_short"); return None
        return Signal(
            time=last.time, side=Side.SHORT, entry=last.close,
            stop=last.close + stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=(
                f"pullback_short sma_l={sma_long_now:.5f} sma_s={sma_short_now:.5f} "
                f"ATR{atr_pips:.1f}p"
            ),
        )

    _record_skip(diagnostics, "no_pullback_setup"); return None


# --- Class C: Volatility compression -> expansion -----------------------
def evaluate_volsqueeze(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    p = state.params
    pre_skip, ctx = _preamble(
        state, diagnostics,
        min_warmup=max(p.bb_period + p.compression_lookback,
                       p.atr_period + 1),
    )
    if ctx is None:
        return pre_skip

    last = ctx["last"]
    closes = ctx["closes"]
    a = ctx["atr"]; atr_pips = ctx["atr_pips"]; stop_distance = ctx["stop_distance"]

    # Rolling BB(20) widths (as % of SMA20) over the last
    # compression_lookback bars, including current.
    widths_pct: list[float] = []
    for i in range(p.compression_lookback):
        end = len(closes) - i
        window = closes[end - p.bb_period : end]
        m = float(window.mean()); sd = float(window.std(ddof=0))
        upper = m + p.bb_mult * sd
        lower = m - p.bb_mult * sd
        if m > 0:
            widths_pct.append((upper - lower) / m)
    widths_pct.reverse()  # oldest first

    if len(widths_pct) < p.compression_lookback:
        _record_skip(diagnostics, "warmup"); return None

    current_width_pct = widths_pct[-1]
    threshold = float(np.percentile(widths_pct, p.compression_pct))
    compressed = current_width_pct < threshold

    if not compressed:
        _record_skip(diagnostics, "not_compressed"); return None

    # Last bar's BB(20) bands
    window = closes[-p.bb_period:]
    m = float(window.mean()); sd = float(window.std(ddof=0))
    upper = m + p.bb_mult * sd
    lower = m - p.bb_mult * sd

    if last.close > upper:
        if state.long_cooldown > 0:
            _record_skip(diagnostics, "cooldown_long"); return None
        return Signal(
            time=last.time, side=Side.LONG, entry=last.close,
            stop=last.close - stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=(
                f"squeeze_long bb_up={upper:.5f} w%={current_width_pct*100:.3f} "
                f"thr={threshold*100:.3f} ATR{atr_pips:.1f}p"
            ),
        )
    if last.close < lower:
        if state.short_cooldown > 0:
            _record_skip(diagnostics, "cooldown_short"); return None
        return Signal(
            time=last.time, side=Side.SHORT, entry=last.close,
            stop=last.close + stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=(
                f"squeeze_short bb_lo={lower:.5f} w%={current_width_pct*100:.3f} "
                f"thr={threshold*100:.3f} ATR{atr_pips:.1f}p"
            ),
        )

    _record_skip(diagnostics, "no_breakout_in_squeeze"); return None


# Backwards-compat alias used by trader.py / backtest.py default.
evaluate = evaluate_donchian


STRATEGIES = {
    "donchian":   evaluate_donchian,
    "pullback":   evaluate_pullback,
    "volsqueeze": evaluate_volsqueeze,
}
