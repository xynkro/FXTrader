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
    # have full warmup history available. Daily swing strategies need 200+
    # bars (~10 months) for SMA(50) etc; bumped accordingly.
    candles: deque = field(default_factory=lambda: deque(maxlen=400))
    long_cooldown: int = 0
    short_cooldown: int = 0
    # Macro features (date -> {us10y_pct, jp10y_pct, yield_diff, vix})
    # Empty for intraday/non-macro strategies; populated for swing.
    macro: dict = field(default_factory=dict)

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
    quote_to_account_rate: Optional[float] = None,
) -> tuple[int, bool]:
    """Return (units, leverage_capped). units >= 0.

    Generalised, account-currency aware sizing.

    For ANY pair BASE_QUOTE on an account in currency ACCT:
      - 1 unit of position = 1 unit of BASE
      - P&L per unit per Δprice (price = QUOTE per BASE) = Δprice  QUOTE
      - P&L per unit per Δprice in ACCT = Δprice × q2a, where q2a is
        units of ACCT per 1 unit of QUOTE.
      - Risk per unit at stop = |entry - stop| × q2a  ACCT
      - units to risk R ACCT: N = R / (|entry - stop| × q2a)
      - Notional per unit in ACCT = entry × q2a (since 1 unit BASE
        = entry QUOTE = entry × q2a ACCT)
      - Leverage cap: N × notional_per_unit ≤ max_leverage × equity

    `quote_to_account_rate` should be passed by the caller (live engine
    queries OANDA's quoteHomeConversionFactors for it).

    For backtests, if not provided, we fall back to the implicit USD-account
    convention (rate = 1/entry for JPY-quote, 1.0 otherwise) so historical
    results stay reproducible.
    """
    inst = instrument or settings.INSTRUMENT
    risk_acct = equity * (settings.RISK_PER_TRADE_PCT / 100.0)
    distance = abs(entry - stop)
    if distance <= 0 or entry <= 0:
        return 0, False

    if quote_to_account_rate is None:
        quote_to_account_rate = (1.0 / entry) if is_jpy_quote(inst) else 1.0

    risk_per_unit = distance * quote_to_account_rate
    if risk_per_unit <= 0:
        return 0, False
    risk_units = int(risk_acct / risk_per_unit)

    notional_per_unit = entry * quote_to_account_rate
    if notional_per_unit <= 0:
        return 0, False
    max_units = int(max_leverage * equity / notional_per_unit)

    if risk_units > max_units:
        return max_units, True
    return max(risk_units, 0), False


# --- shared signal preamble ---------------------------------------------
def _preamble(
    state: StrategyState,
    diagnostics: Optional[dict],
    min_warmup: int,
    check_session: bool = True,
):
    """Common gate checks. Returns either a tuple (candles, p, closes, highs,
    lows, atr_value, stop_distance, pip, last) ready for evaluation, or
    a `None` from `skip(...)` already recorded in diagnostics.

    `check_session=False` for swing/daily strategies where the intraday
    session filter doesn't apply.
    """
    def skip(key: str):
        if diagnostics is not None:
            k = f"skip_{key}"
            diagnostics[k] = diagnostics.get(k, 0) + 1
        return None

    if not state.warm(min_warmup):
        return skip("warmup"), None
    candles = list(state.candles)
    last = candles[-1]
    if check_session and not in_session(last.time):
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


