"""Wire settings, config, store, IB client and venues."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qqq_rsi_bot.adapters.ib.client import FakeIbClient, IbClient
from qqq_rsi_bot.config.settings import AppConfig, Settings, load_config, resolve_allocated_usd
from qqq_rsi_bot.execution.dry_run_venue import DryRunVenue
from qqq_rsi_bot.execution.ib_venue import IbVenue
from qqq_rsi_bot.execution.order_manager import OrderManager
from qqq_rsi_bot.execution.venue import ExecutionVenue
from qqq_rsi_bot.risk.gate import RiskGate
from qqq_rsi_bot.risk.limits import resolve_allocation
from qqq_rsi_bot.runtime.telegram_commands import OVERRIDE_FILE
from qqq_rsi_bot.storage.store import TradeStore


@dataclass
class AppContext:
    settings: Settings
    cfg: AppConfig
    data_dir: Path
    database_path: Path
    allocated_usd: float
    broker: IbClient | FakeIbClient
    venue: ExecutionVenue
    store: TradeStore
    risk: RiskGate
    orders: OrderManager


def load_context(*, fake: IbClient | FakeIbClient | None = None) -> AppContext:
    settings = Settings()
    cfg = load_config(
        settings.strategy_config_path,
        settings.runtime_config_path,
        settings.risk_config_path,
    )
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    allocated = resolve_allocation(
        cfg.risk,
        env_value=settings.allocated_usd,
        override_path=data_dir / OVERRIDE_FILE,
    )
    broker: IbClient | FakeIbClient
    if fake is not None:
        broker = fake
    else:
        broker = IbClient(settings.ib_host, settings.ib_port, settings.ib_client_id)

    if settings.dry_run:
        venue: ExecutionVenue = DryRunVenue(broker.quote)
    else:
        venue = IbVenue(broker, settings.ib_account)

    store = TradeStore(data_dir / "qqq_rsi.sqlite3")
    risk = RiskGate(
        allocated_usd=allocated,
        min_shares=cfg.risk.min_shares,
        slippage_bps=cfg.strategy.slippage_bps,
    )
    orders = OrderManager(venue, store)
    return AppContext(
        settings=settings,
        cfg=cfg,
        data_dir=data_dir,
        database_path=data_dir / "qqq_rsi.sqlite3",
        allocated_usd=allocated,
        broker=broker,
        venue=venue,
        store=store,
        risk=risk,
        orders=orders,
    )


def default_allocated(settings: Settings, cfg: AppConfig) -> float:
    return resolve_allocated_usd(settings, cfg.risk)
