from __future__ import annotations

from datetime import date

from rsi_cross_swing_bot.core.models import EntryReason, SignalAction
from rsi_cross_swing_bot.engine.signal_engine import IndicatorSnapshot, evaluate


def _snap(
    *,
    rsi: float,
    rsi_ma: float,
    prev_rsi: float,
    prev_rsi_ma: float,
    close: float = 100.0,
    ema200: float = 90.0,
    day: date = date(2024, 6, 3),
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        session_date=day,
        close=close,
        rsi=rsi,
        rsi_ma=rsi_ma,
        ema200=ema200,
        prev_rsi=prev_rsi,
        prev_rsi_ma=prev_rsi_ma,
    )


def test_oversold_cross_enters() -> None:
    snap = _snap(rsi=40, rsi_ma=39, prev_rsi=38, prev_rsi_ma=39, close=80, ema200=90)
    d = evaluate(snap, bot_qty=0)
    assert d.action is SignalAction.ENTER
    assert d.reason is EntryReason.OVERSOLD


def test_trend_cross_with_rsi_above_50_enters() -> None:
    snap = _snap(rsi=55, rsi_ma=54, prev_rsi=53, prev_rsi_ma=54, close=110, ema200=100)
    d = evaluate(snap, bot_qty=0)
    assert d.action is SignalAction.ENTER
    assert d.reason is EntryReason.TREND


def test_cross_above_50_under_ema_does_not_enter() -> None:
    snap = _snap(rsi=55, rsi_ma=54, prev_rsi=53, prev_rsi_ma=54, close=90, ema200=100)
    d = evaluate(snap, bot_qty=0)
    assert d.action is SignalAction.HOLD


def test_both_reasons() -> None:
    snap = _snap(rsi=40, rsi_ma=39, prev_rsi=38, prev_rsi_ma=39, close=110, ema200=100)
    d = evaluate(snap, bot_qty=0)
    assert d.reason is EntryReason.BOTH


def test_bearish_cross_exits() -> None:
    snap = _snap(rsi=45, rsi_ma=46, prev_rsi=47, prev_rsi_ma=46)
    d = evaluate(snap, bot_qty=10)
    assert d.action is SignalAction.EXIT


def test_bearish_cross_while_flat_holds() -> None:
    snap = _snap(rsi=45, rsi_ma=46, prev_rsi=47, prev_rsi_ma=46)
    d = evaluate(snap, bot_qty=0)
    assert d.action is SignalAction.HOLD


def test_bullish_cross_while_long_does_not_add() -> None:
    snap = _snap(rsi=40, rsi_ma=39, prev_rsi=38, prev_rsi_ma=39)
    d = evaluate(snap, bot_qty=5)
    assert d.action is SignalAction.HOLD
