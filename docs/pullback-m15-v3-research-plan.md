# Pullback M15 v3 — structural research plan (3 variants, pre-registered)

**Status**: Pre-registered. No execution until current Pullback H1 demo concludes.
**Created**: 2026-05-06
**Predecessor**: `pullback-m15-v2-candidate.md` — KILLED, 8 of 10 bars failed
**Origin**: red-team analysis identifying that v2's failure modes were
*structural*, not parametric.

---

## Background

The v2 M15 candidate (sma_long=200, sma_short=50, pullback_lookback=5,
stop_atr_mult=3.0) was killed on out-of-distribution validation. Failure
modes diagnosed:

- **Regime-dependent**: only 1 of 4 years (2019-2020) was profitable on
  the fresh 2017-2021 USD_JPY M15 window. The optimizer's apparent OOS
  hold (Sharpe +0.83 on 2025-2026) was a third favorable-regime
  coincidence, not edge.
- **Thin profit factor**: PF 0.98 on fresh data. The strategy bleeds in
  most regimes and earns in a narrow subset.
- **Architecturally just "slow H1 on a fast timeframe"**: longer SMAs +
  wider stops compensate for friction but don't introduce a genuinely
  distinct edge mechanism.

## Why this plan exists

To stop ourselves from doing the seductive but worthless thing: nudging
parameters around the dead candidate cluster until something looks green
on a fresh window. That is overfitting with extra steps. Three guesses
in, the laws of statistics deliver another corpse.

The right move is to attack one *structural* weakness at a time, with a
real mechanism story, on fresh data, with the bar set before testing.

## Research discipline (binding for all variants)

1. **One variant at a time.** No compounding tests. No "what if we add
   variant 2 to variant 1's surviving version" — that's how you smuggle
   in degrees of freedom.
2. **Test only on data not used by v1, v2, or any prior cycle**:
   `USD_JPY M15 2014-2017` is the proposed fresh window. (We've now seen
   2017-2026.) If OANDA history doesn't reach back that far, abort the
   entire program — fresh data is non-negotiable.
3. **Pre-register the bars BEFORE running.** Locked in this document
   before any new test fires.
4. **Reject quickly.** If the variant fails its primary bar on first
   clean test, the variant is dead. No re-testing with adjusted bars.
   No "let me just check what happens if..."
5. **Branch kill rule**: if Variant 1 fails AND Variant 3 fails, the
   M15 pullback family is closed. We do not pursue Variant 2 alone as a
   "save" — a session filter that improves stats by trading less is
   cosmetic, not structural.

---

## Variant 1 — M15 entry, H1 regime permission

### Hypothesis

The M15 pullback edge exists ONLY when the H1 timeframe independently
confirms a directional, healthy regime. M15 alone is too noisy to make
that judgment; bleed in 2017-18, 2018-19, 2020-21 was M15 firing during
H1-flat or H1-choppy regimes.

### Mechanism story

Higher-timeframe context filters out the regimes where M15 continuation
quality is structurally poor. This isn't a curve fit — it encodes the
trader-known principle that lower-timeframe trades survive only inside
higher-timeframe trends.

### Exact rules

**Entry conditions** (long; mirror for short):
- All current Pullback M15 v2 candidate conditions on M15 bars
- AND H1 regime gate, evaluated on the most recent CLOSED H1 bar:
  - `H1 close > H1 SMA(100)` (price above H1 trend)
  - `H1 SMA(100) slope positive over last 10 H1 bars` (≈10 hrs)
  - `H1 ATR(14) ≥ 8 pips` (H1 volatility floor — confirms not flat)
  - `(H1 close − H1 SMA(100)) ≥ 0.5 × H1 ATR(14)` (price meaningfully
    away from H1 mean — not glued to it)

**No other change** to entry triggers, stops, or sizing. The structural
change is the H1 permission layer.

**Implementation note**: requires the engine to consume H1 candles in
parallel with M15. Either fetch separately from OANDA or aggregate from
M15 within the strategy. This is non-trivial code work — budget ~1
day to implement before any backtest.

### Pre-registered bars (USD_JPY M15 2014-2017, fresh)

| Bar | Metric | Threshold | Pass condition |
|---|---|---:|:---:|
| 1A | Sharpe | ≥ 0.50 | ≥ |
| 1B | CAGR | ≥ +1.5% | ≥ |
| 1C | Profit factor | ≥ 1.10 | ≥ |
| 1D | Max DD | ≤ 12% | ≤ |
| 1E | Yearly positive count | ≥ 2 of 3 | ≥ |
| 1F | Trades/yr | ≥ 80 (some throttling expected) | ≥ |
| 1G | Sharpe vs v2 candidate | strictly better | > |

### Falsification triggers

- Trade count collapses below 50/yr → filter is too aggressive,
  variant is over-throttling
- Sharpe better than v2 but CAGR worse → improvement is purely from
  trading less; not real
- Any single bar fails

---

## Variant 2 — Session-constrained M15 pullback

### Hypothesis

