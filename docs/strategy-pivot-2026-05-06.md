# Strategy pivot report — Pullback family killed, v5 candidates

**Generated**: 2026-05-06 (per `strategy-pivot-designer` skill methodology)
**Trigger**: Iteration stagnation detected after 6 failed variants in one day on the M15 Pullback family. Decision tree exhausted.
**Status**: Research-only proposals. NO live deployment until current Pullback H1 demo concludes. v4 (USD_JPY + GBP_JPY portfolio) is the next deployment slot; these v5 candidates queue behind it.

---

## Stagnation diagnosis (auto-detected from iteration history)

| Trigger | Status | Evidence |
|---|---|---|
| Plateau on backtest score | ✅ FIRED | Six iterations, all fresh-data Sharpe in -0.46 to +0.27 range; no upward trajectory |
| Overfitting (high IS, low OOS) | ✅ FIRED | H1 IS optimization: top-10 IS Sharpe +1.78 → OOS -1.20 (textbook) |
| Cost defeats thin edge | ✅ FIRED | M15 timeframe: friction = 36% of stop distance; PF degrades from 1.19 (H1) to 0.90 (M15) |
| Tail risk exceeds threshold | ✅ FIRED | 2015-16 BoJ-shock year breaks every variant: -5% USD_JPY, -5.4% V1, -4.86% V3, -1.89% EUR_JPY |
| Architectural redundancy | ✅ FIRED | V1 H1 SMA(100)=100h overlapped with M15 SMA(200)=50h → null filter |

**Verdict**: stagnation across 5 of 5 triggers. Pivot mandatory.

## Pivot techniques applied

The skill's framework: instead of tweaking parameters, mutate the strategy's *skeleton*. Three techniques.

---

## Pivot 1 — CARRY-HEDGED TREND  (Archetype Switch)

**Rank**: #1 (highest upside × novelty)

### What's switched

| Component | Dead Pullback family | Carry-Hedged Trend |
|---|---|---|
| Source of edge | price-trend continuation | **interest-rate differential (carry)** |
| Signal generator | SMA crossover + retracement | **BoJ-Fed (or BoJ-ECB, BoJ-BOE) policy rate spread** |
| Holding horizon | hours-days | **weeks-months** |
| Entry trigger | M15/H1 pullback touch | **regime threshold cross on rate spread** |
| Exit trigger | trailing chandelier stop | **carry inversion or vol-regime kill** |

### Mechanism story

The 2014-2026 USD_JPY trend that powered our backtest wasn't random — it was the cumulative integral of BoJ's structural dovishness vs Fed's normalization cycles. Pullback strategies *implicitly* harvest this by riding the price drift; carry strategies *explicitly* harvest it by holding long the high-yielder and pocketing the rollover swap.

OANDA pays/charges nightly swap on open positions. For long USD_JPY at the 2024-2025 rate differential, that was ~+5 pips/day in swap revenue. **The Pullback strategy's avg trade made +3.2 pips after friction; a carry-hedged hold during the same period would have collected ~+5 pips/day** continuously, modulo position size.

The mechanism story is durable: **BoJ has held rates near zero for 25 years.** Whenever USD/EUR/GBP central banks tighten, carry exists. When they ease (2008, 2020), carry compresses but doesn't usually invert.

### Falsification specs (pre-registration sketch)

