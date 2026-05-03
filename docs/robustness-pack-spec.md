# Pullback Robustness Pack — pre-registered

**Locked before code. Pullback only. Same engine, same friction. No
parameter changes inside this pack.**

## Frozen bake-off context

- Donchian: demoted (still alive but baseline-thin, regime-dependent).
- VolSqueeze: dead (OOS negative, regime concentration > 100%).
- Pullback: research winner. **Not** deployment winner.

This pack determines whether Pullback earns broker-connected demo or
stays in research.

## Three tests (all run before any deployment decision)

### Test 1 — Session constraint structural test

Question: is the session-end forced close amputating the right tail?

Method:
- Pullback v1, USD/JPY H1, 5y, default friction.
- Two runs: `force_close_at_session_end=True` (control, baseline result)
  vs `False` (lets trades hold across session boundaries until stop or
  trail hit).
- Signal generation stays in-session both ways. Only the exit rule changes.

Pre-registered reading:
- If "no force close" materially improves expectancy and friction PF,
  the session constraint was the binding flaw, not the thesis. Pass.
- If "no force close" makes things worse (overnight risk eats the gains),
  the constraint was protective. Pass *if and only if* the original
  configuration is solid.
- If both look similar, the session rule is neutral and we can ignore it.

### Test 2 — Walk-forward stability

Question: does the edge live across regimes, or is it carried by one
window the IS/OOS split happened to capture nicely?

Method:
- Split the 5y series into **rolling 12-month windows stepped 3 months
  forward**. Roughly 14 overlapping windows.
- Run Pullback v1 on each window as a standalone backtest. Same friction.
- For each window, record: trades, PF, expectancy, total return, max DD,
  win rate.

Pre-registered reading:
- Pass: positive expectancy in **at least 70%** of windows (≥10 of 14),
  and **PF distribution median ≥ 1.05**. No single window > 50% of
  cumulative across-windows P&L.
- Fail: <70% positive windows, OR median PF < 1.0, OR a single window
  carries > 50% of total P&L.

### Test 3 — Shadow live mode

Question: does Pullback produce sane live signals with real spreads
and behaviour matching backtest, *without* placing real orders?

Method:
- Engine runs in shadow mode: same tick loop, same strategy evaluation,
  same trail update cadence — but `client.market_order` and
  `client.replace_trade_stop` are stubbed. Instead, hypothetical fills
  and stop updates are recorded to the local DB with a `shadow=true`
  flag.
- For each shadow signal: capture real OANDA bid/ask, hypothetical fill
  at the relevant side, hypothetical slippage = 0.2 pip (matches
  backtest model), hypothetical stop = sig.stop.
- Trail computed exactly as live engine would, but never sent.
- Stop-out detection: each new bar, check if bar's high/low crosses the
  current shadow stop. If yes, mark "closed" with the stop price.
- Run for **2 weeks calendar OR 5 closed shadow trades**, whichever later.
- At end, compute the same diagnostics as backtest: avg duration,
  exit-mix, cost-as-%-of-stop, expectancy, PF.

Pre-registered reading:
- Pass: shadow behaviour stays inside backtest envelope on:
  - Avg duration: within ±50% of backtest median (4 bars → range 2–6)
  - Exit-mix: trailing_stop > 30%, initial_stop < 20%, session_end ~50%
  - Realised round-trip cost (entry spread + entry slip + exit slip):
    < 1.8 pip (= 2× backtest model)
- Fail: any of the above out of envelope. Strategy is doing something
  meaningfully different live than the backtest models.

## Final gate after all three tests

To earn **broker-connected demo**, all three must pass. AND
friction-adjusted economics must be "meaningfully above why bother" —
defined here as **friction-shocked annualized return ≥ 2.5%** in the
walk-forward median window. (Same bar as the bake-off's criterion 4,
applied here per-window so we're not anchored on a single 5y number.)

If any test fails, the strategy stays in research. We do not deploy.

## What this pack does NOT include

- New parameter sweeps on Pullback. The whole point is to validate the
  current logic, not to optimize it past these gates.
- Combining theses (e.g. Pullback + compression filter together).
- Trying Pullback on other instruments. Same-instrument-only test.
- Walk-forward with parameter re-fitting per window. The strategy is
  parameter-light by design; refitting would invite curve-fit charges.

## Honesty constraints (binding)

- No "looks promising" language.
- Each test produces an explicit PASS / FAIL with the binding criterion.
- If all three pass *and* the economic bar is met, then and only then
  do we propose broker demo. If two pass and one fails, that's a fail
  for the pack — not a "majority vote" win.
- Shadow mode runs unconditionally regardless of how tests 1 and 2 land,
  because it observes live integrity which the backtest cannot tell us.
