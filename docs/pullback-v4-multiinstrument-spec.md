# Pullback v4 — multi-instrument JPY-cross deployment, pre-registered

**Status**: Pre-registered. NO execution until current Pullback H1 demo concludes.
**Created**: 2026-05-06
**Predecessor**: v3 research plan (M15 family killed) + cross-instrument
findings on 2026-05-06 + USD_JPY × GBP_JPY correlation analysis.
**Origin**: today's research established that the deployed Pullback H1
default is a JPY-cross-specific edge (positive on USD_JPY, GBP_JPY,
EUR_JPY; negative on EUR/USD, GBP/USD, AUD/USD). The natural next move
is multi-instrument deployment for diversification, NOT a new strategy.

---

## Background — why this plan exists

Today (2026-05-06) we tested the deployed Pullback H1 default parameters
across 9 instruments and found a clean dichotomy:

| Family | Avg Sharpe (5y) | Verdict |
|---|---:|---|
| JPY pairs (USD_JPY, GBP_JPY, EUR_JPY) | +0.75 | strong |
| Marginal JPY pairs (AUD_JPY) | +0.25 | weak |
| Negative JPY pairs (NZD_JPY) | −0.59 | dead |
| Non-JPY majors (EUR/USD, GBP/USD, AUD/USD) | −0.88 | dead |
| Gold (XAU_USD) | +0.23 | marginal |

**The strategy is a "JPY-cross trend continuation" edge**, mechanically
plausible because JPY pairs trend cleanly under structural BoJ
divergence from other central banks. Three of five JPY pairs show real
edge with the same default parameters — that's strong cross-instrument
generalization within a coherent family.

The USD_JPY × GBP_JPY correlation analysis (5y daily H1):
- Daily return correlation: **+0.62**
- Rolling 30d correlation: mean +0.62, std 0.20, range −0.12 to +0.93
- 6.6% of windows highly correlated (>0.85)
- 21.4% of windows weakly correlated (<0.50)
- 50/50 portfolio (full size each): **20.8% variance reduction**, 11.0%
  vol reduction — modest but real

The diversification math says: running both at half-size each gives the
*same* total dollar risk as running one at full size, but with ~11%
lower portfolio vol — a Sharpe improvement of roughly 12%.

## Why this is NOT yet validated for live deployment

1. **Multi-instrument engine doesn't exist.** The current `trader.py`
   runs ONE strategy on ONE instrument. Real engineering needed before
   anything goes live.
2. **EUR_JPY hasn't passed freshness.** Only USD_JPY and GBP_JPY have
   2014-2017 fresh-data validation. EUR_JPY freshness is required before
   it joins the deployed pool.
3. **Risk allocation rule not chosen.** Multiple defensible options
   (third-size each / half-size each / inverse-vol weighted); needs a
   pre-registered choice.
4. **Correlation regime variance is large.** ~7% of weeks the pairs
   move nearly identically (correlation >0.85); during those weeks
   diversification disappears and concurrent same-direction trades
   double effective exposure. Sizing must account for worst-case.

## Pre-registered design decisions (LOCKED before any test)

### Pair selection

**v4 deployment pool** (must all pass pre-deployment validation):
- USD_JPY (currently deployed, 5y Sharpe +0.69, freshness passed at +0.35)
- GBP_JPY (5y Sharpe +1.01, freshness passed at +0.27)
- EUR_JPY (5y Sharpe +0.54, freshness PENDING)

**Excluded from v4**:
- AUD_JPY (5y Sharpe +0.25 — too marginal)
- NZD_JPY (5y Sharpe −0.59 — fails)
- All non-JPY pairs (negative on this strategy)

### Risk allocation rule

**LOCKED choice**: each instrument gets `RISK_PER_TRADE_PCT / 3` per
trade. With current `RISK_PER_TRADE_PCT=0.25%`, each instrument trades
at 0.0833% per trade. Total max risk per concurrent-trade-trio = 0.25%
(same as current single-instrument single-trade).

