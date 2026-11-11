from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rsi_cross_swing_bot.app.telegram_control import telegram_control
from rsi_cross_swing_bot.app.watchdog import watchdog
from rsi_cross_swing_bot.config.settings import (
    Settings,
    list_sleeve_ids,
    load_indicator_config,
    load_sleeve_map,
)
from rsi_cross_swing_bot.core.clock import ET
from rsi_cross_swing_bot.runtime.heartbeat import write_heartbeat


class _Notifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)


def _empty_sleeves(tmp_path: Path) -> Path:
    path = tmp_path / "sleeves.yaml"
    path.write_text("sleeves: {}\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("body", ["sleeves: {}\n", "sleeves:\n"])
def test_empty_sleeves_section_means_watch_only(tmp_path: Path, body: str) -> None:
    path = tmp_path / "sleeves.yaml"
    path.write_text(body, encoding="utf-8")
    assert load_sleeve_map(path) == {}
    assert list_sleeve_ids(path) == []


def test_sleeves_file_without_any_mapping_still_rejected(tmp_path: Path) -> None:
    path = tmp_path / "sleeves.yaml"
    path.write_text("other: 1\nnested: [1]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_sleeve_map(path)


def test_indicator_config_needs_no_sleeve() -> None:
    strategy, runtime = load_indicator_config()
    assert strategy.rsi_period == 14
    assert runtime.decision_time == "15:58"


def test_watch_client_id_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IB_CLIENT_ID", "17")
    monkeypatch.setenv("WATCH_IB_CLIENT_ID", "")
    assert Settings().watch_ib_client_id == 77
    monkeypatch.setenv("WATCH_IB_CLIENT_ID", "90")
    assert Settings().watch_ib_client_id == 90


def test_telegram_control_runs_with_no_sleeves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99")
    monkeypatch.setenv("SLEEVES_CONFIG_PATH", str(_empty_sleeves(tmp_path)))
    notifier = _Notifier()
    monkeypatch.setattr(
        "rsi_cross_swing_bot.app.telegram_control.poll_updates",
        lambda _t, _o: (1, [("99", "/watch add AAPL"), ("99", "/status")]),
    )
    monkeypatch.setattr(
        "rsi_cross_swing_bot.app.telegram_control.build_notifier", lambda _s: notifier
    )

    assert telegram_control(once=True, sleep_fn=lambda _: None) == 0
    assert "sleeves=(none; watch-only)" in notifier.messages[0]
    assert "[watch] AAPL added" in notifier.messages
    assert any("no sleeves configured" in m for m in notifier.messages)
    assert (tmp_path / "data" / "watchlist" / "watchlist.json").exists()


def test_watchdog_monitors_watch_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("HEALTHCHECK_URL", "")
    monkeypatch.setenv("SLEEVES_CONFIG_PATH", str(_empty_sleeves(tmp_path)))
    notifier = _Notifier()
    monkeypatch.setattr("rsi_cross_swing_bot.app.watchdog.build_notifier", lambda _s: notifier)
    hb = data / "watchlist" / "heartbeat.json"

    # No watch heartbeat yet: nothing to monitor.
    assert watchdog(once=True) == 0

    write_heartbeat(hb, datetime.now(ET) - timedelta(hours=3))
    assert watchdog(once=True) == 1
    assert any("WATCHDOG [watch]" in m for m in notifier.messages)

    write_heartbeat(hb, datetime.now(ET))
    assert watchdog(once=True) == 0
