import type { OandaPosition } from "../types";
import { pnlColor } from "../lib/format";

export default function PositionsTable({
  positions,
}: {
  positions: OandaPosition[];
}) {
  return (
    <div className="panel p-4">
      <div className="text-sm font-bold mb-3 text-neutral-200">Open positions</div>
      {positions.length === 0 ? (
        <div className="text-sm text-muted py-4 text-center">no open positions</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-muted text-xs">
            <tr>
              <th className="text-left py-1">Instrument</th>
              <th className="text-right">Units</th>
              <th className="text-right">Open price</th>
              <th className="text-right">Unrealised</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const upl = parseFloat(p.unrealizedPL);
              return (
                <tr key={p.id} className="border-t border-border/40">
                  <td className="py-1.5">{p.instrument}</td>
                  <td className="text-right">{p.currentUnits}</td>
                  <td className="text-right">{parseFloat(p.price).toFixed(5)}</td>
                  <td className={`text-right ${pnlColor(upl)}`}>
                    {upl >= 0 ? "+" : ""}
                    {upl.toFixed(2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
