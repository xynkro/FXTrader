"""Thin wrapper around oandapyV20. Synchronous calls run via asyncio.to_thread
from the trading loop so we don't block the event loop on network I/O."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import oandapyV20
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
import oandapyV20.endpoints.pricing as pricing
import oandapyV20.endpoints.trades as trades_ep
from oandapyV20.exceptions import V20Error

from .config import settings
from .models import AccountSnapshot, Candle


class OandaError(RuntimeError):
    pass


def _parse_oanda_time(t: str) -> datetime:
    # OANDA format: 2024-01-15T13:45:00.000000000Z (nanoseconds → trim)
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    if "." in t:
        head, _, frac_tz = t.partition(".")
        frac, sign, tz = (
            frac_tz.partition("+") if "+" in frac_tz else frac_tz.partition("-")
        )
        frac = frac[:6]
        t = f"{head}.{frac}{sign}{tz}" if sign else f"{head}.{frac}"
    return datetime.fromisoformat(t)


class OandaClient:
    def __init__(self):
        if not settings.OANDA_API_KEY or settings.OANDA_API_KEY.startswith("paste"):
            raise OandaError(
                "OANDA_API_KEY not configured — edit .env at the project root"
            )
        self.api = oandapyV20.API(
            access_token=settings.OANDA_API_KEY,
            environment=settings.OANDA_ENV,
        )
        self.account_id = settings.OANDA_ACCOUNT_ID

    # ----------------------------- account ---------------------------------
    def _account_summary_sync(self) -> dict:
        r = accounts.AccountSummary(accountID=self.account_id)
        try:
            self.api.request(r)
        except V20Error as e:
            raise OandaError(f"AccountSummary failed: {e}") from e
        return r.response["account"]

    async def account_snapshot(self) -> AccountSnapshot:
        a = await asyncio.to_thread(self._account_summary_sync)
        return AccountSnapshot(
            timestamp=datetime.now(timezone.utc),
            balance=float(a["balance"]),
            equity=float(a["NAV"]),
            margin_used=float(a.get("marginUsed", 0)),
            open_position_count=int(a.get("openPositionCount", 0)),
            currency=a.get("currency", "USD"),
        )

    # ----------------------------- candles ---------------------------------
    def _candles_sync(
        self,
        instrument: str,
        granularity: str,
        count: Optional[int] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> list[Candle]:
        params: dict = {"granularity": granularity, "price": "M"}
        if count is not None:
            params["count"] = count
        if from_time is not None:
            params["from"] = from_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        if to_time is not None:
            params["to"] = to_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        r = instruments.InstrumentsCandles(instrument=instrument, params=params)
        try:
            self.api.request(r)
        except V20Error as e:
            raise OandaError(f"Candles failed: {e}") from e
        out: list[Candle] = []
        for c in r.response.get("candles", []):
            if not c.get("complete", False):
                continue
            mid = c["mid"]
            out.append(
                Candle(
                    time=_parse_oanda_time(c["time"]),
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=int(c.get("volume", 0)),
                )
            )
        return out

    async def candles(self, **kw) -> list[Candle]:
        return await asyncio.to_thread(self._candles_sync, **kw)

    # ----------------------------- pricing ---------------------------------
    def _current_price_sync(self, instrument: str) -> tuple[float, float]:
        r = pricing.PricingInfo(
            accountID=self.account_id, params={"instruments": instrument}
        )
        try:
            self.api.request(r)
        except V20Error as e:
            raise OandaError(f"PricingInfo failed: {e}") from e
        p = r.response["prices"][0]
        bid = float(p["bids"][0]["price"])
        ask = float(p["asks"][0]["price"])
        return bid, ask

    async def current_price(self, instrument: str) -> tuple[float, float]:
        return await asyncio.to_thread(self._current_price_sync, instrument)

    # ----------------------------- orders ----------------------------------
    def _market_order_sync(
        self,
        instrument: str,
        units: int,
        stop_price: float,
        target_price: Optional[float] = None,
    ) -> dict:
        """Place a market order with a fixed initial stop loss.

        The trailing logic is deliberately kept on the engine side (bar-close
        anchored chandelier) to preserve backtest/live parity. We only set
        `stopLossOnFill` here; subsequent stop tightening is done via
        `replace_trade_stop()` on each new closed bar.
        """
        order: dict = {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": f"{stop_price:.5f}"},
        }
        if target_price is not None and target_price > 0:
            order["takeProfitOnFill"] = {"price": f"{target_price:.5f}"}
        r = orders.OrderCreate(accountID=self.account_id, data={"order": order})
        try:
            self.api.request(r)
        except V20Error as e:
            raise OandaError(f"OrderCreate failed: {e}") from e
        return r.response

    async def market_order(
        self,
        instrument: str,
        units: int,
        stop_price: float,
        target_price: Optional[float] = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._market_order_sync, instrument, units, stop_price, target_price
        )

    # ----------------------------- stop replace ---------------------------
    def _replace_trade_stop_sync(self, trade_id: str, stop_price: float) -> dict:
        """Replace the stop loss on an existing trade. Used by the engine to
        manually tighten the stop on each new bar close."""
        body = {
            "stopLoss": {
                "timeInForce": "GTC",
                "price": f"{stop_price:.5f}",
            }
        }
        r = trades_ep.TradeCRCDO(
            accountID=self.account_id, tradeID=trade_id, data=body
        )
        try:
            self.api.request(r)
        except V20Error as e:
            raise OandaError(f"TradeCRCDO failed: {e}") from e
        return r.response

    async def replace_trade_stop(self, trade_id: str, stop_price: float) -> dict:
        return await asyncio.to_thread(
            self._replace_trade_stop_sync, trade_id, stop_price
        )

    # ----------------------------- positions -------------------------------
    def _close_all_sync(self, instrument: str) -> dict:
        body = {"longUnits": "ALL", "shortUnits": "ALL"}
        r = positions.PositionClose(
            accountID=self.account_id, instrument=instrument, data=body
        )
        try:
            self.api.request(r)
        except V20Error as e:
            # 404 means no open position — fine
            if "NO_SUCH_POSITION" in str(e):
                return {"closed": False, "reason": "no_position"}
            raise OandaError(f"PositionClose failed: {e}") from e
        return r.response

    async def close_position(self, instrument: str) -> dict:
        return await asyncio.to_thread(self._close_all_sync, instrument)

    def _open_trades_sync(self) -> list[dict]:
        r = trades_ep.OpenTrades(accountID=self.account_id)
        try:
            self.api.request(r)
        except V20Error as e:
            raise OandaError(f"OpenTrades failed: {e}") from e
        return r.response.get("trades", [])

    async def open_trades(self) -> list[dict]:
        return await asyncio.to_thread(self._open_trades_sync)


# Lazy singleton — only constructed when first accessed, so the backtester
# (which doesn't need OANDA credentials) can import this module freely.
_client: Optional[OandaClient] = None


def get_client() -> OandaClient:
    global _client
    if _client is None:
        _client = OandaClient()
    return _client
