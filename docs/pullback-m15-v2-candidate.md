# Pullback M15 v2 — pre-registered validation spec

**Status**: KILLED — failed 8 of 10 pre-registered bars on 2017-2021 fresh data
**Created**: 2026-05-06
**Killed**: 2026-05-06 (same day; pre-registered fresh-data validation rejected it)
**Origin**: Walk-forward optimization on USD_JPY M15 5y (2021-05 to 2026-05),
ranked by IS Sharpe, top-K evaluated on held-out OOS year.
**Discovery output**: `backend/data/backtest_results/pullback_m15_optimization.json`
**Validation output**: `backend/data/backtest_results/pullback_m15_v2_validation.json`
**Successor**: `pullback-m15-v3-research-plan.md` — three structural variants
(H1-gated, session-constrained, restart-confirmed), pre-registered, await
execution after current H1 demo concludes.

---

## Candidate parameters (frozen at pre-registration)

```yaml
strategy: pullback
instrument: USD_JPY
granularity: M15
sma_long: 200            # was 100 in deployed H1
sma_short: 50            # was 20 in deployed H1
pullback_lookback: 5     # was 3 in deployed H1
trend_slope_lookback: 20 # was 10 in deployed H1
atr_period: 14           # unchanged
stop_atr_mult: 3.0       # was 2.0 in deployed H1 (50% wider)
min_atr_pips: 3.0        # unchanged
```

Mechanically: a *slower* Pullback. Longer trend filter (50h vs deployed 100h on H1
— similar absolute time horizon), longer pullback target (12.5h SMA vs 5h),
wider stops (3× ATR vs 2×), wider window for pullback registration. The wider
stops + longer SMAs are what enables it to survive M15 friction (friction:stop
ratio ~6-9% on this candidate vs ~10% on naive M15 default).

## Why this is a candidate

In the M15 walk-forward optimization on 2021-2025 USD_JPY data:

- 2,304 viable parameter combinations searched (≥100 trades on IS)
- Optimizer ranked top by IS Sharpe; evaluated those EXACT parameter sets on
  held-out 2025-2026 year
- **This candidate held**: IS Sharpe 0.82 → OOS Sharpe 0.83 (gap −0.01)
- 7 of top-10 IS-best blew up on OOS (typical overfit signature)
- This candidate (and 2 immediate variants) clustered on the same parameter
  region — mechanically coherent, not random

For comparison, the equivalent H1 optimization had **0 of top-10 IS-best survive
OOS** — pure overfitting. The M15 result was qualitatively different.

## Why this is NOT yet validated

1. **Search-width inflation**: 2,304 trials searched. Even with the OOS hold,
   the deflated Sharpe (Bailey-López de Prado) is reduced. Without proper
   correction, the 0.83 cannot be claimed as statistically significant.
2. **OOS contamination**: having looked at the 2025-2026 result for this
   candidate, that window is no longer truly held-out for further validation
   of THIS candidate.
3. **Single instrument, single regime**: only tested on USD_JPY 2021-2026.
   May be regime-specific to the current macro environment.

## Pre-registered validation bars

These bars are LOCKED before any new data is loaded. Any modification to
these thresholds AFTER seeing test results invalidates the entire test.

### Test 1: Truly fresh USD_JPY M15 (2017-05-01 to 2021-05-01)

This window is older than the optimization dataset and was never seen by the
optimizer.

- **Bar A**: friction-shocked Sharpe ≥ **0.50**
- **Bar B**: friction-shocked CAGR ≥ **+1.5%**
- **Bar C**: max drawdown ≤ **15%**
- **Bar D**: trade count ≥ **200/yr** (representative sample density)
- **Bar E**: profit factor ≥ **1.05**

### Test 2: EUR_USD M15, same 4y window (2017-05-01 to 2021-05-01)

Cross-instrument robustness check. EUR_USD has different volatility regime,
different session microstructure, different broker spread profile.