The pullback edge on M15 exists only in the highest-quality liquidity
window (London open through NY overlap), and the rest of the
07:00-17:00 UTC window is contributing dead weight or noise.

### Mechanism story

Order flow, spread, and continuation quality are mechanically tied to
participation. Outside the densest liquidity hours, USD_JPY M15
continuation tends to mean-revert (or whip) rather than trend. The
strategy's edge — pullback into trend — depends on the trend half of
the regime, which lives in the high-participation window.

### Exact rules

**Entry conditions**: identical to v2 candidate, EXCEPT session window
is narrowed to `12:00 - 16:00 UTC` only (London-NY overlap).

All other params unchanged.

**Implementation note**: trivial. Existing `SESSION_START_UTC` /
`SESSION_END_UTC` config covers it. NO code changes.

### Pre-registered bars (USD_JPY M15 2014-2017, fresh)

| Bar | Metric | Threshold | Pass condition |
|---|---|---:|:---:|
| 2A | Sharpe | ≥ 0.50 | ≥ |
| 2B | CAGR | ≥ +1.5% | ≥ |
| 2C | Profit factor | ≥ 1.10 | ≥ |
| 2D | Max DD | ≤ 12% | ≤ |
| 2E | Yearly positive count | ≥ 2 of 3 | ≥ |
| 2F | Trades/yr | ≥ 60 (narrower window expected) | ≥ |
| 2G | Sharpe vs v2 candidate | strictly better | > |

### Falsification triggers

- Sharpe rises only because trades dropped below 60/yr → cosmetic
  improvement, not real
- Sharpe < v2 candidate's level → narrower window doesn't help; bad
  hours weren't the problem
- Yearly variance still high → session wasn't the source of regime fit

### Branch-kill flag

If Variant 1 has already failed, Variant 2 is run only if explicitly
elevated. Variant 2 alone surviving is suspect (cosmetic improvement).

---

## Variant 3 — Restart-confirmed M15 pullback

### Hypothesis

"Touch SMA(50) then go" is too weak as an entry trigger. The strategy
is firing on drifting retracements that never re-accelerate, paying
friction for limp continuations. Requiring evidence the pullback has
actually ended (continuation has restarted) before entry should
materially improve entry quality and PF.

### Mechanism story

A real pullback in a trending instrument has a specific microstructure:
price retraces to a mean, *then* breaks the most recent micro-swing in
the trend direction (= continuation restarting). The current logic
fires on retracement-in-progress; it should fire on
retracement-completed-and-reversing.

### Exact rules

**Entry conditions**: all v2 candidate conditions, AND the entry bar
must show:
- For longs: bar's high exceeds the prior bar's high
- For shorts: bar's low breaches the prior bar's low

(This is one specific confirmation rule. Variants of it — close above
fast EMA, momentum re-cross, etc. — are NOT tested simultaneously.
That would be a knob hunt. Pick one mechanism, test it cleanly.)

**Implementation note**: small code change. ~1-2 hour task.

### Pre-registered bars (USD_JPY M15 2014-2017, fresh)

| Bar | Metric | Threshold | Pass condition |
|---|---|---:|:---:|
| 3A | Sharpe | ≥ 0.55 (higher bar — confirmation should help) | ≥ |
| 3B | CAGR | ≥ +1.5% | ≥ |
| 3C | Profit factor | ≥ 1.15 (specifically expecting PF improvement) | ≥ |
| 3D | Win rate | ≥ 38% (confirmation should improve hit rate) | ≥ |
| 3E | Max DD | ≤ 10% | ≤ |
| 3F | Yearly positive count | ≥ 2 of 3 | ≥ |
| 3G | Trades/yr | ≥ 80 (later entries means fewer fires) | ≥ |

### Falsification triggers

- Win rate up but expectancy down → confirmation comes too late,
  giving away the move
- PF unchanged from v2 → confirmation isn't actually filtering bad
  setups, it's filtering both equally

---

## Run order and decision tree

```
START
  │
  ▼
Run Variant 1 (H1 regime gate)
  │
  ├─ PASS all bars ──► CANDIDATE — schedule v3 demo cycle (post current H1 demo)
  │
  └─ FAIL ──► Run Variant 3 (restart confirmation)
                │
                ├─ PASS all bars ──► CANDIDATE — schedule v3 demo cycle
                │
                └─ FAIL ──► Run Variant 2 (session filter)
                              │
                              ├─ PASS all bars ──► [yellow flag — see note]
                              │
                              └─ FAIL ──► M15 PULLBACK FAMILY DEAD
                                          Document and move to a structurally
                                          different family (e.g. mean-reversion
                                          with VWAP anchoring, OR different
                                          instrument entirely)
```

**Note on Variant 2 alone passing**: if V1 and V3 both fail and V2
passes, treat with skepticism. Session filtering improves stats by
removing trades, which can mask underlying weakness. Required action:
re-validate Variant 2 on a SECOND fresh window before promoting to
candidate. (This is the only place where additional testing is
permitted, because session-only-pass is the lowest-confidence
verdict.)

