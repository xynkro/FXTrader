import { useEffect, useState } from "react";
import type { EngineEvent, EquityPoint } from "../types";

/** Engine health derived from local state — no extra backend endpoint needed.
 *
 * - "ticks_per_min" = recent equity-snapshot rate (engine snapshots every ~30s)
 * - "last_tick_age" = seconds since most recent equity snapshot
 * - "net_warns_24h"  = WARN-level network_error events in last 24h
 * - "code_errs_24h"  = ERROR-level events tagged tick_exception/order_failed/etc.
 *
 * The "alive" indicator goes red if last_tick_age > 90s. Yellow if 60-90s.
 * Green otherwise.
 */
export default function ConnectionHealth({
  equity,
  events,
}: {
  equity: EquityPoint[];
  events: EngineEvent[];
}) {
  // re-render every 5s so last_tick_age stays fresh between data fetches
  const [, force] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => force((n) => n + 1), 5000);
    return () => window.clearInterval(id);
  }, []);

  const now = Date.now();
  const last = equity.length ? new Date(equity[equity.length - 1].t).getTime() : 0;
  const lastAgeSec = last ? Math.round((now - last) / 1000) : Infinity;

  // ticks per minute over last 5 minutes
  const cutoff = now - 5 * 60 * 1000;
  const recent = equity.filter((p) => new Date(p.t).getTime() > cutoff);
  const tpm = recent.length / 5;

  // 24h event counts
  const dayCutoff = now - 24 * 60 * 60 * 1000;
  let netWarns = 0;
  let codeErrs = 0;
  for (const e of events) {
    const t = new Date(e.timestamp).getTime();
    if (t < dayCutoff) continue;
    if (e.level === "WARN" && e.event.includes("network_error")) netWarns++;
    if (e.level === "ERROR" &&
        (e.event === "tick_exception" || e.event === "order_failed" ||
         e.event === "kill_close_failed" || e.event.startsWith("warm_unexpected")))
      codeErrs++;
  }

  let dot: string;
  let label: string;
  if (lastAgeSec === Infinity) {
    dot = "bg-muted";
    label = "no data yet";
  } else if (lastAgeSec > 90) {
    dot = "bg-danger";
    label = "engine stalled";
  } else if (lastAgeSec > 60) {
    dot = "bg-warn";
    label = "ticks lagging";
  } else {
    dot = "bg-accent";
    label = "engine ticking";
  }

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`w-2 h-2 rounded-full ${dot}`}></span>
      <span className="text-neutral-300">{label}</span>
      <span className="text-muted">·</span>
      <span className="text-muted">{lastAgeSec === Infinity ? "—" : `${lastAgeSec}s`}</span>
      <span className="text-muted">·</span>
      <span className="text-muted">{tpm.toFixed(1)}/min</span>
      {(netWarns > 0 || codeErrs > 0) && (
        <>
          <span className="text-muted">·</span>
          {netWarns > 0 && (
            <span className="text-warn">net:{netWarns}</span>
          )}
          {codeErrs > 0 && (
            <span className="text-danger ml-1">err:{codeErrs}</span>
          )}
        </>
      )}
    </div>
  );
}
