# Pullback at institutional spreads — pre-registered retest

**Locked before run. 2026-05-04 SGT.**

## Hypothesis

Pullback's edge is real but eaten by retail spreads. At institutional /
ECN-broker spreads (Pepperstone Razor, IC Markets Raw, Tickmill Pro,
LMAX, Saxo Pro), the friction-shocked CAGR clears the 8% deployment bar.

## What changes vs prior test

Strategy code: **unchanged**. Same `evaluate_pullback()` from
`backend/app/strategy.py`, same parameters (SMA 100/20, K=2.0 ATR, ATR
period 14).

Friction model: **lower per-side cost**.

| | Per-side spread | Per-side slip | Round-trip 1× | 2× shock |
|---|---|---|---|---|
| Retail (original test) | 0.5 pips | 0.2 pips | 1.4 pips | 2.8 pips |
| **Institutional (this test)** | **0.2 pips** | **0.1 pips** | **0.6 pips** | **1.2 pips** |

Reduction: friction at 2× shock falls from 2.8 → 1.2 pips per round trip
(57% less). This matches what the named ECN brokers actually quote on
EUR/USD and USD/JPY during liquid sessions.

## Data

Same 5-year H1 datasets already on disk:
- `USD_JPY_H1_1825d.json`
- `GBP_JPY_H1_1825d.json`

Both pairs because the cross-instrument stress test established the
edge exists on JPY-family pairs specifically.

## Pre-registered pass gate

Single hard gate (since this is a re-friction of an already-tested
strategy, not a new strategy):

**Friction-shocked CAGR ≥ 8% on USD/JPY** *AND* **friction-shocked
PF ≥ 1.05 on USD/JPY**.

Pass → broker-switch is on the table. Run on GBP/JPY confirms whether
the edge generalises.

Fail → institutional spreads also don't clear it. The edge isn't
there at any retail-accessible spread tier; FX systematic on retail
brokers (any tier) is dead for this project.

## Honesty constraint

If USD/JPY clears 8% but only by tweaking the spread parameter
post-hoc, that's data-mining. Lock at 0.2 pip BEFORE running. If the
result is 7.9%, that's a fail, not a "close enough."

If the live broker quote at deployment time turns out to be 0.4 pip
not 0.2 pip, the deployment doesn't happen. The test parameter is the
deployment parameter.
