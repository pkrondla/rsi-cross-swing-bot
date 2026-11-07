"""TradingView-style EMA: seed with SMA of the first `period` closes."""

from __future__ import annotations


def ema(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    mult = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        prev = (values[i] - prev) * mult + prev
        out[i] = prev
    return out
