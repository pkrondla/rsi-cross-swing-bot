from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rsi_cross_swing_bot.adapters.ib.client import FakeIbClient
from rsi_cross_swing_bot.app.context import load_context
from rsi_cross_swing_bot.app.serve import serve
from rsi_cross_swing_bot.config.settings import Settings
from rsi_cross_swing_bot.core.models import Quote
from rsi_cross_swing_bot.execution.dry_run_venue import DryRunVenue
from rsi_cross_swing_bot.execution.ib_venue import IbVenue
from rsi_cross_swing_bot.execution.models import OrderIntent, OrderRecord, OrderStatus
from rsi_cross_swing_bot.execution.order_manager import OrderManager
from rsi_cross_swing_bot.runtime.arming import configured_mode_label
from rsi_cross_swing_bot.runtime.calendar import next_wake
from rsi_cross_swing_bot.runtime.guard import SafetyError, assert_order_config
from rsi_cross_swing_bot.runtime.notify import TelegramNotifier, build_notifier
from rsi_cross_swing_bot.runtime.telegram_commands import poll_updates
from rsi_cross_swing_bot.storage.store import TradeStore

ET = ZoneInfo("America/New_York")


def test_arming_labels() -> None:
    assert "dry-run" in configured_mode_label(Settings.model_validate({"DRY_RUN": True}))
    disarmed = Settings.model_validate(
        {"DRY_RUN": False, "LIVE_ARMED": False, "IB_ACCOUNT": "DU1", "IB_PORT": 4002}
    )
    assert "disarmed" in configured_mode_label(disarmed)
    assert "armed" in configured_mode_label(
        Settings.model_validate(
            {
                "DRY_RUN": False,
                "LIVE_ARMED": True,
                "LIVE_MODE": "paper",
                "IB_ACCOUNT": "DU1",
                "IB_PORT": 4002,
            }
        )
    )


def test_guard_paper_and_live_ok() -> None:
    assert_order_config(
        Settings.model_validate(
            {
                "DRY_RUN": False,
                "LIVE_ARMED": True,
                "LIVE_MODE": "paper",
                "IB_ACCOUNT": "DU123",
                "IB_PORT": 4002,
            }
        )
    )
    assert_order_config(
        Settings.model_validate(
            {
                "DRY_RUN": False,
                "LIVE_ARMED": True,
                "LIVE_MODE": "live",
                "IB_ACCOUNT": "U1234567",
                "IB_PORT": 4001,
            }
        )
    )
    with pytest.raises(SafetyError):
        assert_order_config(
            Settings.model_validate(
                {"DRY_RUN": False, "LIVE_ARMED": True, "LIVE_MODE": "paper", "IB_ACCOUNT": ""}
            )
        )


def test_telegram_notifier_and_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp:
        def read(self) -> bytes:
            return b'{"ok":true}'

        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: Resp(),
    )
    TelegramNotifier("tok", "1").send("hi")
    settings = Settings.model_validate(
        {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "1"}
    )
    assert build_notifier(settings)

    class PollResp:
        def read(self) -> bytes:
            return (
                b'{"ok":true,"result":[{"update_id":5,"message":'
                b'{"text":"/status","chat":{"id":1}}}]}'
            )

        def __enter__(self) -> PollResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: PollResp())
    offset, messages = poll_updates("tok", 0)
    assert offset == 6
    assert messages == [("1", "/status")]


def test_order_manager_cancel(tmp_path: Path) -> None:
    broker = FakeIbClient(
        quotes={
            "TQQQ": Quote("TQQQ", 50, 50.1, 50, False, datetime(2024, 6, 3, 15, 58, tzinfo=ET))
        }
    )
    store = TradeStore(tmp_path / "t.sqlite3")
    om = OrderManager(DryRunVenue(broker.quote), store)
    intent = OrderIntent("sig", "TQQQ", "BUY", 1, 50.1, "rsi-cross:sig")
    rec = om.submit(intent, datetime(2024, 6, 3, 15, 58, tzinfo=ET))
    om.cancel(rec, datetime(2024, 6, 3, 15, 59, tzinfo=ET))
    DryRunVenue(broker.quote).cancel(rec)
    DryRunVenue(broker.quote).poll(rec)


def test_ib_venue_empty_broker_id() -> None:
    broker = FakeIbClient(
        quotes={
            "TQQQ": Quote("TQQQ", 50, 50.1, 50, False, datetime(2024, 6, 3, 15, 58, tzinfo=ET))
        }
    )
    venue = IbVenue(broker, "DU1")
    intent = OrderIntent("sig", "TQQQ", "BUY", 1, 50.1, "rsi-cross:sig")
    rec = OrderRecord(intent, status=OrderStatus.NEW, broker_order_id="")
    assert venue.cancel(rec) is rec
    assert venue.poll(rec) is rec


def test_serve_with_telegram(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("IB_ACCOUNT", "DU123456")
    monkeypatch.setenv("ALLOCATED_USD", "10000")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99")
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("STRATEGY_CONFIG_PATH", str(repo / "config" / "strategy.yaml"))
    monkeypatch.setenv("RUNTIME_CONFIG_PATH", str(repo / "config" / "runtime.yaml"))
    monkeypatch.setenv("RISK_CONFIG_PATH", str(repo / "config" / "risk.yaml"))
    monkeypatch.setenv("SLEEVES_CONFIG_PATH", str(repo / "config" / "sleeves.yaml"))
    monkeypatch.setenv("SLEEVE", "tqqq")
    broker = FakeIbClient(
        bars=[],
        quotes={
            "TQQQ": Quote("TQQQ", 50, 50.1, 50, False, datetime(2024, 6, 3, 15, 58, tzinfo=ET)),
            "QQQ": Quote("QQQ", 400, 400.1, 400, False, datetime(2024, 6, 3, 15, 58, tzinfo=ET)),
        },
        accounts=["DU123456"],
    )
    ctx = load_context(fake=broker)
    # Telegram polling lives in rsi-bot telegram; serve only drains inbox + trades.
    assert serve(ctx, once=True, sleep_fn=lambda _: None) == 0


def test_next_wake_paths() -> None:
    # before open
    w = next_wake(datetime(2024, 6, 3, 8, 0, tzinfo=ET))
    assert w.hour == 9
    # weekend -> next trading day
    w2 = next_wake(datetime(2024, 6, 1, 12, 0, tzinfo=ET))
    assert w2.weekday() < 5
    # after decision
    w3 = next_wake(datetime(2024, 6, 3, 16, 5, tzinfo=ET))
    assert w3.date() > date(2024, 6, 3)


def test_settings_validators() -> None:
    s = Settings.model_validate(
        {
            "ALLOCATED_USD": "",
            "TELEGRAM_CHAT_ID": " 123 ",
            "TELEGRAM_BOT_TOKEN": " tok \n",
        }
    )
    assert s.allocated_usd is None
    assert s.telegram_chat_id == "123"
