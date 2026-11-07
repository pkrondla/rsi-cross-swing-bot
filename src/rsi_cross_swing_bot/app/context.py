"""Wire settings, config, store, IB client and venues for one sleeve."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rsi_cross_swing_bot.adapters.ib.client import FakeIbClient, IbClient
from rsi_cross_swing_bot.config.settings import (
    AppConfig,
    Settings,
    load_config,
    resolve_allocated_usd,
    resolve_ib_client_id,
    sleeve_data_dir,
)
from rsi_cross_swing_bot.execution.dry_run_venue import DryRunVenue
from rsi_cross_swing_bot.execution.ib_venue import IbVenue
from rsi_cross_swing_bot.execution.order_manager import OrderManager
from rsi_cross_swing_bot.execution.venue import ExecutionVenue
from rsi_cross_swing_bot.risk.gate import RiskGate
from rsi_cross_swing_bot.risk.limits import resolve_allocation
from rsi_cross_swing_bot.runtime.dry_run_switch import effective_dry_run
from rsi_cross_swing_bot.runtime.telegram_commands import OVERRIDE_FILE
from rsi_cross_swing_bot.storage.store import TradeStore

DB_NAME = "rsi_cross.sqlite3"


@dataclass
class AppContext:
    settings: Settings
    cfg: AppConfig
    sleeve_id: str
    data_dir: Path
    root_data_dir: Path
    database_path: Path
    allocated_usd: float
    ib_client_id: int
    broker: IbClient | FakeIbClient
    venue: ExecutionVenue
    store: TradeStore
    risk: RiskGate
    orders: OrderManager


def load_context(
    *,
    sleeve: str | None = None,
    fake: IbClient | FakeIbClient | None = None,
) -> AppContext:
    settings = Settings()
    sleeve_id = (sleeve or settings.sleeve).strip().lower()
    cfg = load_config(
        settings.strategy_config_path,
        settings.runtime_config_path,
        settings.risk_config_path,
        sleeves_path=settings.sleeves_config_path,
        sleeve_id=sleeve_id,
    )
    root_data_dir = Path(settings.data_dir)
    root_data_dir.mkdir(parents=True, exist_ok=True)
    data_dir = sleeve_data_dir(root_data_dir, sleeve_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    _maybe_migrate_legacy_db(root_data_dir, data_dir, sleeve_id)

    allocated = resolve_allocation(
        cfg.risk,
        env_value=settings.allocated_usd,
        override_path=data_dir / OVERRIDE_FILE,
    )
    client_id = resolve_ib_client_id(settings, cfg.strategy)
    broker: IbClient | FakeIbClient
    broker = fake if fake is not None else IbClient(settings.ib_host, settings.ib_port, client_id)

    dry_run = effective_dry_run(data_dir, settings.dry_run)
    venue = _make_venue(broker, settings, dry_run)
    db_path = data_dir / DB_NAME
    store = TradeStore(db_path)
    risk = RiskGate(
        allocated_usd=allocated,
        min_shares=cfg.risk.min_shares,
        slippage_bps=cfg.strategy.slippage_bps,
    )
    orders = OrderManager(venue, store)
    return AppContext(
        settings=settings,
        cfg=cfg,
        sleeve_id=sleeve_id,
        data_dir=data_dir,
        root_data_dir=root_data_dir,
        database_path=db_path,
        allocated_usd=allocated,
        ib_client_id=client_id,
        broker=broker,
        venue=venue,
        store=store,
        risk=risk,
        orders=orders,
    )


def refresh_venue(ctx: AppContext) -> None:
    """Re-bind venue/orders if Telegram /dryrun override changed."""
    dry_run = effective_dry_run(ctx.data_dir, ctx.settings.dry_run)
    ctx.venue = _make_venue(ctx.broker, ctx.settings, dry_run)
    ctx.orders = OrderManager(ctx.venue, ctx.store)


def _make_venue(
    broker: IbClient | FakeIbClient, settings: Settings, dry_run: bool
) -> ExecutionVenue:
    if dry_run:
        return DryRunVenue(broker.quote)
    return IbVenue(broker, settings.ib_account)


def _maybe_migrate_legacy_db(root: Path, sleeve_dir: Path, sleeve_id: str) -> None:
    """Move legacy single-DB files into the tqqq sleeve folder once."""
    if sleeve_id != "tqqq":
        return
    dest = sleeve_dir / DB_NAME
    if dest.exists():
        return
    for name in (DB_NAME, "qqq_rsi.sqlite3"):
        src = root / name
        if src.exists():
            sleeve_dir.mkdir(parents=True, exist_ok=True)
            src.replace(dest)
            return


def default_allocated(settings: Settings, cfg: AppConfig) -> float:
    return resolve_allocated_usd(settings, cfg.risk)
