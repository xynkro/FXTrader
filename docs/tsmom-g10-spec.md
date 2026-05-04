# Time-Series Momentum (TSMOM) on G10 FX — pre-registered spec

**Locked before code.** Single-instrument FX has now failed three protocols:
intraday H1 (best 4.7% friction-shocked annualised), single-pair swing
carry-momentum (0.40% friction-shocked annualised). Both failures pointed
at the same root cause: insufficient diversification + thin retail edge
on any one currency pair.

This spec resets to **multi-instrument time-series momentum**, which is
the academic/practitioner gold-standard FX systematic strategy and runs
in production at multi-billion-AUM scale (AQR Managed Futures, Man AHL,
Winton, Lynx, Aspect).

## Thesis (clear, falsifiable)

**Each currency-pair's own past 12-month return predicts its next-month
return, and a portfolio of such signals across G10 majors generates a
diversified return stream uncorrelated with any single pair.**

Backed by:
- Moskowitz, Ooi, Pedersen "Time Series Momentum" *J. Financial Economics*
  2012 — documented ~10-12% pre-cost annualised across 58 instruments
  including FX, with statistically significant 12-month lookback signal.
- Hurst, Ooi, Pedersen "A Century of Evidence on Trend-Following"
  *J. Portfolio Management* 2017 — consistent return premium on
  diversified trend across 137 years.
- AQR Managed Futures Strategy public live track record — same construction.

## Instrument universe & timeframe

**G10-majors-vs-USD, daily bars:**
1. EUR_USD — most liquid, EUR funding regime
2. GBP_USD — cable, BoE-Fed differential
3. USD_JPY — JPY funding currency, BoJ regime
4. USD_CHF — CHF safe-haven, SNB regime
5. AUD_USD — commodity carry currency
6. NZD_USD — high-yield carry currency
7. USD_CAD — commodity, BoC-Fed

7 pairs is enough for the signal to diversify; pulling in EUR_GBP /
EUR_CHF / etc. just adds correlated bets.

**Daily bars. 10 years history (2015-05 → 2025-05) for IS, last 1.5 years
held out as OOS (2024-11 → 2026-05).**

## Signal logic (locked)

For each pair on each daily close:

1. Compute 12-month (252-trading-day) trailing total return: `r_252 =
   (close[t] / close[t-252]) - 1`
2. **Long signal**: `r_252 > 0`. **Short signal**: `r_252 < 0`. Flat if
   exactly zero (vanishingly rare).
3. **No additional filter.** No SMA, no carry overlay, no regime gate.
   Pure TSMOM as published. Adding filters here = the start of
   curve-fitting.

## Position management

**Per-pair sizing (inverse-volatility):**
- Compute trailing 60-day daily-return standard deviation `σ_60`
- Target portfolio annualised vol contribution per pair: 4% (so 7 pairs
  × 4% = 28% naive sum, but realised will be ~10-12% due to
  cross-correlations — typical multi-pair TSMOM target)
- Position size in units = `(target_vol / (σ_60 × sqrt(252))) × equity / price`
- This is the Moskowitz-Ooi-Pedersen sizing rule, not our existing
  per-trade risk framework. Stop-loss is implicit in the vol target.

**Rebalance frequency:** monthly. On the last trading day of each month,
re-evaluate signals and rebalance positions. Between rebalances,
positions stay constant (no intra-month adjustments).

**Hard exits (regime override):** none in v1. The pure TSMOM rule has
no discretionary exits. If the spec needs them later, that's a
documented v2 change.

## Friction model

- Spread: 1.0 pip per side on majors, 1.5 pips on crosses (USD_JPY,
  AUD_USD, NZD_USD)
- Slippage: 0.3 pips per side
- **Friction shock test: 2× spread + 2× slippage.** Same protocol as
  prior tests.

## Pre-registered pass gates (LOCKED)

A strategy **wins this round** only if it meets ALL of:

1. **IS portfolio PF ≥ 1.2** AND **expectancy > 0** (matches swing v1)
2. **OOS portfolio PF doesn't degrade by more than 50%** vs IS
3. **No single year > 60% of cumulative profit** (regime concentration)
4. **No single pair > 60% of cumulative profit** (instrument concentration)
5. **Friction shock PF ≥ 1.05**
6. **Friction-shocked annualised portfolio return ≥ 8%**
7. **Sharpe ≥ 0.6 friction-shocked** (documented academic benchmark for
   diversified trend is ~0.7-1.0)

The 8% bar is the same as swing — doesn't move, the protocol exists to
prevent that exact tweaking.

If v1 passes ALL gates → broker demo with multi-pair execution. If
v1 fails any gate, strategy is killed and we accept the result.

## What this spec explicitly does NOT include

- Carry overlay (we tested it, failed)
- Cross-sectional momentum (long top-3, short bottom-3) — different
  hypothesis, would need separate spec
- Volatility-targeting at portfolio level (only per-pair). v2 if v1 passes.
- Asymmetric long/short scaling (some literature suggests TSMOM is
  stronger short-side in bonds, mixed in FX). Symmetric in v1.
- Multiple lookback periods (some implementations use 1m/3m/12m
  ensemble). Single 12m lookback in v1.

## Files that change

- `backend/scripts/multi_pair_backtest.py` — NEW: multi-instrument harness
- `backend/app/strategy.py` — add `evaluate_tsmom_signal` (per-pair signal)
- `backend/app/portfolio_backtest.py` — NEW: portfolio P&L aggregator
- `docs/tsmom-g10-spec.md` — this file (locked)

## Honesty constraints (binding, copied from prior specs)

- No "looks promising" language.
- No parameter polishing in response to bad runs.
- If v1 fails, the failure is the result. Don't tweak lookback from 252
  to 200 and re-run pretending it was always the plan.
- The 8% annualised bar reflects what's defensible vs alternatives
  (cash, S&P buy-and-hold). Below it, the strategy doesn't justify the
  operational tax.

**Author**: locked 2026-05-04 14:55 SGT, before any code or backtest run.