# --- Class D: Liquidity Sweep / Spring Reversal -------------------------
def evaluate_liquidity_sweep(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    """Osler-style stop-cluster cascade fade.

    A bar prints a wick beyond the prior N-bar swing high/low (sweep) and
    closes back inside the range (rejection). The candle is the entire
    setup — no next-bar confirmation needed since the engine fills at the
    bar's close. Stop is placed beyond the wick + buffer (wider than
    K*ATR), so the strategy's stop_distance is overridden by the actual
    geometry; sizing scales accordingly via the engine's general formula.
    """
    p = state.params
    pre_skip, ctx = _preamble(
        state, diagnostics,
        min_warmup=max(p.donchian_period + 1, p.atr_period + 1),
    )
    if ctx is None:
        return pre_skip

    last = ctx["last"]; highs = ctx["highs"]; lows = ctx["lows"]
    a = ctx["atr"]; atr_pips = ctx["atr_pips"]

    n = p.donchian_period
    prev_high = float(highs[-n - 1 : -1].max())
    prev_low  = float(lows[ -n - 1 : -1].min())

    sweep_thresh = 0.25 * a  # require meaningful penetration
    buffer = 0.5 * a

    # SHORT: bar swept above the prior swing high but closed back below it
    if (last.high > prev_high + sweep_thresh) and (last.close < prev_high):
        if state.short_cooldown > 0:
            _record_skip(diagnostics, "cooldown_short"); return None
        entry = last.close
        stop = last.high + buffer
        sd = stop - entry
        if sd <= 0:
            _record_skip(diagnostics, "stop_below_entry"); return None
        return Signal(
            time=last.time, side=Side.SHORT, entry=entry,
            stop=stop, target=None, atr=a, stop_distance=sd,
            reason=(
                f"sweep_short prev_hi={prev_high:.5f} wick={last.high:.5f} "
                f"ATR{atr_pips:.1f}p"
            ),
        )

    # LONG: mirror
    if (last.low < prev_low - sweep_thresh) and (last.close > prev_low):
        if state.long_cooldown > 0:
            _record_skip(diagnostics, "cooldown_long"); return None
        entry = last.close
        stop = last.low - buffer
        sd = entry - stop
        if sd <= 0:
            _record_skip(diagnostics, "stop_below_entry"); return None
        return Signal(
            time=last.time, side=Side.LONG, entry=entry,
            stop=stop, target=None, atr=a, stop_distance=sd,
            reason=(
                f"sweep_long prev_lo={prev_low:.5f} wick={last.low:.5f} "
                f"ATR{atr_pips:.1f}p"
            ),
        )

    _record_skip(diagnostics, "no_sweep"); return None


# --- Class E: Z-score Mean Reversion ------------------------------------
def evaluate_zscore_meanrev(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    """Standardised price-deviation reversion. Andersen-Bollerslev 1998
    documented intraday FX reversion structure; this is the simplest direct
    encoding. Requires |z| > 2 for entry."""
    p = state.params
    pre_skip, ctx = _preamble(
        state, diagnostics,
        min_warmup=max(p.bb_period + 1, p.atr_period + 1),
    )
    if ctx is None:
        return pre_skip

    last = ctx["last"]; closes = ctx["closes"]
    a = ctx["atr"]; atr_pips = ctx["atr_pips"]; stop_distance = ctx["stop_distance"]

    n = p.bb_period
    window = closes[-n:]
    mean = float(window.mean())
    sd = float(window.std(ddof=0))
    if sd <= 0:
        _record_skip(diagnostics, "no_std"); return None
    z = (last.close - mean) / sd

    Z_THRESH = 2.0
    if z < -Z_THRESH:
        if state.long_cooldown > 0:
            _record_skip(diagnostics, "cooldown_long"); return None
        return Signal(
            time=last.time, side=Side.LONG, entry=last.close,
            stop=last.close - stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"zscore_long z={z:.2f} mean={mean:.5f} ATR{atr_pips:.1f}p",
        )
    if z > Z_THRESH:
        if state.short_cooldown > 0:
            _record_skip(diagnostics, "cooldown_short"); return None
        return Signal(
            time=last.time, side=Side.SHORT, entry=last.close,
            stop=last.close + stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"zscore_short z={z:.2f} ATR{atr_pips:.1f}p",
        )
    _record_skip(diagnostics, "no_zscore_extreme"); return None


# --- Class F: Session VWAP Reversion ------------------------------------
def evaluate_session_vwap(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    """Volume-weighted intraday mean (anchored at session open). Tick-volume
    proxy weakens the academic thesis — degrades to vol-weighted-mean
    reversion if true notional doesn't transfer cleanly."""
    p = state.params
    pre_skip, ctx = _preamble(
        state, diagnostics,
        min_warmup=max(p.bb_period + 1, p.atr_period + 1),
    )
    if ctx is None:
        return pre_skip

    candles = ctx["candles"]; last = ctx["last"]
    a = ctx["atr"]; atr_pips = ctx["atr_pips"]; stop_distance = ctx["stop_distance"]

    sess_start_h = int(settings.SESSION_START_UTC.split(":")[0])
    sess_end_h   = int(settings.SESSION_END_UTC.split(":")[0])
    last_date = last.time.date()
    session_bars = [
        c for c in candles
        if c.time.date() == last_date
        and sess_start_h <= c.time.hour < sess_end_h
    ]
    if len(session_bars) < 3:
        _record_skip(diagnostics, "session_warmup"); return None

    typicals = [(c.high + c.low + c.close) / 3.0 for c in session_bars]
    weights = [max(c.volume, 1) for c in session_bars]
    total_w = float(sum(weights))
    vwap = sum(t * w for t, w in zip(typicals, weights)) / total_w
    sq_dev = sum(w * (t - vwap) ** 2 for t, w in zip(typicals, weights)) / total_w
    sd = sq_dev ** 0.5
    if sd <= 0:
        _record_skip(diagnostics, "no_vwap_std"); return None

    K_BAND = 2.0
    if last.close > vwap + K_BAND * sd:
        if state.short_cooldown > 0:
            _record_skip(diagnostics, "cooldown_short"); return None
        return Signal(
            time=last.time, side=Side.SHORT, entry=last.close,
            stop=last.close + stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"vwap_short vwap={vwap:.5f} sd={sd:.5f} ATR{atr_pips:.1f}p",
        )
    if last.close < vwap - K_BAND * sd:
        if state.long_cooldown > 0:
            _record_skip(diagnostics, "cooldown_long"); return None
        return Signal(
            time=last.time, side=Side.LONG, entry=last.close,
            stop=last.close - stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"vwap_long vwap={vwap:.5f} ATR{atr_pips:.1f}p",
        )
    _record_skip(diagnostics, "within_vwap_band"); return None


# --- Class G: Bollinger Squeeze release ---------------------------------
def evaluate_bb_squeeze(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    """Carter-style squeeze-release. Trade the bar where BB(20,2) exits
    Keltner(20, 1.5*ATR), in the direction of price-vs-mid momentum.
    Different from the existing volsqueeze (which trades while compressed)."""
    p = state.params
    pre_skip, ctx = _preamble(
        state, diagnostics,
        min_warmup=max(p.bb_period + 2, p.atr_period + 2),
    )
    if ctx is None:
        return pre_skip

    last = ctx["last"]
    closes = ctx["closes"]; highs = ctx["highs"]; lows = ctx["lows"]
    a = ctx["atr"]; atr_pips = ctx["atr_pips"]; stop_distance = ctx["stop_distance"]

    n = p.bb_period
    window = closes[-n:]
    mid = float(window.mean())
    bb_sd = float(window.std(ddof=0))
    bb_upper = mid + p.bb_mult * bb_sd
    bb_lower = mid - p.bb_mult * bb_sd
    KC_MULT = 1.5
    kc_upper = mid + KC_MULT * a
    kc_lower = mid - KC_MULT * a

    # Prior bar's BB vs Keltner: was it squeezed?
    prev_window = closes[-n - 1 : -1]
    prev_mid = float(prev_window.mean())
    prev_bb_sd = float(prev_window.std(ddof=0))
    prev_bb_upper = prev_mid + p.bb_mult * prev_bb_sd
    prev_bb_lower = prev_mid - p.bb_mult * prev_bb_sd
    prev_atr = atr(highs[:-1], lows[:-1], closes[:-1], p.atr_period)
    if np.isnan(prev_atr):
        _record_skip(diagnostics, "warmup"); return None
    prev_kc_upper = prev_mid + KC_MULT * prev_atr
    prev_kc_lower = prev_mid - KC_MULT * prev_atr

    was_squeezed = (prev_bb_upper < prev_kc_upper) and (prev_bb_lower > prev_kc_lower)
    is_released = (bb_upper > kc_upper) or (bb_lower < kc_lower)
    if not (was_squeezed and is_released):
        _record_skip(diagnostics, "no_squeeze_release"); return None

    momentum = last.close - mid
    if momentum > 0:
        if state.long_cooldown > 0:
            _record_skip(diagnostics, "cooldown_long"); return None
        return Signal(
            time=last.time, side=Side.LONG, entry=last.close,
            stop=last.close - stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"sq_release_long mid={mid:.5f} ATR{atr_pips:.1f}p",
        )
    else:
        if state.short_cooldown > 0:
            _record_skip(diagnostics, "cooldown_short"); return None
        return Signal(
            time=last.time, side=Side.SHORT, entry=last.close,
            stop=last.close + stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"sq_release_short mid={mid:.5f} ATR{atr_pips:.1f}p",
        )


# --- Class H: Engulfing/Pin at Pivot ------------------------------------
def evaluate_engulfing_pivot(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    """Engulfing or pin-bar within 0.25*ATR of PDH/PDL/Classic Pivot/R1/S1.
    Fully deterministic — no swing-pivot ambiguity, levels are computed
    from the prior UTC day's OHLC."""
    p = state.params
    pre_skip, ctx = _preamble(
        state, diagnostics,
        min_warmup=48,  # need ~2 days of H1 history
    )
    if ctx is None:
        return pre_skip

    candles = ctx["candles"]; last = ctx["last"]
    a = ctx["atr"]; atr_pips = ctx["atr_pips"]; stop_distance = ctx["stop_distance"]

    if len(candles) < 2:
        _record_skip(diagnostics, "warmup"); return None
    prev_bar = candles[-2]

    # Find prior UTC day's OHLC from candle history
    last_date = last.time.date()
    prior = [c for c in candles[:-1] if c.time.date() < last_date]
    if not prior:
        _record_skip(diagnostics, "no_prior_day"); return None
    pd_date = max(c.time.date() for c in prior)
    pd_bars = [c for c in prior if c.time.date() == pd_date]
    if len(pd_bars) < 5:
        _record_skip(diagnostics, "thin_prior_day"); return None
    pdh = max(c.high for c in pd_bars)
    pdl = min(c.low  for c in pd_bars)
    pdc = pd_bars[-1].close

    pivot = (pdh + pdl + pdc) / 3.0
    r1 = 2 * pivot - pdl
    s1 = 2 * pivot - pdh
    levels = [pdh, pdl, pivot, r1, s1]

    # --- Pattern detection ---
    body = abs(last.close - last.open)
    rng = last.high - last.low
    if rng <= 0:
        _record_skip(diagnostics, "zero_range"); return None
    upper_wick = last.high - max(last.open, last.close)
    lower_wick = min(last.open, last.close) - last.low

    bull_engulf = (
        prev_bar.close < prev_bar.open and
        last.close > last.open and
        last.close > prev_bar.open and
        last.open  < prev_bar.close
    )
    bear_engulf = (
        prev_bar.close > prev_bar.open and
        last.close < last.open and
        last.close < prev_bar.open and
        last.open  > prev_bar.close
    )
    bull_pin = (
        body > 0 and
        lower_wick >= 2 * body and
        lower_wick >= 0.66 * rng and
        upper_wick <= 0.20 * rng
    )
    bear_pin = (
        body > 0 and
        upper_wick >= 2 * body and
        upper_wick >= 0.66 * rng and
        lower_wick <= 0.20 * rng
    )

    near_thresh = 0.25 * a
    near_level = any(abs(last.close - lv) < near_thresh for lv in levels)
    if not near_level:
        _record_skip(diagnostics, "no_pivot_proximity"); return None

    if bull_engulf or bull_pin:
        if state.long_cooldown > 0:
            _record_skip(diagnostics, "cooldown_long"); return None
        kind = "engulf" if bull_engulf else "pin"
        return Signal(
            time=last.time, side=Side.LONG, entry=last.close,
            stop=last.close - stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"{kind}_long_at_pivot pdh={pdh:.5f} pdl={pdl:.5f} ATR{atr_pips:.1f}p",
        )
    if bear_engulf or bear_pin:
        if state.short_cooldown > 0:
            _record_skip(diagnostics, "cooldown_short"); return None
        kind = "engulf" if bear_engulf else "pin"
        return Signal(
            time=last.time, side=Side.SHORT, entry=last.close,
            stop=last.close + stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=f"{kind}_short_at_pivot pdh={pdh:.5f} pdl={pdl:.5f} ATR{atr_pips:.1f}p",
        )
    _record_skip(diagnostics, "no_engulfing_or_pin"); return None


# --- Class S: Swing Carry-Momentum (daily) ------------------------------
def evaluate_swing_carry(
    state: StrategyState,
    equity: float = 0.0,
    diagnostics: Optional[dict] = None,
) -> Optional[Signal]:
    """Multi-day carry-momentum on USD/JPY daily bars.

    Long entry — ALL three conditions must hold at daily close:
      1. close > SMA(20) > SMA(50)  (trend)
      2. yield_diff (US10Y − JP10Y) > 0  (carry favourable)
      3. VIX < 25  (no risk-off / crash regime)

    Short — mirror.

    Stop = entry ± K × ATR(20). Hard regime kill: VIX > 30 — handled by
    the engine's risk layer, not in this signal function.
    """
    p = state.params
    # Bigger warmup for daily swing — need SMA(50)+ history.
    # Session filter disabled — daily bars don't have an intraday session.
    pre_skip, ctx = _preamble(
        state, diagnostics,
        min_warmup=max(p.sma_long, 60),
        check_session=False,
    )
    if ctx is None:
        return pre_skip

    last = ctx["last"]
    closes = ctx["closes"]
    a = ctx["atr"]; atr_pips = ctx["atr_pips"]; pip = ctx["pip"]

    # Override stop multiplier — daily ATRs are bigger; K=2.0 still applies
    # but min_stop_pips needs to be 20 for daily (set in StrategyParams
    # default for swing usage; here we just verify).
    stop_distance = p.stop_atr_mult * a
    if stop_distance < 20.0 * pip:
        return _record_skip(diagnostics, "stop_below_min_swing")

    # Trend filter
    sma20 = float(closes[-20:].mean())
    sma50 = float(closes[-50:].mean())
    long_trend = (last.close > sma20) and (sma20 > sma50)
    short_trend = (last.close < sma20) and (sma20 < sma50)

    # Macro lookup
    bar_date = last.time.date()
    macro = state.macro.get(bar_date)
    if macro is None:
        # Try a few earlier dates (weekend / holiday shifts)
        from datetime import timedelta as _td
        for back in range(1, 5):
            macro = state.macro.get(bar_date - _td(days=back))
            if macro is not None:
                break
    if macro is None:
        return _record_skip(diagnostics, "no_macro_data")

    yield_diff = macro["yield_diff"]    # US10Y - JP10Y, %
    vix = macro["vix"]

    # Risk-regime filter — fundamentally non-directional
    if vix >= 25.0:
        return _record_skip(diagnostics, "vix_risk_off")

    # Carry filter — directional
    long_carry = yield_diff > 0
    short_carry = yield_diff < 0

    if long_trend and long_carry:
        if state.long_cooldown > 0:
            return _record_skip(diagnostics, "cooldown_long")
        return Signal(
            time=last.time, side=Side.LONG, entry=last.close,
            stop=last.close - stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=(
                f"swing_long sma20={sma20:.4f} sma50={sma50:.4f} "
                f"yd={yield_diff:+.2f}pp vix={vix:.1f} ATR{atr_pips:.0f}p"
            ),
        )
    if short_trend and short_carry:
        if state.short_cooldown > 0:
            return _record_skip(diagnostics, "cooldown_short")
        return Signal(
            time=last.time, side=Side.SHORT, entry=last.close,
            stop=last.close + stop_distance, target=None, atr=a,
            stop_distance=stop_distance,
            reason=(
                f"swing_short yd={yield_diff:+.2f}pp vix={vix:.1f} "
                f"ATR{atr_pips:.0f}p"
            ),
        )

    return _record_skip(diagnostics, "no_swing_alignment")


# Backwards-compat alias used by trader.py / backtest.py default.
evaluate = evaluate_donchian


STRATEGIES = {
    "donchian":         evaluate_donchian,
    "pullback":         evaluate_pullback,
    "volsqueeze":       evaluate_volsqueeze,
    "liquidity_sweep":  evaluate_liquidity_sweep,
    "zscore":           evaluate_zscore_meanrev,
    "session_vwap":     evaluate_session_vwap,
    "bb_squeeze":       evaluate_bb_squeeze,
    "engulfing_pivot":  evaluate_engulfing_pivot,
    "swing_carry":      evaluate_swing_carry,
}
