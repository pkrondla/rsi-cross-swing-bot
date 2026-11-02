from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from qqq_rsi_bot.runtime.calendar import decision_datetime, in_decision_window, is_trading_day

ET = ZoneInfo("America/New_York")


def test_regular_decision_refused_at_1540_allowed_at_1558() -> None:
    # 2024-06-03 was a Monday, regular session.
    day = datetime(2024, 6, 3, tzinfo=ET).date()
    assert is_trading_day(day)
    assert not in_decision_window(datetime(2024, 6, 3, 15, 40, tzinfo=ET))
    assert in_decision_window(datetime(2024, 6, 3, 15, 58, tzinfo=ET))
    assert decision_datetime(day).hour == 15
    assert decision_datetime(day).minute == 58


def test_early_close_decision_at_1258() -> None:
    # 2024-07-03 was an NYSE early close ahead of July 4.
    day = datetime(2024, 7, 3, tzinfo=ET).date()
    assert is_trading_day(day)
    decide = decision_datetime(day)
    assert decide.hour == 12
    assert decide.minute == 58
    assert in_decision_window(datetime(2024, 7, 3, 12, 58, tzinfo=ET))
    assert not in_decision_window(datetime(2024, 7, 3, 15, 58, tzinfo=ET))