- **Bar F**: friction-shocked Sharpe ≥ **0.30** (lower bar — different instrument
  is expected to perform less well)
- **Bar G**: friction-shocked CAGR ≥ **+0.5%**
- **Bar H**: profit factor ≥ **1.0** (must at minimum not lose money)

### Test 3: Cross-window consistency

The Sharpe across the four 1-year sub-windows of Test 1 (2017-2018, 2018-2019,
2019-2020, 2020-2021) must show:

- **Bar I**: at least 3 of 4 years with positive expectancy
- **Bar J**: max year-to-year Sharpe range ≤ 1.5 (no single year carrying
  the entire result)

## Friction model

Same as deployed engine:
- Spread: 1.0 pip (2× retail FX default)
- Slippage: 0.4 pip (2× retail FX default)
- No forced session-end close
- Signal entries restricted to 07:00-17:00 UTC session window
- Starting equity: $110,000 (= live demo balance)

## Decision rule

- **All 10 bars (A through J) met** → Candidate ADVANCES to v2 status:
  scheduled for a separate pre-registered demo cycle AFTER the current
  Pullback H1 demo concludes. We do NOT swap live.
- **Any one bar failed** → Candidate is KILLED. Mark as falsified. Do not
  re-test on additional data (= would burn statistical power for no gain).

## What this validation does NOT do

- Does NOT change the deployed Pullback H1 strategy
- Does NOT shorten or modify the current Pullback H1 demo evaluation window
- Does NOT promote the candidate to "live-ready" — even on full pass, it
  enters the v2 candidate pool, not the deployed engine

## Audit log

| Step | Action | Date | Outcome |
|------|--------|------|---------|
| 1 | Write this spec | 2026-05-06 | DONE |
| 2 | Download USD_JPY M15 9y | 2026-05-06 | DONE |
| 3 | Run candidate on fresh USD_JPY data (Test 1) | 2026-05-06 | DONE — Sharpe -0.10, CAGR -0.51%, FAILED bars A/B/E |
| 4 | Download EUR_USD M15 9y | 2026-05-06 | DONE |
| 5 | Run candidate on EUR_USD data (Test 2) | 2026-05-06 | DONE — 0 trades (pip_size bug surfaced) |
| 6 | Compute Test 3 (cross-window) | 2026-05-06 | DONE — only 1 of 4 years positive, FAILED bars I/J |
| 7 | Apply decision rule | 2026-05-06 | DONE — KILLED, 8/10 bars failed |
| 8 | Diagnose failure modes for v3 plan | 2026-05-06 | DONE — regime-dependent, thin PF, structural rather than parametric weaknesses |
| 9 | Write v3 research plan | 2026-05-06 | DONE — `pullback-m15-v3-research-plan.md` |

## Lessons learned

1. **Walk-forward IS/OOS is necessary but not sufficient.** The candidate
   passed the optimizer's own held-out 2025-2026 OOS test (Sharpe +0.83
   essentially identical to IS +0.82), but failed catastrophically on
   genuinely fresh 2017-2021 data. **Selection bias of the OOS year was
   the issue** — 2025-2026 happened to be a regime-favorable year, just
   like 2019-2020. Pre-registered fresh-data testing is the only way to
   catch this.
2. **The original 2,304-trial search inflated apparent significance.**
   Even with a 0.83 OOS Sharpe, the deflated significance after
   accounting for search width was lower than initial appearance. The
   fresh-data result confirms this empirically.
3. **`pip_size()` bug in `strategy.py`** (uses global `settings.INSTRUMENT`
   instead of taking instrument as parameter): makes cross-instrument
   backtests produce 0 trades. Must be fixed before any v3
   cross-instrument validation.
4. **Parameter optimization on a known-bad family is wasted effort.** The
   right next step is structural change (regime gate, session filter,
   entry confirmation), not tuning around the dead candidate. v3 plan
   formalizes this.
