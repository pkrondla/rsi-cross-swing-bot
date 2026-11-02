"""Hash strategy config so every decision records which rules produced it."""

from __future__ import annotations

import hashlib
import json

from qqq_rsi_bot.config.settings import StrategyConfig


def strategy_hash(cfg: StrategyConfig) -> str:
    payload = json.dumps(cfg.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
