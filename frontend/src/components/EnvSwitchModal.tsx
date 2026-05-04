import { useState } from "react";
import { api } from "../lib/api";
import type { Config } from "../types";

export default function EnvSwitchModal({
  config,
  target,
  onClose,
  onDone,
}: {
  config: Config;
  target: "practice" | "live";
  onClose: () => void;
  onDone: () => void;
}) {
  const goingLive = target === "live";
  const expectedPhrase = goingLive ? "GO LIVE" : "GO DEMO";
  const credsAlreadySet = config.live_credentials_configured ?? false;

  const [phrase, setPhrase] = useState("");
  const [liveKey, setLiveKey] = useState("");
  const [liveAccount, setLiveAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit =
    phrase === expectedPhrase &&
    (!goingLive || credsAlreadySet || (liveKey && liveAccount));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.switchEnv({
        target,
        confirmation: phrase,
        ...(goingLive && !credsAlreadySet
          ? { live_api_key: liveKey, live_account_id: liveAccount }
          : {}),
      });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className={`panel max-w-lg w-full p-5 border-2 ${
          goingLive ? "border-danger/60" : "border-accent/40"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-3">
          {goingLive ? (
            <span className="tag-danger">⚠ LIVE</span>
          ) : (
            <span className="tag-on">DEMO</span>
          )}
          <div className="text-base font-bold">
            Switch to {target.toUpperCase()}
          </div>
        </div>

        {goingLive ? (
          <div className="text-sm text-neutral-300 space-y-2 mb-4 leading-6">
            <p className="text-danger font-semibold">
              You are about to switch to REAL-MONEY trading.
            </p>
            <p>
              The engine will:
            </p>
            <ul className="list-disc list-inside text-xs text-muted space-y-1">
              <li>Disable trading and close any open positions on the demo account</li>
              <li>Swap OANDA credentials to the live account</li>
              <li>Reset in-memory state (trade history continues to be recorded but with the new account)</li>
              <li>NOT auto-re-enable trading — you must explicitly hit "Enable trading" after</li>
            </ul>
            <p className="text-xs text-warn pt-1">
              The pre-registered demo protocol requires the demo window to
              complete with envelope-conforming behaviour before promotion to
              live. Proceeding before that is your call.
            </p>
          </div>
        ) : (
          <p className="text-sm text-neutral-300 mb-4">
            Returns to the practice account. All open live positions (if any)
            are closed first. Trading is disabled after the swap; re-enable
            manually.
          </p>
        )}

        {goingLive && !credsAlreadySet && (
          <div className="space-y-2 mb-4">
            <div className="text-xs text-muted">
              No live credentials in <span className="font-mono">.env</span> —
              supply them now (used for this session only; persist by editing{" "}
              <span className="font-mono">.env</span>).
            </div>
            <input
              type="password"
              placeholder="Live OANDA API token"
              value={liveKey}
              onChange={(e) => setLiveKey(e.target.value)}
              className="w-full bg-bg border border-border rounded px-2 py-1.5 text-sm font-mono"
            />
            <input
              type="text"
              placeholder="Live account ID (e.g. 001-XXX-XXXXXXX-XXX)"
              value={liveAccount}
              onChange={(e) => setLiveAccount(e.target.value)}
              className="w-full bg-bg border border-border rounded px-2 py-1.5 text-sm font-mono"
            />
          </div>
        )}

        <div className="space-y-2 mb-4">
          <div className="text-xs text-muted">
            Type <span className="font-mono text-neutral-100">{expectedPhrase}</span>{" "}
            exactly to confirm.
          </div>
          <input
            type="text"
            value={phrase}
            onChange={(e) => setPhrase(e.target.value)}
            placeholder={expectedPhrase}
            className="w-full bg-bg border border-border rounded px-2 py-1.5 text-sm font-mono"
            autoFocus
          />
        </div>

        {error && (
          <div className="text-xs text-danger border border-danger/40 bg-danger/10 rounded p-2 mb-3">
            {error}
          </div>
        )}

        <div className="flex gap-2">
          <button
            disabled={!canSubmit || busy}
            onClick={submit}
            className={`flex-1 ${goingLive ? "btn-kill" : "btn-go"}`}
          >
            {busy
              ? "Switching..."
              : goingLive
              ? "Switch to LIVE"
              : "Switch to DEMO"}
          </button>
          <button
            disabled={busy}
            onClick={onClose}
            className="flex-1 btn-ghost"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
