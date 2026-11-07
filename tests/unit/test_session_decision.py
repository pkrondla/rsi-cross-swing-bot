from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from rsi_cross_swing_bot.adapters.ib.client import FakeIbClient
from rsi_cross_swing_bot.config.settings import (
    AppConfig,
    RiskConfig,
    RuntimeConfig,
    Settings,
    StrategyConfig,
)
from rsi_cross_swing_bot.core.clock import FixedClock
from rsi_cross_swing_bot.core.models import Bar, Quote, SignalAction
from rsi_cross_swing_bot.execution.dry_run_venue import DryRunVenue
from rsi_cross_swing_bot.execution.order_manager import OrderManager
from rsi_cross_swing_bot.risk.gate import RiskGate
from rsi_cross_swing_bot.runtime.notify import NullNotifier
from rsi_cross_swing_bot.runtime.session import TradingSession
from rsi_cross_swing_bot.storage.store import TradeStore

ET = ZoneInfo("America/New_York")


def _bars_for_cross(n: int = 250) -> list[Bar]:
    closes: list[float] = []
    price = 100.0
    for _ in range(n - 5):
        price *= 0.999
        closes.append(price)
    for bump in (1.01, 1.015, 1.02, 1.025, 1.03):
        price *= bump
        closes.append(price)
    day = date(2023, 1, 3)
    bars: list[Bar] = []
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(Bar(day, c, c, c, c))
        day += timedelta(days=1)
    return bars


def test_decision_buys_only_bot_qty(tmp_path: Path) -> None:
    bars = _bars_for_cross()
    bars = list(bars)
    bars[-1] = Bar(date(2024, 6, 3), bars[-1].open, bars[-1].high, bars[-1].low, bars[-1].close)
    clock = FixedClock(datetime(2024, 6, 3, 15, 58, tzinfo=ET))
    broker = FakeIbClient(
        bars=bars,
        quotes={
            "TQQQ": Quote("TQQQ", 50.0, 50.1, 50.05, False, clock.now()),
            "QQQ": Quote("QQQ", 400.0, 400.1, 400.05, False, clock.now()),
        },
        cash=100_000,
        positions={"TQQQ": 500},
        accounts=["DU1"],
    )
    settings = Settings.model_validate(
        {
            "IB_ACCOUNT": "DU1",
            "LIVE_MODE": "paper",
            "LIVE_ARMED": False,
            "DRY_RUN": True,
            "ALLOCATED_USD": 10_000,
            "DATA_DIR": str(tmp_path),
        }
    )
    cfg = AppConfig(
        strategy=StrategyConfig(ema_period=50, history_days=400),
        runtime=RuntimeConfig(),
        risk=RiskConfig(allocated_usd=10_000),
    )
    store = TradeStore(tmp_path / "t.sqlite3")
    risk = RiskGate(allocated_usd=10_000, slippage_bps=10)
    orders = OrderManager(DryRunVenue(broker.quote), store)
    session = TradingSession(
        settings=settings,
        cfg=cfg,
        clock=clock,
        data=broker,
        store=store,
        risk=risk,
        orders=orders,
        notifier=NullNotifier(),
        data_dir=tmp_path,
        allocated_usd=10_000,
    )
    decision = session.run_decision()
    assert decision is not None
    if decision.action is SignalAction.ENTER:
        pos = store.bot_position("TQQQ")
        assert pos.quantity == 199
        assert broker.place_calls == []
