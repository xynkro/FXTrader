from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "backend" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    OANDA_API_KEY: str = Field(default="")
    OANDA_ACCOUNT_ID: str = Field(default="")
    OANDA_ENV: Literal["practice", "live"] = "practice"

    INSTRUMENT: str = "EUR_USD"
    GRANULARITY: str = "M5"

    RISK_PER_TRADE_PCT: float = 0.5
    MAX_TRADES_PER_DAY: int = 4
    MAX_CONCURRENT_POSITIONS: int = 1
    DAILY_LOSS_LIMIT_PCT: float = 2.0
    MAX_DRAWDOWN_PCT: float = 5.0
    CONSECUTIVE_LOSS_LIMIT: int = 4

    SESSION_START_UTC: str = "12:00"
    SESSION_END_UTC: str = "16:00"

    TRADING_ENABLED: bool = False

    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8765
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    @field_validator("RISK_PER_TRADE_PCT", "DAILY_LOSS_LIMIT_PCT", "MAX_DRAWDOWN_PCT")
    @classmethod
    def positive_pct(cls, v: float) -> float:
        if v <= 0 or v > 50:
            raise ValueError("percentage must be in (0, 50]")
        return v

    @property
    def db_path(self) -> Path:
        return DATA_DIR / "trades.db"

    @property
    def historical_dir(self) -> Path:
        p = DATA_DIR / "historical"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def backtest_dir(self) -> Path:
        p = DATA_DIR / "backtest_results"
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
