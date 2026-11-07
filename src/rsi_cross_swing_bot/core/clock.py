"""Time helpers. All market logic runs in America/New_York; a Clock is injected for tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC).astimezone(ET)


class FixedClock:
    """A settable clock for tests and replay."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = start.astimezone(ET)

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value.astimezone(ET)

    def advance(self, **kwargs: float) -> None:
        self._now = self._now + timedelta(**kwargs)
