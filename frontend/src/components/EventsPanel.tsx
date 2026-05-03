import type { EngineEvent } from "../types";
import { fmtTime } from "../lib/format";

const LEVEL_COLOR: Record<string, string> = {
  INFO: "text-neutral-300",
  WARN: "text-warn",
  ERROR: "text-danger",
};

export default function EventsPanel({ events }: { events: EngineEvent[] }) {
  return (
    <div className="panel p-4">
      <div className="text-sm font-bold mb-3 text-neutral-200">Engine events</div>
      {events.length === 0 ? (
        <div className="text-sm text-muted py-4 text-center">no events yet</div>
      ) : (
        <div className="max-h-64 overflow-y-auto pr-1 space-y-1 text-xs">
          {events.map((e, i) => (
            <div
              key={i}
              className="flex gap-2 border-b border-border/40 last:border-0 pb-1"
            >
              <span className="text-muted whitespace-nowrap">
                {fmtTime(e.timestamp)}
              </span>
              <span className={`font-semibold ${LEVEL_COLOR[e.level] ?? ""}`}>
                {e.level}
              </span>
              <span className="text-neutral-200">{e.event}</span>
              {e.detail && (
                <span className="text-muted truncate">{e.detail}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
