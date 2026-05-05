"""Live trading loop. Polls OANDA every 30s, evaluates the strategy on
newly-closed candles, places orders through the risk manager, manages
the bar-close-anchored chandelier trail manually (NOT broker-native),
and reconciles fills/closures into the local trade log.

Live ↔ backtest parity contract (preserved deliberately):
- Initial stop is fixed at entry ± K * ATR_at_signal.
- Trail update is computed only at the close of a NEW bar, using
  highest_high_since_entry (or lowest_low_since_entry for shorts) and
  the FROZEN ATR at signal time.
- A trail tightening triggers an OANDA TradeCRCDO call to replace the
  stop loss on the existing trade. This matches backtest semantics
  (bar-close anchored chandelier) rather than OANDA's tick-by-tick
  trailingStopLossOnFill.
- Known acceptable mismatch: backtest fills at bar t+1 open while live
  fills at bar t close (~30s post-close). Documented in the demo protocol.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from .config import settings
from .db import trade_log
from .models import EngineStatus, Side, Trade, TradeStatus
from .oanda_client import OandaClient, OandaError, get_client, reset_client
from .risk import risk
from .strategy import (
    STRATEGIES,
    StrategyState,
    in_session,
    is_jpy_quote,
    pip_size,
    position_size,
)


log = logging.getLogger("trader")


class Engine:
    def __init__(self):
        self.state = StrategyState()
        self.last_candle_time: Optional[datetime] = None
        self.last_signal_time: Optional[datetime] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._oanda_id_to_local: dict[str, int] = {}
        self._client: Optional[OandaClient] = None
        self._equity: float = 0.0
        # Pending trail updates per shadow trade (active next bar).
        self._shadow_pending_stops: dict[int, float] = {}
        # Per-side last bar that we already logged a missed-setup for
        # (stops repeat-logging on the same bar from multiple ticks).
        self._last_missed_bar: dict[str, str] = {}

    @property
    def evaluate_fn(self):
        name = settings.STRATEGY_NAME or "donchian"
        return STRATEGIES.get(name, STRATEGIES["donchian"])

    @property
    def client(self) -> OandaClient:
        if self._client is None:
            self._client = get_client()
        return self._client

    # ------------------------------------------------------------------
    async def warm_history(self, count: int = 200) -> None:
        candles = await self.client.candles(
            instrument=settings.INSTRUMENT,
            granularity=settings.GRANULARITY,
            count=count,
        )
        for c in candles:
            self.state.add(c)
        if candles:
            self.last_candle_time = candles[-1].time
        trade_log.log_event(
            "INFO", "warm_history", f"loaded {len(candles)} candles"
        )

    # ------------------------------------------------------------------
    async def tick(self) -> None:
        snap = await self.client.account_snapshot()
        self._equity = snap.equity
        trade_log.snapshot_equity(snap)
        risk.update_equity(snap.timestamp, snap.equity)

        # Pull last 5 candles, only keep ones newer than what we have.
        candles = await self.client.candles(
            instrument=settings.INSTRUMENT,
            granularity=settings.GRANULARITY,
            count=5,
        )
        new_bar = False
        for c in candles:
            if self.last_candle_time is None or c.time > self.last_candle_time:
                self.state.add(c)
                self.last_candle_time = c.time
                new_bar = True

        await self._reconcile_closures()

        # Per-bar shadow lifecycle (stop-out check, trail update) runs
        # before signal evaluation.
        if new_bar:
            await self._advance_shadow_trades_on_new_bars()
            await self._update_trail_stops()

        if not new_bar:
            return

        block = risk.check(
            now=snap.timestamp,
            equity=snap.equity,
            open_count=snap.open_position_count,
            trades_today=len(trade_log.trades_today(snap.timestamp)),
        )
        if block:
            return

        sig = self.evaluate_fn(self.state, snap.equity)
        if sig is None:
            # Quarantined research log: if a setup would have fired but for
            # the session-window gate, record it. Engine does NOT trade.
            # Read-only data for future "extended-session" pre-registered test.
            self._maybe_log_missed_setup()
            return
        self.last_signal_time = sig.time

        await self._open_trade_from_signal(sig, snap.equity)

    # ------------------------------------------------------------------
    def _maybe_log_missed_setup(self) -> None:
        """If we're out-of-session and the strategy's vitals say all OTHER
        gates pass, log a `missed_setup` INFO event. Quarantined research
        signal — never opens a trade."""
        from .strategy import compute_strategy_vitals
        from .strategy import in_session as _in_session
        if self.last_candle_time is None:
            return
        if _in_session(self.last_candle_time):
            return  # in-session = handled by normal path or genuine no-setup
        try:
            v = compute_strategy_vitals(self.state, settings.STRATEGY_NAME)
        except Exception:
            return
        if v.get("warming_up") or v.get("not_implemented"):
            return
        long_w = v.get("long", {}).get("would_fire_if_session_open", False)
        short_w = v.get("short", {}).get("would_fire_if_session_open", False)
        bar_t = self.last_candle_time.isoformat()[:16]
        # Idempotency: only log once per bar
        if long_w and self._last_missed_bar.get("LONG") != bar_t:
            trade_log.log_event(
                "INFO", "missed_setup",
                f"LONG bar={bar_t} (out-of-session, gates aligned)",
            )
            self._last_missed_bar["LONG"] = bar_t
        if short_w and self._last_missed_bar.get("SHORT") != bar_t:
            trade_log.log_event(
                "INFO", "missed_setup",
                f"SHORT bar={bar_t} (out-of-session, gates aligned)",
            )
            self._last_missed_bar["SHORT"] = bar_t

    # ------------------------------------------------------------------
    async def _open_trade_from_signal(self, sig, equity: float) -> None:
        # Capture spread + bid/ask + quote->account conversion at signal time.
        # This is the foundation for account-currency-aware sizing.
        try:
            bid_at_signal, ask_at_signal, q2a_rate = (
                await self.client.pricing_with_conversion(settings.INSTRUMENT)
            )
            spread_at_signal = ask_at_signal - bid_at_signal
            mid_at_signal = (bid_at_signal + ask_at_signal) / 2.0
        except OandaError:
            bid_at_signal = ask_at_signal = spread_at_signal = None
            mid_at_signal = sig.entry
            q2a_rate = None  # let position_size fall back to backtest-style assumption

        pip = pip_size(settings.INSTRUMENT)
        spread_pips = (
            spread_at_signal / pip if spread_at_signal is not None else None
        )

        units, leverage_capped = position_size(
            equity, sig.entry, sig.stop,
            quote_to_account_rate=q2a_rate,
        )
        if units <= 0:
            trade_log.log_event(
                "WARN", "size_zero",
                f"computed 0 units entry={sig.entry} stop={sig.stop} "
                f"q2a={q2a_rate}",
            )
            return
        if leverage_capped:
            trade_log.log_event(
                "WARN", "leverage_capped",
                f"units capped to {units} on entry={sig.entry}",
            )

        # Realised risk vs intended risk — observability for kill criterion 1
        # and parity audit (so any mismatch is caught immediately).
        intended_risk_pct = settings.RISK_PER_TRADE_PCT
        if q2a_rate is not None and equity > 0:
            realised_risk_acct = (
                units * abs(sig.entry - sig.stop) * q2a_rate
            )
            realised_risk_pct = 100.0 * realised_risk_acct / equity
        else:
            realised_risk_pct = float("nan")
        trade_log.log_event(
            "INFO", "sizing",
            f"units={units} q2a={q2a_rate} "
            f"intended_risk_pct={intended_risk_pct:.3f} "
            f"realised_risk_pct={realised_risk_pct:.3f} "
            f"leverage_capped={leverage_capped}",
        )

        signed_units = units if sig.side == Side.LONG else -units

        if settings.SHADOW_MODE:
            # Synthesize a fill at the appropriate side of the live spread
            # plus a slippage assumption that mirrors the backtest model
            # (0.2 pip detrimental). No broker order is placed.
            if bid_at_signal is None or ask_at_signal is None:
                trade_log.log_event(
                    "WARN", "shadow_skip_no_quote",
                    "no current price available; skipping shadow signal",
                )
                return
            base = ask_at_signal if sig.side == Side.LONG else bid_at_signal
            slip_assumed = 0.2 * pip
            fill_price = (
                base + slip_assumed if sig.side == Side.LONG
                else base - slip_assumed
            )
            oanda_trade_id = None
            oanda_stop_price: Optional[float] = sig.stop
            rounding = 0.0
        else:
            try:
                resp = await self.client.market_order(
                    instrument=settings.INSTRUMENT,
                    units=signed_units,
                    stop_price=sig.stop,
                    target_price=sig.target,
                )
            except OandaError as e:
                trade_log.log_event("ERROR", "order_failed", str(e))
                risk.trip(f"order_failed:{e}")
                return

            fill = resp.get("orderFillTransaction", {})
            oanda_trade_id = fill.get("tradeOpened", {}).get("tradeID")
            fill_price = float(fill.get("price", sig.entry))

            slot = resp.get("stopLossOrderTransaction") or {}
            oanda_stop_price = None
            if slot:
                try:
                    oanda_stop_price = float(slot.get("price"))
                except (TypeError, ValueError):
                    oanda_stop_price = None
            rounding = (
                abs(oanda_stop_price - sig.stop)
                if oanda_stop_price is not None else 0.0
            )

        # Slippage = actual fill vs signal-time mid.
        slippage_price = abs(fill_price - mid_at_signal) if mid_at_signal else 0.0
        slippage_pips = slippage_price / pip

        # Record the trade with full provenance for trail logic + audit.
        local_trade = Trade(
            oanda_trade_id=oanda_trade_id,
            instrument=settings.INSTRUMENT,
            side=sig.side,
            units=signed_units,
            entry_time=sig.time,
            entry_price=fill_price,
            stop_price=sig.stop,
            initial_stop=sig.stop,
            atr_at_entry=sig.atr,
            trailed=False,
            is_shadow=bool(settings.SHADOW_MODE),
            target_price=sig.target,
            status=TradeStatus.OPEN,
            reason=sig.reason,
        )
        trade_id = trade_log.insert_trade(local_trade)
        if oanda_trade_id:
            self._oanda_id_to_local[oanda_trade_id] = trade_id

        # Single, audit-grade entry log line (kill criteria depend on this).
        kind = "shadow" if settings.SHADOW_MODE else "live"
        sp = f"{spread_pips:.2f}" if spread_pips is not None else "NA"
        trade_log.log_event(
            "INFO", "trade_opened",
            f"[{kind}] id={trade_id} oanda={oanda_trade_id} "
            f"side={sig.side.value} units={units} "
            f"sig_entry={sig.entry:.5f} fill={fill_price:.5f} "
            f"bid={bid_at_signal} ask={ask_at_signal} "
            f"spread_pips={sp} "
            f"slippage_pips={slippage_pips:.2f} assumed_slip_pips=0.20 "
            f"initial_stop_req={sig.stop:.5f} "
            f"initial_stop_active={oanda_stop_price} "
            f"stop_rounding={rounding:.5f} "
            f"stop_distance={sig.stop_distance:.5f} "
            f"atr={sig.atr:.5f} strategy={settings.STRATEGY_NAME} "
            f"reason={sig.reason}",
        )

    # ------------------------------------------------------------------
    async def _update_trail_stops(self) -> None:
        """For each open local trade, compute the bar-close trail stop and
        push the update to OANDA if it tightens. Mirrors backtest semantics:
        trail computed at end of bar, applies starting next bar."""
        candles = list(self.state.candles)
        for t in trade_log.open_trades():
            if t.atr_at_entry is None or t.initial_stop is None:
                continue
            # Bars strictly after entry — those held by us
            held = [c for c in candles if c.time > t.entry_time]
            if not held:
                continue
            stop_distance = abs(t.entry_price - t.initial_stop)
            if stop_distance <= 0:
                continue
            if t.side == Side.LONG:
                ext = max(c.high for c in held)
                new_trail = ext - stop_distance
                if new_trail > t.stop_price:
                    await self._push_trail(t, new_trail, ext)
            else:
                ext = min(c.low for c in held)
                new_trail = ext + stop_distance
                if new_trail < t.stop_price:
                    await self._push_trail(t, new_trail, ext)

    async def _push_trail(self, t: Trade, new_stop: float, ext: float) -> None:
        pip = pip_size(settings.INSTRUMENT)
        if t.is_shadow:
            # Activate at NEXT bar (parity with backtest's delayed activation).
            self._shadow_pending_stops[t.id] = new_stop
            trade_log.log_event(
                "INFO", "trail_update_pending",
                f"[shadow] id={t.id} side={t.side.value} "
                f"prev_stop={t.stop_price:.5f} pending_new_stop={new_stop:.5f} "
                f"ext={ext:.5f} "
                f"tighter_by_pips={(abs(new_stop - t.stop_price) / pip):.2f}",
            )
            return

        if t.oanda_trade_id is None:
            return
        try:
            await self.client.replace_trade_stop(t.oanda_trade_id, new_stop)
        except OandaError as e:
            trade_log.log_event(
                "ERROR", "trail_replace_failed",
                f"id={t.id} attempted_stop={new_stop:.5f} err={e}",
            )
            return
        trade_log.update_trade_stop(t.id, new_stop, trailed=True)
        trade_log.log_event(
            "INFO", "trail_update",
            f"[live] id={t.id} oanda={t.oanda_trade_id} side={t.side.value} "
            f"prev_stop={t.stop_price:.5f} new_stop={new_stop:.5f} "
            f"ext={ext:.5f} tighter_by_pips={(abs(new_stop - t.stop_price) / pip):.2f}",
        )

    # ------------------------------------------------------------------
    async def _advance_shadow_trades_on_new_bars(self) -> None:
        """For each closed bar that hasn't been processed for shadow trades,
        (1) activate any pending trail update from the prior bar,
        (2) check stop-out using the bar's full range,
        (3) close the trade if hit."""
        candles = list(self.state.candles)
        for t in trade_log.open_trades():
            if not t.is_shadow:
                continue
            held = [c for c in candles if c.time > t.entry_time]
            if not held:
                continue

            # The "newest" bar is the trail-update activation moment.
            # We process bars in chronological order to avoid skipping a
            # stop-out that occurred before a later trail tightening.
            for bar in held:
                # 1. Activate pending stop (computed at end of previous bar)
                if t.id in self._shadow_pending_stops:
                    new_stop = self._shadow_pending_stops.pop(t.id)
                    trade_log.update_trade_stop(t.id, new_stop, trailed=True)
                    t.stop_price = new_stop
                    t.trailed = True

                # 2. Stop-out check
                stop_hit = (
                    bar.low <= t.stop_price if t.side == Side.LONG
                    else bar.high >= t.stop_price
                )
                if stop_hit:
                    await self._close_shadow_trade(t, t.stop_price, bar.time)
                    break  # done with this trade

    async def _close_shadow_trade(
        self, t: Trade, exit_price: float, exit_time: datetime
    ) -> None:
        # P&L conversion (same as live) — shadow uses the stop-fill price.
        if is_jpy_quote(t.instrument):
            if t.side == Side.LONG:
                gross = ((exit_price - t.entry_price) * abs(t.units)) / exit_price
            else:
                gross = ((t.entry_price - exit_price) * abs(t.units)) / exit_price
            planned_risk = (
                abs(t.entry_price - (t.initial_stop or t.stop_price))
                * abs(t.units) / t.entry_price
            )
        else:
            if t.side == Side.LONG:
                gross = (exit_price - t.entry_price) * abs(t.units)
            else:
                gross = (t.entry_price - exit_price) * abs(t.units)
            planned_risk = (
                abs(t.entry_price - (t.initial_stop or t.stop_price))
                * abs(t.units)
            )
        pnl_pct = 100.0 * gross / self._equity if self._equity > 0 else 0.0
        r = gross / planned_risk if planned_risk > 0 else 0.0
        trade_log.close_trade(
            trade_id=t.id, exit_time=exit_time, exit_price=exit_price,
            pnl=gross, pnl_pct=pnl_pct, r_multiple=r,
        )
        exit_label = "trailing_stop" if t.trailed else "initial_stop"
        trade_log.log_event(
            "INFO", "trade_closed",
            f"[shadow] id={t.id} side={t.side.value} "
            f"exit_price={exit_price:.5f} pnl=${gross:.2f} "
            f"pnl_pct={pnl_pct:+.3f}% R={r:+.2f} exit_type={exit_label}",
        )

    # ------------------------------------------------------------------
    async def _reconcile_closures(self) -> None:
        """Any local OPEN live trade not in OANDA's open list = closed.
        Shadow trades are excluded (their lifecycle is handled by
        _advance_shadow_trades_on_new_bars)."""
        try:
            oanda_open = await self.client.open_trades()
        except OandaError:
            return
        oanda_open_ids = {t["id"] for t in oanda_open}

        for t in trade_log.open_trades():
            if t.is_shadow:
                continue
            if t.oanda_trade_id and t.oanda_trade_id not in oanda_open_ids:
                bid, ask = await self.client.current_price(t.instrument)
                exit_price = bid if t.side == Side.LONG else ask
                # P&L: convert to USD if quote=JPY (account in USD).
                if is_jpy_quote(t.instrument):
                    if t.side == Side.LONG:
                        gross = ((exit_price - t.entry_price) * abs(t.units)) / exit_price
                    else:
                        gross = ((t.entry_price - exit_price) * abs(t.units)) / exit_price
                    planned_risk = (
                        abs(t.entry_price - (t.initial_stop or t.stop_price))
                        * abs(t.units) / t.entry_price
                    )
                else:
                    if t.side == Side.LONG:
                        gross = (exit_price - t.entry_price) * abs(t.units)
                    else:
                        gross = (t.entry_price - exit_price) * abs(t.units)
                    planned_risk = (
                        abs(t.entry_price - (t.initial_stop or t.stop_price))
                        * abs(t.units)
                    )

                pnl_pct = (
                    100.0 * gross / self._equity if self._equity > 0 else 0.0
                )
                r = gross / planned_risk if planned_risk > 0 else 0.0
                trade_log.close_trade(
                    trade_id=t.id,
                    exit_time=datetime.now(timezone.utc),
                    exit_price=exit_price,
                    pnl=gross,
                    pnl_pct=pnl_pct,
                    r_multiple=r,
                )
                t.exit_price = exit_price
                t.pnl = gross
                t.pnl_pct = pnl_pct
                t.r_multiple = r
                t.status = TradeStatus.CLOSED
                risk.record_trade_close(t)
                exit_label = "trailing_stop" if t.trailed else "initial_stop"
                trade_log.log_event(
                    "INFO", "trade_closed",
                    f"id={t.id} oanda={t.oanda_trade_id} side={t.side.value} "
                    f"exit_price={exit_price:.5f} pnl=${gross:.2f} "
                    f"pnl_pct={pnl_pct:+.3f}% R={r:+.2f} exit_type={exit_label}",
                )

    # ------------------------------------------------------------------
    @staticmethod
    def _classify_exception(e: BaseException) -> tuple[str, str]:
        """Return (level, kind). Network/transient → WARN/network_error;
        code/everything else → ERROR/tick_exception."""
        s = repr(e).lower()
        network_signals = (
            "connection reset by peer",
            "remoteDisconnected".lower(),
            "remote end closed connection",
            "read timed out",
            "max retries exceeded",
            "nameresolutionerror",
            "failed to resolve",
            "temporary failure in name resolution",
            "connectionerror",
            "connectionresetterror",
            "timeout",
            "sslerror",
        )
        if any(sig in s for sig in network_signals):
            return "WARN", "network_error"
        return "ERROR", "tick_exception"

    async def _loop(self) -> None:
        # warm_history: retry on network errors, hard-fail only on auth/config
        for attempt in range(5):
            try:
                await self.warm_history()
                break
            except OandaError as e:
                level, kind = self._classify_exception(e)
                trade_log.log_event(level, f"warm_{kind}", str(e))
                if level == "ERROR":
                    log.error("warm_history hard-failed: %s", e)
                    return
                await asyncio.sleep(min(30 * (attempt + 1), 120))
            except BaseException as e:  # noqa: BLE001
                log.exception("warm_history unexpected: %s", e)
                trade_log.log_event("ERROR", "warm_unexpected", repr(e))
                return

        # Main loop: NEVER die silently. Catch BaseException (including
        # asyncio.CancelledError from idle-connection reaps in 3.8+).
        # Classify network turbulence as WARN so kill criterion 2 doesn't
        # mistake it for engine instability.
        while self._running:
            try:
                await self.tick()
            except BaseException as e:  # noqa: BLE001
                level, kind = self._classify_exception(e)
                if level == "ERROR":
                    log.exception("tick failed (code error)")
                trade_log.log_event(level, kind, str(e)[:500])
            try:
                await asyncio.sleep(30)
            except BaseException:  # noqa: BLE001
                # Cancelled mid-sleep → just break out cleanly
                break

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        trade_log.log_event("INFO", "engine_start", "")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        trade_log.log_event("INFO", "engine_stop", "")

    # ------------------------------------------------------------------
    async def kill(self) -> None:
        """Hard stop: close all open positions and trip the kill switch."""
        risk.trip("manual_kill")
        try:
            await self.client.close_position(settings.INSTRUMENT)
        except OandaError as e:
            trade_log.log_event("ERROR", "kill_close_failed", str(e))
        trade_log.log_event("WARN", "manual_kill", "all positions closed")

    # ------------------------------------------------------------------
    async def switch_env(
        self, target: str, api_key: str, account_id: str
    ) -> dict:
        """Hot-swap the OANDA environment between practice and live.

        Steps (each one logged so a botched switch is reconstructible):
          1. Disable trading + close any open positions on CURRENT env.
          2. Stop the tick task.
          3. Mutate settings (in-memory only — .env is unchanged).
          4. Reset the OandaClient singleton so the new env is picked up.
          5. Validate the new credentials with an account_summary call.
             If that fails, roll back and raise.
          6. Reset in-memory engine state (state, last_candle_time,
             pending stops, equity).
          7. Restart the tick task.
        """
        prev_env = settings.OANDA_ENV
        prev_key = settings.OANDA_API_KEY
        prev_account = settings.OANDA_ACCOUNT_ID

        # 1. Stand down trading + close positions on outgoing env.
        settings.TRADING_ENABLED = False
        trade_log.log_event(
            "WARN", "env_switch_begin",
            f"{prev_env} → {target} (account={account_id})",
        )
        try:
            await self.client.close_position(settings.INSTRUMENT)
        except OandaError as e:
            trade_log.log_event(
                "WARN", "env_switch_close_warn", f"close on {prev_env}: {e}"
            )

        # 2. Stop tick task cleanly.
        await self.stop()

        # 3+4. Swap settings + drop client cache.
        settings.OANDA_ENV = target  # type: ignore[assignment]
        settings.OANDA_API_KEY = api_key
        settings.OANDA_ACCOUNT_ID = account_id
        reset_client()
        self._client = None

        # 5. Validate new creds. If this raises OandaError the api.py
        #    handler will roll back the settings.
        try:
            snap = await self.client.account_snapshot()
        except OandaError:
            # Roll back here so engine state stays consistent even though
            # api.py also restores the in-memory settings. (Defence in depth.)
            settings.OANDA_ENV = prev_env  # type: ignore[assignment]
            settings.OANDA_API_KEY = prev_key
            settings.OANDA_ACCOUNT_ID = prev_account
            reset_client()
            self._client = None
            # Restart the tick task so we don't leave the engine dead.
            self.start()
            raise

        # 6. Reset volatile state — different account = different history.
        self.state = StrategyState()
        self.last_candle_time = None
        self.last_signal_time = None
        self._oanda_id_to_local.clear()
        self._shadow_pending_stops.clear()
        self._equity = snap.equity

        # 7. Restart tick task.
        self.start()
        trade_log.log_event(
            "WARN", "env_switch_done",
            f"now on {target} account={account_id} balance={snap.balance:.2f} "
            f"{snap.currency}",
        )
        return {
            "ok": True,
            "env": target,
            "account": account_id,
            "balance": snap.balance,
            "currency": snap.currency,
            "trading_enabled": False,  # caller must explicitly re-enable
        }

    # ------------------------------------------------------------------
    def status(self) -> EngineStatus:
        now = datetime.now(timezone.utc)
        return EngineStatus(
            trading_enabled=settings.TRADING_ENABLED and not risk.state.kill_switch_tripped,
            kill_switch_tripped=risk.state.kill_switch_tripped,
            kill_reason=risk.state.kill_reason,
            in_session=in_session(now),
            consecutive_losses=risk.state.consecutive_losses,
            trades_today=len(trade_log.trades_today(now)),
            daily_pnl_pct=risk.daily_pnl_pct(self._equity),
            peak_equity=risk.state.peak_equity,
            current_drawdown_pct=risk.drawdown_pct(self._equity),
            last_signal_time=self.last_signal_time,
            last_candle_time=self.last_candle_time,
        )


engine = Engine()
