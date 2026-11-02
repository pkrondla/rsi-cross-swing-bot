"""NYSE session calendar (holidays and early closes)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from qqq_rsi_bot.core.clock import ET


@lru_cache(maxsize=1)
def _xnys() -> Any:
    return xcals.get_calendar("XNYS")


def is_trading_day(day: date) -> bool:
    return bool(_xnys().is_session(day.isoformat()))


def is_early_close(day: date) -> bool:
    if not is_trading_day(day):
        return False
    try:
        close = _xnys().session_close(day.isoformat())
    except Exception:  # noqa: BLE001
        return False
    local = close.tz_convert("America/New_York") if hasattr(close, "tz_convert") else close
    close_time = local.time() if hasattr(local, "time") else time(16, 0)
    return close_time < time(16, 0)


def next_trading_day(day: date) -> date:
    candidate = day
    for _ in range(366):
        if is_trading_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise RuntimeError(f"no trading day found within a year of {day}")


def parse_hhmm(value: str) -> time:
    parts = value.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    return time(h, m, s)


def session_dt(day: date, hhmm: str, tz: ZoneInfo = ET) -> datetime:
    return datetime.combine(day, parse_hhmm(hhmm), tzinfo=tz)


def decision_datetime(
    day: date,
    *,
    decision_time: str = "15:58",
    early_close_decision_time: str = "12:58",
) -> datetime:
    hhmm = early_close_decision_time if is_early_close(day) else decision_time
    return session_dt(day, hhmm)


def in_decision_window(
    now: datetime,
    *,
    decision_time: str = "15:58",
    early_close_decision_time: str = "12:58",
    window_minutes: int = 2,
) -> bool:
    local = now.astimezone(ET)
    day = local.date()
    if not is_trading_day(day):
        return False
    start = decision_datetime(
        day,
        decision_time=decision_time,
        early_close_decision_time=early_close_decision_time,
    )
    end = start + timedelta(minutes=window_minutes)
    return start <= local <= end


def next_wake(
    now: datetime,
    *,
    session_open: str = "09:30",
    decision_time: str = "15:58",
    early_close_decision_time: str = "12:58",
) -> datetime:
    local = now.astimezone(ET)
    day = local.date()
    if is_trading_day(day):
        open_dt = session_dt(day, session_open)
        decide = decision_datetime(
            day,
            decision_time=decision_time,
            early_close_decision_time=early_close_decision_time,
        )
        if local < open_dt:
            return open_dt
        if local < decide:
            nxt_hour = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            return min(nxt_hour, decide)
    nxt = next_trading_day(day + timedelta(days=1))
    return session_dt(nxt, session_open)
