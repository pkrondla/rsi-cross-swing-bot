from __future__ import annotations

from pathlib import Path

import pytest

from qqq_rsi_bot import __version__
from qqq_rsi_bot.config.fingerprint import strategy_hash
from qqq_rsi_bot.config.settings import RiskConfig, StrategyConfig, load_config
from qqq_rsi_bot.risk.limits import resolve_allocation, save_allocation_override


def test_version_matches_pyproject() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in text


def test_load_config() -> None:
    cfg = load_config()
    assert cfg.strategy.signal_symbol == "QQQ"
    assert cfg.strategy.execution_symbol == "TQQQ"
    assert cfg.runtime.decision_time == "15:58"


def test_strategy_hash_stable() -> None:
    a = strategy_hash(StrategyConfig())
    b = strategy_hash(StrategyConfig())
    assert a == b
    assert len(a) == 16


def test_allocation_override_wins(tmp_path: Path) -> None:
    risk = RiskConfig(allocated_usd=10_000, min_allocated_usd=100, max_allocated_usd=1_000_000)
    path = tmp_path / "LIMITS_OVERRIDE.json"
    save_allocation_override(path, 25_000)
    assert resolve_allocation(risk, env_value=15_000, override_path=path) == 25_000


def test_allocation_out_of_range() -> None:
    risk = RiskConfig(allocated_usd=10_000, min_allocated_usd=100, max_allocated_usd=1_000)
    with pytest.raises(ValueError):
        resolve_allocation(risk, env_value=5_000)
