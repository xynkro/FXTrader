import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type {
  Sensitivity,
  SensitivityMetrics,
  SensitivityParam,
} from "../types";

/**
 * Read-only parameter sensitivity dashboard. Renders pre-computed
 * one-factor sweeps as mini-charts. The deployed value is highlighted
 * in cyan. The chart's purpose is to show the SHAPE of each
 * parameter's sensitivity — a broad plateau means the deployed value
 * sits in a robust region; a sharp peak means it's fragile / likely
 * overfit.
 *
 * Design constraint: this component intentionally does NOT include any
 * "apply this value" / "re-run with overrides" UI. Cherry-picking the
 * highest-scoring value from an in-sample sweep is the canonical
 * backtest-overfitting trap, and the deployed parameters are locked for
 * the current evaluation window.
 */

type Metric =
  | "cagr_pct"
  | "sharpe"
  | "max_dd_pct"
  | "win_rate_pct"
  | "total_return_pct"
  | "profit_factor";

interface MetricOption {
  key: Metric;
  label: string;
  format: (v: number) => string;
}

const METRIC_OPTIONS: MetricOption[] = [
  {
    key: "cagr_pct",
    label: "CAGR",
    format: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`,
  },
  { key: "sharpe", label: "Sharpe", format: (v) => v.toFixed(2) },
  { key: "max_dd_pct", label: "Max DD", format: (v) => `${v.toFixed(2)}%` },
  { key: "win_rate_pct", label: "Win rate", format: (v) => `${v.toFixed(1)}%` },
  {
    key: "total_return_pct",
    label: "Total return",
    format: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`,
  },
  { key: "profit_factor", label: "PF", format: (v) => v.toFixed(2) },
];

function classifyShape(
  values: number[],
  deployedIdx: number
): "plateau" | "peak" | "slope" | "n/a" {
  if (values.length < 3 || deployedIdx < 0) return "n/a";
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min;
  if (range < 1e-9) return "plateau";
  // How "spiky" is the curve relative to its level?
  const sorted = [...values].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const flatness = Math.abs(median) > 1e-3 ? range / Math.abs(median) : range;
  // Is the deployed value near the maximum?
  const deployed = values[deployedIdx];
  const pctOfMax = (deployed - min) / range; // 0 if min, 1 if max

  if (flatness < 0.3) return "plateau";
  if (pctOfMax > 0.8 && flatness > 0.5) return "peak";
  return "slope";
}

