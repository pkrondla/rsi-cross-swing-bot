"""Dry-run venue: prices against the quote, never calls placeOrder."""

from __future__ import annotations

from collections.abc import Callable

from rsi_cross_swing_bot.core.models import Quote
from rsi_cross_swing_bot.execution.models import FillReport, OrderIntent, OrderRecord, OrderStatus


class DryRunVenue:
    def __init__(self, quote_fn: Callable[[str], Quote]) -> None:
        self._quote_fn = quote_fn
        self._fills: dict[str, list[FillReport]] = {}

    def submit(self, intent: OrderIntent) -> OrderRecord:
        quote = self._quote_fn(intent.symbol)
        fill_px = quote.ask if intent.side == "BUY" else quote.bid
        now = quote.as_of
        record = OrderRecord(
            intent=intent,
            status=OrderStatus.FILLED,
            broker_order_id=f"DRY-{intent.idempotency_key}",
            filled_qty=intent.quantity,
            avg_price=fill_px,
            updated_at=now,
        )
        self._fills[intent.order_ref] = [
            FillReport(
                order_ref=intent.order_ref,
                signal_id=intent.signal_id,
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.quantity,
                price=fill_px,
                time=now,
                broker_order_id=record.broker_order_id,
            )
        ]
        return record

    def cancel(self, record: OrderRecord) -> OrderRecord:
        return record

    def poll(self, record: OrderRecord) -> OrderRecord:
        return record

    def recent_fills(self, record: OrderRecord) -> list[FillReport]:
        return list(self._fills.get(record.intent.order_ref, []))
