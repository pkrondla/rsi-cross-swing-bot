from __future__ import annotations

from datetime import date
from pathlib import Path

from qqq_rsi_bot.runtime.day_stop import is_stopped
from qqq_rsi_bot.runtime.telegram_commands import CommandContext, handle_command


def test_stop_and_allocation(tmp_path: Path) -> None:
    replies: list[str] = []
    ctx = CommandContext(
        data_dir=tmp_path,
        reply=replies.append,
        status_text=lambda: "ok",
        positions_text=lambda: "flat",
        flatten=lambda: "flat",
        get_allocated=lambda: 10_000.0,
        risk_min=100,
        risk_max=1_000_000,
        today=lambda: date(2024, 6, 3),
    )
    handle_command("/stop", ctx)
    assert is_stopped(tmp_path, date(2024, 6, 3))
    handle_command("/allocation 20000", ctx)
    assert any("20000" in r for r in replies)
    handle_command("/help", ctx)
    assert any("Commands" in r for r in replies)
