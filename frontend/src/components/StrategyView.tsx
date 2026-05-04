import type { Config } from "../types";

/**
 * Plain-English explanation of the Pullback-in-trend strategy currently
 * loaded in the live engine. Source of truth for the rules is
 * `backend/app/strategy.py:evaluate_pullback`.
 *
 * If you change the strategy logic, update the relevant section here too.
 */
export default function StrategyView({ config }: { config: Config | null }) {
  const p = config?.strategy_params ?? {};
  const name = config?.strategy_name ?? "—";
  const instrument = config?.instrument ?? "—";
  const granularity = config?.granularity ?? "—";
  const sessionStart = config?.session_start_utc ?? "—";
  const sessionEnd = config?.session_end_utc ?? "—";
  const risk = config?.risk_per_trade_pct ?? 0;

  return (
    <div className="space-y-4">
      <div className="panel p-5">
        <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
          <div>
            <div className="text-lg font-bold text-neutral-100">
              Pullback-in-trend
            </div>
            <div className="text-xs text-muted">
              {instrument} · {granularity} · session {sessionStart}–{sessionEnd} UTC
            </div>
          </div>
          <span className="tag-on">{name.toUpperCase()}</span>
        </div>
        <p className="text-sm text-neutral-300 leading-6">
          The engine waits for an established trend, then enters only when
          price has temporarily pulled back toward the mean and started
          resuming in the trend's direction. It does not buy fresh highs.
          The thesis: continuation after a pullback is structurally cleaner
          than chasing breakouts on a liquid major like EUR/USD or USD/JPY.
        </p>
      </div>

      {/* --- Entry rules --- */}
      <div className="panel p-5">
        <div className="text-sm font-bold mb-3 text-neutral-200">
          Entry rules
        </div>

        <div className="text-xs text-muted mb-1">LONG</div>
        <ol className="list-decimal list-inside text-sm text-neutral-300 space-y-1 mb-4 leading-6">
          <li>
            <span className="text-neutral-100 font-mono">
              SMA({p.sma_long ?? 100})
            </span>{" "}
            on H1 is rising over the last{" "}
            <span className="text-neutral-100 font-mono">
              {p.trend_slope_lookback ?? 10}
            </span>{" "}
            bars (uptrend filter).
          </li>
          <li>
            Current bar's close is above{" "}
            <span className="font-mono text-neutral-100">
              SMA({p.sma_long ?? 100})
            </span>{" "}
            (still in trend) AND above{" "}
            <span className="font-mono text-neutral-100">
              SMA({p.sma_short ?? 20})
            </span>{" "}
            (back above pullback mean).
          </li>
          <li>
            In the last{" "}
            <span className="font-mono text-neutral-100">
              {p.pullback_lookback ?? 3}
            </span>{" "}
            bars, at least one bar's <em>low</em> touched{" "}
            <span className="font-mono text-neutral-100">
              SMA({p.sma_short ?? 20})
            </span>{" "}
            from above — the actual pullback.
          </li>
          <li>
            Cooldown clear: no LONG stop-out in the last{" "}
            <span className="font-mono text-neutral-100">
              {p.cooldown_bars ?? 20}
            </span>{" "}
            bars.
          </li>
        </ol>

        <div className="text-xs text-muted mb-1">SHORT — mirror image</div>
        <p className="text-sm text-neutral-300 leading-6">
          Same logic with the trend filter saying "down" (close below
          SMA(100), SMA(100) falling), and the pullback condition checking
          a recent <em>high</em> touching SMA(20) from below.
        </p>
      </div>

      {/* --- Stop & trail --- */}
      <div className="panel p-5">
        <div className="text-sm font-bold mb-3 text-neutral-200">
          Stop & trail (entry-anchored chandelier)
        </div>
        <ul className="list-disc list-inside text-sm text-neutral-300 space-y-1 leading-6">
          <li>
            <span className="text-neutral-100">Initial stop</span>: at entry,
            placed{" "}
            <span className="font-mono text-neutral-100">
              {p.stop_atr_mult ?? 2.0}
            </span>{" "}
            × ATR({p.atr_period ?? 14}) away (LONG: below entry; SHORT:
            above). The ATR is <em>frozen</em> at signal time and never
            updates.
          </li>
          <li>
            <span className="text-neutral-100">Trail update</span>: at the
            close of every new H1 bar, recompute{" "}
            <span className="font-mono">
              new_stop = highest_high_since_entry − K × ATR_at_entry
            </span>{" "}
            (LONG; mirror for SHORT). If tighter than the current stop,
            update via OANDA <span className="font-mono">TradeCRCDO</span>.
          </li>
          <li>
            <span className="text-neutral-100">Activation timing</span>: a
            new trail computed at the close of bar{" "}
            <span className="font-mono">t</span> only becomes active at bar{" "}
            <span className="font-mono">t+1</span>. This delay matches the
            backtest exactly so live ≠ overshooting the model.
          </li>
          <li>
            <span className="text-neutral-100">No take-profit</span>. Trades
            close only on the (initial or trailed) stop. There is no fixed
            profit target — let winners run, let the trail collect.
          </li>
          <li>
            <span className="text-neutral-100">Session boundary</span>:
            signals fire only inside {sessionStart}–{sessionEnd} UTC, but
            open trades hold across the boundary until their stop is hit.
            (The "session-end forced close" used by earlier baselines was
            falsified by Test 1 of the robustness pack — it cut the right
            tail off winners.)
          </li>
        </ul>
      </div>

      {/* --- Sizing --- */}
      <div className="panel p-5">
        <div className="text-sm font-bold mb-3 text-neutral-200">
          Position sizing (account-currency aware)
        </div>
        <div className="text-sm text-neutral-300 leading-6 space-y-2">
          <p>
            Each trade risks exactly{" "}
            <span className="font-mono text-neutral-100">{risk}%</span> of
            current account equity if it stops out at the initial stop.
          </p>
          <p>
            For a pair{" "}
            <span className="font-mono">BASE_QUOTE</span> with the account
            in currency <span className="font-mono">ACCT</span>, units are
            solved from:
          </p>
          <pre className="bg-bg border border-border rounded p-3 text-xs text-accent overflow-x-auto">
{`risk_acct       = equity × ${risk}/100
risk_per_unit   = |entry − stop| × q2a   (q2a = ACCT per QUOTE)
units           = risk_acct / risk_per_unit
notional_per_u  = entry × q2a
units_capped    = min(units, max_leverage × equity / notional_per_u)`}
          </pre>
          <p>
            <span className="font-mono">q2a</span> comes live from OANDA's{" "}
            <span className="font-mono">quoteHomeConversionFactors</span>{" "}
            on every signal — so a USD/JPY trade on an SGD account is
            sized correctly through the SGD/JPY cross. Both intended and
            realised risk are logged on every entry under the{" "}
            <span className="font-mono">"sizing"</span> event.
          </p>
        </div>
      </div>

      {/* --- Sanity guards --- */}
      <div className="panel p-5">
        <div className="text-sm font-bold mb-3 text-neutral-200">
          Sanity guards (every signal)
        </div>
        <ul className="list-disc list-inside text-sm text-neutral-300 space-y-1 leading-6">
          <li>
            Skip if ATR(14) below{" "}
            <span className="font-mono">{p.min_atr_pips ?? 3}</span> pips
            (dead market).
          </li>
          <li>
            Skip if K × ATR is below{" "}
            <span className="font-mono">{p.min_stop_pips ?? 5}</span> pips
            (refuse to size up around an implausibly tight stop).
          </li>
          <li>
            Cap leverage at{" "}
            <span className="font-mono">{p.max_leverage ?? 30}:1</span> on
            account-currency notional. Logged when the cap binds.
          </li>
          <li>
            Same-direction lockout for{" "}
            <span className="font-mono">{p.cooldown_bars ?? 20}</span> bars
            after a stop-out (no immediate revenge re-entry).
          </li>
        </ul>
      </div>

      {/* --- Risk controls --- */}
      <div className="panel p-5">
        <div className="text-sm font-bold mb-3 text-neutral-200">
          Hard risk controls
        </div>
        <ul className="list-disc list-inside text-sm text-neutral-300 space-y-1 leading-6">
          <li>
            Daily P&amp;L kill: stop trading if equity drops below{" "}
            <span className="font-mono">
              −{config?.daily_loss_limit_pct ?? 2}%
            </span>{" "}
            on the day.
          </li>
          <li>
            Max drawdown kill:{" "}
            <span className="font-mono">
              −{config?.max_drawdown_pct ?? 5}%
            </span>{" "}
            from peak equity.
          </li>
          <li>
            Consecutive-loss pause: 24h pause after{" "}
            <span className="font-mono">
              {config?.consecutive_loss_limit ?? 4}
            </span>{" "}
            losses in a row.
          </li>
          <li>
            Max trades per day:{" "}
            <span className="font-mono">
              {config?.max_trades_per_day ?? 4}
            </span>
            ; max concurrent:{" "}
            <span className="font-mono">
              {config?.max_concurrent_positions ?? 1}
            </span>
            .
          </li>
          <li>
            Manual kill switch on Dashboard tab — closes any open position
            and disables trading until you re-enable.
          </li>
        </ul>
      </div>

      {/* --- Why pullback over breakout --- */}
      <div className="panel p-5">
        <div className="text-sm font-bold mb-3 text-neutral-200">
          Why this strategy
        </div>
        <p className="text-sm text-neutral-300 leading-6">
          We tested two thesis classes head-to-head over 5 years on
          USD/JPY H1: <em>Donchian breakout</em> vs{" "}
          <em>Pullback-in-trend</em> (and a third, vol-squeeze). Pullback
          beat breakout on every measurable dimension — higher PF in
          IS/OOS/friction, lower regime concentration, longer trade
          duration, more trail-stop exits. Removing the session-end forced
          close lifted friction-shocked annualised return to ~4.7%. None
          of this proves the strategy will be profitable live — that's
          what the demo window is for.
        </p>
        <p className="text-sm text-muted mt-2 leading-6">
          See{" "}
          <a
            href="https://github.com/xynkro/FXTrader/blob/main/docs/bakeoff-spec.md"
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-accent"
          >
            bakeoff-spec.md
          </a>
          ,{" "}
          <a
            href="https://github.com/xynkro/FXTrader/blob/main/docs/robustness-pack-spec.md"
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-accent"
          >
            robustness-pack-spec.md
          </a>
          ,{" "}
          <a
            href="https://github.com/xynkro/FXTrader/blob/main/docs/demo-protocol.md"
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-accent"
          >
            demo-protocol.md
          </a>{" "}
          for the full pre-registered specifications.
        </p>
      </div>
    </div>
  );
}