function MiniChart({
  pname,
  param,
  metric,
  format,
}: {
  pname: string;
  param: SensitivityParam;
  metric: Metric;
  format: (v: number) => string;
}) {
  const W = 240;
  const H = 130;
  const PAD = { top: 10, right: 8, bottom: 26, left: 38 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const values: number[] = param.results.map((r) => {
    const v = (r.metrics as SensitivityMetrics)[metric];
    return typeof v === "number" && !Number.isNaN(v) ? v : 0;
  });
  const xs = param.results.map((r) => r.value);
  const deployedIdx = param.values.indexOf(param.deployed_value);

  let yMin = Math.min(...values);
  let yMax = Math.max(...values);
  if (yMin === yMax) {
    yMin -= 1;
    yMax += 1;
  }
  const yPad = (yMax - yMin) * 0.12;
  yMin -= yPad;
  yMax += yPad;

  const xToPx = (i: number) =>
    PAD.left + (i / Math.max(values.length - 1, 1)) * innerW;
  const yToPx = (y: number) =>
    PAD.top + (1 - (y - yMin) / (yMax - yMin)) * innerH;

  const linePath = values
    .map(
      (v, i) =>
        `${i === 0 ? "M" : "L"} ${xToPx(i).toFixed(1)} ${yToPx(v).toFixed(1)}`
    )
    .join(" ");
  const zeroY = yMin <= 0 && yMax >= 0 ? yToPx(0) : null;

  const shape = classifyShape(values, deployedIdx);
  const shapeColor =
    shape === "plateau"
      ? "text-success"
      : shape === "peak"
      ? "text-danger"
      : shape === "slope"
      ? "text-warn"
      : "text-muted";

  const deployedValue =
    deployedIdx >= 0 ? values[deployedIdx] : Number.NaN;

  return (
    <div className="rounded-md border border-neutral-800 p-2 bg-bg/40">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-mono text-neutral-200">{pname}</span>
        <span
          className={"text-[10px] uppercase font-bold " + shapeColor}
          title={
            shape === "plateau"
              ? "Curve is flat across the swept range — deployed value is robust."
              : shape === "peak"
              ? "Deployed value sits near a sharp maximum — fragile / likely overfit."
              : shape === "slope"
              ? "Curve trends up or down — deployed value is in the middle, not on a peak."
              : ""
          }
        >
          {shape}
        </span>
      </div>
      <svg width={W} height={H} className="block">
        {zeroY !== null && (
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={zeroY}
            y2={zeroY}
            stroke="#3a3a3a"
            strokeDasharray="2 3"
          />
        )}
        {deployedIdx >= 0 && (
          <line
            x1={xToPx(deployedIdx)}
            x2={xToPx(deployedIdx)}
            y1={PAD.top}
            y2={H - PAD.bottom}
            stroke="#22d3ee"
            strokeOpacity="0.25"
            strokeDasharray="2 2"
          />
        )}
        <path d={linePath} fill="none" stroke="#facc15" strokeWidth="1.5" />
        {values.map((v, i) => (
          <circle
            key={i}
            cx={xToPx(i)}
            cy={yToPx(v)}
            r={i === deployedIdx ? 4 : 2}
            fill={i === deployedIdx ? "#22d3ee" : "#facc15"}
            stroke={i === deployedIdx ? "#06b6d4" : "none"}
            strokeWidth={i === deployedIdx ? 1.5 : 0}
          />
        ))}
        <text
          x="2"
          y={yToPx(yMax) + 4}
          fontSize="9"
          fill="#888"
          fontFamily="monospace"
        >
          {format(yMax)}
        </text>
        <text
          x="2"
          y={yToPx(yMin) + 4}
          fontSize="9"
          fill="#888"
          fontFamily="monospace"
        >
          {format(yMin)}
        </text>
        {deployedIdx >= 0 && (
          <text
            x={xToPx(deployedIdx)}
            y={H - 14}
            fontSize="9"
            fill="#22d3ee"
            textAnchor="middle"
            fontFamily="monospace"
            fontWeight="bold"
          >
            {param.deployed_value}
          </text>
        )}
        <text
          x={PAD.left}
          y={H - 4}
          fontSize="9"
          fill="#666"
          textAnchor="start"
          fontFamily="monospace"
        >
          {xs[0]}
        </text>
        <text
          x={W - PAD.right}
          y={H - 4}
          fontSize="9"
          fill="#666"
          textAnchor="end"
          fontFamily="monospace"
        >
          {xs[xs.length - 1]}
        </text>
      </svg>
      <div className="text-[10px] text-muted mt-0.5 flex justify-between tabular-nums">
        <span>at deployed:</span>
        <span className="text-neutral-200">
          {Number.isFinite(deployedValue) ? format(deployedValue) : "—"}
        </span>
      </div>
    </div>
  );
}

export default function SensitivityPanel() {
  const [data, setData] = useState<Sensitivity | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [metric, setMetric] = useState<Metric>("cagr_pct");

  useEffect(() => {
    let cancel = false;
    api
      .sensitivity()
      .then((d) => {
        if (!cancel) {
          setData(d);
          setErr(null);
        }
      })
      .catch((e) => {
        if (!cancel) setErr((e as Error).message);
      });
    return () => {
      cancel = true;
    };
  }, []);

  if (err) {
    return (
      <div className="panel p-4">
        <div className="text-sm font-bold mb-2 text-neutral-200">
          Parameter Sensitivity
        </div>
        <div className="text-danger text-xs">fetch failed: {err}</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="panel p-4">
        <div className="text-sm font-bold mb-2 text-neutral-200">
          Parameter Sensitivity
        </div>
        <div className="text-muted text-xs">loading…</div>
      </div>
    );
  }
  if (!data.available) {
    return (
      <div className="panel p-4">
        <div className="text-sm font-bold mb-2 text-neutral-200">
          Parameter Sensitivity
        </div>
        <div className="text-warn text-xs">
          {data.message ?? "not available"}
        </div>
      </div>
    );
  }

  const baseline = data.baseline_metrics!;
  const sweeps = data.sweeps!;
  const opt = METRIC_OPTIONS.find((o) => o.key === metric)!;
  const generated = data.generated_at
    ? new Date(data.generated_at).toLocaleString()
    : "?";

  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div>
          <div className="text-sm font-bold text-neutral-200">
            Parameter Sensitivity
          </div>
          <div className="text-xs text-muted">
            {data.strategy} · {data.instrument} {data.granularity} ·{" "}
            {data.data_window_bars?.toLocaleString()} bars · spread{" "}
            {data.spread_pips}p slip {data.slippage_pips}p (friction-shocked)
          </div>
        </div>
        <div className="flex gap-1 flex-wrap">
          {METRIC_OPTIONS.map((o) => (
            <button
              key={o.key}
              onClick={() => setMetric(o.key)}
              className={
                "px-2 py-1 text-[11px] rounded border " +
                (o.key === metric
                  ? "bg-accent/20 border-accent text-accent"
                  : "border-neutral-800 text-muted hover:text-neutral-200")
              }
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-md border border-warn/40 bg-warn/5 p-3 mb-3 text-xs leading-relaxed">
        <div className="font-bold text-warn mb-1">
          DIAGNOSTIC ONLY — do not use to pick "better" parameter values
        </div>
        <div className="text-neutral-300">
          One-factor sweep on the same 5y window used to find the strategy.
          The deployed value is in{" "}
          <span className="text-cyan-400 font-bold">cyan</span>. Read the
          SHAPE, not the winner: a broad{" "}
          <span className="text-success font-bold">PLATEAU</span> = robust
          edge; a sharp{" "}
          <span className="text-danger font-bold">PEAK</span> = fragile /
          overfit;{" "}
          <span className="text-warn font-bold">SLOPE</span> = monotonic
          drift, deployed value isn't optimised either way. Selecting the
          highest-scoring value mid-evaluation is the textbook
          backtest-overfitting trap, and the deployed parameters are{" "}
          <em>locked</em> for the current evaluation window.
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 mb-3 text-xs gap-x-4 gap-y-1">
        <div className="flex justify-between">
          <span className="text-muted">Baseline trades</span>
          <span className="tabular-nums text-neutral-200">
            {baseline.trades}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">Baseline CAGR</span>
          <span className="tabular-nums text-neutral-200">
            {baseline.cagr_pct >= 0 ? "+" : ""}
            {baseline.cagr_pct.toFixed(2)}%
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">Baseline Sharpe</span>
          <span className="tabular-nums text-neutral-200">
            {baseline.sharpe.toFixed(2)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">Baseline max DD</span>
          <span className="tabular-nums text-neutral-200">
            {baseline.max_dd_pct.toFixed(2)}%
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {Object.entries(sweeps).map(([pname, p]) => (
          <MiniChart
            key={pname}
            pname={pname}
            param={p}
            metric={metric}
            format={opt.format}
          />
        ))}
      </div>

      <div className="text-[10px] text-muted mt-3 leading-relaxed">
        Generated {generated}. Data window:{" "}
        {data.data_window_start?.slice(0, 10)} →{" "}
        {data.data_window_end?.slice(0, 10)}. Re-run offline with{" "}
        <code className="font-mono text-neutral-300">
          python -m scripts.run_sensitivity
        </code>{" "}
        from <code className="font-mono text-neutral-300">backend/</code>.
      </div>
    </div>
  );
}
