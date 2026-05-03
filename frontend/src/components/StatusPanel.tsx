import type { AccountSnapshot, EngineStatus } from "../types";
import { fmtMoney, fmtTime } from "../lib/format";

export default function StatusPanel({
  status,
  account,
}: {
  status: EngineStatus | null;
  account: AccountSnapshot | null;
}) {
  return (
    <div className="panel p-4">
      <div className="text-sm font-bold mb-3 text-neutral-200">Status</div>
      <div className="kv-row">
        <span className="kv-key">Trading</span>
        <span className="kv-val">
          {status?.trading_enabled ? (
            <span className="tag-on">ENABLED</span>
          ) : (
            <span className="tag-off">DISABLED</span>
          )}
        </span>
      </div>
      <div className="kv-row">
        <span className="kv-key">Trades today</span>
        <span className="kv-val">{status?.trades_today ?? 0}</span>
      </div>
      <div className="kv-row">
        <span className="kv-key">Consecutive losses</span>
        <span className="kv-val">{status?.consecutive_losses ?? 0}</span>
      </div>
      <div className="kv-row">
        <span className="kv-key">Open positions</span>
        <span className="kv-val">{account?.open_position_count ?? 0}</span>
      </div>
      <div className="kv-row">
        <span className="kv-key">Margin used</span>
        <span className="kv-val">
          {account ? fmtMoney(account.margin_used, account.currency) : "—"}
        </span>
      </div>
      <div className="kv-row">
        <span className="kv-key">Last candle</span>
        <span className="kv-val">{fmtTime(status?.last_candle_time)}</span>
      </div>
      <div className="kv-row">
        <span className="kv-key">Last signal</span>
        <span className="kv-val">{fmtTime(status?.last_signal_time)}</span>
      </div>
      {status?.kill_switch_tripped && status.kill_reason && (
        <div className="mt-3 text-xs text-danger border border-danger/30 bg-danger/10 p-2 rounded">
          {status.kill_reason}
        </div>
      )}
    </div>
  );
}
