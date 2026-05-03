# Post-demo research plan

**Pre-registered before demo data arrives.** This is the contract for what
gets researched *after* the USD/JPY H1 demo window closes. Ranked by truth
value, not excitement.

## Operating rule during the wait

While the demo runs, **no new strategy work** unless the demo trips a kill
criterion or the window closes. The temptation will be to add symbols, poke
parameters, or invent a "quick test." All of that is shopping for a lucky
curve. Don't.

## Decision rule once demo concludes

| Demo outcome | First research move |
|---|---|
| Demo trips a kill criterion or behaves materially outside backtest envelope | Start at thesis class 1 (pullback-in-trend) |
| Demo behaves roughly inside envelope but edge is too thin to be useful | Start at thesis class 2 (volatility compression → expansion) |
| Demo behaves inside envelope **and** the edge looks economically usable | Add a small live capital tranche. Then revisit class 1 in parallel. |

Class 3 (regime-conditioning) is **never the first thing** tested. It only
runs after at least one simpler thesis class has been tested honestly and
found wanting.

## Class 1 — Pullback-in-trend (highest truth value)

**Thesis**: don't buy every fresh high; buy continuation after a temporary
retracement *inside* an established trend. Conditions on two things instead
of one (trend exists, then price gives a discount).

**Sketch**:
- Higher-timeframe trend filter says up (e.g. H4 EMA slope, or H4 close above
  20-period high)
- Price pulls back into a defined zone (e.g. EMA(20) on H1, or 50% retrace
  of last impulsive leg)
- Re-entry trigger: H1 close back in trend direction
- ATR stop, trailing or structure-based exit

**Why it ranks first**:
- Directly attacks the failure mode the breakout family showed: noisy
  probes fading quickly
- Doesn't pay spread/slippage at the obvious breakout level where everyone
  piles in
- Still simple enough to falsify cleanly

**What to watch**:
- Fewer trades than breakout (expected — that's the point)
- Better average entry quality
- Higher PF even if win rate doesn't dramatically improve
- Less dependence on a single macro year

## Class 2 — Volatility compression → expansion

**Thesis**: not all breakouts matter. Only breakouts that follow a measurable
squeeze. Compression stores energy, expansion releases it.

**Sketch**:
- Compression definition (pick one for v1, don't combine):
  - ATR percentile low (e.g. ATR(14) below 25th percentile of last 200 bars)
  - Bollinger Band width contracting below a threshold
  - Range compression across last N bars
  - Inside-bar clusters
- Entry: directional breakout once compression resolves
- Exit: trail or structure target

**Why it ranks second**:
- Still close to the breakout family — risk of dressing up the same weak idea
- But it directly attacks "most breakouts are noise" by selecting only the
  subset where structure suggests they should matter
- Falsifiable

**What to watch**:
- Fewer but better trades
- Higher winner concentration (top-5 % of gross profit)
- Less churn, lower trade count per month
- Edge survives friction better because frequency drops

## Class 3 — Coarse regime-conditioned logic (test last)

**Thesis**: USD/JPY's own backtest already showed regime dependence. A
one-state model may be the wrong unit of analysis.

**Hard constraint to avoid overfit**:
- **Coarse regimes only.** Two states max for v1. Not ten micro-states. Not
  optimiser bait.
- Examples:
  - High-vol vs low-vol (e.g. realized 30-day vol above/below median)
  - Trend strength above/below a fixed ADX threshold
  - Policy-divergence proxy (defined without hindsight leakage)
  - Session-only vs hold-overnight environment
- Either:
  - One strategy that only trades in one regime, sits out the other
  - Two very simple sub-strategies with hard regime boundaries

**Why it ranks third**:
- Most powerful potentially, but easiest to fool yourself with
- "Regime-switching" is a frequent euphemism for overfitting
- Should only come after a simpler thesis has been tested honestly

**What to watch**:
- Whether it genuinely removes losing regimes (not just smoothing average)
- Whether trade count remains sufficient in each regime
- OOS degradation becomes less violent than current

## What I will not do

- Add more symbols on the same naive Donchian breakout
- Test BTC/USD just because it moves — too easy to fool yourself with one
  short sample
- "Slightly different Donchian settings" disguised as research
- Combine thesis classes before each is independently tested

## The hardest summary

> The next research win will not come from a better symbol. It will come
> from a better reason to trade.

Build the case for *why* a trade should work, then test that case. Don't
shop the universe for a curve that flatters the current logic.
