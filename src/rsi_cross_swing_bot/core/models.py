"""Shared value types for bars, quotes and bot position state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class SignalAction(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    HOLD = "HOLD"


class EntryReason(StrEnum):
    OVERSOLD = "oversold"
    TREND = "trend"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class Bar:
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    delayed: bool
    as_of: datetime


@dataclass(frozen=True, slots=True)
class BotPosition:
    """Shares this bot bought and still holds (never the full IB account)."""

    symbol: str
    quantity: int
    avg_price: float

    @property
    def is_flat(self) -> bool:
        return self.quantity <= 0


@dataclass(frozen=True, slots=True)
class BrokerFill:
    """Raw fill from the broker before the execution layer records it."""

    order_ref: str
    symbol: str
    side: str
    quantity: int
    price: float
    time: datetime
    broker_order_id: str = ""
