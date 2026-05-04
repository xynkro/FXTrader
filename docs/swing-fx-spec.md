# Swing / macro-informed FX research — pre-registered spec

**Locked before code.** The intraday FX research path was exhausted at
~4.7% friction-shocked annualised on USD/JPY (best result), which is
below current US 2Y yields and not deployment-grade. This spec resets
the project to where the public FX evidence actually lives:
**multi-day carry-momentum on daily bars**.

## Thesis (clear, falsifiable)

**Long high-yielder when both momentum and macro risk-regime agree.**

The structural backing for carry trade is one of the strongest in all
of FX academia:
- Brunnermeier, Nagel & Pedersen (NBER WP 14473, 2008): documented
  carry-trade payoff structure; identified crash-risk asymmetry as
  the primary failure mode.
- Asness, Moskowitz & Pedersen (J. Finance 2013): value & momentum
  everywhere — carry-momentum hybrids dominate either factor alone.
- Lustig, Stathopoulos, Verdelhan (ECB WP 2149): yield-curve slope
  augments the carry signal; flatter relative slope predicts lower
  excess returns.
- BIS Triennial / Galati-Heath: documents JPY's historical role as
  the dominant funding currency.

The intraday research project established USD/JPY as the cleanest
JPY-cross instrument we have working infrastructure for. Swing
extends that with the macro layer.

## Instrument & timeframe

- **USD/JPY only** for v1. The most-liquid major + clearest carry
  story (USD lender, JPY borrower funding currency).
- **Daily bars (D)**. Decisions made on daily close, orders fire at
  next daily open. Holds typically 5–15 days.
- 5+ years of history (2020–2025) for IS, plus reservation of 2026
  H1 as OOS.

## Data sources

- **OANDA v20 REST**: USD/JPY daily bars (already wired)
- **FRED (Federal Reserve Economic Data)**: free public API
  - `DGS2` — US 2-year Treasury yield
  - `IRLTLT01JPM` — Japan long-term yield (10Y proxy; 2Y not directly
    available daily, will use 10Y differential as carry signal)
  - `VIXCLS` — CBOE VIX index for risk-regime filter
- All cached locally; FRED rate-limits at ~120 requests/min with key
  but our needs are far below

## Signal logic (locked for v1)

### Long entry — all three conditions must hold at daily close

1. **Trend filter**: `close > SMA(20) AND SMA(20) > SMA(50)` on USD/JPY daily.
2. **Carry filter**: `(US 10Y yield − JP 10Y yield) > 0` AND rising or stable
   (compare today vs 20-day mean of the differential).
3. **Risk-regime filter**: `VIX < 25` (no crash regime).

### Short entry — mirror

All three inverted. Exits same.

### Position management

- **Stop**: at entry ± `K × ATR(20)` where `K = 2.0`. ATR computed on
  daily bars.
- **Trail**: same engine-side bar-close anchored chandelier as
  intraday, just on daily close.
- **Hard exit (regime override)**: VIX closes above 30 → close any
  open position next day's open regardless of strategy state.
- **Carry-flip exit**: if yield differential flips negative AND stays
  there for 5 consecutive trading days while in a long, force-close.

### Sizing

- 0.5% risk per trade (account-currency aware — already implemented).
- Max 1 concurrent position.
- MIN_STOP_PIPS guard raised to **20 pips** for daily timeframe (was 5
  for H1). Reflects daily ATR scale.

## Pre-registered pass gates (same protocol)

A strategy **wins this swing round** only if it meets ALL of:

1. **IS expectancy > 0 AND IS PF ≥ 1.2** (slightly stricter than the
   intraday bar of 1.1, because lower trade count means we want a
   stronger signal per trade)
2. **OOS doesn't degrade by more than 50%** on PF (stricter than 80%
   from intraday — fewer trades makes degradation more diagnostic)
3. **No single year > 60% of cumulative profit** (stricter than 70%)
4. **Friction shock PF ≥ 1.05** (stricter than 1.0)
5. **Friction-shocked annualised return ≥ 8%** (stricter than 2.5%
   bar from intraday — daily horizons should produce more, not less,
   because friction is amortised over larger moves)

If v1 passes ALL gates → broker demo on USD/JPY. If not, kill the
swing branch and take the result honestly to inform the larger
"is retail FX a productive sandbox" question.

## What this spec explicitly does NOT include

- Multi-currency carry portfolio (BIS-cited "diversified carry"
  research uses 5–10 currencies). v1 is single-instrument first to
  validate the framework before scaling.
- Dynamic position sizing based on yield differential magnitude.
  Standard 0.5% per trade for v1 to maintain comparison with
  intraday baseline.
- Fundamental data beyond FRED (no central-bank communication
  parsing, no economic-surprise indices, no positioning data from
  CFTC COT).
- Pyramiding, scaling-in, or layered entries. One trade at a time.

## Validation ladder (after v1 in-sample / out-of-sample passes)

1. **Friction shock** (2× spread + slip) — already in protocol
2. **Walk-forward** rolling 12-month windows stepped 3 months
3. **Cross-instrument** generalisation test on the same swing logic
   applied to GBP/JPY, EUR/USD, AUD/USD with their respective
   yield differentials (5 instruments minimum; 3+ must pass)
4. **Mechanism honesty check**: report friction-shocked return
   broken down by years where carry differential was widest vs
   narrowest. If the strategy only works during BoJ-Fed divergence
   peaks, surface that.

## Honesty constraints (binding)

- No "looks promising" language.
- No parameter polishing in response to bad runs.
- If v1 fails, the failure is the result. Don't tweak K from 2.0 to
  1.8 and re-run pretending it was always the plan.
- The 8% annualised bar reflects what's defensible vs alternatives
  (cash, S&P buy-and-hold, simple momentum portfolios). Below it,
  the strategy doesn't justify the operational tax.

## Files that will change

- `backend/app/data_sources.py` — new: FRED client (rate yields, VIX)
- `backend/app/strategy.py` — add `evaluate_swing_carry`
- `backend/app/strategies_swing.py` — separate file if the daily
  feature handling gets large (decide during implementation)
- `backend/scripts/download_history.py` — already supports `--granularity D`
- `backend/scripts/run_backtest.py` — add support for swing exits
  (carry-flip, VIX regime hard-stop)
- `.env.example` — add `FRED_API_KEY` placeholder
- `docs/post-demo-research-plan.md` — update to reflect this pivot
