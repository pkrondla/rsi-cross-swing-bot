from __future__ import annotations

import pytest

from rsi_cross_swing_bot.indicators import ema, rsi_wilder, sma


def test_sma_simple() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    out = sma(values, 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)
    assert out[4] == pytest.approx(4.0)


def test_ema_seeds_with_sma() -> None:
    values = [float(i) for i in range(1, 11)]
    out = ema(values, 5)
    assert out[:4] == [None, None, None, None]
    assert out[4] == pytest.approx(3.0)  # SMA(1..5)
    assert out[5] == pytest.approx(4.0)


def test_rsi_wilder_up_series() -> None:
    closes = [float(100 + i) for i in range(20)]
    out = rsi_wilder(closes, 14)
    assert out[14] == pytest.approx(100.0)
    assert out[-1] == pytest.approx(100.0)


def test_rsi_down_series() -> None:
    closes = [float(100 - i) for i in range(20)]
    out = rsi_wilder(closes, 14)
    assert out[14] == pytest.approx(0.0)
