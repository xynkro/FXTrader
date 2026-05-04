# Demo Deployment Protocol — Pullback (no-session-close) USD/JPY H1

**Pre-registered before broker-connected demo. This doc is the contract.**

This replaces the original v1-B Donchian deployment plan. The bake-off
(see `bakeoff-spec.md`) and robustness pack (see `robustness-pack-spec.md`)
falsified Donchian as the deployment candidate and validated Pullback
without session-close as the candidate to test live.

The user explicitly chose to skip the shadow-mode rung and proceed
straight to broker-connected demo. Demo orders incur no real money cost
(OANDA practice account); the only thing risked is the deployed-engine's
infrastructure attention budget on a thin candidate.

## Strategy under test

- File: `backend/app/strategy.py` → `evaluate_pullback`
- Engine: `backend/app/trader.py`
- Instrument: `USD_JPY`
- Timeframe: `H1`
- Account: `101-003-39231292-001` (OANDA practice / demo)
- Strategy entry rule: SMA(100) trend filter + recent SMA(20) pullback
  + close-back-in-trend trigger
- Stop & trail: entry-anchored chandelier, K=2.0, ATR(14) frozen at signal
- Session: signals only fire 07:00–17:00 UTC, **but trades hold across
  session boundaries** (no force-close at session end). This is the
  configuration validated by walk-forward (17/17 windows positive).

## Live↔backtest parity contract

- **Initial stop**: fixed at entry ± K × ATR(14)_at_signal. Submitted to
  OANDA via `stopLossOnFill`. Never moves except via the engine's bar-close
  trail logic.
- **Trail logic is engine-side, NOT broker-side.** OANDA's
  `trailingStopLossOnFill` is *not* used — its tick-by-tick distance
  trail has different semantics from the backtest's bar-close anchored
  chandelier. Mixing them would invalidate the backtest as a behavioural
  envelope.
- **Trail update cadence**: on every new closed H1 bar, the engine computes
  `new_trail = highest_high_since_entry − K × ATR_at_entry` (long; mirror
  for short) and, if it tightens, calls `TradeCRCDO` to replace the OANDA
  stop loss. ATR is frozen at signal time.
- **Known acceptable mismatch**: backtest fills at bar t+1 open; live fills
  at bar t close (~30s later). This is the only intentional drift.
- **Per-trade audit log fields**: every entry records intended entry, fill
  price, bid/ask, spread in pips, realised slippage, requested vs submitted
  stop price, broker rounding, stop distance, ATR at entry, signal reason.
  Every trail update records prev/new stop and amount tightened. Every
  exit records exit type (initial_stop vs trailing_stop), realised PnL,
  pnl_pct, R-multiple.

## Backtest envelope (the standard live behaviour is measured against)

Pullback no-session-close, 5-year USD/JPY H1 at default friction
(0.5 pip half-spread + 0.2 pip slippage = 0.9 pip round-trip baseline):

| | IS | OOS | Friction-shock (2× costs) |
|---|---|---|---|
| Trades | 480 | 107 | 588 |
| Win rate | 46.4% | 47.1% | 37.9% |
| Expectancy | +0.0508%/trade | +0.0510%/trade | +0.0379%/trade |
| Profit factor | **1.26** | **1.26** | **1.18** |
| Total return | +24.4% over 4y | +5.6% over 1y | +23.7% over 5y |
| Avg duration | 9.6 bars | 9.4 bars | 9.5 bars |
| Median duration | 5 bars | 6 bars | 5 bars |
| Avg stop | 42.8 pips | 42.2 pips | 42.6 pips |
| Cost as % of stop | 2.74% | 2.32% | 5.33% |
| Exit-mix (initial / trailing / session) | 4% / 96% / 0% | 3% / 97% / 0% | 4% / 96% / 0% |

## Operational rules (non-negotiable for review window)

- **One instrument**: USD_JPY only.
- **Demo only**: `OANDA_ENV=practice`. Live (real-money) promotion requires
  a separate decision after this window.
- **No parameter changes** during the window. If a parameter feels wrong,
  log the observation; do not edit `strategy.py`.
- **No discretionary overrides**: do not manually open/close trades on the
  account during the window. Kill switch only.
- **Logging on by default**: every signal, fill, spread snapshot, slippage,
  and exit reason recorded to `backend/data/trades.db`.

## Review window

End the window at **whichever comes later**:
- 4 weeks of calendar time, OR
- 10 closed trades.

(At backtest pace ~120 trades/year, expect ~9–10 trades in 4 weeks.)

## Kill criteria (any one trips the switch immediately)

1. **Friction divergence**. If realised round-trip cost averaged over 5+
   closed trades exceeds **1.8 pips** (= 2× the 0.9 pip backtest model),
   stop.

   **Round-trip cost is precisely defined as:**
   ```
   round_trip_cost_pips =
       (ask_at_signal − bid_at_signal)        # entry spread, full pips
     + |fill_price − mid_at_signal| / pip     # entry slippage
     + |exit_price − mid_at_exit|  / pip      # exit slippage
   ```
   Adverse stop *execution drift* is measured separately under criterion 3.

2. **Execution errors**. Any of `order_failed`, `kill_close_failed`, or
   `tick_exception` (engine-side bugs / unhandled code paths) appearing
   more than twice in any 24h period.

   **Note**: `network_error` events are *not* counted toward this
   criterion — they're transient OANDA-side or local-network turbulence
   (connection reset, DNS failure, read timeout, idle-connection reap)
   and are auto-recovered on the next 30s tick. Only events the
   classifier tags as code errors trip this criterion.

3. **Behavioural drift**. After 5+ closed trades, if any of these are
   true:
   - Median duration < 3 bars OR > 8 bars (backtest median = 5)
   - Avg duration < 5 bars OR > 14 bars (backtest avg = 9.5)
   - Initial-stop exits > 15% of trades (backtest = ~4%)
   - Trailing-stop exits < 80% of trades (backtest = ~96%)
   - More than 1 leverage-cap binding (backtest = 0)

4. **Live realised loss without backtest-shape behaviour**. If at the
   end of the review window the engine is bleeding *and* exit-mix /
   duration distributions don't roughly match the backtest envelope, stop.

## What I will *not* do during the window

- Add parameters / switch instrument / optimize anything
- Run a fresh backtest in response to a bad week
- Promote to real-money trading

## What I *will* do at the end of the window

Compute the same diagnostics the backtest produces. Compare side-by-side
to the envelope above. Three honest outcomes:

1. **Inside envelope, positive P&L** → real-money promotion is on the
   table. We then need a separate decision about size.
2. **Inside envelope, flat or small loss** → strategy is operating as
   modelled but the edge is too thin to capitalise. Useful negative result.
3. **Outside envelope** → fail, regardless of P&L direction. Stop.
   Diagnose why live diverged from backtest.
