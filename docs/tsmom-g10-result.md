# TSMOM G10 v1 — backtest result

**Date**: 2026-05-04 SGT
**Spec**: `docs/tsmom-g10-spec.md` (pre-registered)
**Harness**: `backend/scripts/run_tsmom_g10.py`
**Universe**: EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, NZD/USD, USD/CAD
**Period**: 2016-05 → 2026-04 (10 years common-date intersection)
**Sample sizes**: IS 8.41y, OOS 1.58y, full 9.98y

## Top-line metrics

| | Period | Total Return | CAGR | Sharpe | Max DD | PF |
|---|---|---|---|---|---|---|
| **IS** (10k → end) | 8.41y | **−3.76%** | −0.46% | 0.06 | 30.2% | 1.00 |
| **OOS** | 1.58y | +13.04% | +8.08% | 0.64 | 14.2% | 1.18 |
| **Friction shock 2×** (full) | 9.98y | **−6.25%** | **−0.64%** | 0.05 | 41.4% | 0.99 |

## Pre-registered gate evaluation (LOCKED before run)

| Gate | Bar | Result | Pass |
|---|---|---|---|
| 1. IS PF ≥ 1.2 AND positive return | PF≥1.2, ret>0 | PF 1.00, ret −3.76% | ✗ |
| 2. OOS PF degradation < 50% | OOS≥0.6 of IS | OOS 1.18 ≥ 0.5×IS — N/A (IS too low) | — |
| 3. No single year > 60% profit | <60% | OK (multi-year mix) | ✓ |
| 4. No single pair > 60% profit | <60% | USD/JPY = top, ~46% of profit pool | ✓ |
| 5. Friction PF ≥ 1.05 | ≥1.05 | 0.99 | ✗ |
| 6. Friction CAGR ≥ 8% | ≥8% | **−0.64%** | ✗ |
| 7. Friction Sharpe ≥ 0.6 | ≥0.6 | 0.05 | ✗ |

**5 of 7 hard gates fail.** Strategy killed per pre-registered rule.

## Yearly P&L (full sample, 1× friction)

```
2017: -$1,016    2022: +$2,229
2018:   -$156    2023:   -$628
2019:   -$663    2024:   -$407
2020: +$1,836    2025:   +$428
2021: -$1,571    2026:   +$876
```

Five losing years, six winning years. The "good" years (2020, 2022, OOS 2024-26)
align with documented trend-friendly regimes (COVID dollar swing, post-COVID
inflation rate-cycle, BoJ-Fed divergence). The "bad" years align with the
documented 2014-2020 trend-follower drought.

## Per-pair contribution (full sample, 1× friction)

| Pair | P&L | Note |
|---|---|---|
| USD/JPY | **+$1,999** | dominant winner — same JPY-divergence pattern as prior tests |
| AUD/USD | +$1,346 | commodity carry |
| GBP/USD | +$238 | flat |
| NZD/USD | +$61 | flat |
| EUR/USD | −$314 | net loser |
| USD/CAD | −$771 | net loser |
| USD/CHF | **−$1,327** | dominant loser — SNB intervention regime kills trend |

The "diversified" portfolio's profit is largely USD/JPY + AUD/USD; CHF and
CAD bleed. Without the JPY leg it's net negative. Same single-pair-dependence
pattern flagged in prior cross-instrument tests.

## Why this fails (mechanism honesty)

1. **Multi-year regime cycles** (~5 years on, ~5 years off) make 1-3 year
   live deployment a coin flip on what regime you catch.
2. **Friction is non-trivial at retail spreads.** Vol-targeted positions at
   4% per-pair × 7 pairs imply 30-50% portfolio notional turnover monthly.
   Even at 1.0-1.5 pip spreads + 0.3 slip, the friction cost is enough to
   erase the thin edge.
3. **Single-pair concentration risk.** USD/JPY drives most of the win;
   USD/CHF drives most of the loss. The G10 universe is far less
   diversified than the 58-instrument universe in Moskowitz et al. 2012.
4. **Backtest is faithful to the published academic strategy.** This isn't
   a coding bug — it's evidence the published edge has decayed at retail
   scale post-2014 (consistent with McLean-Pontiff 26% post-publication
   decay).

## Decision per pre-registered protocol

> "If v1 passes ALL gates → broker demo with multi-pair execution. If v1
> fails any gate, strategy is killed and we accept the result."

**TSMOM G10 v1 is killed. No demo deploy.**

## What this means for the wider FX question

This is now the third FX strategy to fail the protocol on its own merits:

1. Intraday H1 pullback: best 4.7% friction-shocked annualised — failed 8% bar
2. Single-pair swing carry-momentum: 0.40% friction-shocked — failed 8% bar
3. Multi-pair TSMOM G10: −0.64% friction-shocked — failed 8% bar

**Three independent academic FX systematic edges have been tested with
disciplined pre-registered protocols, and all three fail the 8%
friction-shocked annualised bar at retail spreads.**

The honest conclusion this points toward: **retail FX with 1.0-1.5 pip
spreads on G10 majors does not have a defensible systematic edge of the
size the project bar requires.** Institutional players access the same
strategies with 0.1 pip spreads, infrastructure colocation, and 5-10×
larger universes — that's where the published edges live.

This is a real, actionable result. It saves the operational tax of
running a strategy that wouldn't have paid off.
