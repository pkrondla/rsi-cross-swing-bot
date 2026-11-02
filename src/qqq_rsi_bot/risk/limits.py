"""Allocated-USD sleeve limits (YAML / env / Telegram override)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qqq_rsi_bot.config.settings import RiskConfig


@dataclass(frozen=True, slots=True)
class AllocationLimits:
    allocated_usd: float
    min_allocated_usd: float
    max_allocated_usd: float
    min_shares: int


def resolve_allocation(
    risk: RiskConfig,
    env_value: float | None = None,
    override_path: Path | None = None,
) -> float:
    """Layers: YAML, then env, then Telegram override file. Later layers win."""
    value = float(risk.allocated_usd)
    if env_value is not None:
        value = float(env_value)
    if override_path is not None and override_path.exists():
        import json

        raw = json.loads(override_path.read_text(encoding="utf-8"))
        if "allocated_usd" in raw:
            value = float(raw["allocated_usd"])
    if value < risk.min_allocated_usd or value > risk.max_allocated_usd:
        raise ValueError(
            f"allocated_usd {value} outside [{risk.min_allocated_usd}, {risk.max_allocated_usd}]"
        )
    return value


def save_allocation_override(path: Path, allocated_usd: float) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"allocated_usd": allocated_usd}, indent=2) + "\n",
        encoding="utf-8",
    )
