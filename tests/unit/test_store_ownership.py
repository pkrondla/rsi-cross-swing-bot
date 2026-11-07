from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from rsi_cross_swing_bot.storage.store import TradeStore

ET = ZoneInfo("America/New_York")


def test_bot_position_from_fills_only(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = TradeStore(tmp_path / "t.sqlite3")
    now = datetime(2024, 6, 3, 15, 59, tzinfo=ET)
    store.record_fill(
        order_ref="rsi-cross:entry",
        signal_id="rsi-cross-2024-06-03-entry-oversold",
        symbol="TQQQ",
        side="BUY",
        quantity=199,
        price=50.0,
        ts=now,
    )
    pos = store.bot_position("TQQQ")
    assert pos.quantity == 199

    store.record_fill(
        order_ref="rsi-cross:exit",
        signal_id="rsi-cross-2024-06-04-exit",
        symbol="TQQQ",
        side="SELL",
        quantity=199,
        price=55.0,
        ts=now,
    )
    assert store.bot_position("TQQQ").quantity == 0


def test_partial_buy_later_sells_partial(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = TradeStore(tmp_path / "t.sqlite3")
    now = datetime(2024, 6, 3, 15, 59, tzinfo=ET)
    store.record_fill(
        order_ref="rsi-cross:entry",
        signal_id="rsi-cross-2024-06-03-entry-oversold",
        symbol="TQQQ",
        side="BUY",
        quantity=50,
        price=50.0,
        ts=now,
    )
    assert store.bot_position("TQQQ").quantity == 50


def test_empty_ledger_stays_flat(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = TradeStore(tmp_path / "t.sqlite3")
    assert store.bot_position("TQQQ").quantity == 0
