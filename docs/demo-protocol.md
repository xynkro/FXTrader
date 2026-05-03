# Demo Deployment Protocol — v1-B USD/JPY H1

**Pre-registered before turning the engine on.** This doc is the contract.

## Strategy under test

- File: `backend/app/strategy.py`
- Engine: `backend/app/trader.py`
- Instrument: `USD_JPY`
- Timeframe: `H1`
- Account: `101-003-39231292-001` (OANDA practice / demo)
- Logic version: v1-B Donchian breakout intraday with entry-anchored
  chandelier trail (commit at deployment time recorded below).

## Live↔backtest parity contract

- **Initial stop**: fixed at entry ± K × ATR(14)_at_signal. Submitted to
  OANDA via `stopLossOnFill`. Never moves except via the engine's bar-close
  trail logic.
- **Trail logic is engine-side, NOT broker-side.** OANDA's
  `trailingStopLossOnFill` is *not* used — its tick-by-tick distance trail
  has different semantics from the backtest's bar-close anchored chandelier.
  Mixing them would invalidate the backtest as a behavioural envelope.
- **Trail update cadence**: on every new closed H1 bar, the engine computes
  `new_trail = highest_high_since_entry − K × ATR_at_entry` (long; mirror
  for short) and, if it tightens, calls `TradeCRCDO` to replace the OANDA
  stop loss. ATR is frozen at signal time.
- **Known acceptable mismatch**: backtest fills at bar t+1 open; live fills
  at bar t close (~30s later). This is the only intentional drift. If
  realised behaviour diverges from backtest *beyond* this known offset, that's
  a kill criterion (see below).
- **Per-trade audit log fields**: every entry records intended entry, fill
  price, bid/ask, spread in pips, realised slippage, requested vs submitted
  stop price, broker rounding, stop distance, ATR at entry, signal reason.
  Every trail update records prev/new stop and amount tightened. Every
  exit records exit type (initial_stop vs trailing_stop), realised PnL,
  pnl_pct, R-multiple.

## Backtest envelope (the standard live behaviour will be measured against)

5-year USD/JPY H1 backtest at default friction (0.5 pip spread one-side,
0.2 pip slippage):

| | IS | OOS | Friction-shock (full sample, 2× costs) |
|---|---|---|---|
| Trades | 752 | 184 | 936 |
| Win rate | 46.41% | 43.48% | 43.16% |
| Expectancy | +0.0271%/trade | +0.0041%/trade | +0.0101%/trade |
| Profit factor | 1.18 | 1.02 | 1.06 |
| Avg duration | 3.7 bars (~3.7h) | 4.1 bars | 3.7 bars |
| Avg stop | 43.2 pips | 44.2 pips | 43.4 pips |
| Cost as % of stop | 2.7% | 2.2% | 5.2% |
| Exit mix (initial / session_end / trailing) | 2% / 49% / 49% | 2% / 50% / 48% | 3% / 50% / 48% |

## Operational rules (non-negotiable for review window)

- **One instrument**: USD_JPY only.
- **Demo only**: `OANDA_ENV=practice`. Live promotion requires a separate decision.
- **No parameter changes** during the window. If a parameter feels wrong, log
  the observation; do not edit `strategy.py`.
- **No discretionary overrides**: do not manually open/close trades on the
  account during the window. Kill switch only.
- **Logging on by default**: every signal, fill, spread snapshot, slippage,
  and exit reason recorded to `backend/data/trades.db`.

## Review window

End the window at **whichever comes later**:
- 4 weeks of calendar time, OR
- 30 closed trades.

At ~80 IS trades per year on H1, expect roughly 6–8 trades in 4 weeks. So
the trade-count gate is the binding one — likely a 6-to-8-week observation.

## Kill criteria (any one trips the switch immediately)

1. **Friction divergence**. If realised round-trip spread + slippage averaged
   over 10+ trades is more than **2× the backtest model** (i.e. > 1.8 pip
   round-trip equivalent), stop. The backtest envelope no longer applies.
2. **Execution errors**. Any `order_failed`, `kill_close_failed`, or
   `tick_exception` event appearing more than twice in any 24h period. The
   engine itself is the unreliable component.
3. **Behavioural drift**. After 10+ closed trades, if any of these:
   - Avg duration < 2.0 bars (trades dying much faster than backtest 3.7)
   - Initial-stop exits > 15% of trades (backtest had 2%)
   - Trailing-stop exits < 25% of trades (backtest had 48%)
   - More than 1 leverage-cap binding (backtest had 0)
4. **Live realised loss without backtest-shape behaviour**. If at the end of
   the review window the engine is bleeding *and* exit-mix or duration
   distributions don't roughly match the backtest, stop. (The strategy
   could be losing in a way the backtest didn't see — that's the failure
   mode worth catching.)

## What I will *not* do during the window

- Add parameters
- Switch instrument
- Optimize anything
- Run a fresh backtest in response to a bad week
- Promote to live

## What I *will* do at the end of the window

Compute the same diagnostics produced by the backtest:
- expectancy, PF, win rate, max DD
- exit-type breakdown
- avg trade duration
- realised cost as % of stop

Compare side-by-side to the envelope above. If the live numbers fall
outside the envelope by more than a clear margin, the result is a fail
regardless of P&L. If they're inside the envelope and P&L is small or
flat, that's a *successful* observation — we've validated execution and
can decide whether the underlying edge is worth the hassle.
