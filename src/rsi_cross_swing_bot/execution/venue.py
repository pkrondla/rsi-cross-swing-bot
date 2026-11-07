"""Execution venue port."""

from __future__ import annotations

from typing import Protocol

from rsi_cross_swing_bot.execution.models import FillReport, OrderIntent, OrderRecord


class ExecutionVenue(Protocol):
    def submit(self, intent: OrderIntent) -> OrderRecord: ...

    def cancel(self, record: OrderRecord) -> OrderRecord: ...

    def poll(self, record: OrderRecord) -> OrderRecord: ...

    def recent_fills(self, record: OrderRecord) -> list[FillReport]: ...
