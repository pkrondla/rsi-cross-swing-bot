from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rsi_cross_swing_bot.adapters.ib.client import FakeIbClient
from rsi_cross_swing_bot.app.context import load_context, refresh_venue
from rsi_cross_swing_bot.app.serve import flatten_bot_qty, serve
from rsi_cross_swing_bot.app.telegram_control import telegram_control
from rsi_cross_swing_bot.config.settings import list_sleeve_ids, load_config, load_sleeve_map
from rsi_cross_swing_bot.core.models import EntryReason, Quote
from rsi_cross_swing_bot.core.signal_id import entry_signal_id, exit_signal_id
from rsi_cross_swing_bot.execution.dry_run_venue import DryRunVenue
from rsi_cross_swing_bot.runtime.dry_run_switch import (
    effective_dry_run,
    read_dry_run_override,
    write_dry_run_override,
)
from rsi_cross_swing_bot.runtime.inbox import drain_commands, push_command
from rsi_cross_swing_bot.runtime.telegram_commands import poll_updates

ET = ZoneInfo("America/New_York")


def test_sleeve_map_has_tqqq_and_goog() -> None:
    sleeves = load_sleeve_map()
    assert set(sleeves) >= {"tqqq", "goog"}
    assert sleeves["tqqq"].execution_symbol == "TQQQ"
    assert sleeves["goog"].signal_symbol == "GOOG"
    assert "tqqq" in list_sleeve_ids()


def test_load_config_goog_sleeve() -> None:
    cfg = load_config(sleeve_id="goog")
    assert cfg.strategy.sleeve_id == "goog"
    assert cfg.strategy.execution_symbol == "GOOG"
    assert "goog" in cfg.strategy.order_ref_prefix


def test_signal_ids_include_sleeve() -> None:
    day = date(2024, 6, 3)
    assert "tqqq" in entry_signal_id(day, EntryReason.OVERSOLD, sleeve_id="tqqq")
    assert "goog" in exit_signal_id(day, sleeve_id="goog")


def test_inbox_push_drain(tmp_path: Path) -> None:
    push_command(tmp_path, "flatten")
    push_command(tmp_path, "dryrun", value=True)
    cmds = drain_commands(tmp_path)
    assert [c.name for c in cmds] == ["flatten", "dryrun"]
    assert cmds[1].payload["value"] is True
    assert drain_commands(tmp_path) == []
    bad = tmp_path / "inbox.json"
    bad.write_text("not-json", encoding="utf-8")
    assert drain_commands(tmp_path) == []
    bad.write_text(
        '{"commands": [null, {"name": ""}, {"name": "x", "payload": 1}]}',
        encoding="utf-8",
    )
    drained = drain_commands(tmp_path)
    assert len(drained) == 1 and drained[0].name == "x"


def test_dry_run_switch(tmp_path: Path) -> None:
    assert read_dry_run_override(tmp_path) is None
    assert effective_dry_run(tmp_path, True) is True
    write_dry_run_override(tmp_path, False)
    assert read_dry_run_override(tmp_path) is False
    assert effective_dry_run(tmp_path, True) is False
    (tmp_path / "DRY_RUN_OVERRIDE.json").write_text("{bad", encoding="utf-8")
    assert read_dry_run_override(tmp_path) is None
    (tmp_path / "DRY_RUN_OVERRIDE.json").write_text('{"other": 1}', encoding="utf-8")
    assert read_dry_run_override(tmp_path) is None


def test_serve_drains_flatten_inbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("IB_ACCOUNT", "DU123456")
    monkeypatch.setenv("ALLOCATED_USD", "10000")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("SLEEVE", "tqqq")
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("SLEEVES_CONFIG_PATH", str(repo / "config" / "sleeves.yaml"))
    as_of = datetime(2024, 6, 3, 15, 58, tzinfo=ET)
    broker = FakeIbClient(
        bars=[],
        quotes={
            "TQQQ": Quote("TQQQ", 50, 50.1, 50, False, as_of),
            "QQQ": Quote("QQQ", 400, 400.1, 400, False, as_of),
        },
        positions={"TQQQ": 10},
        accounts=["DU123456"],
    )
    ctx = load_context(fake=broker)
    ctx.store.record_fill(
        order_ref="rsi-cross:tqqq:x",
        signal_id="rsi-cross-tqqq-2024-06-03-entry-oversold",
        symbol="TQQQ",
        side="BUY",
        quantity=10,
        price=50.0,
        ts=as_of,
    )
    push_command(ctx.data_dir, "flatten")
    push_command(ctx.data_dir, "dryrun", value=True)
    push_command(ctx.data_dir, "reconcile")
    push_command(ctx.data_dir, "unknown")
    assert serve(ctx, once=True, sleep_fn=lambda _: None) == 0
    assert isinstance(ctx.venue, DryRunVenue)
    msg = flatten_bot_qty(ctx)
    assert msg


def test_refresh_venue_respects_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("LIVE_ARMED", "true")
    monkeypatch.setenv("LIVE_MODE", "paper")
    monkeypatch.setenv("IB_ACCOUNT", "DU1")
    monkeypatch.setenv("SLEEVE", "tqqq")
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("SLEEVES_CONFIG_PATH", str(repo / "config" / "sleeves.yaml"))
    broker = FakeIbClient(
        bars=[],
        quotes={"TQQQ": Quote("TQQQ", 1, 1, 1, False, datetime.now(ET))},
        accounts=["DU1"],
    )
    ctx = load_context(fake=broker)
    write_dry_run_override(ctx.data_dir, True)
    refresh_venue(ctx)
    assert isinstance(ctx.venue, DryRunVenue)


def test_telegram_control_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99")
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("SLEEVES_CONFIG_PATH", str(repo / "config" / "sleeves.yaml"))

    def fake_poll(token: str, offset: int) -> tuple[int, list[tuple[str, str]]]:
        return 2, [("99", "/sleeves"), ("99", "/status all")]

    monkeypatch.setattr(
        "rsi_cross_swing_bot.app.telegram_control.poll_updates", fake_poll
    )
    monkeypatch.setattr(
        "rsi_cross_swing_bot.app.telegram_control.build_notifier",
        lambda _s: type("N", (), {"send": staticmethod(lambda _t: None)})(),
    )
    assert telegram_control(once=True, sleep_fn=lambda _: None) == 0


def test_poll_updates_handles_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def boom(*_a, **_k):  # noqa: ANN001
        raise urllib.error.URLError("down")

    monkeypatch.setattr(
        "rsi_cross_swing_bot.runtime.telegram_commands.urllib.request.urlopen", boom
    )
    offset, msgs = poll_updates("tok", 0)
    assert offset == 0
    assert msgs == []
