from __future__ import annotations

from datetime import date
from pathlib import Path

from rsi_cross_swing_bot.runtime.day_stop import is_stopped
from rsi_cross_swing_bot.runtime.telegram_commands import (
    ControlContext,
    SleeveView,
    handle_control_command,
)
from rsi_cross_swing_bot.runtime.watchlist import SymbolState, load_entries, save_state


def _ctrl(tmp_path: Path, replies: list[str]) -> ControlContext:
    view = SleeveView(
        sleeve_id="tqqq",
        data_dir=tmp_path / "tqqq",
        status_text=lambda: "ok",
        positions_text=lambda: "flat",
        get_allocated=lambda: 10_000.0,
        risk_min=100,
        risk_max=1_000_000,
    )
    view.data_dir.mkdir(parents=True, exist_ok=True)
    return ControlContext(
        sleeves={"tqqq": view},
        reply=replies.append,
        today=lambda: date(2024, 6, 3),
        version="0.2.0",
    )


def test_stop_and_allocation(tmp_path: Path) -> None:
    replies: list[str] = []
    ctx = _ctrl(tmp_path, replies)
    handle_control_command("/stop tqqq", ctx)
    assert is_stopped(ctx.sleeves["tqqq"].data_dir, date(2024, 6, 3))
    handle_control_command("/allocation tqqq 20000", ctx)
    assert any("20000" in r for r in replies)
    handle_control_command("/help", ctx)
    assert any("Commands" in r for r in replies)


def _watch_ctrl(tmp_path: Path, replies: list[str]) -> ControlContext:
    ctx = _ctrl(tmp_path, replies)
    ctx.watch_dir = tmp_path / "watch"
    return ctx


def test_watch_add_list_mark_remove(tmp_path: Path) -> None:
    replies: list[str] = []
    ctx = _watch_ctrl(tmp_path, replies)

    handle_control_command("/watch", ctx)
    assert replies[-1].startswith("[watch] watchlist empty")

    handle_control_command("/watch add aapl", ctx)
    assert replies[-1] == "[watch] AAPL added"
    handle_control_command("/watch add AAPL", ctx)
    assert "already" in replies[-1]

    handle_control_command("/watch list", ctx)
    assert "AAPL flat" in replies[-1]

    handle_control_command("/watch long aapl", ctx)
    assert replies[-1] == "[watch] AAPL marked long"
    handle_control_command("/watch", ctx)
    assert replies[-1] == "[watch] AAPL long"

    handle_control_command("/watch flat AAPL", ctx)
    assert replies[-1] == "[watch] AAPL marked flat"
    handle_control_command("/watch", ctx)
    assert replies[-1] == "[watch] AAPL flat"

    handle_control_command("/watch remove AAPL", ctx)
    assert replies[-1] == "[watch] AAPL removed"
    handle_control_command("/watch remove AAPL", ctx)
    assert "not on the watchlist" in replies[-1]


def test_watch_usage_and_invalid_symbol(tmp_path: Path) -> None:
    replies: list[str] = []
    ctx = _watch_ctrl(tmp_path, replies)

    handle_control_command("/watch add", ctx)
    assert replies[-1].startswith("usage:")
    handle_control_command("/watch bogus AAPL", ctx)
    assert replies[-1].startswith("usage:")
    handle_control_command("/watch add !!!", ctx)
    assert "invalid symbol" in replies[-1]
    handle_control_command("/watch long MSFT", ctx)
    assert "not on the watchlist" in replies[-1]


def test_watch_list_shows_last_alert_state(tmp_path: Path) -> None:
    replies: list[str] = []
    ctx = _watch_ctrl(tmp_path, replies)
    handle_control_command("/watch add AAPL", ctx)
    (entry,) = load_entries(ctx.watch_dir)
    save_state(
        ctx.watch_dir,
        {
            "AAPL": SymbolState(
                added=entry.added,
                long=True,
                position_ts="2024-06-03T20:00:00+00:00",
                last_bullish_day="2024-06-03",
            )
        },
    )
    handle_control_command("/watch", ctx)
    assert replies[-1] == "[watch] AAPL long last buy=2024-06-03"


def test_watch_only_control_has_no_sleeves(tmp_path: Path) -> None:
    replies: list[str] = []
    ctx = ControlContext(
        sleeves={},
        reply=replies.append,
        today=lambda: date(2024, 6, 3),
        version="0.2.0",
        watch_dir=tmp_path / "watch",
    )
    handle_control_command("/sleeves", ctx)
    assert replies[-1] == "sleeves: (none; watch-only)"
    for cmd in ("/status", "/flatten all", "/allocation tqqq 100"):
        handle_control_command(cmd, ctx)
        assert "no sleeves configured" in replies[-1]
    handle_control_command("/watch add AAPL", ctx)
    assert replies[-1] == "[watch] AAPL added"
