"""Order manager: persist intents, submit to venue, record this bot's fills."""

from __future__ import annotations

from datetime import datetime

from qqq_rsi_bot.execution.models import OrderIntent, OrderRecord, OrderStatus
from qqq_rsi_bot.execution.venue import ExecutionVenue
from qqq_rsi_bot.storage.store import TradeStore


class OrderManager:
    def __init__(self, venue: ExecutionVenue, store: TradeStore) -> None:
        self._venue = venue
        self._store = store

    def submit(self, intent: OrderIntent, now: datetime) -> OrderRecord:
        existing = self._store.order_by_signal(intent.signal_id)
        if existing is not None and existing["status"] not in {
            OrderStatus.REJECTED.value,
            OrderStatus.CANCELLED.value,
        }:
            return OrderRecord(
                intent=intent,
                status=OrderStatus(existing["status"]),
                broker_order_id=str(existing["broker_order_id"] or ""),
                filled_qty=int(existing["filled_qty"]),
                avg_price=float(existing["avg_price"]),
                updated_at=now,
            )

        self._store.upsert_order(
            idempotency_key=intent.idempotency_key,
            signal_id=intent.signal_id,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            status=OrderStatus.SENT.value,
            order_ref=intent.order_ref,
            updated_at=now,
        )
        self._store.append_event(
            "order_sent",
            {
                "signal_id": intent.signal_id,
                "side": intent.side,
                "quantity": intent.quantity,
                "limit_price": intent.limit_price,
                "order_ref": intent.order_ref,
            },
            ts=now,
            signal_id=intent.signal_id,
        )
        record = self._venue.submit(intent)
        record.updated_at = now
        self._persist(record, now)
        for fill in self._venue.recent_fills(record):
            self._store.record_fill(
                order_ref=fill.order_ref,
                signal_id=fill.signal_id,
                symbol=fill.symbol,
                side=fill.side,
                quantity=fill.quantity,
                price=fill.price,
                ts=fill.time,
            )
            self._store.append_event(
                "fill",
                {
                    "order_ref": fill.order_ref,
                    "side": fill.side,
                    "quantity": fill.quantity,
                    "price": fill.price,
                },
                ts=fill.time,
                signal_id=fill.signal_id,
            )
        return record

    def cancel(self, record: OrderRecord, now: datetime) -> OrderRecord:
        updated = self._venue.cancel(record)
        updated.updated_at = now
        self._persist(updated, now)
        return updated

    def _persist(self, record: OrderRecord, now: datetime) -> None:
        self._store.upsert_order(
            idempotency_key=record.intent.idempotency_key,
            signal_id=record.intent.signal_id,
            side=record.intent.side,
            quantity=record.intent.quantity,
            limit_price=record.intent.limit_price,
            status=record.status.value,
            order_ref=record.intent.order_ref,
            broker_order_id=record.broker_order_id,
            filled_qty=record.filled_qty,
            avg_price=record.avg_price,
            updated_at=now,
        )