**Rejected alternatives**:
- *Half-size each (1/2 RISK)*: 0.125% per pair × 3 pairs = 0.375%
  total. Above current single-instrument. Adds risk we haven't
  validated.
- *Full-size each (RISK)*: 0.25% per pair × 3 pairs = 0.75% concurrent
  worst case. Trips daily 2% kill switch on a 3-pair-loss-day. Far
  too aggressive.
- *Inverse-vol weighted*: requires runtime variance estimation per
  instrument; over-complicates v4. Defer to v5 if v4 succeeds.

### Per-instrument cooldown semantics

Cooldowns track per instrument: a USD_JPY long stop-out triggers
USD_JPY long cooldown only. GBP_JPY and EUR_JPY remain free to fire.
Rationale: cross-pair contagion isn't the failure mode that cooldowns
defend against (that's "same-thesis re-entry within the same pair").

### Concurrent position rule

`MAX_CONCURRENT_POSITIONS` becomes per-instrument (1 per pair, 3 total
across portfolio). Portfolio-level concurrency cap = 3.

### Daily trade cap

`MAX_TRADES_PER_DAY` becomes per-instrument (4 each, 12 total across
portfolio). Portfolio-level trade cap = 12 / day. With 0.0833%-per-trade
sizing, worst-case all-loss-day = 12 × 0.0833% = 1.0%. Safely below
the 2% daily kill switch.

### Kill switch behavior

Daily P&L kill, max drawdown kill, consecutive-loss kill all evaluate
on PORTFOLIO-LEVEL equity, not per-instrument. Same thresholds:
- Daily loss: −2%
- Max drawdown: −5%
- Consecutive losses: 4 in a row across portfolio

If kill switch trips, ALL instruments halt simultaneously.

## Pre-registered validation bars (LOCKED before live deployment)

### Stage 1 — fresh-data validation per pair

Each pair must pass freshness on its truly-fresh window before joining
the live pool.

| Bar | Pair | Metric | Threshold |
|---|---|---|---:|
| 1A | EUR_JPY | 2014-2017 fresh Sharpe | ≥ +0.30 |
| 1B | EUR_JPY | 2014-2017 fresh CAGR | ≥ +0.5% |
| 1C | EUR_JPY | 2014-2017 fresh PF | ≥ 1.05 |

USD_JPY (already passed: 0.35, +1.04%, 1.09) and GBP_JPY (already
passed: 0.27, +0.79%, 1.06) are grandfathered.

### Stage 2 — combined-portfolio backtest on 5y H1

Run all qualifying pairs simultaneously with the third-size sizing rule
on 2021-2026 H1, friction-shocked.

| Bar | Metric | Threshold |
|---|---|---:|
| 2A | Combined Sharpe | ≥ deployed USD_JPY-only Sharpe (= +0.69) |
| 2B | Combined max DD | ≤ deployed USD_JPY-only max DD (= 4.19%) |
| 2C | Each pair's expectancy on combined run | > 0 |
| 2D | No single pair contributes > 60% of combined gross profit | strict |
| 2E | Total trades / yr | ≥ 3× single-instrument (= ~350/yr) |

Failure of ANY bar at Stage 2 → v4 abandoned, reanalyze.

### Stage 3 — pre-registered live demo (after current demo concludes)

| Bar | Metric | Threshold |
|---|---|---:|
| 3A | Demo length | 4 calendar weeks minimum |
| 3B | Live trade count across portfolio | ≥ 30 |
| 3C | Live combined Sharpe vs Stage 2 backtest | ≥ 50% (i.e. ≥ +0.35) |
| 3D | Live max DD | ≤ 1.5× backtest max DD |
| 3E | Per-pair expectancy positive | all 3 pairs |
| 3F | No kill switch trips | strict |

If 3A-3F all pass → graduate v4 to "validated multi-pair deployment."
If any fail → roll back to single-instrument, document, learn.

## Engineering scope (estimate)

### Required code changes

1. **`trader.py`** — refactor from single-instrument loop to
   multi-instrument:
   - Per-instrument candle-fetch tasks (3× OANDA REST calls per cycle)
   - Per-instrument `StrategyState` instances in a dict keyed by
     instrument
   - Per-instrument signal evaluation
   - Per-instrument open-trade tracking (currently single global)
   - OANDA position-query becomes per-instrument
   - Live trail update per instrument
   - Resilience layer: failure of one instrument's data feed must
     NOT halt the others

2. **`config.py`** / **`.env`** — `INSTRUMENT` becomes `INSTRUMENTS`
   (comma-separated). Backwards compat: single value treated as a
   one-instrument list.

3. **`risk.py`** — risk allocation rule (third-size); kill switch
   evaluates portfolio-level equity, not per-instrument.

4. **`api.py`** — endpoints become per-instrument-aware:
   - `/api/strategy_vitals` → returns dict keyed by instrument
   - `/api/positions` → multi-instrument list
   - `/api/status` → per-instrument flags rolled up
   - `/api/trades` → already filterable by instrument
   - New endpoint: `/api/portfolio_summary` for combined view

5. **PWA frontend** — per-instrument tabs / strips on the dashboard:
   - Strategy Vitals: 3 panels stacked
   - Positions table: instrument column
   - Live chart: dropdown to switch between pairs
   - Equity chart: shows portfolio total + per-pair contribution

6. **`backtest.py`** — extend `run_backtest()` to accept a list of
   (instrument, candles) tuples and run portfolio-level simulation.
   Required for Stage 2 validation.

### Estimate

- Backend multi-instrument refactor: ~1 day
- Backtest portfolio harness: ~0.5 day
- Frontend per-pair display: ~0.5 day
- Testing + validation: ~0.5 day
- **Total: ~2.5 days of focused engineering**

## Hard constraints

1. **No code change ships before current Pullback H1 demo concludes.**
   The current single-instrument demo must run uninterrupted to its
   pre-registered evaluation point.

2. **EUR_JPY freshness must pass Stage 1** before EUR_JPY joins live.
   If it fails, v4 deploys as a 2-pair portfolio (USD_JPY + GBP_JPY)
   and EUR_JPY is dropped.

3. **Stage 2 backtest must pass all bars** before Stage 3 live demo.
   No "the backtest is close enough, let's just see" carve-outs.

4. **Stage 3 demo runs at 0.0833% per-pair sizing**, not at any
   higher level. Earning the right to scale up requires demo data
   first.

5. **No additions to the pair pool** mid-evaluation (no "let's just
   add AUD_JPY since we're already running 3"). Pre-registered pool is
   locked at: USD_JPY, GBP_JPY, EUR_JPY (pending freshness).

## Audit log

| Step | Action | Date | Status |
|------|--------|------|--------|
| 0 | Cross-instrument finding (JPY edge) | 2026-05-06 | DONE |
| 1 | Correlation analysis USD_JPY × GBP_JPY | 2026-05-06 | DONE — 0.62, real but modest diversification |
| 2 | Test new JPY pairs (AUD/EUR/NZD) on deployed defaults | 2026-05-06 | DONE — EUR_JPY qualifies, AUD/NZD don't |
| 3 | Write this v4 spec | 2026-05-06 | DONE |
| 4 | Wait for current Pullback H1 demo to conclude | — | pending |
| 5 | EUR_JPY freshness validation (Stage 1) | — | pending |
| 6 | Engineering: multi-instrument refactor | — | pending |
| 7 | Stage 2 portfolio backtest | — | pending |
| 8 | Stage 3 live demo at third-size sizing | — | pending |
| 9 | Apply Stage 3 decision rule | — | pending |

## What this plan deliberately does NOT do

- Does not deploy mid-current-demo (the discipline that's worked all
  day stays in force)
- Does not include non-JPY pairs (the data is unambiguous they fail)
- Does not optimize parameters per-pair (uses the same defaults that
  passed validation across the family)
- Does not add inverse-vol weighting or other complex sizing schemes
  (defer to v5 if v4 demonstrates the simple version works)
- Does not assume EUR_JPY will pass freshness — the plan handles both
  3-pair and 2-pair fallback cases
