"""Runtime settings (environment) and typed YAML config."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_PROJECT_ROOT / ".env", _PROJECT_ROOT / "config" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    sleeve: str = Field(default="tqqq", alias="SLEEVE")
    ib_host: str = Field(default="127.0.0.1", alias="IB_HOST")
    ib_port: int = Field(default=4002, alias="IB_PORT")
    ib_client_id: int | None = Field(default=None, alias="IB_CLIENT_ID")
    watch_ib_client_id: int = Field(default=77, gt=0, alias="WATCH_IB_CLIENT_ID")
    ib_account: str = Field(default="", alias="IB_ACCOUNT")
    allocated_usd: float | None = Field(default=None, alias="ALLOCATED_USD")
    live_mode: Literal["paper", "live"] = Field(default="paper", alias="LIVE_MODE")
    live_armed: bool = Field(default=False, alias="LIVE_ARMED")
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    telegram_bot_token: SecretStr = Field(default=SecretStr(""), alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    healthcheck_url: str = Field(default="", alias="HEALTHCHECK_URL")
    strategy_config_path: Path = Field(
        default=Path("config/strategy.yaml"), alias="STRATEGY_CONFIG_PATH"
    )
    runtime_config_path: Path = Field(
        default=Path("config/runtime.yaml"), alias="RUNTIME_CONFIG_PATH"
    )
    risk_config_path: Path = Field(default=Path("config/risk.yaml"), alias="RISK_CONFIG_PATH")
    sleeves_config_path: Path = Field(
        default=Path("config/sleeves.yaml"), alias="SLEEVES_CONFIG_PATH"
    )

    @field_validator("allocated_usd", mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("ib_client_id", mode="before")
    @classmethod
    def _empty_client_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("watch_ib_client_id", mode="before")
    @classmethod
    def _empty_watch_client_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return 77
        return value

    @field_validator("telegram_chat_id", mode="before")
    @classmethod
    def _strip_chat_id(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        text = value.strip().strip('"').strip("'")
        try:
            return str(int(text)) if text else ""
        except ValueError:
            return text

    @field_validator("telegram_bot_token", mode="before")
    @classmethod
    def _strip_bot_token(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            return value.strip().strip('"').strip("'").replace("\\n", "").replace("\\r", "")
        return value

    @field_validator("sleeve", mode="before")
    @classmethod
    def _strip_sleeve(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() or "tqqq"
        return value

    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token.get_secret_value() and self.telegram_chat_id)


class SleeveConfig(BaseModel):
    signal_symbol: str
    execution_symbol: str
    order_ref_prefix: str
    ib_client_id: int = Field(gt=0)
    allocated_usd: float = Field(default=10_000, gt=0)


class StrategyConfig(BaseModel):
    signal_symbol: str = "QQQ"
    execution_symbol: str = "TQQQ"
    rsi_period: int = Field(default=14, gt=0)
    rsi_ma_period: int = Field(default=14, gt=0)
    ema_period: int = Field(default=200, gt=0)
    oversold_rsi_max: float = Field(default=50.0, gt=0, le=100)
    slippage_bps: float = Field(default=10.0, ge=0)
    order_ref_prefix: str = "rsi-cross:tqqq:"
    history_days: int = Field(default=1100, gt=200)
    sleeve_id: str = "tqqq"
    ib_client_id: int = Field(default=17, gt=0)


class RuntimeConfig(BaseModel):
    timezone: str = "America/New_York"
    session_open: str = "09:30"
    decision_time: str = "15:58"
    early_close_decision_time: str = "12:58"
    cancel_unfilled_at: str = "15:59:30"
    decision_deadline: str = "15:59:20"
    decision_retry_sec: int = Field(default=30, ge=1)
    hourly_from: str = "09:30"
    heartbeat_path: str = "heartbeat.json"


class RiskConfig(BaseModel):
    allocated_usd: float = Field(default=10_000, gt=0)
    min_allocated_usd: float = Field(default=100, gt=0)
    max_allocated_usd: float = Field(default=5_000_000, gt=0)
    min_shares: int = Field(default=1, ge=1)
    allow_margin: bool = False


class AppConfig(BaseModel):
    strategy: StrategyConfig
    runtime: RuntimeConfig
    risk: RiskConfig


def _load_yaml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping: {path}")
    return raw


def _resolve_config_path(path: Path | None, default_name: str) -> Path:
    if path is None:
        return _PROJECT_ROOT / "config" / default_name
    if path.is_absolute() and path.exists():
        return path
    if path.exists():
        return path
    fallback = _PROJECT_ROOT / "config" / default_name
    if fallback.exists():
        return fallback
    return path


def load_sleeve_map(path: Path | None = None) -> dict[str, SleeveConfig]:
    """Sleeves by id. An explicit empty `sleeves:` means watch-only (no trading)."""
    raw = _load_yaml(_resolve_config_path(path, "sleeves.yaml"))
    if "sleeves" in raw and raw["sleeves"] in (None, {}):
        return {}
    block = raw.get("sleeves", raw)
    if not isinstance(block, dict) or not block:
        raise ValueError("sleeves.yaml must define a 'sleeves' mapping (may be empty)")
    out: dict[str, SleeveConfig] = {}
    for key, value in block.items():
        if not isinstance(value, dict):
            raise ValueError(f"sleeve {key!r} must be a mapping")
        out[str(key).lower()] = SleeveConfig.model_validate(value)
    return out


def list_sleeve_ids(path: Path | None = None) -> list[str]:
    return sorted(load_sleeve_map(path).keys())


def load_config(
    strategy_path: Path | None = None,
    runtime_path: Path | None = None,
    risk_path: Path | None = None,
    *,
    sleeves_path: Path | None = None,
    sleeve_id: str = "tqqq",
) -> AppConfig:
    sleeve_id = sleeve_id.strip().lower()
    sleeves = load_sleeve_map(sleeves_path)
    if sleeve_id not in sleeves:
        known = ", ".join(sorted(sleeves))
        raise ValueError(f"unknown sleeve {sleeve_id!r}; known: {known}")
    sleeve = sleeves[sleeve_id]

    strategy_raw = _load_yaml(_resolve_config_path(strategy_path, "strategy.yaml"))
    # Legacy single-pair strategy.yaml may still list symbols; sleeve wins.
    strategy_raw.update(
        {
            "signal_symbol": sleeve.signal_symbol,
            "execution_symbol": sleeve.execution_symbol,
            "order_ref_prefix": sleeve.order_ref_prefix,
            "sleeve_id": sleeve_id,
            "ib_client_id": sleeve.ib_client_id,
        }
    )
    strategy = StrategyConfig.model_validate(strategy_raw)
    runtime = RuntimeConfig.model_validate(
        _load_yaml(_resolve_config_path(runtime_path, "runtime.yaml"))
    )
    risk_raw = _load_yaml(_resolve_config_path(risk_path, "risk.yaml"))
    if "allocated_usd" not in risk_raw:
        risk_raw["allocated_usd"] = sleeve.allocated_usd
    else:
        # Sleeve allocated_usd is the sleeve default; YAML risk still seeds min/max.
        risk_raw["allocated_usd"] = sleeve.allocated_usd
    risk = RiskConfig.model_validate(risk_raw)
    return AppConfig(strategy=strategy, runtime=runtime, risk=risk)


def load_indicator_config(
    strategy_path: Path | None = None, runtime_path: Path | None = None
) -> tuple[StrategyConfig, RuntimeConfig]:
    """Shared RSI/EMA periods and session times, independent of any sleeve."""
    strategy = StrategyConfig.model_validate(
        _load_yaml(_resolve_config_path(strategy_path, "strategy.yaml"))
    )
    runtime = RuntimeConfig.model_validate(
        _load_yaml(_resolve_config_path(runtime_path, "runtime.yaml"))
    )
    return strategy, runtime


def resolve_allocated_usd(settings: Settings, risk: RiskConfig) -> float:
    """Env ALLOCATED_USD wins over YAML when set."""
    if settings.allocated_usd is not None:
        return float(settings.allocated_usd)
    return float(risk.allocated_usd)


def resolve_ib_client_id(settings: Settings, strategy: StrategyConfig) -> int:
    if settings.ib_client_id is not None:
        return int(settings.ib_client_id)
    return int(strategy.ib_client_id)


def sleeve_data_dir(root: Path, sleeve_id: str) -> Path:
    return Path(root) / "sleeves" / sleeve_id.lower()
