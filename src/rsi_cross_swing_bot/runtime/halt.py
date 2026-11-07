"""Persistent halt flag (position mismatch, etc.)."""

from __future__ import annotations

import json
from pathlib import Path


def halt_path(data_dir: Path) -> Path:
    return data_dir / "HALT.json"


def is_halted(data_dir: Path) -> bool:
    return halt_path(data_dir).exists()


def set_halt(data_dir: Path, reason: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    halt_path(data_dir).write_text(
        json.dumps({"reason": reason}) + "\n", encoding="utf-8"
    )


def clear_halt(data_dir: Path) -> None:
    path = halt_path(data_dir)
    if path.exists():
        path.unlink()


def halt_reason(data_dir: Path) -> str:
    path = halt_path(data_dir)
    if not path.exists():
        return ""
    return str(json.loads(path.read_text(encoding="utf-8")).get("reason", ""))
