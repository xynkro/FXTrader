export interface EngineStatus {
  trading_enabled: boolean;
  kill_switch_tripped: boolean;
  kill_reason: string | null;
  in_session: boolean;
  consecutive_losses: number;
  trades_today: number;
  daily_pnl_pct: number;
  peak_equity: number;
  current_drawdown_pct: number;
  last_signal_time: string | null;
  last_candle_time: string | null;
}

export interface AccountSnapshot {
  timestamp: string;
  balance: number;
  equity: number;
  margin_used: number;
  open_position_count: number;
  currency: string;
}

export interface Trade {
  id: number;
  oanda_trade_id: string | null;
  instrument: string;
  side: "long" | "short";
  units: number;
  entry_time: string;
  entry_price: number;
  stop_price: number;
  target_price: number | null;
  initial_stop: number | null;
  atr_at_entry: number | null;
  trailed: boolean;
  is_shadow: boolean;
  exit_time: string | null;
  exit_price: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  r_multiple: number | null;
  status: "open" | "closed" | "cancelled";
  reason: string;
}

export interface EquityPoint {
  t: string;
  equity: number;
}

export interface EngineEvent {
  timestamp: string;
  level: string;
  event: string;
  detail: string;
}

export interface Config {
  instrument: string;
  granularity: string;
  oanda_env: string;
  oanda_account_id: string;
  trading_enabled: boolean;
  risk_per_trade_pct: number;
  max_trades_per_day: number;
  max_concurrent_positions: number;
  daily_loss_limit_pct: number;
  max_drawdown_pct: number;
  consecutive_loss_limit: number;
  session_start_utc: string;
  session_end_utc: string;
}

export interface OandaPosition {
  id: string;
  instrument: string;
  currentUnits: string;
  unrealizedPL: string;
  price: string;
  openTime: string;
}
