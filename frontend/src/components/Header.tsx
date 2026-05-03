import type { AccountSnapshot, Config, EngineStatus } from "../types";
import { fmtMoney, fmtPct, pnlColor } from "../lib/format";

export default function Header({
  status,
  account,
  config,
}: {
  status: EngineStatus | null;
  account: AccountSnapshot | null;
  config: Config | null;
}) {
  const env = config?.oanda_env ?? "—";
  const envBadge =
    env === "live" ? (
      <span className="tag-danger">LIVE</span>
    ) : (
      <span className="tag-on">DEMO</span>
    );

  return (
    <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
      <div className="flex items-center gap-3">
        <div className="text-2xl font-bold tracking-tight">
          FX<span className="text-accent">Trader</span>
        </div>
        {envBadge}
        {status?.in_session ? (
          <span className="tag-on">IN SESSION</span>
        ) : (
          <span className="tag-off">OUT OF SESSION</span>
        )}
        {status?.kill_switch_tripped && (
          <span className="tag-danger">KILL SWITCH</span>
        )}
      </div>

      <div className="flex items-center gap-6">
        <div className="text-right">
          <div className="text-xs text-muted">Equity</div>
          <div className="text-xl font-bold">
            {account ? fmtMoney(account.equity, account.currency) : "—"}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-muted">Today</div>
          <div className={`text-xl font-bold ${pnlColor(status?.daily_pnl_pct ?? null)}`}>
            {status ? fmtPct(status.daily_pnl_pct) : "—"}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-muted">Drawdown</div>
          <div
            className={`text-xl font-bold ${
              (status?.current_drawdown_pct ?? 0) > 2 ? "text-warn" : "text-neutral-200"
            }`}
          >
            -{(status?.current_drawdown_pct ?? 0).toFixed(2)}%
          </div>
        </div>
      </div>
    </div>
  );
}