Pre-register before testing on fresh data:
- **Bar A**: 5y carry-hedged backtest Sharpe ≥ 0.70 (must beat deployed Pullback's 0.69)
- **Bar B**: max drawdown ≤ 8% (allowing wider given longer holds)
- **Bar C**: explicit kill switch on carry inversion or vol-regime spike (avoid 2024-08 yen-carry-unwind type events)
- **Bar D**: same fresh-data freshness test on 2014-2017 USD_JPY
- **Bar E**: must work on at least 2 of the 3 v4-validated JPY pairs (USD/JPY, GBP/JPY)

### Why it pivots correctly

- Doesn't reuse SMA / Pullback / regime-gate logic — entirely different signal source
- Has a real macro mechanism (rate differential = cash flow), not a curve-fit
- Different timeframe (weeks-months) means different friction profile (1 trade per regime cycle vs 117/yr)
- Can be tested on the same OANDA practice account (rollover is computed automatically)

### Risks / why it might fail

- **Carry blowup risk** — 2008 GFC, Aug 2024 yen-carry unwind: events where the carry currency rallies 8-10% in days as the trade unwinds. Need a hard volatility-spike kill switch.
- **OANDA's swap rates** are worse than institutional carry, eats some of the edge
- **Different from existing engine architecture** — would need a new state machine for "regime-following hold" vs "discrete trades"

---

## Pivot 2 — VOL-REGIME FILTERED PULLBACK  (Assumption Inversion)

**Rank**: #2 (lowest engineering cost, directly addresses observed failure mode)

### What's inverted

The dead family ASSUMED: "The strategy works across regimes; we just need to find the right entry filter."

The DATA SAYS: "The strategy works in normal regimes and dies in volatility-regime breaks (2015-16). Stop trying to make M15 alignment fix a regime problem."

The INVERSION: "**The strategy already works. Don't change it. Just turn it OFF when the regime breaks.**"

### What's switched

| Component | Dead Pullback variants | Vol-Regime Filter |
|---|---|---|
| Strategy skeleton | unchanged | unchanged Pullback H1 deployed defaults |
| New element | (was: regime gate, restart conf) | **realized-vol regime kill switch** |
| Mechanism | (M15 entry filtering) | **macro vol classifier (separate from price action)** |

### Mechanism story

Look at the 2015-16 catastrophe across every variant:

| Variant | 2015-16 CAGR |
|---|---:|
| Deployed Pullback H1 | -5.00% |
| V1 (H1 gate) | -5.40% |
| V3 (restart) | -4.86% |

That year had three structural events:
1. PBoC yuan devaluation (Aug 2015) → cross-FX correlation spike
2. BoJ negative rates announcement (Jan 2016) → JPY pair shock
3. Brexit referendum (Jun 2016) → GBP shock

These aren't normal trading regimes. They're **macro vol events** that break trend strategies as a class — not specifically Pullback's M15 logic.

The pivot: instead of trying to "fix" the strategy for these regimes (impossible), explicitly DETECT them and pause trading.

### Concrete rule sketch (pre-registration)

```
SUSPEND_TRADING_IF:
  - 30-day realized vol on USD/JPY > 1.5 × (5-year rolling mean of 30-day realized vol)
  - OR JPY-cross intraday range > 2.0 × 252-day average
  - OR trailing 60-day Pullback drawdown > 4% (live PnL signal)

RESUME_TRADING_IF:
  - All conditions above clear for ≥10 consecutive trading days
```

### Falsification specs

- **Bar A**: 5y backtest with filter ≥ deployed Pullback Sharpe (0.69) — filter shouldn't hurt
- **Bar B**: 2015-16 specific year must show ≤ -2% CAGR (vs -5% currently) — filter must materially improve bad-regime year
- **Bar C**: filter must be active during 2015-16 BoJ-shock window AND during 2024-08 yen-carry-unwind (look-ahead vol thresholds verifiable from historical realized vol)
- **Bar D**: false-positive rate: filter must NOT pause trading more than 15% of the time in non-shock years (otherwise it's just trade reduction)

### Why it pivots correctly

- Inverts the failed assumption: "fix the entry" → "fix WHEN to be active at all"
- Different decision layer: vol-regime classifier operates above the strategy, not inside it
- Doesn't share code with the dead M15 variants
- Direct test of the "tail-risk-bounded" failure mode the data exposed

### Risks

- Could over-fit the vol thresholds to look-back 2015-16 specifically
- Defense: pre-register thresholds before running test, use multi-criteria filter (not just one vol number)
- The 4 trades you save in 2015-16 vs the 13 trades you give up in normal years — needs careful balance

---

## Pivot 3 — BOJ EVENT-REACTION TRADER  (Objective Reframe)

**Rank**: #3 (most academically interesting, hardest to validate due to small N)

### What's reframed

The dead family OPTIMIZED for: **per-trade Sharpe averaged over many trades**.

The REFRAME: **per-event return concentrated around discrete macro decision points**.

If the JPY-divergence edge is real, where is the signal density highest? Most likely answer: the moments when BoJ announces a policy decision relative to market expectations. Those are the few events where the divergence regime actually re-prices.

### What's switched

| Component | Dead Pullback family | BoJ Event-Reaction |
|---|---|---|
| Trades/year | 117 (continuous) | **~16** (discrete, around 8 BoJ meetings + 8 FOMC meetings) |
| Per-trade size | 0.25% risk | **3-5x larger** to compensate for fewer trades |
| Signal | price action | **policy surprise vs OIS-implied consensus** |
| Holding period | 9.5 bars (~10h) | **24-72 hours per event window** |

### Mechanism story

Academic FX research (e.g. Lustig & Roussanov, 2009; Berge, Jordà & Taylor, 2010) shows that FX risk premia are concentrated around scheduled monetary policy announcements. The market PRICES IN expected policy via OIS (overnight indexed swaps); the trade is to pre-position for SURPRISES.

Specifically: when BoJ holds and Fed hikes (or vice versa), JPY-pair price action in the 24-72 hours after BoJ's statement reflects the differential surprise. This is the "macro event reaction premium" — concentrated, episodic, and driven by exactly the BoJ-divergence regime that powers the deployed Pullback's edge.

### Concrete rule sketch

```
For each scheduled BoJ Monetary Policy Meeting (~8/year):
  PRE_EVENT (24h before):
    - Read OIS-implied probability of rate hike/cut/hold
    - Read Bloomberg/Reuters consensus survey
    - Compute "surprise potential" = |consensus - OIS-implied|

  POST_EVENT (within 1h of statement):
    - Compute realized policy outcome
    - Surprise direction = realized vs consensus

    IF surprise dovish (BoJ more dovish than expected) → LONG USD_JPY for 48h
    IF surprise hawkish → SHORT USD_JPY for 48h
    ELSE no trade

  EXIT after 48 hours OR on 2*ATR adverse move (whichever first)
```

### Falsification specs

- **Bar A**: 10-year backtest needs ≥ 30 BoJ events with surprise signal
- **Bar B**: signal direction correct (above 60% directional accuracy)
- **Bar C**: avg event-reaction return after 48h ≥ 30 pips per trade
- **Bar D**: walk-forward validation: 2014-2020 train, 2020-2026 test, must hold

### Why it pivots correctly

- Completely different time-axis: 16 trades/year, not continuous
- Completely different signal source: policy surprise vs price action
- Extremely high signal-to-noise per trade if the academic literature holds
- Tests if the macro mechanism we believe in (BoJ divergence) is actually concentrated at announcement events

### Risks

- **Sample size**: ~80 events in 10 years is statistically thin
- **Data dependency**: need OIS-implied data + analyst consensus historically (free sources unclear; OANDA doesn't provide)
- **Black-box risk**: if the surprise direction matters more than magnitude, simple "hawkish/dovish" classification might be too coarse
- **Could be already priced in**: HFT desks already trade BoJ surprises in the first second; retail might not have alpha left

---

## Comparative ranking

| Pivot | Mechanism | Engineering | Data needs | Time to validate | Upside if valid | Downside if invalid |
|---|---|---|---|---|---|---|
| **#1 Carry-hedged trend** | Macro carry differential | Medium (new state machine) | Existing OANDA + rollover history | 1-2 weeks | High — different return profile, real cash flow | Just confirms Pullback was the only working approach |
| **#2 Vol-regime filter** | Tail-risk avoidance via realized vol | Low (filter wraps existing) | Just price history | Days | Medium — same strategy, smoother profile | We learn that 2015-16-type events aren't predictable |
| **#3 BoJ event-reaction** | Policy-surprise premium | High (event scheduling, OIS data) | OIS implied + analyst consensus | 2-4 weeks | High — concentrated alpha if real | Sample-size kills hypothesis test power |

## Recommendation order for v5 research cycle

1. **Pivot #2 (Vol-Regime Filter) first** — lowest cost, directly addresses observed failure mode, can be tested in days. If it works, we ship the deployed Pullback + filter as v5; if not, we've learned 2015-16 type events are unpredictable.

2. **Pivot #1 (Carry-Hedged Trend) second** — natural macro extension of the JPY-divergence thesis we already validated. If it works, fundamentally different return stream than the deployed Pullback (low correlation; real diversification beyond v4's 11% modest gain).

3. **Pivot #3 (BoJ Event-Reaction) last** — most theoretically interesting but data infrastructure is a separate engineering project (OIS feed, consensus surveys). Defer until the simpler pivots resolve.

## What this report does NOT do

- Does not modify the live engine (deployed Pullback runs unchanged on USD_JPY)
- Does not start the v4 multi-instrument cycle (queued for after current demo concludes)
- Does not commit to any of these pivots — they're pre-design proposals; each needs its own pre-registration spec when its turn comes
- Does not optimize parameters within the dead M15 Pullback family (the discipline that closed it stays closed)

## Audit log

| Step | Date | Status |
|---|---|---|
| Stagnation detection (5/5 triggers fired) | 2026-05-06 | DONE |
| Pivot #1 (Carry-hedged) drafted | 2026-05-06 | DONE — research-only |
| Pivot #2 (Vol-regime filter) drafted | 2026-05-06 | DONE — research-only |
| Pivot #3 (BoJ event-reaction) drafted | 2026-05-06 | DONE — research-only |
| User review and selection | — | pending |
| Pre-registration spec for selected pivot | — | pending |
| Engineering | — | pending (post current-demo + v4) |
| Fresh-data validation | — | pending |
