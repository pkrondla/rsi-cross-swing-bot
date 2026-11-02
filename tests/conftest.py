from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from qqq_rsi_bot.core.models import Bar, Quote

ET = ZoneInfo("America/New_York")


@pytest.fixture
def et_now() -> datetime:
    return datetime(2024, 6, 3, 15, 58, tzinfo=ET)


def make_bars(closes: list[float], start: date | None = None) -> list[Bar]:
    """Build sequential weekday bars (skips Sat/Sun) from closes."""
    day = start or date(2020, 1, 2)
    bars: list[Bar] = []
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(
            Bar(
                session_date=day,
                open=close,
                high=close,
                low=close,
                close=close,
            )
        )
        day += timedelta(days=1)
    return bars


def quote(symbol: str, bid: float, ask: float, *, delayed: bool = False) -> Quote:
    return Quote(
        symbol=symbol,
        bid=bid,
        ask=ask,
        last=(bid + ask) / 2,
        delayed=delayed,
        as_of=datetime(2024, 6, 3, 15, 58, tzinfo=ET),
    )
