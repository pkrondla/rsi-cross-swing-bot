from __future__ import annotations

from datetime import date
from pathlib import Path

from rsi_cross_swing_bot.runtime.day_stop import is_stopped
from rsi_cross_swing_bot.runtime.telegram_commands import (
    ControlContext,
    SleeveView,
    handle_control_command,
)


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
