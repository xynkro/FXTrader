import { useState } from "react";
import { api } from "../lib/api";
import type { EngineStatus } from "../types";

export default function ControlPanel({
  status,
  onAction,
}: {
  status: EngineStatus | null;
  onAction: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState(false);
  const [confirmKill, setConfirmKill] = useState(false);

  const wrap = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      await onAction();
    } finally {
      setBusy(false);
    }
  };

  const enabled = status?.trading_enabled ?? false;
  const killed = status?.kill_switch_tripped ?? false;

  return (
    <div className="panel p-4">
      <div className="text-sm font-bold mb-3 text-neutral-200">Controls</div>
      <div className="flex flex-col gap-2">
        {killed && (
          <button
            disabled={busy}
            onClick={() => wrap(api.resetKill)}
            className="btn-ghost"
          >
            Reset kill switch
          </button>
        )}
        {!enabled ? (
          <button
            disabled={busy || killed}
            onClick={() => wrap(api.enable)}
            className="btn-go"
          >
            ▶ Enable trading
          </button>
        ) : (
          <button
            disabled={busy}
            onClick={() => wrap(api.disable)}
            className="btn-stop"
          >
            ⏸ Disable trading
          </button>
        )}

        {!confirmKill ? (
          <button
            disabled={busy}
            onClick={() => setConfirmKill(true)}
            className="btn-kill"
          >
            ✕ Kill switch
          </button>
        ) : (
          <div className="border border-danger/40 bg-danger/10 rounded-md p-2 flex flex-col gap-2">
            <div className="text-xs text-danger">
              Closes ALL open positions and disables trading. Continue?
            </div>
            <div className="flex gap-2">
              <button
                disabled={busy}
                onClick={() =>
                  wrap(async () => {
                    await api.kill();
                    setConfirmKill(false);
                  })
                }
                className="btn-kill flex-1"
              >
                YES — kill it
              </button>
              <button
                disabled={busy}
                onClick={() => setConfirmKill(false)}
                className="btn-ghost flex-1"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
