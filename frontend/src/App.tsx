import { useEffect, useState } from "react";
import { api, openStatusSocket } from "./lib/api";
import type {
  AccountSnapshot,
  Config,
  EngineEvent,
  EngineStatus,
  EquityPoint,
  OandaPosition,
  Trade,
} from "./types";
import Header from "./components/Header";
import StatusPanel from "./components/StatusPanel";
import EquityChart from "./components/EquityChart";
import PositionsTable from "./components/PositionsTable";
import TradesTable from "./components/TradesTable";
import ControlPanel from "./components/ControlPanel";
import EventsPanel from "./components/EventsPanel";

export default function App() {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [account, setAccount] = useState<AccountSnapshot | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [positions, setPositions] = useState<OandaPosition[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [events, setEvents] = useState<EngineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  // initial load + polling for slower-moving data
  useEffect(() => {
    let cancel = false;
    const tick = async () => {
      try {
        const [s, a, c, p, t, e, ev] = await Promise.all([
          api.status(),
          api.account().catch(() => null),
          api.config(),
          api.positions().catch(() => []),
          api.trades(50),
          api.equity(2000),
          api.events(100),
        ]);
        if (cancel) return;
        setStatus(s);
        setAccount(a);
        setConfig(c);
        setPositions(p);
        setTrades(t);
        setEquity(e);
        setEvents(ev);
        setError(null);
      } catch (err) {
        setError((err as Error).message);
      }
    };
    void tick();
    const i = window.setInterval(tick, 5000);
    return () => {
      cancel = true;
      window.clearInterval(i);
    };
  }, []);

  // live status from websocket
  useEffect(() => {
    const close = openStatusSocket(setStatus);
    return close;
  }, []);

  const refresh = async () => {
    setStatus(await api.status());
    setAccount(await api.account().catch(() => null));
    setPositions(await api.positions().catch(() => []));
    setTrades(await api.trades(50));
  };

  return (
    <div className="min-h-screen p-4 md:p-6 max-w-[1400px] mx-auto">
      <Header status={status} account={account} config={config} />

      {error && (
        <div className="panel p-3 mb-4 border-danger/40 text-danger text-sm">
          backend not reachable: {error}. Is the backend running on port 8765?
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <div className="lg:col-span-2">
          <EquityChart points={equity} />
        </div>
        <div className="space-y-4">
          <StatusPanel status={status} account={account} />
          <ControlPanel status={status} onAction={refresh} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <PositionsTable positions={positions} />
        <EventsPanel events={events} />
      </div>

      <TradesTable trades={trades} />

      <footer className="mt-6 text-xs text-muted text-center">
        FXTrader — {config?.oanda_env ?? "?"} env • account{" "}
        {config?.oanda_account_id ?? "?"} • {config?.instrument ?? "?"}{" "}
        {config?.granularity ?? ""}
      </footer>
    </div>
  );
}
