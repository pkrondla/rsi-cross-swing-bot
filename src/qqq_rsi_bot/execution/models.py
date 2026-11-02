"""Order intents and state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class OrderStatus(StrEnum):
    NEW = "NEW"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: frozenset({OrderStatus.SENT, OrderStatus.CANCELLED, OrderStatus.REJECTED}),
    OrderStatus.SENT: frozenset(
        {
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIAL,
            OrderStatus.FILLED,
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
        }
    ),
    OrderStatus.ACKNOWLEDGED: frozenset(
        {OrderStatus.PARTIAL, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
    ),
    OrderStatus.PARTIAL: frozenset(
        {OrderStatus.PARTIAL, OrderStatus.FILLED, OrderStatus.CANCELLED}
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


def can_transition(current: OrderStatus, new: OrderStatus) -> bool:
    return new in _TRANSITIONS.get(current, frozenset())


@dataclass(frozen=True, slots=True)
class OrderIntent:
    signal_id: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    order_ref: str
    attempt: int = 1

    @property
    def idempotency_key(self) -> str:
        return f"{self.signal_id}:{self.attempt}"


@dataclass(slots=True)
class FillReport:
    order_ref: str
    signal_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    time: datetime
    broker_order_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderRecord:
    intent: OrderIntent
    status: OrderStatus = OrderStatus.NEW
    broker_order_id: str = ""
    filled_qty: int = 0
    avg_price: float = 0.0
    reject_reason: str = ""
    updated_at: datetime | None = None

    def transition(self, new: OrderStatus) -> None:
        if not can_transition(self.status, new):
            raise ValueError(f"illegal transition {self.status} -> {new}")
        self.status = new
