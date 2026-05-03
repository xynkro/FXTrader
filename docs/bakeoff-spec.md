# Bake-off spec — pre-registered before code

**Locked before implementation, before backtest run, before report.**
This is the contract. Any deviation gets called out explicitly.

## Sample

- Instrument: **USD/JPY only**. No multi-instrument noise.
- Timeframe: H1
- History: 5 years (1825 days), already downloaded
- Split: 80% IS / 20% OOS
- Friction: 0.5 pip half-spread + 0.2 pip slippage per side (= 0.9 pip
  round-trip). Friction shock: 2× both (= 1.8 pip round-trip).
- Equity: $10,000 starting
- Risk per trade: 0.5% of equity
- Session window: 07:00–17:00 UTC (forced exit at session end)
- Cooldown after stop-out: 20 bars same direction
- Sizing safeguards: MIN_STOP_PIPS=5, MAX_LEVERAGE=30 — both apply across
  all three strategies identically

## Strategies under comparison

All three share the same engine framework (entry-anchored chandelier
trail, K=2.0 ATR(14), session filter, cooldown, sizing safeguards).
Only the **entry condition** differs.

### Class A — Donchian breakout (baseline, already run)
- LONG when current bar close > highest high of previous N=20 bars
- SHORT when current bar close < lowest low of previous N=20 bars
- Already validated; result reproduced for comparison.

### Class B — Pullback-in-trend
- **Trend filter**: SMA(100) on H1
  - Up trend: close > SMA(100) AND SMA(100) rising over last 10 bars
  - Down trend: close < SMA(100) AND SMA(100) falling over last 10 bars
- **Pullback condition**: in last 3 bars, low touched SMA(20) (long) or
  high touched SMA(20) (short)
- **Re-entry trigger**: current bar close > SMA(20) (long, after up-trend
  pullback) or close < SMA(20) (short, after down-trend pullback)
- Stop & trail: same K=2.0 ATR chandelier as Class A

### Class C — Volatility compression → expansion
- **Compression metric**: BB(20, 2.0) width as % of mid =
  (upper - lower) / sma_20
- **Compressed**: current width_pct < 30th percentile of width_pct over
  last 100 bars
- **Entry**: while compressed,
  - LONG when close > upper Bollinger band
  - SHORT when close < lower Bollinger band
- Stop & trail: same K=2.0 ATR chandelier as Class A

## Reporting (identical across all three)

For each strategy:
- IS full stats (PF, expectancy, return, max DD, Sharpe, win rate, avg dur)
- OOS full stats (with note if trade count < 30)
- Friction shock full stats
- Yearly breakdown of P&L, trades, W/L, win rate
- Top-5 winner concentration
- Exit-type breakdown (initial_stop / trailing_stop / session_end / forced_eod)
- Cost as % of stop
- Skip counts (per signal-skip reason)
- One-line diagnosis ("FAIL X" / "PASS Y" — no "looks promising")

## Pre-registered winning criteria

A strategy **wins the bake-off** only if it meets ALL of these:

1. **Clears the gates honestly**: IS expectancy > 0 AND IS PF ≥ 1.1 AND
   OOS doesn't degrade by more than 80% on PF or expectancy.
2. **Less regime concentration than Donchian**: no single year contributes
   > 70% of cumulative profit. (Donchian on USD/JPY had 2022 = ~80% of
   cumulative — the bar to beat.)
3. **Survives friction shock**: PF ≥ 1.0 with 2× costs.
4. **Better economic profile**: friction-shocked annualized return >
   2% AND > 1.5× the equivalent number for Donchian (which was ~1.7%
   annualized friction-shocked). I.e. friction-shocked annualized
   return ≥ 2.5%.

A "barely passing" strategy that just clears 1.1 PF but is otherwise
identical-to-worse than Donchian does NOT win — that's running in
place with a different shape.

## Possible outcomes

| Outcome | Action |
|---|---|
| One strategy wins outright | That becomes the demo candidate. Old demo plan replaced. |
| Two strategies tie / two pass | Pick the simpler one. If tied on simplicity, pick the one with lower regime concentration. |
| All three fail | None deserves demo. Move on to harder questions: maybe this entire framework isn't where retail edge lives. |
| Donchian remains the only survivor but doesn't clear the new bar | Same as "all three fail" — Donchian's prior bar was lower; under the new criteria it would not have passed either. |

## What this bake-off does NOT test

- Multi-instrument portability (deliberately — that was the previous
  failure mode)
- Higher / lower timeframes (H1 only)
- Combinations of theses (e.g. pullback + compression filter together —
  v2 territory)
- Walk-forward parameter optimization (none of the strategies should
  need it; they're all parameter-light by design)

## Honesty constraints (binding)

- No "looks promising" language.
- Each one-line diagnosis must say PASS or FAIL plus the binding criterion.
- If a strategy fails, do not propose tweaks in the same report. Tweaks
  belong to a separate, deliberate decision after the bake-off concludes.
- The pre-registered criteria above are not editable mid-run. If they
  feel wrong after seeing results, that itself is a finding worth
  reporting separately.
