"""SQLite audit log and bot-owned fill ledger."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from qqq_rsi_bot.core.models import BotPosition, Side
from qqq_rsi_bot.storage.migrations import apply_migrations


class TradeStore:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        if self._path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        apply_migrations(self._conn)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    def append_event(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        ts: datetime,
        signal_id: str | None = None,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO events (ts, kind, signal_id, payload) VALUES (?,?,?,?)",
                (ts.isoformat(), kind, signal_id, json.dumps(payload)),
            )

    def record_signal(
        self,
        signal_id: str,
        trade_date: date,
        action: str,
        status: str,
        strategy_hash: str,
        payload: dict[str, Any],
        reason: str | None = None,
    ) -> bool:
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO signals "
                "(signal_id, trade_date, action, reason, status, strategy_hash, payload) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    signal_id,
                    trade_date.isoformat(),
                    action,
                    reason,
                    status,
                    strategy_hash,
                    json.dumps(payload),
                ),
            )
            return cur.rowcount == 1

    def signal_exists(self, signal_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM signals WHERE signal_id=?", (signal_id,)
        ).fetchone()
        return row is not None

    def set_signal_status(self, signal_id: str, status: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE signals SET status=? WHERE signal_id=?", (status, signal_id)
            )

    def upsert_order(
        self,
        *,
        idempotency_key: str,
        signal_id: str,
        side: str,
        quantity: int,
        limit_price: float | None,
        status: str,
        order_ref: str,
        broker_order_id: str = "",
        filled_qty: int = 0,
        avg_price: float = 0.0,
        updated_at: datetime,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO orders "
                "(idempotency_key, signal_id, side, quantity, limit_price, status, "
                "broker_order_id, order_ref, filled_qty, avg_price, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(idempotency_key) DO UPDATE SET "
                "status=excluded.status, broker_order_id=excluded.broker_order_id, "
                "filled_qty=excluded.filled_qty, avg_price=excluded.avg_price, "
                "updated_at=excluded.updated_at",
                (
                    idempotency_key,
                    signal_id,
                    side,
                    quantity,
                    limit_price,
                    status,
                    broker_order_id,
                    order_ref,
                    filled_qty,
                    avg_price,
                    updated_at.isoformat(),
                ),
            )

    def order_by_signal(self, signal_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM orders WHERE signal_id=? ORDER BY updated_at DESC LIMIT 1",
            (signal_id,),
        ).fetchone()
        return row

    def record_fill(
        self,
        *,
        order_ref: str,
        signal_id: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        ts: datetime,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO fills "
                "(order_ref, signal_id, symbol, side, quantity, price, ts) "
                "VALUES (?,?,?,?,?,?,?)",
                (order_ref, signal_id, symbol, side, quantity, price, ts.isoformat()),
            )

    def bot_position(self, symbol: str) -> BotPosition:
        """Net shares from this bot's fills only."""
        rows = self._conn.execute(
            "SELECT side, quantity, price FROM fills WHERE symbol=?", (symbol,)
        ).fetchall()
        qty = 0
        cost = 0.0
        for row in rows:
            q = int(row["quantity"])
            px = float(row["price"])
            if row["side"] == Side.BUY.value:
                cost += q * px
                qty += q
            else:
                if qty > 0:
                    # reduce average by sold shares at prior avg
                    avg = cost / qty
                    cost -= avg * min(q, qty)
                qty -= q
        qty = max(0, qty)
        avg_price = (cost / qty) if qty > 0 else 0.0
        return BotPosition(symbol=symbol, quantity=qty, avg_price=avg_price)

    def signals_for_day(self, day: date) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM signals WHERE trade_date=? ORDER BY signal_id",
                (day.isoformat(),),
            )
        )

    def orders_for_day(self, day: date) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT o.* FROM orders o "
                "JOIN signals s ON s.signal_id = o.signal_id "
                "WHERE s.trade_date=? ORDER BY o.updated_at",
                (day.isoformat(),),
            )
        )
