from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from rsi_cross_swing_bot.core.models import EntryReason, SignalAction
from rsi_cross_swing_bot.engine.signal_engine import IndicatorSnapshot, SignalDecision
from rsi_cross_swing_bot.risk.gate import RiskGate, share_count

ET = ZoneInfo("America/New_York")


def test_share_count_floor() -> None:
    qty, cut = share_count(10_000, 50.10, 10_000)
    assert qty == 199
    assert cut is False


def test_share_count_cash_cut() -> None:
    qty, cut = share_count(10_000, 50.10, 1_000)
    assert qty == 19
    assert cut is True


def _enter_decision() -> SignalDecision:
    snap = IndicatorSnapshot(
        session_date=datetime(2024, 6, 3, tzinfo=ET).date(),
        close=100,
        rsi=40,
        rsi_ma=39,
        ema200=90,
        prev_rsi=38,
        prev_rsi_ma=39,
    )
    return SignalDecision(
        action=SignalAction.ENTER,
        signal_id="rsi-cross-2024-06-03-entry-oversold",
        reason=EntryReason.OVERSOLD,
        snapshot=snap,
        bullish_cross=True,
        bearish_cross=False,
    )


def test_exit_sells_bot_qty_not_account() -> None:
    gate = RiskGate(allocated_usd=10_000)
    snap = _enter_decision().snapshot
    decision = SignalDecision(
        action=SignalAction.EXIT,
        signal_id="rsi-cross-2024-06-03-exit",
        reason=None,
        snapshot=snap,
        bullish_cross=False,
        bearish_cross=True,
    )
    risk = gate.evaluate(
        decision,
        now=datetime(2024, 6, 3, 15, 58, tzinfo=ET),
        in_decision_window=True,
        bot_qty=199,
        account_tqqq_qty=500,
        available_cash=50_000,
        ask=50.2,
        bid=50.0,
        signal_already_used=False,
        stopped_for_day=False,
        halted=False,
        delayed_data=False,
        bar_is_today=True,
    )
    assert risk.allowed
    assert risk.quantity == 199


def test_account_below_bot_blocks_exit() -> None:
    gate = RiskGate(allocated_usd=10_000)
    snap = _enter_decision().snapshot
    decision = SignalDecision(
        action=SignalAction.EXIT,
        signal_id="rsi-cross-2024-06-03-exit",
        reason=None,
        snapshot=snap,
        bullish_cross=False,
        bearish_cross=True,
    )
    risk = gate.evaluate(
        decision,
        now=datetime(2024, 6, 3, 15, 58, tzinfo=ET),
        in_decision_window=True,
        bot_qty=199,
        account_tqqq_qty=100,
        available_cash=50_000,
        ask=50.2,
        bid=50.0,
        signal_already_used=False,
        stopped_for_day=False,
        halted=False,
        delayed_data=False,
        bar_is_today=True,
    )
    assert not risk.allowed
    assert risk.reason == "account_qty_below_bot"


def test_outside_window_blocked() -> None:
    gate = RiskGate(allocated_usd=10_000)
    risk = gate.evaluate(
        _enter_decision(),
        now=datetime(2024, 6, 3, 15, 40, tzinfo=ET),
        in_decision_window=False,
        bot_qty=0,
        account_tqqq_qty=0,
        available_cash=50_000,
        ask=50.2,
        bid=50.0,
        signal_already_used=False,
        stopped_for_day=False,
        halted=False,
        delayed_data=False,
        bar_is_today=True,
    )
    assert risk.reason == "outside_decision_window"
