"""Per-day /stop flag remembered across restarts."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def stop_path(data_dir: Path) -> Path:
    return data_dir / "DAY_STOP.json"


def is_stopped(data_dir: Path, day: date) -> bool:
    path = stop_path(data_dir)
    if not path.exists():
        return False
    raw = json.loads(path.read_text(encoding="utf-8"))
    return str(raw.get("date", "")) == day.isoformat()


def set_stopped(data_dir: Path, day: date, stopped: bool) -> None:
    path = stop_path(data_dir)
    if not stopped:
        if path.exists():
            path.unlink()
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": day.isoformat()}) + "\n", encoding="utf-8")
