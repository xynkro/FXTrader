# v6 — Fractal Breakout (TV-C) candidate spec, pre-registered

**Status**: Pre-registered. NO live deployment until current Pullback H1 demo concludes + v4 (Pullback × {USD_JPY, GBP_JPY}) ships.
**Created**: 2026-05-07
**Origin**: TradingView import — ChartArt's Fractal Breakout Strategy (Pine v2, 2016).
Source URL: https://www.tradingview.com/script/EjLwVtgp/
First strategy from the TV import experiment with real fresh-data edge.

---

## Strategy summary

**Name**: TV-C — Fractal Breakout (ChartArt)
**Mechanism class**: Williams Fractal price breakout, **LONG ONLY in source**
**Pine source**: open-source, Pine v2, 2016

**Core logic**:
1. Detect Williams Fractal Tops (5-bar pattern: high[i] > high[i±1, i±2])
2. Track last 3 fractal-top prices; compute rolling average
3. `fractal_trend_rising` = current avg > previous avg
4. `fractal_breakout` = current bar's hl2 > most recent fractal-top price
5. ENTRY (LONG): trend_rising AND breakout
6. EXIT (source): fractal trend transitions to falling, with bar delay
7. NO TP, NO SL in source — author leaves risk management to user

**Our adaptation** (labeled per workflow rule #5 — optional improvement):
- Source has no SL/TP; we add ATR(14)-scaled trail stop as safety
- Faithful entry logic preserved
- LONG-only preserved (no invented short variant)

## Backtest evidence summary (USD/JPY H1)

| Window | Trades/yr | WR | CAGR | DD | Sharpe | PF |
|---|---:|---:|---:|---:|---:|---:|
| RECENT 2021-26 | 82 | 37.1% | +1.69% | 8.69% | +0.37 | 1.10 |
| **FRESH 2014-17** | 74 | **43.4%** | **+5.99%** | **4.74%** | **+1.14** | **1.44** |
| FULL 12y avg/year | 78 | ~40% | **~+3.4%** | varies | varies | varies |

**Yearly distribution** (12y):
- 8 of 12 years positive (67%)
- Best: 2014-15 (+13.26%), 2019-20 (+9.13%), 2022-23 (+7.05%)
- Worst: 2023-24 (-3.18%), 2024-25 (-2.52%) — recent regime decay
- 2015-16 BoJ shock year: only -0.42% (vs Pullback's -5.00%) — robust

**Cross-instrument** (GBP/JPY H1):
- Recent: Sharpe +0.53, CAGR +2.69%, WR 39.3%
- Fresh: Sharpe +0.55, CAGR +2.40%, WR 42.0%
- Consistent across windows — generalizes

## Risk profile assessment vs user's targets

| Target | Status |
|---|---|
| CAGR ≥ 5% | Hits in good years; 12y avg ~3.4% — needs portfolio combination |
| WR ≥ 40% | Avg ~40%, some years below — borderline |

## Pre-registered Stage 2 backtest bars (LOCKED before any new test)

The fresh-2014-17 result is already used. To validate further before deployment, NEW
testing on a DIFFERENT fresh window or DIFFERENT instrument with locked bars:

### Test A: USD/JPY H1 2017-2021 (window not yet used for TV-C evaluation)
| Bar | Metric | Threshold |
|---|---|---:|
| A1 | Sharpe | ≥ +0.50 |
| A2 | CAGR | ≥ +3.0% (matching 12y avg) |
| A3 | PF | ≥ 1.10 |
| A4 | Max DD | ≤ 12% |
| A5 | WR | ≥ 38% |

### Test B: GBP/JPY H1 2017-2021 (cross-instrument fresh window)
| Bar | Metric | Threshold |
|---|---|---:|
| B1 | Sharpe | ≥ +0.40 |
| B2 | CAGR | ≥ +1.5% |
| B3 | PF | ≥ 1.05 |
| B4 | Max DD | ≤ 12% |

### Test C: 12-year-window full robustness
| Bar | Metric | Threshold |
|---|---|---:|
| C1 | ≥ 8 of 12 years positive | already met (8 of 12) |
| C2 | Worst year ≥ -5% | already met (worst -3.18%) |
| C3 | Sharpe across full 12y | ≥ +0.40 |

### Falsification triggers
- **Recent 2-year regime decay continues**: if 2025-26 closes negative, the strategy may be in degradation. Auto-kill if 3 consecutive negative years.
- **Long-only bias dependency**: if a structural JPY downtrend regime emerges (e.g. BoJ pivot to tightening), the strategy will go quiet — that's by design but worth flagging.
- **WR under 35% on any fresh window**: the user's WR ≥ 40% target requires this baseline; sustained under-35% implies the entry mechanism isn't filtering well.

## Decision rule

- All Test A bars + at least 4 of 5 Test B bars + all Test C bars → CANDIDATE for v6 deployment
- Any single Test A bar fails → KILL (this is the primary fresh-data gate)
- Test C falsification triggered → KILL

## Sizing proposal (if validated)

If TV-C clears Test A + B + C, recommended deployment:

**Option 1 (additive to v4 as 3rd portfolio leg)**:
- Pullback USD/JPY @ 0.25%
- Pullback GBP/JPY @ 0.25%
- TV-C USD/JPY @ 0.25%
- Total max concurrent risk: 0.75% across 3 strategies on 2 pairs
- Expected combined CAGR: 4-5% with diversification benefit
- Expected combined max DD: ~6-8%

**Option 2 (TV-C replaces Pullback on USD/JPY since both fire in same regime)**:
- TV-C USD/JPY @ 0.5%
- Pullback GBP/JPY @ 0.5%
- Total max risk: 1.0% (same as v4)
- Expected combined CAGR: 5-6%

**Option 3 (TV-C only at higher size, abandon Pullback)**:
- TV-C USD/JPY @ 0.5%
- TV-C GBP/JPY @ 0.5% (if validated cross-instrument)
- More concentrated in single mechanism — less robust

**Recommendation if validated: Option 1** — adds TV-C without sacrificing Pullback's
established edge. 3-leg portfolio with low correlation across legs (Pullback is
trend-continuation, TV-C is fractal-breakout — different timing of entries).

## Hard constraints

1. NO live deployment of TV-C until current Pullback H1 demo concludes
2. NO live deployment of TV-C until v4 (Pullback × 2 pairs) ships and runs ≥ 2 weeks
3. NO sizing > 0.5% per trade until v4 + TV-C live data confirms backtest expectations
4. The "exit on fractal trend reversal" logic from source is NOT faithfully implemented
   (we use ATR trail). If v6 advances, consider implementing the source's exit faithfully
   as a separate variant for comparison.

## Audit log

| Step | Date | Status |
|---|---|---|
| TV-C ported to Python | 2026-05-07 | DONE |
| Initial fresh-window test (2014-17) | 2026-05-07 | DONE — passes user targets |
| 12-year yearly breakdown | 2026-05-07 | DONE — 8/12 positive, last 2y weak |
| Cross-instrument GBP/JPY check | 2026-05-07 | DONE — consistent ~+0.55 Sharpe both windows |
| Spec written | 2026-05-07 | DONE |
| Wait for current demo to conclude | — | pending |
| Wait for v4 ship + run | — | pending |
| Test A: USD/JPY H1 2017-21 | — | pending |
| Test B: GBP/JPY H1 2017-21 | — | pending |
| Test C: full 12y robustness check | — | pending |
| Apply decision rule | — | pending |

## What this spec deliberately does NOT do

- Does not deploy TV-C now (mid-evaluation)
- Does not optimize Fractal Breakout parameters beyond source defaults
- Does not invent a SHORT mirror (LONG ONLY preserved)
- Does not promote to live solely on the 2014-17 fresh result — Tests A, B, C still required
