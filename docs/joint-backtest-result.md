# Joint backtest: Pullback + Liquidity Sweep — FAIL the bar

**Run date**: 2026-05-04. Pre-registered rules: 0.25% risk per lane,
priority=Pullback (suppresses Sweep on shared bars), no session-end
forced close, max 1 concurrent per lane, separate cooldowns.

## Headline numbers

| | Pullback solo (0.5%) | Joint combo (0.25% + 0.25%) | Δ |
|---|---:|---:|---:|
| Trades | 587 | 1098 (587 + 511) | +511 from B |
| Default friction return | +33.37% | +26.64% | **−6.73 pp** |
| **2× friction return** | **+23.66%** | **+16.50%** | **−7.16 pp** |
| **2× friction annualised** | **4.34%** | **3.11%** | **−28.5% relative** |
| Max DD (2× friction) | 8.22% | 6.06% | −2.16 pp (better) |

The combo has **lower return AND lower drawdown** — symptoms of *lower
average exposure*, not real diversification benefit. Each lane sized at
0.25% (half the solo budget) means smaller positions; smaller positions
deliver smaller returns AND smaller drawdowns approximately
proportionally.

## Why the combo loses on returns

- Pullback in combo: 587 trades → +16.29% (~half of solo's +33.37%, as
  expected from half-size positions).
- Sweep in combo: 511 trades → +10.35%.
- Both contributing positively, but Sweep's per-trade economics are
  thinner than Pullback's.
- Sum: +26.64% < +33.37%. The thinner edge drags the weighted average.

## Why the combo wins on DD

- Lower position sizes → lower drawdowns mechanically.
- Plus mild diversification: **per-month P&L correlation = +0.015
  (essentially zero)**, so they don't draw down at the same time.
  But near-zero correlation isn't enough to overcome the return drag
  from blending a thin edge with a strong one.

## Per-period correlation breakdown

```
Months where both produced trades: 60
Full sample : +0.015
2022–2023   : −0.008
2024–2025   : +0.093
```

Correlation is consistently near zero across periods. **The two
strategies are statistically independent** in their P&L timing — but
that independence doesn't rescue the combo because:
- Diversification math (Markowitz) only delivers Sharpe uplift when
  both components have *positive* Sharpe of similar magnitude.
- Pullback has clean positive Sharpe; Sweep has thin positive Sharpe.
- The weighted blend's Sharpe ≈ weighted average ≈ slightly worse than
  the strong component alone.

## Yearly contribution

Both lanes contribute positively most years; Sweep's loss in 2023
(−$127) drags the combo when Pullback was already weak that year (−$5).
2024–2026 all positive both lanes.

```
2021: combined +$250  [A: 79 trades +$130, B: 71 trades +$120]
2022: combined +$1148 [A:114      +$699, B: 99       +$449]
2023: combined −$132  [A:129 −$5,         B:101 −$127]
2024: combined +$746  [A:121      +$427, B: 98       +$319]
2025: combined +$529  [A:104      +$378, B:110       +$151]
2026: combined +$123  [A: 40 +$0,         B: 32 +$123]   (4 months)
```

## Operational notes (signal interaction)

- Bars where both lanes fired same bar: **16 / 31,104** (~0.05%)
- Pullback's trade count solo (587) = in-combo (587). The priority
  rule never blocked a Pullback signal, only blocked Sweep when both
  fired. Crowding is **not** a meaningful issue.

## Verdict per pre-registered bar

User-locked criteria for combo to win:
1. ≥15% improvement in friction-shocked annualised return → **−28.5%** ✗
2. No worse, or meaningfully better, max DD → −2.16 pp better ✓
3. Lower regime concentration → not measurably so
4. No ugly dependence on overlap → confirmed (16/31104) ✓
5. Operational complexity justified by improvement → no — return drag
   wipes out the DD benefit

**FAIL.** The user's stated threshold was clear: "I would not accept
slightly better." Combo is *worse on returns and better on DD by
roughly equivalent magnitudes* — same risk-adjusted return with extra
complexity. That's the textbook "operational mess for negligible
portfolio benefit" the framework explicitly rejects.

## Decision

**Deploy Pullback-only for the demo window.**

Per the user's pre-registered escape rule: "If the combo is not clearly
better, deploy Pullback-only" — invoked.

This is the third converging finding in this project's research history
that a borderline component should NOT be promoted into deployment by
combining it with a stronger one. Pattern across all three:

| Test | Result |
|---|---|
| Original bake-off (Pullback vs Donchian vs VolSqueeze) | Donchian "borderline alive" was demoted to research-only after Pullback won |
| Expanded bake-off (5 new candidates added) | Liquidity Sweep "borderline" was held out of deployment despite passing auto-gates |
| Joint backtest (this) | Borderline + Strong does not improve on Strong alone |

The honest path forward remains the post-demo research plan:
1. Validate Pullback live on demo
2. Develop the *next* validated edge (Pullback variants — multi-TF
   filter, regime gate)
3. *Only after* there's a second cleanly validated edge, retest the
   joint configuration with that edge instead of Sweep.

## Files

- Joint backtester: `backend/scripts/joint_backtest.py`
- Joint result artifact (this run, default friction):
  `backend/data/backtest_results/<stamped>_joint_pullback_sweep/` (none
  saved — joint results not persisted as the spec was a one-shot test)
