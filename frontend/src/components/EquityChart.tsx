import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EquityPoint } from "../types";

export default function EquityChart({ points }: { points: EquityPoint[] }) {
  const data = points.map((p) => ({
    t: new Date(p.t).getTime(),
    equity: p.equity,
  }));
  const min = data.length ? Math.min(...data.map((d) => d.equity)) : 0;
  const max = data.length ? Math.max(...data.map((d) => d.equity)) : 0;
  const padding = (max - min) * 0.05 || 1;

  return (
    <div className="panel p-4 h-[360px] flex flex-col">
      <div className="text-sm font-bold mb-2 text-neutral-200">Equity</div>
      {data.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-muted text-sm">
          no equity data yet — run the backend and let it log a few snapshots
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#262626" strokeDasharray="3 3" />
            <XAxis
              dataKey="t"
              stroke="#737373"
              fontSize={11}
              tickFormatter={(t) =>
                new Date(t).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                })
              }
            />
            <YAxis
              stroke="#737373"
              fontSize={11}
              domain={[min - padding, max + padding]}
              tickFormatter={(v) => v.toFixed(0)}
            />
            <Tooltip
              contentStyle={{
                background: "#141414",
                border: "1px solid #262626",
                fontSize: 12,
              }}
              labelFormatter={(t) => new Date(t as number).toLocaleString()}
              formatter={(v: number) => [`$${v.toFixed(2)}`, "Equity"]}
            />
            <Area
              type="monotone"
              dataKey="equity"
              stroke="#10b981"
              fill="url(#eq)"
              strokeWidth={2}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
