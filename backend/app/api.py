"""HTTP API for the PWA dashboard."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .config import settings
from .db import trade_log
from .oanda_client import OandaError
from .risk import risk
from .trader import engine


router = APIRouter(prefix="/api")


@router.get("/status")
async def status():
    return engine.status().model_dump()


@router.get("/config")
async def config():
    """Read-only view of effective config (without the API key)."""
    return {
        "instrument": settings.INSTRUMENT,
        "granularity": settings.GRANULARITY,
        "oanda_env": settings.OANDA_ENV,
        "oanda_account_id": settings.OANDA_ACCOUNT_ID,
        "trading_enabled": settings.TRADING_ENABLED,
        "risk_per_trade_pct": settings.RISK_PER_TRADE_PCT,
        "max_trades_per_day": settings.MAX_TRADES_PER_DAY,
        "max_concurrent_positions": settings.MAX_CONCURRENT_POSITIONS,
        "daily_loss_limit_pct": settings.DAILY_LOSS_LIMIT_PCT,
        "max_drawdown_pct": settings.MAX_DRAWDOWN_PCT,
        "consecutive_loss_limit": settings.CONSECUTIVE_LOSS_LIMIT,
        "session_start_utc": settings.SESSION_START_UTC,
        "session_end_utc": settings.SESSION_END_UTC,
    }


@router.get("/account")
async def account():
    try:
        snap = await engine.client.account_snapshot()
    except OandaError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return snap.model_dump(mode="json")


@router.get("/positions")
async def positions():
    try:
        oanda_open = await engine.client.open_trades()
    except OandaError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return oanda_open


@router.get("/trades")
async def trades(limit: int = 100):
    return [t.model_dump(mode="json") for t in trade_log.recent_trades(limit)]


@router.get("/equity")
async def equity(limit: int = 5000):
    return trade_log.equity_curve(limit)


@router.get("/events")
async def events(limit: int = 200):
    return trade_log.recent_events(limit)


@router.post("/trading/enable")
async def enable():
    settings.TRADING_ENABLED = True
    risk.reset_kill_switch()
    trade_log.log_event("INFO", "trading_enabled", "via api")
    return {"trading_enabled": True}


@router.post("/trading/disable")
async def disable():
    settings.TRADING_ENABLED = False
    trade_log.log_event("INFO", "trading_disabled", "via api")
    return {"trading_enabled": False}


@router.post("/kill")
async def kill():
    """Hard stop: close all open positions and trip the kill switch."""
    settings.TRADING_ENABLED = False
    await engine.kill()
    return {"killed": True, "trading_enabled": False}


@router.post("/reset-kill")
async def reset_kill():
    """Resets the kill switch flag. Does NOT re-enable trading — user must
    explicitly hit /trading/enable after."""
    risk.reset_kill_switch()
    return {"kill_switch_tripped": False}
