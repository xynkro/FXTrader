import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { StrategyVitals as Vitals, VitalGate } from "../types";

function GateRow({ g }: { g: VitalGate }) {
  return (
    <div className="flex items-center gap-2 py-1 text-xs">
      <span
        className={
          g.ok ? "text-success font-bold w-4" : "text-danger font-bold w-4"
        }
      >
        {g.ok ? "✓" : "✗"}
      </span>
      <span
        className={
          g.ok ? "text-neutral-200 flex-1" : "text-neutral-100 flex-1 font-medium"
        }
      >
        {g.label}
      </span>
      <span className="text-muted tabular-nums">{g.value}</span>
      <span className="text-muted text-[10px] hidden md:inline">
        ↳ {g.needed}
      </span>
    </div>
  );
}

function Side({
  title,
  side,
}: {
  title: string;
  side: { all_pass: boolean; passes: number; total: number; gates: VitalGate[] };
}) {
  const colorClass = side.all_pass
    ? "border-success/40 bg-success/5"
    : side.passes === side.total - 1
    ? "border-warn/40 bg-warn/5"
    : "border-neutral-800";
  return (
    <div className={`rounded-md border p-2 ${colorClass}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-bold text-neutral-200 uppercase">
          {title}
        </span>
        <span
          className={
            side.all_pass
              ? "text-success text-xs font-bold"
              : side.passes === side.total - 1
              ? "text-warn text-xs font-bold"
              : "text-muted text-xs"
          }
        >
          {side.all_pass
            ? "WILL FIRE NEXT BAR"
            : `${side.passes}/${side.total} gates`}
        </span>
      </div>
      <div>
        {side.gates.map((g, i) => (
          <GateRow key={i} g={g} />
        ))}
      </div>
    </div>
  );
}

export default function StrategyVitals() {
  const [v, setV] = useState<Vitals | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    const tick = async () => {
      try {
        const data = await api.strategyVitals();
        if (cancel) return;
        setV(data);
        setErr(null);
      } catch (e) {
        if (!cancel) setErr((e as Error).message);
      }
    };
    void tick();
    const i = window.setInterval(tick, 5000);
    return () => {
      cancel = true;
      window.clearInterval(i);
    };
  }, []);

  if (err) {
    return (
      <div className="panel p-4">
        <div className="text-sm font-bold mb-2 text-neutral-200">
          Strategy Vitals
        </div>
        <div className="text-danger text-xs">vitals fetch failed: {err}</div>
      </div>
    );
  }
  if (!v) {
    return (
      <div className="panel p-4">
        <div className="text-sm font-bold mb-2 text-neutral-200">
          Strategy Vitals
        </div>
        <div className="text-muted text-xs">loading…</div>
      </div>
    );
  }
  if (v.warming_up) {
    return (
      <div className="panel p-4">
        <div className="text-sm font-bold mb-2 text-neutral-200">
          Strategy Vitals — {v.strategy}
        </div>
        <div className="text-warn text-xs">
          Warming up: {v.bars_loaded}/{v.bars_needed} bars
        </div>
      </div>
    );
  }
  if (v.not_implemented) {
    return (
      <div className="panel p-4">
        <div className="text-sm font-bold mb-2 text-neutral-200">
          Strategy Vitals — {v.strategy}
        </div>
        <div className="text-muted text-xs">{v.message}</div>
      </div>
    );
  }

  const ind = v.indicators!;
  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-bold text-neutral-200">
          Strategy Vitals
          <span className="text-muted font-normal ml-2">
            {v.strategy} · {v.instrument} {v.granularity}
          </span>
        </div>
        <div className="text-xs text-muted">
          last bar {v.last_candle_time?.slice(11, 16)} UTC · close{" "}
          <span className="text-neutral-200 tabular-nums">
            {v.last_close?.toFixed(3)}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-3 text-xs">
        <div className="flex justify-between">
          <span className="text-muted">SMA(short)</span>
          <span className="tabular-nums text-neutral-200">
            {ind.sma_short.toFixed(3)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">SMA(long)</span>
          <span className="tabular-nums text-neutral-200">
            {ind.sma_long_now.toFixed(3)}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">SMA(long) slope</span>
          <span
            className={
              "tabular-nums " +
              (ind.sma_long_slope_pips > 0 ? "text-success" : "text-danger")
            }
          >
            {ind.sma_long_slope_pips >= 0 ? "+" : ""}
            {ind.sma_long_slope_pips.toFixed(1)}p
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">ATR</span>
          <span className="tabular-nums text-neutral-200">
            {ind.atr_pips.toFixed(1)}p
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">Stop dist</span>
          <span className="tabular-nums text-neutral-200">
            {ind.stop_distance_pips.toFixed(1)}p
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <Side title="Long setup" side={v.long!} />
        <Side title="Short setup" side={v.short!} />
      </div>
    </div>
  );
}
