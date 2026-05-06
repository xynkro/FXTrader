# v5-α and v5-β — Pullback enhancement candidates from TV lessons

**Status**: Pre-registered. NO execution until current Pullback H1 demo + v4 (USD_JPY + GBP_JPY portfolio) ship.
**Created**: 2026-05-06 (extracted as lessons from TradingView strategy ports)
**Origin**: Caspar's red-team challenge → self-audit revealed frame-lock bias and ensemble-vs-standalone bar conflation. The audit also produced two structural lessons that don't fit the dead M15-Pullback family or the v3 plan but DO fit as enhancements to deployed Pullback.

---

## Background

Today's TV strategy import (Forex Master v4 + FX Master L/S) produced
ZERO new deployable strategies — both failed pre-registered bars on
JPY pairs. **But each contained a coherent mechanism worth absorbing
into Pullback as a structural filter.**

The discipline rule (workflow doc rule #5: don't invent features) was
maintained — these v5 candidates are pre-registered AS NEW
HYPOTHESES, not as silent modifications to the deployed Pullback.

The audit also revealed that:
- TV-B on USD/JPY M15 5y RECENT passed bars (Sharpe +0.64, CAGR +1.67%, PF 1.11)
- TV-B on USD/JPY M15 2014-2017 FRESH failed (Sharpe −0.01) → recency-fit, killed
- 50/50 Pullback + TV-B portfolio improved Calmar 0.53 → 0.92, BUT relies on
  TV-B as a component which itself fails freshness

So: TV strategies as standalone or as ensemble components don't survive
discipline. But two structural insights do.

---

## v5-α — Pullback + ADX-falling no-trade filter

### Insight extracted

TV-A's `EMA(6) of DX < EMA(12) of DX` ("ADX is falling") is a
real trend-dying detector. The Pullback strategy fires "continuation
in trend" — but if the ADX is decreasing, the trend isn't healthy and
we're firing pullbacks into trends about to die.

### Hypothesis

The 2015-16 catastrophe year for Pullback (-5% CAGR) was driven by
firing trend-continuation signals during a regime where multi-day
trends were degrading. An ADX-falling NO-TRADE filter would skip those
bars. This is *structurally different* from V1's H1-SMA gate (which
killed because H1 SMA(100) was redundant with M15 SMA(200)) — ADX
velocity is an orthogonal signal.

### Exact rules

**Entry conditions (long; mirror for short):**
- All current deployed Pullback rules (unchanged)
- AND ADX-rising filter: `EMA(6) of DX > EMA(12) of DX` (the OPPOSITE
  of TV-A's mean-reversion gate, since we want to ENTER when trend is
  healthy not dying)

**Implementation note**: ~2 hours of code. Adapt the Wilder ADX
calculation already implemented in `evaluate_tv_forex_master_v4`. New
evaluator `evaluate_pullback_adx_filter`.

### Pre-registered bars (USD_JPY H1 2014-2017, fresh)

