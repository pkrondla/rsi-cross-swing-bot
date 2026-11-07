from __future__ import annotations

from datetime import date, timedelta

from rsi_cross_swing_bot.app.replay import replay_bars
from rsi_cross_swing_bot.core.models import Bar


def _synthetic_trend_then_dip_then_cross() -> list[Bar]:
    """Long flat/up series for EMA warmup, then a dip and RSI reclaim."""
    closes: list[float] = []
    price = 100.0
    for _ in range(220):
        price *= 1.001
        closes.append(price)
    for _ in range(20):
        price *= 0.99
        closes.append(price)
    for _ in range(10):
        price *= 1.02
        closes.append(price)

    day = date(2022, 1, 3)
    bars: list[Bar] = []
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(Bar(day, c, c, c, c))
        day += timedelta(days=1)
    return bars


def test_golden_replay_is_deterministic() -> None:
    bars = _synthetic_trend_then_dip_then_cross()
    first = replay_bars(bars, allocated_usd=10_000, ema_period=50)
    second = replay_bars(bars, allocated_usd=10_000, ema_period=50)
    assert [(t.day, t.action, t.quantity, t.signal_id) for t in first] == [
        (t.day, t.action, t.quantity, t.signal_id) for t in second
    ]
    # Expect at least one entry after the reclaim.
    assert any(t.action == "ENTER" for t in first)
    # Exits sell the same quantity that was bought (bot-owned only).
    open_qty = 0
    for t in first:
        if t.action == "ENTER":
            open_qty = t.quantity
        else:
            assert t.quantity == open_qty
            open_qty = 0
