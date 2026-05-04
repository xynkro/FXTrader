# Strategy research synthesis (post-/research)

**Date**: 2026-05-04. Five parallel research agents covered five thesis
families with peer-reviewed / BIS-backed evidence where available, and
honest "this is practitioner-only" flags where not.

## Findings by family

### Family 1 — ICT/SMC + Wyckoff (smart-money)

| Concept | Evidence | Verdict |
|---|---|---|
| **Liquidity sweep / spring reversal** | Osler NY Fed SR150, EPR 2000, NBER 12413 — strong | **TEST** |
| Round-number + flow-imbalance | Evans-Lyons 2002, Cont-Stoikov 2014 — strong but needs OFI proxy | Layer onto #1 |
| Pure FVG fill | Practitioner only; one cited study showed 30–45% non-tradeable | Skip |
| Order/breaker/mitigation blocks | No peer-reviewed evidence; collapses into S/R + momentum | Skip |
| Wyckoff phases A–E | Non-falsifiable in raw form; spring = sweep | Skip |

### Family 2 — VWAP + Volume Profile

**Foundational caveat**: FX is OTC. OANDA's "volume" is tick count, not
notional. The widely-cited 90% tick-vs-real-volume correlation circulates
without a clean primary source. BIS WP 93/2 explicitly note tick frequency
is a noisy proxy. Volume Profile transferred verbatim from CME futures into
OANDA spot is **not the same indicator** — expect ~60–70% of futures-tested
edge.

| Strategy | Evidence | Verdict |
|---|---|---|
| **Session VWAP ±2σ reversion (Tokyo / London)** | Larisma USD/JPY+VWAP+RVI, equity 2σ band literature | **TEST** (degrades to vol-weighted-mean reversion if tick-vol thesis fails) |
| Previous-day POC / VA reversion | Practitioner; futures-derived | Risky — tick-vol POC ≈ time-modal price |
| Naked POC magnet | "80% revisit" stat is futures folklore | Skip |
| Multi-timeframe VWAP confluence | Subsumed by session VWAP + daily filter | Skip |

### Family 3 — Classical indicators

| Strategy | Evidence | Verdict |
|---|---|---|
| **Z-score mean reversion** | Andersen-Bollerslev 1998 *JoF* directly supports intraday FX reversion | **TEST** — strongest academic spine |
| **Bollinger Squeeze (vol expansion)** | Carter/ChartSchool; vol-clustering microstructure (Engle ARCH) | **TEST** — different from prior VolSqueeze (squeeze release timing, not while-compressed) |
| KAMA trend filter | Kaufman; equity backtests | Useful as overlay, not standalone |
| Ichimoku | Liberated Stock Trader 15,024-trade test underperformed B&H 90% | Skip standalone |
| SuperTrend | Practitioner-only; 67% win rate on liquid futures | Skip — too similar to existing trail logic |
| Heikin-Ashi reversal | Risk reduction, not alpha | Skip |
| RSI divergence | Pivot detection is retrospective, high overfit risk | Skip — overfit-bait |
| Connors RSI(2) | Magic numbers from daily-equity context, no theoretical re-derivation | Skip — overfit-bait |
| Keltner reversion | ATR-bands smoother but theoretically weaker than BB | Folded into BB Squeeze |

### Family 4 — Macro / event-driven

| Strategy | Evidence | Verdict |
|---|---|---|
| Carry-momentum hybrid | Brunnermeier-Nagel-Pedersen 2008 (gold standard) | **Skip for this round** — needs FRED data; horizon is days-weeks not H1 |
| Term-spread / curvy trade | Lustig-Stathopoulos-Verdelhan ECB WP 2149 | Skip — same data + horizon constraints |
| **FOMC/BoJ event fade** | Lucca-Moench NY Fed SR512; Lee-Wang SSRN 4386170 (~65% reversal) | **Skip for this round** — small sample (16/yr); won't accumulate enough demo trades in window |
| Risk-off JPY safe-haven | CEPR; correlation regime-shifts | Useful filter, not standalone |
| Time-of-day / session | Ito-Hashimoto NBER 12413 | Already encoded as session filter |

### Family 5 — Pure price action + geometric

| Strategy | Evidence | Verdict |
|---|---|---|
| **Engulfing/pin bar at PDH-PDL or Camarilla pivot + EMA200 trend filter** | QuantifiedStrategies engulfing-at-context 71% win on equities; Park-Irwin survey 56/95 positive on TA in FX | **TEST** — fully deterministic, no swing ambiguity |
| Fib retracement-in-trend (as confluence filter) | Lento-Gradojevic, Bhattacharya — Fib alone indistinguishable from random | Skip — only useful as filter, not primary signal |
| Harmonic patterns (Gartley/Bat/Crab/etc) | No peer-reviewed evidence; multiple-comparisons + post-hoc selection | Skip — un-falsifiable for systematic use |
| Elliott Wave | Aronson "story not theory"; Prechter forecast record | Skip — un-testable |

## The 6-strategy bake-off

All implementations share the same engine framework: bar-close anchored
chandelier trail (K=2.0 ATR(14) frozen at signal), session filter for entry
(07:00–17:00 UTC), trades hold across session boundaries, account-currency
aware sizing (0.5% risk per trade), MIN_STOP_PIPS=5 + MAX_LEVERAGE=30
safeguards. Only the **entry condition** differs.

| # | Strategy | Family | Core thesis |
|---|---|---|---|
| 0 | **Pullback-in-trend** (existing baseline) | Mean-rev-in-trend | Buy continuation after pullback to SMA(20) inside SMA(100) trend |
| 1 | **Liquidity Sweep / Spring Reversal** | ICT/Wyckoff | Fade exhaustion of stop-cluster cascades at swing extremes / round numbers |
| 2 | **Z-Score Mean Reversion** | Statistical | Standardised price-deviation reversion (Andersen-Bollerslev) |
| 3 | **Session VWAP ±2σ Reversion** | Volume-aware | Fade overstretch from vol-weighted intraday mean (anchored at session open) |
| 4 | **Bollinger Squeeze (release)** | Vol-cycle | Trade volatility expansion at the moment BB exits Keltner |
| 5 | **Engulfing/Pin at Pivot** | Price action | Engulfing/pin bar within 0.25*ATR of PDH/PDL/Camarilla pivot |

**Pre-registered pass criteria** (same as bake-off + robustness pack):
- IS expectancy > 0 AND IS PF ≥ 1.1
- OOS doesn't degrade by more than 80% on PF or expectancy
- No single year > 70% of cumulative profit
- Friction shock PF ≥ 1.0
- Friction-shocked annualised return ≥ 2.5% (current Pullback bar to beat: ~4.7%)

If multiple strategies pass: pick the one with the best combination of
**friction PF, regime distribution, and OOS retention** — not the highest
raw return.

## What this round explicitly will not test

- Carry/term-spread (data + horizon mismatch with current engine)
- FOMC event fade (sample too small for demo window)
- Order-flow proxies / CFTC COT / triangular arb
- Harmonic patterns / Elliott Wave (un-falsifiable)
- RSI divergence / Connors RSI (overfit-bait flagged)
- Pure FVG / order blocks (no peer-reviewed evidence)
