"""SQLite trade log + equity snapshots. Sync sqlite is fine here — the
strategy loop is not high-throughput and the DB is single-writer."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .config import settings
from .models import AccountSnapshot, Side, Trade, TradeStatus


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oanda_trade_id TEXT,
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    units INTEGER NOT NULL,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    target_price REAL NOT NULL,
    exit_time TEXT,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,
    r_multiple REAL,
    status TEXT NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);

CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    balance REAL NOT NULL,
    equity REAL NOT NULL,
    margin_used REAL NOT NULL,
    open_position_count INTEGER NOT NULL,
    currency TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_equity_timestamp ON equity(timestamp);

CREATE TABLE IF NOT EXISTS engine_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT
);
"""


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    return datetime.fromisoformat(s)


class TradeLog:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or settings.db_path
        self._init()

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # --- trades ---------------------------------------------------------
    def insert_trade(self, t: Trade) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO trades
                   (oanda_trade_id, instrument, side, units, entry_time,
                    entry_price, stop_price, target_price, status, reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    t.oanda_trade_id,
                    t.instrument,
                    t.side.value,
                    t.units,
                    _to_iso(t.entry_time),
                    t.entry_price,
                    t.stop_price,
                    t.target_price,
                    t.status.value,
                    t.reason,
                ),
            )
            return int(cur.lastrowid)

    def close_trade(
        self,
        trade_id: int,
        exit_time: datetime,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        r_multiple: float,
    ) -> None:
        with self._conn() as c:
            c.execute(
                """UPDATE trades SET exit_time=?, exit_price=?, pnl=?,
                   pnl_pct=?, r_multiple=?, status=?
                   WHERE id=?""",
                (
                    _to_iso(exit_time),
                    exit_price,
                    pnl,
                    pnl_pct,
                    r_multiple,
                    TradeStatus.CLOSED.value,
                    trade_id,
                ),
            )

    def open_trades(self) -> list[Trade]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM trades WHERE status = ? ORDER BY entry_time DESC",
                (TradeStatus.OPEN.value,),
            ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def recent_trades(self, limit: int = 100) -> list[Trade]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def trades_today(self, day_utc: datetime) -> list[Trade]:
        start = day_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM trades WHERE entry_time >= ? AND entry_time <= ?",
                (_to_iso(start), _to_iso(end)),
            ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def _row_to_trade(self, r: sqlite3.Row) -> Trade:
        return Trade(
            id=r["id"],
            oanda_trade_id=r["oanda_trade_id"],
            instrument=r["instrument"],
            side=Side(r["side"]),
            units=r["units"],
            entry_time=_from_iso(r["entry_time"]),
            entry_price=r["entry_price"],
            stop_price=r["stop_price"],
            target_price=r["target_price"],
            exit_time=_from_iso(r["exit_time"]),
            exit_price=r["exit_price"],
            pnl=r["pnl"],
            pnl_pct=r["pnl_pct"],
            r_multiple=r["r_multiple"],
            status=TradeStatus(r["status"]),
            reason=r["reason"] or "",
        )

    # --- equity ---------------------------------------------------------
    def snapshot_equity(self, snap: AccountSnapshot) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO equity
                   (timestamp, balance, equity, margin_used,
                    open_position_count, currency)
                   VALUES (?,?,?,?,?,?)""",
                (
                    _to_iso(snap.timestamp),
                    snap.balance,
                    snap.equity,
                    snap.margin_used,
                    snap.open_position_count,
                    snap.currency,
                ),
            )

    def equity_curve(self, limit: int = 5000) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT timestamp, equity FROM equity "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        rows = list(reversed(rows))
        return [{"t": r["timestamp"], "equity": r["equity"]} for r in rows]

    # --- engine events --------------------------------------------------
    def log_event(self, level: str, event: str, detail: str = "") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO engine_events (timestamp, level, event, detail) "
                "VALUES (?,?,?,?)",
                (_to_iso(datetime.now(timezone.utc)), level, event, detail),
            )

    def recent_events(self, limit: int = 200) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT timestamp, level, event, detail FROM engine_events "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


trade_log = TradeLog()