| Bar | Metric | Threshold |
|---|---|---:|
| α-1 | Fresh Sharpe | ≥ +0.40 (Pullback baseline freshness was +0.35; must improve) |
| α-2 | 2015-16 specific year CAGR | ≥ −2.5% (vs Pullback's −5.0%; filter must materially help bad-regime year) |
| α-3 | Trades/yr | ≥ 70 (filter shouldn't over-throttle) |
| α-4 | Max DD on fresh window | ≤ 7% (vs Pullback's 8.20%) |
| α-5 | 2 of 3 fresh years positive (vs Pullback's 2 of 3 — must hold or improve) | ≥ 2 |

### Falsification triggers

- Trade count drops below 50/yr → over-throttling
- Sharpe improves but CAGR drops → improvement is from trading less, not from filtering bad setups
- 2015-16 doesn't improve → filter doesn't fix the actual failure mode

### Decision rule

- All α-1 through α-5 pass → CANDIDATE for v5-α demo cycle
- Any fail → KILLED, do not retry with adjusted bars

---

## v5-β — Pullback + smoothed-RSI momentum confirmation

### Insight extracted

TV-B's smoothed-RSI is a noise-filtered momentum signal. Raw RSI(14)
crosses 50 dozens of times per session; EMA(20) of RSI(10) crosses 50
maybe 1-2 times per week and only when momentum is genuinely aligned.
Pullback already filters by trend (SMA position) and pullback (touch),
but doesn't currently confirm momentum direction independently.

### Hypothesis

Pullback's losing trades are disproportionately ones where the trend
filter said "yes" but underlying momentum (smoothed-RSI) was actually
pointing the other way. Adding smoothed-RSI as a **confirmation gate**
should skip those mismatch setups.

### Exact rules

**Entry conditions (long; mirror for short):**
- All current deployed Pullback rules (unchanged)
- AND `EMA(20) of RSI(10) > 50` for longs (momentum agreement)
- AND mirror for shorts: `EMA(30) of RSI(30) < 50`

**Implementation note**: ~1 hour of code. Reuse RSI/EMA helpers from
`evaluate_tv_fx_master_longshort`. New evaluator
`evaluate_pullback_rsi_confirm`.

### Pre-registered bars (USD_JPY H1 2014-2017, fresh)

| Bar | Metric | Threshold |
|---|---|---:|
| β-1 | Fresh Sharpe | ≥ +0.40 |
| β-2 | Fresh CAGR | ≥ +1.2% (must improve over Pullback's +1.04%) |
| β-3 | Trades/yr | ≥ 60 (smoothed-RSI shouldn't kill too many) |
| β-4 | Max DD ≤ 7% | ≤ 7% |
| β-5 | Win rate ≥ 40% (confirmation should improve hit rate) | ≥ 40% |

### Falsification triggers (anti-cosmetic)

- WR rises but expectancy falls → confirmation comes too late, gives away the move (same trap as V3 from yesterday)
- Same 2015-16 catastrophe year → momentum filter doesn't fix regime breakdown
- Smoothed-RSI ALIGNS with deployed Pullback's existing trend filter (high redundancy → no new info)

### Decision rule

- All β-1 through β-5 pass → CANDIDATE for v5-β demo cycle
- Any fail → KILLED

---

## Decision tree (v5)

```
START
  │
  ▼
Run v5-α (ADX-falling filter)
  │
  ├─ PASS all bars ──► v5-α CANDIDATE → schedule v5-α demo cycle
  │                     (after current demo + v4)
  │
  └─ FAIL ──► Run v5-β (smoothed-RSI confirmation)
                │
                ├─ PASS all bars ──► v5-β CANDIDATE
                │
                └─ FAIL ──► Both lessons absorbed but neither survives.
                            Pullback baseline holds. Consider pivot to
                            v5-γ candidates from strategy-pivot-2026-05-06.md
                            (carry-hedged trend, vol-regime filter, BoJ events).
```

## Cross-references

- TV strategy import results: `pullback-v4-multiinstrument-spec.md`
- v3 dead family: `pullback-m15-v3-research-plan.md`
- Pivot proposals: `strategy-pivot-2026-05-06.md`
- Workflow doc: `tradingview-mcp-workflow.md`
- Self-audit results: `backend/data/backtest_results/self_audit_2026_05_06.json`

## Audit log

| Step | Date | Status |
|---|---|---|
| Lessons extracted from TV-A and TV-B | 2026-05-06 | DONE |
| v5-α pre-registered | 2026-05-06 | DONE |
| v5-β pre-registered | 2026-05-06 | DONE |
| Wait for current Pullback H1 demo to conclude | — | pending |
| Wait for v4 (Pullback × {USD_JPY, GBP_JPY}) to ship + run | — | pending |
| Implement v5-α | — | pending |
| Run v5-α validation | — | pending |
| Apply v5-α decision rule | — | pending |
| If failed: implement v5-β | — | conditional |

## What this plan deliberately does NOT do

- Does not deploy v5-α or v5-β NOW (mid-evaluation rule still binding)
- Does not optimize parameters for either filter beyond the source's defaults
- Does not silently modify deployed Pullback — these are EXPLICITLY new variants
- Does not commit to multiple-comparison correction since we're testing one variant at a time
- Does not assume passing recent-data validation means anything; freshness is the only gate
