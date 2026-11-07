"""Optional dry-run override file (Telegram /dryrun)."""

from __future__ import annotations

import json
from pathlib import Path

DRY_RUN_FILE = "DRY_RUN_OVERRIDE.json"


def read_dry_run_override(data_dir: Path) -> bool | None:
    path = data_dir / DRY_RUN_FILE
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(raw, dict) and "dry_run" in raw:
        return bool(raw["dry_run"])
    return None


def write_dry_run_override(data_dir: Path, dry_run: bool) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / DRY_RUN_FILE).write_text(
        json.dumps({"dry_run": dry_run}, indent=2),
        encoding="utf-8",
    )


def effective_dry_run(data_dir: Path, configured: bool) -> bool:
    override = read_dry_run_override(data_dir)
    return configured if override is None else override
