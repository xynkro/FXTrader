from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Candle(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    @property
    def hl2(self) -> float:
        return (self.high + self.low) / 2.0


class Signal(BaseModel):
    time: datetime
    side: Side
    entry: float           # estimate (signal-bar close); backtest fills at t+1 open
    stop: float            # estimate (entry ± K*ATR); backtest recomputes from t+1 fill
    target: Optional[float] = None       # None for trend follower
    atr: float                            # frozen at signal bar
    stop_distance: float = 0.0            # K * ATR in price units (used by backtest)
    reason: str


class Trade(BaseModel):
    id: Optional[int] = None
    oanda_trade_id: Optional[str] = None
    instrument: str
    side: Side
    units: int                          # signed: long > 0, short < 0
    entry_time: datetime
    entry_price: float
    stop_price: float
    target_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None        # realised, in account currency
    pnl_pct: Optional[float] = None    # vs equity at entry
    r_multiple: Optional[float] = None # actual / planned risk
    status: TradeStatus = TradeStatus.OPEN
    reason: str = ""


class AccountSnapshot(BaseModel):
    timestamp: datetime
    balance: float
    equity: float           # balance + unrealised
    margin_used: float
    open_position_count: int
    currency: str = "USD"


class EngineStatus(BaseModel):
    trading_enabled: bool
    kill_switch_tripped: bool
    kill_reason: Optional[str] = None
    in_session: bool
    consecutive_losses: int
    trades_today: int
    daily_pnl_pct: float
    peak_equity: float
    current_drawdown_pct: float
    last_signal_time: Optional[datetime] = None
    last_candle_time: Optional[datetime] = None


class BacktestResult(BaseModel):
    start: datetime
    end: datetime
    instrument: str
    bars: int
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_r: float
    expectancy_pct: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    profit_factor: float
    final_equity: float
    starting_equity: float
