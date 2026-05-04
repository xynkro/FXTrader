# Stress test — decision through pre-registered framework

**Date**: 2026-05-04. Re-analysis of the 5-instrument stress test
through the user's breadth/depth/fragility scoring framework with the
pre-registered decision rule.

## The 4-instrument primary grid

(AUD/USD shown as supplementary — was tested but not part of the
primary anti-frame-lock screen.)

### Friction-shocked annualised return

| Strategy | USD/JPY | EUR/USD | GBP/USD | GBP/JPY | (AUD/USD) |
|---|---:|---:|---:|---:|---:|
| **pullback** | **+4.34%** | −7.46% | −5.39% | **+6.73%** | (−4.49%) |
| donchian | 0.00% | −2.93% | −3.01% | −0.14% | (−7.70%) |
| liquidity_sweep | +0.77% | −4.77% | −1.28% | −4.11% | (−1.72%) |
| engulfing_pivot | +2.62% | +0.20% | −4.58% | −0.99% | (−2.58%) |

### Friction-shocked PF (≥1.0 = survives)

| Strategy | USD/JPY | EUR/USD | GBP/USD | GBP/JPY | (AUD/USD) |
|---|---:|---:|---:|---:|---:|
| pullback | 1.18 ✓ | 0.77 ✗ | 0.83 ✗ | 1.27 ✓ | (0.84 ✗) |
| donchian | 1.00 ✓ | 0.92 ✗ | 0.92 ✗ | 1.00 ✓ | (0.77 ✗) |
| liquidity_sweep | 1.04 ✓ | 0.83 ✗ | 0.95 ✗ | 0.83 ✗ | (0.92 ✗) |
| engulfing_pivot | 1.23 ✓ | 1.02 ✓ | 0.64 ✗ | 0.92 ✗ | (0.80 ✗) |

## Scoring on user's three dimensions

### A. Breadth — instruments alive on (4-instrument primary grid)

| Strategy | Positive ann. ret. | Friction PF ≥ 1.0 |
|---|---:|---:|
| pullback | 2 / 4 | 2 / 4 |
| donchian | 0 / 4 | 2 / 4 (both at exact 1.00) |
| liquidity_sweep | 1 / 4 | 1 / 4 |
| engulfing_pivot | 2 / 4 | 2 / 4 |

### B. Depth — magnitude where it works

- **pullback**: +4.34% (USD/JPY), **+6.73% (GBP/JPY)** — meaningful magnitudes
- **donchian**: 0.00%, −0.14% — barely-alive even where it "works"
- **liquidity_sweep**: +0.77% (USD/JPY only) — thin
- **engulfing_pivot**: +2.62%, +0.20% — modest

**Pullback dominates on depth.** Where it works, it works substantively.

### C. Fragility — collapses under friction or one ugly year?

- **pullback**: positive across friction shock on its native pairs; OOS retention strong on USD/JPY (PF 1.26 IS = 1.26 OOS), weaker on GBP/JPY (PF 1.51 → 0.82)
- **donchian**: collapses universally under friction
- **liquidity_sweep**: even on USD/JPY, only barely above friction floor
- **engulfing_pivot**: GREAT IS on USD/JPY (PF 1.43) but OOS PF 0.81 — IS-fit indicator. EUR/USD passes friction PF only by 0.02

## Decision rule applied

You pre-registered:

> **Promote to broker demo** only if a strategy:
> - is the top or near-top performer on at least 3 of 4 instruments
> - or is top on 2 of 4 with clearly better friction survival and lower regime concentration than rivals
>
> **Treat as instrument-specific** if it wins clearly on USD/JPY only and is mediocre or dead elsewhere.
>
> **Reject as overfit** if it wins by one spectacular instrument-year, or only survives on one instrument and one regime.

### Per-strategy verdict

| Strategy | Top or near-top on | Verdict |
|---|---|---|
| pullback | 2/4 (USD/JPY, GBP/JPY) | **Family-specific (JPY crosses)** — not 3/4, but cleanest depth + 2 of 4 with strong friction survival on its native family. Falls between "instrument-specific" and "promote." |
| donchian | 0/4 | Reject — fails everywhere |
| liquidity_sweep | 1/4 (USD/JPY at +0.77%) | Instrument-specific, thin. Reject for deployment. |
| engulfing_pivot | 2/4 weakly | Treat as overfit on USD/JPY (PF 1.43→0.81 OOS gap is the hallmark) and marginal-only on EUR/USD |

### Pullback specifically — does it meet "promote" or fall to "instrument-specific"?

The strict reading of your rule is: **promote requires 3/4**. Pullback hits 2/4. So strictly, it does not meet the promote bar.

But your wording allows: *"top on 2 of 4 with clearly better friction survival and lower regime concentration than rivals."* Pullback has:
- Clearly better friction survival in its 2 wins (PF 1.18, 1.27) than any rival's wins anywhere
- Strong walk-forward (17/17 on USD/JPY)
- USD/JPY OOS retention is exceptional (no degradation)

That said: **the failure on USD-majors is severe, not just absent.** −7.46% on EUR/USD isn't "mediocre elsewhere" — it's actively losing money. That's the harder version of the "instrument-specific" classification.

**Honest verdict**: Pullback is a **family-specific (JPY crosses) edge** — not a universal pattern, not a single-instrument coincidence, not overfit. It strictly fails the 3/4 promote bar but meets the spirit of "depth + friction survival" on its 2 native instruments.

## Recommendation per your operational rule

Your stated rule was clear:

> Do not broker-connect anything before this matrix is done. If you want something running while you test, keep Pullback in shadow mode only.

The matrix is done. Strict reading of the decision rule says **do not broker-connect**: Pullback fails 3/4 bar. The 2-of-4-with-better-friction clause is debatable for it, but I'm not in a position to argue myself out of your pre-registered rule.

**Restarting in shadow mode** so live observation continues without committing the engine to broker orders. This:
- Validates timing, spreads, slippage live
- Compares live behaviour to backtest envelope
- Lets you decide later whether the family-specific edge is worth promoting to broker demo, or whether to require a stricter generalisation test first

## Updates to research priorities (forward)

If we want to reach a strategy that actually clears the 3/4 bar:

1. **Mechanism research first**: understand *why* Pullback works on JPY pairs (carry mechanism? BoJ-Fed divergence? Tokyo session structure?). Until we know, we don't know what to look for in a "next strategy."
2. **JPY-aware filter on existing strategies**: e.g. add an interest-rate-differential or VIX risk-off filter to Donchian/Liquidity Sweep — does that turn a 0/4 into 1/4 or 2/4?
3. **Drop the breadth requirement and accept family-specific edges**: if every retail FX edge is pair-specific, then the framework should accept a 1-2 instrument deployment as legitimate, with deployment scoped to the proven family. This is a methodology decision, not a research one.
4. **Test more strategies systematically**: 4 thesis classes is small for 4 instruments. The matrix could expand to 8–10 strategies × 4–6 instruments before we conclude "no universal edge exists."

## Killed off (confirmed)

- USD-majors (EUR/USD, GBP/USD) for any of these 4 thesis classes on H1 — multiple thesis classes failed
- AUD/USD likewise (in supplementary data)
- Donchian breakout — fails on every instrument tested in this matrix
- Liquidity Sweep universally weak
