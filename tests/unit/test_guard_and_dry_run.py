from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from qqq_rsi_bot.adapters.ib.client import FakeIbClient
from qqq_rsi_bot.config.settings import Settings
from qqq_rsi_bot.core.models import Quote
from qqq_rsi_bot.core.signal_id import order_ref
from qqq_rsi_bot.execution.dry_run_venue import DryRunVenue
from qqq_rsi_bot.execution.ib_venue import IbVenue
from qqq_rsi_bot.execution.models import OrderIntent
from qqq_rsi_bot.execution.order_manager import OrderManager
from qqq_rsi_bot.runtime.guard import SafetyError, assert_order_config
from qqq_rsi_bot.storage.store import TradeStore

ET = ZoneInfo("America/New_York")


def test_dry_run_never_calls_place_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []
    broker = FakeIbClient(
        quotes={
            "TQQQ": Quote(
                "TQQQ", 50.0, 50.1, 50.05, False, datetime(2024, 6, 3, 15, 58, tzinfo=ET)
            )
        },
        place_calls=calls,
    )
    store = TradeStore(tmp_path / "t.sqlite3")
    venue = DryRunVenue(broker.quote)
    om = OrderManager(venue, store)
    intent = OrderIntent(
        signal_id="qqq-rsi-2024-06-03-entry-oversold",
        symbol="TQQQ",
        side="BUY",
        quantity=10,
        limit_price=50.15,
        order_ref=order_ref("qqq-rsi-2024-06-03-entry-oversold"),
    )
    record = om.submit(intent, datetime(2024, 6, 3, 15, 58, tzinfo=ET))
    assert record.filled_qty == 10
    assert calls == []
    assert store.bot_position("TQQQ").quantity == 10


def test_ib_venue_records_place(tmp_path) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []
    broker = FakeIbClient(
        quotes={
            "TQQQ": Quote(
                "TQQQ", 50.0, 50.1, 50.05, False, datetime(2024, 6, 3, 15, 58, tzinfo=ET)
            )
        },
        place_calls=calls,
        accounts=["DU123"],
    )
    store = TradeStore(tmp_path / "t.sqlite3")
    venue = IbVenue(broker, "DU123")
    om = OrderManager(venue, store)
    intent = OrderIntent(
        signal_id="qqq-rsi-2024-06-03-entry-oversold",
        symbol="TQQQ",
        side="BUY",
        quantity=10,
        limit_price=50.15,
        order_ref=order_ref("qqq-rsi-2024-06-03-entry-oversold"),
    )
    om.submit(intent, datetime(2024, 6, 3, 15, 58, tzinfo=ET))
    assert len(calls) == 1
    assert store.bot_position("TQQQ").quantity == 10


def test_signal_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    broker = FakeIbClient(
        quotes={
            "TQQQ": Quote(
                "TQQQ", 50.0, 50.1, 50.05, False, datetime(2024, 6, 3, 15, 58, tzinfo=ET)
            )
        },
    )
    store = TradeStore(tmp_path / "t.sqlite3")
    om = OrderManager(DryRunVenue(broker.quote), store)
    intent = OrderIntent(
        signal_id="qqq-rsi-2024-06-03-entry-oversold",
        symbol="TQQQ",
        side="BUY",
        quantity=10,
        limit_price=50.15,
        order_ref=order_ref("qqq-rsi-2024-06-03-entry-oversold"),
    )
    now = datetime(2024, 6, 3, 15, 58, tzinfo=ET)
    om.submit(intent, now)
    om.submit(intent, now)
    assert store.bot_position("TQQQ").quantity == 10


def test_live_on_paper_port_fails() -> None:
    settings = Settings.model_validate(
        {
            "LIVE_MODE": "live",
            "LIVE_ARMED": True,
            "DRY_RUN": False,
            "IB_ACCOUNT": "U1234567",
            "IB_PORT": 7497,
        }
    )
    with pytest.raises(SafetyError):
        assert_order_config(settings)


def test_live_on_du_account_fails() -> None:
    settings = Settings.model_validate(
        {
            "LIVE_MODE": "live",
            "LIVE_ARMED": True,
            "DRY_RUN": False,
            "IB_ACCOUNT": "DU123456",
            "IB_PORT": 4001,
        }
    )
    with pytest.raises(SafetyError):
        assert_order_config(settings)
