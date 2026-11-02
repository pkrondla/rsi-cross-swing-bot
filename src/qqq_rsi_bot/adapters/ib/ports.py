"""Market-data and account ports implemented by the IB Gateway client."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from qqq_rsi_bot.core.models import Bar, Quote


class MarketDataPort(Protocol):
    def daily_bars(self, symbol: str, end: date, days: int) -> list[Bar]: ...

    def quote(self, symbol: str) -> Quote: ...


class AccountPort(Protocol):
    def available_usd_cash(self, account: str) -> float: ...

    def position_qty(self, account: str, symbol: str) -> int: ...

    def accounts(self) -> list[str]: ...
