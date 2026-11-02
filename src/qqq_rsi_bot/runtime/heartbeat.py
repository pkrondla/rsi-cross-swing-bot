"""Heartbeat file for the watchdog."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def write_heartbeat(path: Path, now: datetime, note: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"ts": now.isoformat(), "note": note}) + "\n",
        encoding="utf-8",
    )


def read_heartbeat(path: Path) -> datetime | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return datetime.fromisoformat(str(raw["ts"]))
