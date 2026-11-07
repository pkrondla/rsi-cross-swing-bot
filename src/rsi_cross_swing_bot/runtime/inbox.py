"""Per-sleeve command inbox written by the Telegram control process."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INBOX_FILE = "inbox.json"


@dataclass(frozen=True, slots=True)
class InboxCommand:
    name: str
    payload: dict[str, Any]


def _path(data_dir: Path) -> Path:
    return data_dir / INBOX_FILE


def push_command(data_dir: Path, name: str, **payload: Any) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = _path(data_dir)
    existing: list[dict[str, Any]] = []
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("commands"), list):
            existing = list(raw["commands"])
    existing.append(
        {
            "name": name,
            "payload": payload,
            "ts": datetime.now(UTC).isoformat(),
        }
    )
    path.write_text(json.dumps({"commands": existing}, indent=2), encoding="utf-8")


def drain_commands(data_dir: Path) -> list[InboxCommand]:
    path = _path(data_dir)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        path.unlink(missing_ok=True)
        return []
    path.write_text(json.dumps({"commands": []}, indent=2), encoding="utf-8")
    out: list[InboxCommand] = []
    if not isinstance(raw, dict):
        return out
    for item in raw.get("commands", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        payload = item.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        out.append(InboxCommand(name=name, payload=payload))
    return out
