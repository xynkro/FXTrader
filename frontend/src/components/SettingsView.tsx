import { useState } from "react";
import type { Config } from "../types";
import EnvSwitchModal from "./EnvSwitchModal";

function Row({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex justify-between items-baseline py-1.5 border-b border-border/40 last:border-0 gap-3">
      <div>
        <div className="text-sm text-neutral-300">{label}</div>
        {hint && <div className="text-[11px] text-muted">{hint}</div>}
      </div>
      <div className="text-sm text-neutral-100 font-mono text-right">{value}</div>
    </div>
  );
}

export default function SettingsView({
  config,
  onConfigChanged,
}: {
  config: Config | null;
  onConfigChanged: () => void;
}) {
  const [modalTarget, setModalTarget] = useState<"practice" | "live" | null>(
    null
  );

  if (!config) {
    return (
      <div className="panel p-5 text-sm text-muted">loading config...</div>
    );
  }

  const env = config.oanda_env;
  const isLive = env === "live";
  const liveSwitchAllowed = config.allow_live_switch ?? false;

  return (
    <div className="space-y-4">
      {/* --- Operating mode --- */}
      <div
        className={`panel p-5 border-2 ${
          isLive ? "border-danger/40" : "border-accent/30"
        }`}
      >
        <div className="text-sm font-bold mb-3 text-neutral-200">
          Operating mode
        </div>
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            <div className="text-xs text-muted">Currently on</div>
            <div className="text-2xl font-bold">
              {isLive ? (
                <span className="text-danger">LIVE (real money)</span>
              ) : (
                <span className="text-accent">DEMO (practice)</span>
              )}
            </div>
            <div className="text-xs text-muted mt-1">
              account <span className="font-mono">{config.oanda_account_id}</span>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {!isLive && (
              <button
                onClick={() => setModalTarget("live")}
                disabled={!liveSwitchAllowed}
                className="btn-kill disabled:opacity-40 disabled:cursor-not-allowed"
                title={
                  liveSwitchAllowed
                    ? "Promote engine to live trading"
                    : "Set ALLOW_LIVE_SWITCH=true in .env to enable"
                }
              >
                Switch to LIVE
              </button>
            )}
            {isLive && (
              <button
                onClick={() => setModalTarget("practice")}
                className="btn-go"
              >
                Back to DEMO
              </button>
            )}
          </div>
        </div>

        {!liveSwitchAllowed && !isLive && (
          <div className="text-xs text-muted bg-warn/5 border border-warn/30 rounded p-2">
            Live switch is currently disabled. Set{" "}
            <span className="font-mono text-neutral-100">
              ALLOW_LIVE_SWITCH=true
            </span>{" "}
            in <span className="font-mono">.env</span> and restart the
            backend to enable. The demo protocol explicitly requires the
            demo window to complete before promotion.
          </div>
        )}
        {liveSwitchAllowed && !config.live_credentials_configured && !isLive && (
          <div className="text-xs text-muted">
            Live API credentials not in{" "}
            <span className="font-mono">.env</span> yet — you'll be prompted
            to enter them when switching. They're used for the current
            session only; persist by editing{" "}
            <span className="font-mono">.env</span>.
          </div>
        )}
      </div>

      {/* --- Strategy + market --- */}
      <div className="panel p-5">
        <div className="text-sm font-bold mb-3 text-neutral-200">
          Strategy &amp; market
        </div>
        <Row label="Strategy" value={(config.strategy_name ?? "—").toUpperCase()} />
        <Row label="Instrument" value={config.instrument} />
        <Row label="Timeframe" value={config.granularity} />
        <Row
          label="Session window (UTC)"
          value={`${config.session_start_utc}–${config.session_end_utc}`}
          hint="Signals fire only within this window; trades hold across boundaries"
        />
        <Row
          label="Shadow mode"
          value={config.shadow_mode ? "ON (no real orders)" : "OFF (broker-connected)"}
        />
      </div>

      {/* --- Risk controls --- */}
      <div className="panel p-5">
        <div className="text-sm font-bold mb-3 text-neutral-200">
          Risk controls
        </div>
        <Row
          label="Risk per trade"
          value={`${config.risk_per_trade_pct}%`}
          hint="Of current equity, on a stop-out at the initial stop"
        />
        <Row
          label="Max leverage"
          value={`${config.strategy_params?.max_leverage ?? 30}:1`}
          hint="Capped on account-currency notional"
        />
        <Row label="Max trades / day" value={config.max_trades_per_day} />
        <Row
          label="Max concurrent positions"
          value={config.max_concurrent_positions}
        />
        <Row
          label="Daily loss kill"
          value={`-${config.daily_loss_limit_pct}%`}
          hint="Trips kill switch immediately"
        />
        <Row
          label="Max drawdown kill"
          value={`-${config.max_drawdown_pct}%`}
          hint="From peak equity"
        />
        <Row
          label="Consecutive loss pause"
          value={`${config.consecutive_loss_limit} losses → 24h pause`}
        />
      </div>

      {/* --- Strategy parameters --- */}
      {config.strategy_params && (
        <div className="panel p-5">
          <div className="text-sm font-bold mb-3 text-neutral-200">
            Strategy parameters (locked for the demo window)
          </div>
          <Row label="Donchian period" value={config.strategy_params.donchian_period} />
          <Row label="ATR period" value={config.strategy_params.atr_period} />
          <Row label="Stop ATR multiplier (K)" value={config.strategy_params.stop_atr_mult} />
          <Row label="SMA long (trend)" value={config.strategy_params.sma_long} />
          <Row label="SMA short (pullback mean)" value={config.strategy_params.sma_short} />
          <Row label="Pullback lookback (bars)" value={config.strategy_params.pullback_lookback} />
          <Row label="Trend slope lookback (bars)" value={config.strategy_params.trend_slope_lookback} />
          <Row label="Cooldown bars (after stop-out)" value={config.strategy_params.cooldown_bars} />
          <Row label="Min ATR (pips)" value={config.strategy_params.min_atr_pips} />
          <Row label="Min stop (pips)" value={config.strategy_params.min_stop_pips} />
        </div>
      )}

      {modalTarget && (
        <EnvSwitchModal
          config={config}
          target={modalTarget}
          onClose={() => setModalTarget(null)}
          onDone={() => {
            setModalTarget(null);
            onConfigChanged();
          }}
        />
      )}
    </div>
  );
}
