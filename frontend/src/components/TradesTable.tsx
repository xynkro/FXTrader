import type { Trade } from "../types";
import { fmtPrice, fmtTime, pnlColor } from "../lib/format";

export default function TradesTable({ trades }: { trades: Trade[] }) {
  return (
    <div className="panel p-4">
      <div className="text-sm font-bold mb-3 text-neutral-200">
        Recent trades ({trades.length})
      </div>
      {trades.length === 0 ? (
        <div className="text-sm text-muted py-4 text-center">no trades yet</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-muted text-xs">
              <tr>
                <th className="text-left py-1">Open</th>
                <th className="text-left">Side</th>
                <th className="text-right">Units</th>
                <th className="text-right">Entry</th>
                <th className="text-right">Init stop</th>
                <th className="text-right">Cur stop</th>
                <th className="text-right">Exit</th>
                <th className="text-right">P&amp;L</th>
                <th className="text-right">R</th>
                <th className="text-center pl-3">Exit type</th>
                <th className="text-center pl-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => {
                const isClosed = t.status === "closed";
                const exitType = !isClosed
                  ? null
                  : t.trailed
                  ? "trail"
                  : "initial";
                return (
                  <tr key={t.id} className="border-t border-border/40">
                    <td className="py-1.5 whitespace-nowrap">
                      {fmtTime(t.entry_time)}
                      {t.is_shadow && (
                        <span className="ml-1 text-[10px] text-muted">[shadow]</span>
                      )}
                    </td>
                    <td>
                      <span
                        className={
                          t.side === "long" ? "text-accent" : "text-danger"
                        }
                      >
                        {t.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="text-right tabular-nums">
                      {Math.abs(t.units).toLocaleString()}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmtPrice(t.entry_price)}
                    </td>
                    <td className="text-right text-muted tabular-nums">
                      {t.initial_stop != null
                        ? fmtPrice(t.initial_stop)
                        : fmtPrice(t.stop_price)}
                    </td>
                    <td
                      className={`text-right tabular-nums ${
                        t.trailed ? "text-accent" : "text-muted"
                      }`}
                    >
                      {fmtPrice(t.stop_price)}
                    </td>
                    <td className="text-right tabular-nums">
                      {t.exit_price != null ? fmtPrice(t.exit_price) : "—"}
                    </td>
                    <td className={`text-right tabular-nums ${pnlColor(t.pnl)}`}>
                      {t.pnl != null
                        ? `${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}`
                        : "—"}
                    </td>
                    <td
                      className={`text-right tabular-nums ${pnlColor(
                        t.r_multiple
                      )}`}
                    >
                      {t.r_multiple != null ? t.r_multiple.toFixed(2) : "—"}
                    </td>
                    <td className="text-center pl-3 text-xs">
                      {exitType === null ? (
                        <span className="text-muted">—</span>
                      ) : exitType === "trail" ? (
                        <span className="text-accent">trail</span>
                      ) : (
                        <span className="text-warn">initial</span>
                      )}
                    </td>
                    <td className="text-center pl-2">
                      {t.status === "open" ? (
                        <span className="tag-warn">OPEN</span>
                      ) : (
                        <span className="tag-off">{t.status.toUpperCase()}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
