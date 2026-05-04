"""HTTP API for the PWA dashboard."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import settings
from .db import trade_log
from .oanda_client import OandaError
from .risk import risk
from .strategy import STRATEGIES, StrategyParams
from .trader import engine


router = APIRouter(prefix="/api")


@router.get("/status")
async def status():
    return engine.status().model_dump()


@router.get("/config")
async def config():
    """Read-only view of effective config (without the API key)."""
    p = StrategyParams()
    return {
        "instrument": settings.INSTRUMENT,
        "granularity": settings.GRANULARITY,
        "oanda_env": settings.OANDA_ENV,
        "oanda_account_id": settings.OANDA_ACCOUNT_ID,
        "trading_enabled": settings.TRADING_ENABLED,
        "shadow_mode": settings.SHADOW_MODE,
        "strategy_name": settings.STRATEGY_NAME,
        "available_strategies": sorted(STRATEGIES.keys()),
        "allow_live_switch": settings.ALLOW_LIVE_SWITCH,
        "live_credentials_configured": bool(
            settings.OANDA_LIVE_API_KEY and settings.OANDA_LIVE_ACCOUNT_ID
        ),
        "risk_per_trade_pct": settings.RISK_PER_TRADE_PCT,
        "max_trades_per_day": settings.MAX_TRADES_PER_DAY,
        "max_concurrent_positions": settings.MAX_CONCURRENT_POSITIONS,
        "daily_loss_limit_pct": settings.DAILY_LOSS_LIMIT_PCT,
        "max_drawdown_pct": settings.MAX_DRAWDOWN_PCT,
        "consecutive_loss_limit": settings.CONSECUTIVE_LOSS_LIMIT,
        "session_start_utc": settings.SESSION_START_UTC,
        "session_end_utc": settings.SESSION_END_UTC,
        # Strategy parameters (read-only — locked for the demo window)
        "strategy_params": {
            "donchian_period": p.donchian_period,
            "atr_period": p.atr_period,
            "stop_atr_mult": p.stop_atr_mult,
            "min_atr_pips": p.min_atr_pips,
            "min_stop_pips": p.min_stop_pips,
            "max_leverage": p.max_leverage,
            "cooldown_bars": p.cooldown_bars,
            "sma_long": p.sma_long,
            "sma_short": p.sma_short,
            "pullback_lookback": p.pullback_lookback,
            "trend_slope_lookback": p.trend_slope_lookback,
        },
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


# ----------------------------------------------------------------------
#  ENV SWITCH — DEMO ↔ LIVE (real money)
# ----------------------------------------------------------------------
class SwitchEnvBody(BaseModel):
    target: Literal["practice", "live"]
    confirmation: str
    live_api_key: Optional[str] = None      # only used when target=live
    live_account_id: Optional[str] = None   # only used when target=live


@router.post("/trading/switch-env")
async def switch_env(body: SwitchEnvBody):
    """Switch between practice (demo) and live (real-money) OANDA accounts
    at runtime. Heavily guarded:

    1. ALLOW_LIVE_SWITCH=true must be set in .env (master gate).
    2. To go to LIVE, body.confirmation must equal exactly "GO LIVE".
       To go to PRACTICE, body.confirmation must equal exactly "GO DEMO".
    3. To go to LIVE, valid live_api_key + live_account_id must be
       supplied either via .env (OANDA_LIVE_API_KEY / OANDA_LIVE_ACCOUNT_ID)
       or via this request body (request body wins if both are present).
    4. Engine is hard-stopped, all positions closed on the OUTGOING env
       before the swap, then engine restarts on the new env.

    The change is in-memory only — on process restart, .env is the
    source of truth again. To make a switch persistent, edit .env.
    """
    if not settings.ALLOW_LIVE_SWITCH:
        raise HTTPException(
            status_code=403,
            detail="ALLOW_LIVE_SWITCH=false in .env — runtime env switch is "
                   "disabled. Edit .env to enable.",
        )

    expected = "GO LIVE" if body.target == "live" else "GO DEMO"
    if body.confirmation != expected:
        raise HTTPException(
            status_code=400,
            detail=f"confirmation must equal exactly '{expected}'",
        )

    if body.target == settings.OANDA_ENV:
        return {
            "ok": True,
            "no_change": True,
            "current_env": settings.OANDA_ENV,
            "current_account": settings.OANDA_ACCOUNT_ID,
        }

    # For target=live, resolve credentials.
    new_api_key = settings.OANDA_API_KEY
    new_account_id = settings.OANDA_ACCOUNT_ID
    if body.target == "live":
        new_api_key = (
            body.live_api_key or settings.OANDA_LIVE_API_KEY or ""
        )
        new_account_id = (
            body.live_account_id or settings.OANDA_LIVE_ACCOUNT_ID or ""
        )
        if not new_api_key or not new_account_id:
            raise HTTPException(
                status_code=400,
                detail="live_api_key + live_account_id must be supplied via "
                       "the request body OR set in .env. Live and practice "
                       "use different API tokens.",
            )

    # Snapshot current creds in case we need to roll back.
    prev = {
        "env": settings.OANDA_ENV,
        "key": settings.OANDA_API_KEY,
        "account": settings.OANDA_ACCOUNT_ID,
    }

    try:
        result = await engine.switch_env(
            target=body.target,
            api_key=new_api_key,
            account_id=new_account_id,
        )
    except OandaError as e:
        # Roll the in-memory settings back; engine state restored by
        # switch_env's own try/except.
        settings.OANDA_ENV = prev["env"]
        settings.OANDA_API_KEY = prev["key"]
        settings.OANDA_ACCOUNT_ID = prev["account"]
        raise HTTPException(
            status_code=502,
            detail=f"env switch failed (auth/account validation): {e}",
        )

    trade_log.log_event(
        "WARN" if body.target == "live" else "INFO",
        "env_switch",
        f"{prev['env']} → {body.target} account={new_account_id}",
    )
    return result
