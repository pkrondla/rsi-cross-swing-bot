"""Live / paper IB venue. Maps broker strings into the order state machine."""

from __future__ import annotations

from typing import Protocol

from qqq_rsi_bot.core.models import BrokerFill
from qqq_rsi_bot.execution.models import FillReport, OrderIntent, OrderRecord, OrderStatus


class IbBrokerPort(Protocol):
    def place_limit(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        limit_price: float,
        order_ref: str,
        account: str,
    ) -> tuple[str, str]: ...

    def cancel_order(self, broker_order_id: str) -> str: ...

    def order_status(self, broker_order_id: str) -> tuple[str, int, float]: ...

    def fills_for(self, order_ref: str) -> list[BrokerFill]: ...


def map_ib_status(raw: str) -> OrderStatus:
    key = (raw or "").lower()
    if key in {"submitted", "presubmitted", "pendingsubmit"}:
        return OrderStatus.SENT
    if key in {"api pending", "pendingcancel"}:
        return OrderStatus.ACKNOWLEDGED
    if key == "filled":
        return OrderStatus.FILLED
    if key in {"cancelled", "inactive", "apicancelled"}:
        return OrderStatus.CANCELLED
    if "partial" in key:
        return OrderStatus.PARTIAL
    if key in {"rejected", "error"}:
        return OrderStatus.REJECTED
    return OrderStatus.ACKNOWLEDGED


def to_fill_report(fill: BrokerFill, signal_id: str) -> FillReport:
    return FillReport(
        order_ref=fill.order_ref,
        signal_id=signal_id,
        symbol=fill.symbol,
        side=fill.side,
        quantity=fill.quantity,
        price=fill.price,
        time=fill.time,
        broker_order_id=fill.broker_order_id,
    )


class IbVenue:
    def __init__(self, broker: IbBrokerPort, account: str) -> None:
        self._broker = broker
        self._account = account
        self._fills: dict[str, list[FillReport]] = {}

    def submit(self, intent: OrderIntent) -> OrderRecord:
        broker_id, raw_status = self._broker.place_limit(
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            order_ref=intent.order_ref,
            account=self._account,
        )
        status = map_ib_status(raw_status)
        filled_qty, avg = 0, 0.0
        if status in {
            OrderStatus.FILLED,
            OrderStatus.PARTIAL,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.SENT,
        }:
            raw2, filled_qty, avg = self._broker.order_status(broker_id)
            status = map_ib_status(raw2)
            if status is OrderStatus.FILLED and filled_qty == 0:
                filled_qty = intent.quantity
                avg = intent.limit_price
        fills = [
            to_fill_report(f, intent.signal_id) for f in self._broker.fills_for(intent.order_ref)
        ]
        self._fills[intent.order_ref] = fills
        if fills and filled_qty == 0:
            filled_qty = sum(f.quantity for f in fills)
            avg = sum(f.price * f.quantity for f in fills) / filled_qty
            status = OrderStatus.FILLED
        return OrderRecord(
            intent=intent,
            status=status,
            broker_order_id=broker_id,
            filled_qty=filled_qty,
            avg_price=avg,
        )

    def cancel(self, record: OrderRecord) -> OrderRecord:
        if not record.broker_order_id:
            return record
        status = map_ib_status(self._broker.cancel_order(record.broker_order_id))
        record.status = status
        return record

    def poll(self, record: OrderRecord) -> OrderRecord:
        if not record.broker_order_id:
            return record
        raw, filled, avg = self._broker.order_status(record.broker_order_id)
        record.status = map_ib_status(raw)
        record.filled_qty = filled
        record.avg_price = avg
        self._fills[record.intent.order_ref] = [
            to_fill_report(f, record.intent.signal_id)
            for f in self._broker.fills_for(record.intent.order_ref)
        ]
        return record

    def recent_fills(self, record: OrderRecord) -> list[FillReport]:
        return list(self._fills.get(record.intent.order_ref, []))
