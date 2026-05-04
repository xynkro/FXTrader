import type { Config, EngineStatus, Trade } from "../types";

/** Live-vs-envelope status for the four pre-registered kill criteria
 * from `docs/demo-protocol.md` (Pullback no-session-close USD/JPY H1).
 *
 * Each row shows: criterion name, live value, threshold, traffic-light
 * status. Yellow when within 30% of trip; red when tripped (or beyond).
 */
export default function EnvelopeStatus({
  status,
  config,
  trades,
}: {
  status: EngineStatus | null;
  config: Config | null;
  trades: Trade[];
}) {
  const closed = trades.filter((t) => t.status === "closed");

  // ----- duration metrics -----
  const durations: number[] = [];
  for (const t of closed) {
    if (!t.entry_time || !t.exit_time) continue;
    // bars_held isn't in the API; we approximate from time diff / granularity
    const ms =
      new Date(t.exit_time).getTime() - new Date(t.entry_time).getTime();
    const granMin =
      config?.granularity === "M5"
        ? 5
        : config?.granularity === "H1"
        ? 60
        : config?.granularity === "H4"
        ? 240
        : 60;
    durations.push(ms / 60000 / granMin);
  }
  durations.sort((a, b) => a - b);
  const median =
    durations.length === 0
      ? null
      : durations[Math.floor(durations.length / 2)];
  const avg =
    durations.length === 0
      ? null
      : durations.reduce((s, x) => s + x, 0) / durations.length;

  // ----- exit-mix -----
  const trailExits = closed.filter((t) => t.trailed === true).length;
  const initialExits = closed.filter(
    (t) => t.exit_price != null && t.trailed === false
  ).length;
  const trailPct = closed.length ? (100 * trailExits) / closed.length : null;
  const initialPct = closed.length
    ? (100 * initialExits) / closed.length
    : null;

  const dailyKill = config?.daily_loss_limit_pct ?? 2.0;
  const ddKill = config?.max_drawdown_pct ?? 5.0;
  const cl = config?.consecutive_loss_limit ?? 4;

  type Row = {
    label: string;
    value: string;
    threshold: string;
    state: "ok" | "warn" | "fail" | "idle";
  };

  const rows: Row[] = [];

  // --- Risk-side (always evaluable) ---
  if (status) {
    const dpl = status.daily_pnl_pct;
    rows.push({
      label: "Daily P&L",
      value: `${dpl >= 0 ? "+" : ""}${dpl.toFixed(2)}%`,
      threshold: `kill at -${dailyKill}%`,
      state:
        dpl <= -dailyKill
          ? "fail"
          : dpl <= -dailyKill * 0.7
          ? "warn"
          : "ok",
    });
    const dd = status.current_drawdown_pct;
    rows.push({
      label: "Drawdown",
      value: `-${dd.toFixed(2)}%`,
      threshold: `kill at ${ddKill}%`,
      state: dd >= ddKill ? "fail" : dd >= ddKill * 0.7 ? "warn" : "ok",
    });
    rows.push({
      label: "Consecutive losses",
      value: `${status.consecutive_losses}`,
      threshold: `pause at ${cl}`,
      state:
        status.consecutive_losses >= cl
          ? "fail"
          : status.consecutive_losses >= cl - 1
          ? "warn"
          : "ok",
    });
  }

  // --- Behavioural-drift criteria (need ≥ 5 closed trades to evaluate) ---
  if (closed.length === 0) {
    rows.push({
      label: "Avg / median duration",
      value: "—",
      threshold: "5–14 / 3–8 bars",
      state: "idle",
    });
    rows.push({
      label: "Trail-stop exits",
      value: "—",
      threshold: "≥80%",
      state: "idle",
    });
    rows.push({
      label: "Initial-stop exits",
      value: "—",
      threshold: "≤15%",
      state: "idle",
    });
  } else {
    const stateForBound = (
      v: number,
      lo: number,
      hi: number
    ): Row["state"] => {
      if (v < lo || v > hi) return "fail";
      // within 20% of either bound = warn
      if (v < lo * 1.2 || v > hi * 0.83) return "warn";
      return "ok";
    };
    rows.push({
      label: "Avg duration (bars)",
      value: avg ? avg.toFixed(1) : "—",
      threshold: "5–14",
      state: avg ? stateForBound(avg, 5, 14) : "idle",
    });
    rows.push({
      label: "Median duration (bars)",
      value: median ? median.toFixed(1) : "—",
      threshold: "3–8",
      state: median ? stateForBound(median, 3, 8) : "idle",
    });
    rows.push({
      label: "Trail-stop exits",
      value: trailPct != null ? `${trailPct.toFixed(0)}%` : "—",
      threshold: "≥80%",
      state:
        trailPct == null
          ? "idle"
          : trailPct < 80
          ? "fail"
          : trailPct < 85
          ? "warn"
          : "ok",
    });
    rows.push({
      label: "Initial-stop exits",
      value: initialPct != null ? `${initialPct.toFixed(0)}%` : "—",
      threshold: "≤15%",
      state:
        initialPct == null
          ? "idle"
          : initialPct > 15
          ? "fail"
          : initialPct > 12
          ? "warn"
          : "ok",
    });
  }

  const stateClass = (s: Row["state"]) =>
    s === "fail"
      ? "bg-danger/15 text-danger border-danger/40"
      : s === "warn"
      ? "bg-warn/15 text-warn border-warn/40"
      : s === "ok"
      ? "bg-accent/10 text-accent border-accent/30"
      : "bg-neutral-700/30 text-muted border-border";

  return (
    <div className="panel p-4">
      <div className="text-sm font-bold mb-3 text-neutral-200">
        Envelope vs kill criteria
      </div>
      <div className="space-y-1.5">
        {rows.map((r, i) => (
          <div
            key={i}
            className="flex items-center justify-between text-xs gap-2"
          >
            <span className="text-muted truncate">{r.label}</span>
            <div className="flex items-center gap-2">
              <span className="text-muted text-[11px]">{r.threshold}</span>
              <span
                className={`px-2 py-0.5 rounded border text-[11px] tabular-nums min-w-[3rem] text-center ${stateClass(
                  r.state
                )}`}
              >
                {r.value}
              </span>
            </div>
          </div>
        ))}
      </div>
      {closed.length === 0 && (
        <div className="mt-3 text-[11px] text-muted">
          Behavioural-drift checks activate after the first 5 closed trades.
        </div>
      )}
    </div>
  );
}