## Data requirements

- USD_JPY M15 2014-05-01 to 2017-05-01 (~3y, fresh, never previously
  evaluated) — primary test set
- If OANDA's M15 history doesn't reach 2014, fall back to the earliest
  available start. Document the actual fetched start date.
- All other data already on disk

## What this plan deliberately does NOT do

- Does not optimize parameters within the chosen variant. Each variant
  uses the v2 candidate's parameter set as the starting point and only
  changes the structural element being tested.
- Does not test variants in parallel. Order matters; passing variants
  may not need testing.
- Does not promote any variant to live mid-evaluation. Even on full
  pass, variant enters the v3 candidate pool, scheduled for a fresh
  pre-registered demo cycle AFTER current Pullback H1 demo concludes.
- Does not test on multiple instruments yet. (EUR_USD cross-instrument
  test was discovered to have a `pip_size()` bug in the strategy code
  during v2 validation. Bug must be fixed before any cross-instrument
  test, otherwise results are uninterpretable.)

## Audit log

| Step | Action | Date | Status |
|------|--------|------|--------|
| 0 | Write this spec | 2026-05-06 | DONE |
| 1 | Wait for Pullback H1 demo to conclude | — | superseded — research ran in parallel |
| 2 | Fix `pip_size()` strategy-code bug | 2026-05-06 | DONE — threaded `instrument` through StrategyState + run_backtest |
| 3 | Verify USD_JPY M15 2014-2017 data availability | 2026-05-06 | DONE — downloaded 12y M15 (2014-05 → 2026-05, 298k bars) |
| 4 | Implement Variant 1 (H1 regime gate) — code work | 2026-05-06 | DONE — `aggregate_to_h1()` helper + `evaluate_pullback_h1_gated` + STRATEGIES registration |
| 5 | Run Variant 1 on fresh data | 2026-05-06 | DONE — `run_v1_validation.py` |
| 6 | Apply Variant 1 decision | 2026-05-06 | **FAILED — 5/7 bars: V1 Sharpe -0.46 (worse than v2 -0.30). H1 gate redundant with M15 SMA(200).** |
| 7 | Implement Variant 3 (restart confirmation) | 2026-05-06 | DONE — `evaluate_pullback_restart_conf` (break of prior bar high/low) |
| 8 | Run Variant 3 on fresh data | 2026-05-06 | DONE — `run_v3_validation.py` |
| 9 | Apply Variant 3 decision | 2026-05-06 | **FAILED — 4/7 bars + ALL 3 falsification triggers fired. WR up but expectancy down (entry too late), PF unchanged from v2.** |
| 10 | **BRANCH KILL** | 2026-05-06 | **M15 pullback family officially DEAD. V1+V3 both failed per pre-reg rule. V2 (session filter) NOT pursued — explicitly flagged as "weakest save".** |
| 11 | H1 deployed freshness check (2014-2017) | 2026-05-06 | DONE — H1 default params: Sharpe +0.35, CAGR +1.04%, PF 1.09. Asymmetric finding: H1 = 2/3 positive years, M15 family = 1/3. |

## Outcome summary

**Branch dead.** All three pullback M15 hypotheses pre-registered here have either failed (V1, V3) or were explicitly de-prioritized as cosmetic by the framework (V2). The data has spoken: there is no parameter or single-axis structural modification of M15 pullback on USD/JPY that produces an edge robust to a 2014-2017 fresh-data test.

**Deployed H1 vindicated (mildly).** The same fresh-data check on the LIVE Pullback H1 default produced a weak-but-real Sharpe of +0.35 and PF of 1.09 — meaningfully different from the M15 family's outright negative results. H1 has 2 of 3 fresh years positive vs M15's 1 of 3.

**The 2015-16 USD/JPY chop window broke every variant tested**, including H1 default. This is a structural property of trend-following on USD/JPY during major policy regime shifts (BoJ negative rates, post-CNY-devaluation, Brexit, US election). Bounded and recoverable at 0.25% sizing, but a known weakness.

**Lessons for future research**:
1. "Slow H1 logic on a faster timeframe" is a dead hypothesis class on this instrument.
2. Adding a permission gate that overlaps the existing trend filter is null information.
3. Confirmation rules that require waiting one extra bar tend to give away the move (validated empirically).
4. Pre-registered fresh-data validation is non-negotiable; the OOS-of-optimization is contaminated.
5. The 2015-16 chop window should be a standard stress test for any trend-following candidate going forward.

## Pivot directions for v4

Don't pursue more pullback variants on USD/JPY. Candidate research directions worth a fresh pre-registered cycle:

- **Different family**: mean-reversion at session VWAP with regime-aware sizing
- **Different instrument**: EUR/USD or AUD/USD pullback (after `pip_size` bug fix, which is now done)
- **Different timeframe direction**: D1 swing carry-momentum (already coded, marginal in earlier tests but pre-registered cleanly is worth revisiting)
- **Different stress profile**: build a regime-detection layer that pauses trading during 2015-16-like volatility/correlation breakdowns
