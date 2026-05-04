import type {
  AccountSnapshot,
  Config,
  EngineEvent,
  EngineStatus,
  EquityPoint,
  OandaPosition,
  Trade,
} from "../types";

const base = "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(base + path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(base + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const api = {
  status: () => get<EngineStatus>("/api/status"),
  config: () => get<Config>("/api/config"),
  account: () => get<AccountSnapshot>("/api/account"),
  positions: () => get<OandaPosition[]>("/api/positions"),
  trades: (limit = 100) => get<Trade[]>(`/api/trades?limit=${limit}`),
  equity: (limit = 5000) => get<EquityPoint[]>(`/api/equity?limit=${limit}`),
  events: (limit = 200) => get<EngineEvent[]>(`/api/events?limit=${limit}`),
  enable: () => post<{ trading_enabled: boolean }>("/api/trading/enable"),
  disable: () => post<{ trading_enabled: boolean }>("/api/trading/disable"),
  kill: () => post<{ killed: boolean }>("/api/kill"),
  resetKill: () => post<{ kill_switch_tripped: boolean }>("/api/reset-kill"),
  switchEnv: (body: {
    target: "practice" | "live";
    confirmation: string;
    live_api_key?: string;
    live_account_id?: string;
  }) => post<{
    ok: boolean;
    env?: string;
    account?: string;
    balance?: number;
    currency?: string;
    no_change?: boolean;
  }>("/api/trading/switch-env", body),
};

export function openStatusSocket(
  onMessage: (s: EngineStatus) => void,
  onError?: (e: Event) => void
): () => void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws`;
  const ws = new WebSocket(url);
  ws.onmessage = (m) => {
    try {
      onMessage(JSON.parse(m.data) as EngineStatus);
    } catch (e) {
      console.error("ws parse failed", e);
    }
  };
  ws.onerror = (e) => onError?.(e);
  return () => ws.close();
}
