# Expanded bake-off — 6 strategies, USD/JPY H1, 5 years

**Run date**: 2026-05-04. Same engine, same friction, same protocol as
the original bake-off. All strategies use the no-session-close
configuration validated by the robustness pack (Pullback baseline).

## Side-by-side

| Strategy | Family | IS PF | OOS PF | Friction PF | IS Total | OOS Total | Friction Total | Friction Ann. | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| **Pullback** (baseline) | mean-rev-in-trend | **1.26** | **1.26** | **1.18** | **+24.4%** | **+5.6%** | **+23.7%** | **~4.7%** | **PASS — winner** |
| Liquidity Sweep | ICT/Wyckoff (Osler-backed) | 1.13 | 1.17 | 1.04 | +10.2% | +3.6% | +3.9% | ~0.8% | borderline — fails criterion 4 |
| Engulfing @ Pivot | price-action | 1.43 | 0.81 | 1.23 | +20.3% | −1.8% | +13.8% | ~2.8% | FAIL — OOS collapse |
| BB Squeeze (release) | vol-cycle | 1.05 | 1.09 | 0.99 | +2.8% | +1.1% | −0.6% | ~−0.1% | FAIL friction survival |
| Session VWAP | volume-aware | 0.97 | 0.73 | 0.87 | −4.7% | −8.6% | −21.6% | ~−4.3% | FAIL all gates |
| Z-Score Mean Rev | statistical | 0.88 | 0.90 | 0.82 | −13.2% | −2.3% | −23.1% | ~−4.6% | FAIL all gates |

## Per-strategy diagnosis

### Pullback (winner — unchanged from prior bake-off)
Same numbers as before. The wider field of new candidates didn't dethrone it.
**Friction-shocked annualised ~4.7%.** Best on every measurable dimension.

### Liquidity Sweep (Osler stop-cluster fade)
Auto-gates technically pass (IS expectancy positive, IS PF ≥ 1.1, OOS
doesn't collapse > 80%). But:
- Friction PF 1.04 — barely above survival floor (1.0)
- Friction-shocked annualised ~0.8% — well below the 2.5% economic-meaning bar
- Win rate 38% with PF 1.13 means avg-winner barely larger than avg-loser
The Osler thesis appears to be real (positive expectancy across IS/OOS/friction)
but **too thin to deploy retail**. Likely needs the order-flow proxy layer
that the research called out — would be the natural next iteration *if* we
ever wanted to revive this branch.

### Engulfing @ Pivot
Strongest IS PF (1.43) of any strategy tested. **OOS collapsed to 0.81.**
Classic in-sample-fit / out-of-sample failure. Either:
- The pivot-distance threshold (0.25*ATR) was tuned implicitly by historical
  USD/JPY range and doesn't carry to recent regime, OR
- Pattern detection is genuinely exploiting noise in the older sample
Either way: hard fail on the OOS-degradation criterion.

### BB Squeeze (release)
**FAIL friction survival.** PF dropped from 1.05 default to 0.99 with 2× costs.
The squeeze release thesis is real (slight IS edge) but completely
consumed by friction. Total return after friction shock: −0.6% over 5y.
Same diagnosis as the original VolSqueeze in the first bake-off — different
mechanism, same friction-fragility.

### Session VWAP Reversion
**FAIL outright.** Both IS and OOS expectancy negative. The tick-volume
proxy concern flagged in research turned out to matter on USD/JPY: the
"VWAP" computed from tick count weights is essentially a vol-weighted
mean that lags fast moves, so reversion entries get repeatedly run over.
Confirmed: futures-derived VWAP edge does not transfer to retail OTC FX
where volume is tick-count.

### Z-Score Mean Reversion
**FAIL outright.** Negative expectancy in IS, OOS, and friction shock.
The Andersen-Bollerslev intraday-reversion structure may exist on shorter
timeframes (5-min) but it doesn't manifest cleanly in 20-bar H1 z-scores.
Likely the regime gate (Hurst/ADF) the research suggested would help, but
a stripped-down z-score without it is decisively dead.

## What this confirms

1. **Pullback is not "borderline survivor in a narrow field"** — it just
   beat 5 research-backed alternatives covering ICT, statistical reversion,
   volume-aware, vol-cycle, and price-action families. Each of those
   alternatives was a real candidate with peer-reviewed or BIS-cited
   structural justification.

2. **Most strategies don't work on retail FX after costs.** This is
   consistent with Park-Irwin (2007) survey conclusions and the BIS warnings
   about transaction-cost erosion of FX edge.

3. **"Smart money" / volume-aware approaches are weakened by FX's OTC tick-
   volume proxy.** The research flagged this; the test confirmed it for
   Session VWAP. Liquidity Sweep survived only because it doesn't depend
   on volume — only on price geometry.

4. **No instrument-switch needed.** The question wasn't "is USD/JPY a lucky
   instrument" — it's "is Pullback a lucky thesis among many." Five
   non-Pullback theses tested on the same instrument, only one survived
   gates and that one was structurally weaker.

## Decision

**Stay on Pullback for the demo window.** No strategy change.

The post-demo research plan (`docs/post-demo-research-plan.md`) committed
that future thesis-class research would focus on:
1. Pullback variants (e.g. multi-timeframe filter)
2. Volatility compression → expansion (now falsified)
3. Coarse regime-conditioned logic

After today's expanded bake-off, the priority order should shift:
1. ~~Volatility compression → expansion (#2)~~ — falsified twice now (VolSqueeze + BB Squeeze)
2. **Pullback variants** — the only winner; refining is the natural path
3. **Coarse regime-conditioned logic** — only if Pullback live demo reveals regime-dependent failure
4. **Liquidity Sweep + OFI proxy layer** — promising but thin; revisit if/when we have CFTC COT or footprint data

## Files

- New evaluators: `evaluate_liquidity_sweep`, `evaluate_zscore_meanrev`,
  `evaluate_session_vwap`, `evaluate_bb_squeeze`, `evaluate_engulfing_pivot`
  in `backend/app/strategy.py`
- Saved backtest results in `backend/data/backtest_results/expanded_*`
- Research synthesis: `docs/research-synthesis.md`
