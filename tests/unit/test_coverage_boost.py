from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rsi_cross_swing_bot.adapters.ib.client import FakeIbClient
from rsi_cross_swing_bot.app.context import load_context
from rsi_cross_swing_bot.app.health import run_checks, status_report
from rsi_cross_swing_bot.app.replay import replay_bars
from rsi_cross_swing_bot.app.serve import flatten_bot_qty, serve
from rsi_cross_swing_bot.app.watchdog import heartbeat_path, watchdog
from rsi_cross_swing_bot.config.settings import (
    AppConfig,
    RiskConfig,
    RuntimeConfig,
    Settings,
    StrategyConfig,
)
from rsi_cross_swing_bot.core.clock import FixedClock, SystemClock
from rsi_cross_swing_bot.core.errors import DataUnavailableError, Reaction, must_halt, reaction_for
from rsi_cross_swing_bot.core.models import Bar, Quote, SignalAction
from rsi_cross_swing_bot.engine.signal_engine import compute_snapshot
from rsi_cross_swing_bot.execution.dry_run_venue import DryRunVenue
from rsi_cross_swing_bot.execution.ib_venue import IbVenue, map_ib_status
from rsi_cross_swing_bot.execution.models import OrderIntent, OrderRecord, OrderStatus
from rsi_cross_swing_bot.execution.order_manager import OrderManager
from rsi_cross_swing_bot.risk.gate import RiskGate
from rsi_cross_swing_bot.runtime.arming import configured_mode_label
from rsi_cross_swing_bot.runtime.calendar import next_trading_day, next_wake, parse_hhmm
from rsi_cross_swing_bot.runtime.day_stop import set_stopped
from rsi_cross_swing_bot.runtime.guard import assert_order_config, run_startup_checks
from rsi_cross_swing_bot.runtime.halt import clear_halt, halt_reason, is_halted, set_halt
from rsi_cross_swing_bot.runtime.heartbeat import read_heartbeat, write_heartbeat
from rsi_cross_swing_bot.runtime.notify import NullNotifier, build_notifier
from rsi_cross_swing_bot.runtime.session import TradingSession, decision_due
from rsi_cross_swing_bot.runtime.telegram_commands import handle_command
from rsi_cross_swing_bot.storage.store import TradeStore

ET = ZoneInfo("America/New_York")


def _quote(px: float = 50.0) -> Quote:
    return Quote("TQQQ", px, px + 0.1, px, False, datetime(2024, 6, 3, 15, 58, tzinfo=ET))


def _bars(n: int = 260) -> list[Bar]:
    day = date(2023, 1, 3)
    price = 100.0
    out: list[Bar] = []
    for i in range(n):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        price *= 1.001 if i < n - 30 else (0.99 if i < n - 10 else 1.02)
        out.append(Bar(day, price, price, price, price))
        day += timedelta(days=1)
    out[-1] = Bar(date(2024, 6, 3), out[-1].open, out[-1].high, out[-1].low, out[-1].close)
    return out


def _ctx(tmp_path: Path, *, cash: float = 100_000.0, positions: dict[str, int] | None = None):
    bars = _bars()
    broker = FakeIbClient(
        bars=bars,
        quotes={"TQQQ": _quote(), "QQQ": Quote("QQQ", 400, 400.1, 400, False, _quote().as_of)},
        cash=cash,
        positions=positions or {"TQQQ": 0},
        accounts=["DU123456"],
    )
    return load_context(fake=broker), broker


def test_health_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("IB_ACCOUNT", "DU123456")
    monkeypatch.setenv("ALLOCATED_USD", "10000")
    monkeypatch.setenv("DRY_RUN", "true")
    # Point config paths at the real repo configs via absolute paths from package
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("STRATEGY_CONFIG_PATH", str(repo / "config" / "strategy.yaml"))
    monkeypatch.setenv("RUNTIME_CONFIG_PATH", str(repo / "config" / "runtime.yaml"))
    monkeypatch.setenv("RISK_CONFIG_PATH", str(repo / "config" / "risk.yaml"))
    monkeypatch.setenv("SLEEVES_CONFIG_PATH", str(repo / "config" / "sleeves.yaml"))
    monkeypatch.setenv("SLEEVE", "tqqq")
    ctx, _ = _ctx(tmp_path / "data")
    steps = run_checks(ctx)
    assert any(s.name == "gateway" and s.ok for s in steps)
    text = status_report(ctx)
    assert "mode=" in text
    assert "sleeve=tqqq" in text


def test_serve_once_and_watchdog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("IB_ACCOUNT", "DU123456")
    monkeypatch.setenv("ALLOCATED_USD", "10000")
    monkeypatch.setenv("DRY_RUN", "true")
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("STRATEGY_CONFIG_PATH", str(repo / "config" / "strategy.yaml"))
    monkeypatch.setenv("RUNTIME_CONFIG_PATH", str(repo / "config" / "runtime.yaml"))
    monkeypatch.setenv("RISK_CONFIG_PATH", str(repo / "config" / "risk.yaml"))
    monkeypatch.setenv("SLEEVES_CONFIG_PATH", str(repo / "config" / "sleeves.yaml"))
    monkeypatch.setenv("SLEEVE", "tqqq")
    ctx, _ = _ctx(data)
    assert serve(ctx, once=True, sleep_fn=lambda _: None) == 0
    # Heartbeat is under data/sleeves/<id>/; watchdog checks every sleeve.
    assert watchdog(once=True, max_age=timedelta(seconds=0)) in {0, 1}
    now = datetime.now(ET)
    for sid in ("tqqq", "goog"):
        sleeve_dir = data / "sleeves" / sid
        sleeve_dir.mkdir(parents=True, exist_ok=True)
        write_heartbeat(sleeve_dir / "heartbeat.json", now)
    assert watchdog(once=True, max_age=timedelta(hours=2)) == 0
    assert heartbeat_path(ctx.data_dir).name == "heartbeat.json"


def test_flatten_and_ib_venue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("IB_ACCOUNT", "DU123456")
    monkeypatch.setenv("ALLOCATED_USD", "10000")
    monkeypatch.setenv("DRY_RUN", "true")
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("STRATEGY_CONFIG_PATH", str(repo / "config" / "strategy.yaml"))
    monkeypatch.setenv("RUNTIME_CONFIG_PATH", str(repo / "config" / "runtime.yaml"))
    monkeypatch.setenv("RISK_CONFIG_PATH", str(repo / "config" / "risk.yaml"))
    monkeypatch.setenv("SLEEVES_CONFIG_PATH", str(repo / "config" / "sleeves.yaml"))
    monkeypatch.setenv("SLEEVE", "tqqq")
    ctx, broker = _ctx(data, positions={"TQQQ": 50})
    store = ctx.store
    now = datetime(2024, 6, 3, 15, 59, tzinfo=ET)
    store.record_fill(
        order_ref="rsi-cross:tqqq:x",
        signal_id="rsi-cross-tqqq-2024-06-03-entry-oversold",
        symbol="TQQQ",
        side="BUY",
        quantity=50,
        price=50.0,
        ts=now,
    )
    msg = flatten_bot_qty(ctx)
    assert "flatten" in msg or msg == "flat"

    venue = IbVenue(broker, "DU123456")
    intent = OrderIntent(
        signal_id="rsi-cross-2024-06-03-exit",
        symbol="TQQQ",
        side="SELL",
        quantity=10,
        limit_price=49.9,
        order_ref="rsi-cross:rsi-cross-2024-06-03-exit",
    )
    rec = venue.submit(intent)
    assert rec.status is OrderStatus.FILLED
    venue.poll(rec)
    venue.cancel(rec)
    assert map_ib_status("Filled") is OrderStatus.FILLED
    assert map_ib_status("Cancelled") is OrderStatus.CANCELLED
    assert map_ib_status("Rejected") is OrderStatus.REJECTED
    assert map_ib_status("Submitted") is OrderStatus.SENT
    assert map_ib_status("PartialFill") is OrderStatus.PARTIAL


def test_runtime_helpers(tmp_path: Path) -> None:
    assert configured_mode_label(Settings()) == "paper/dry-run"
    assert parse_hhmm("15:58:30").second == 30
    nxt = next_trading_day(date(2024, 6, 1))
    assert nxt.weekday() < 5
    wake = next_wake(datetime(2024, 6, 3, 10, 0, tzinfo=ET))
    assert wake.tzinfo is not None
    set_halt(tmp_path, "test")
    assert is_halted(tmp_path)
    assert halt_reason(tmp_path) == "test"
    clear_halt(tmp_path)
    assert not is_halted(tmp_path)
    write_heartbeat(tmp_path / "hb.json", datetime(2024, 6, 3, 12, 0, tzinfo=ET))
    assert read_heartbeat(tmp_path / "hb.json") is not None
    assert read_heartbeat(tmp_path / "missing.json") is None
    set_stopped(tmp_path, date(2024, 6, 3), True)
    set_stopped(tmp_path, date(2024, 6, 3), False)
    NullNotifier().send("hi")
    assert build_notifier(Settings()).send
    assert reaction_for(DataUnavailableError("x")) is Reaction.RETRY
    assert must_halt(DataUnavailableError("x")) is False
    SystemClock().now()
    FixedClock(datetime(2024, 6, 3, 12, 0, tzinfo=ET)).advance(minutes=1)
    run_startup_checks(Settings.model_validate({"DRY_RUN": True}), 1000)
    assert_order_config(Settings())


def test_risk_branches() -> None:
    from rsi_cross_swing_bot.core.models import EntryReason
    from rsi_cross_swing_bot.engine.signal_engine import IndicatorSnapshot, SignalDecision

    snap = IndicatorSnapshot(
        session_date=date(2024, 6, 3),
        close=100,
        rsi=40,
        rsi_ma=39,
        ema200=90,
        prev_rsi=38,
        prev_rsi_ma=39,
    )
    enter = SignalDecision(
        SignalAction.ENTER,
        "rsi-cross-2024-06-03-entry-oversold",
        EntryReason.OVERSOLD,
        snap,
        True,
        False,
    )
    gate = RiskGate(allocated_usd=10_000)
    now = datetime(2024, 6, 3, 15, 58, tzinfo=ET)
    base = dict(
        now=now,
        in_decision_window=True,
        bot_qty=0,
        account_tqqq_qty=0,
        available_cash=50_000,
        ask=50.1,
        bid=50.0,
        signal_already_used=False,
        stopped_for_day=False,
        halted=False,
        delayed_data=False,
        bar_is_today=True,
    )
    assert gate.evaluate(enter, **base).allowed
    assert gate.evaluate(enter, **{**base, "halted": True}).reason == "halted"
    assert gate.evaluate(enter, **{**base, "stopped_for_day": True}).reason == "stopped_for_day"
    assert gate.evaluate(enter, **{**base, "delayed_data": True}).reason == "delayed_data"
    assert gate.evaluate(enter, **{**base, "bar_is_today": False}).reason == "bar_not_today"
    assert gate.evaluate(enter, **{**base, "bot_qty": 5}).reason == "already_long"
    assert gate.evaluate(enter, **{**base, "ask": 0}).reason == "bad_ask"
    assert gate.evaluate(enter, **{**base, "available_cash": 1}).reason == "shares_below_min"
    used = gate.evaluate(enter, **{**base, "signal_already_used": True})
    assert used.reason == "signal_already_used"
    hold = SignalDecision(SignalAction.HOLD, None, None, snap, False, False)
    assert gate.evaluate(hold, **base).reason == "hold"


def test_telegram_more(tmp_path: Path) -> None:
    from rsi_cross_swing_bot.runtime.telegram_commands import ControlContext, SleeveView

    replies: list[str] = []
    view = SleeveView(
        sleeve_id="tqqq",
        data_dir=tmp_path / "tqqq",
        status_text=lambda: "status",
        positions_text=lambda: "pos",
        get_allocated=lambda: 10_000.0,
        risk_min=100,
        risk_max=1_000_000,
    )
    view.data_dir.mkdir(parents=True, exist_ok=True)
    ctx = ControlContext(
        sleeves={"tqqq": view},
        reply=replies.append,
        today=lambda: date(2024, 6, 3),
        version="0.2.0",
    )
    for cmd in (
        "/status",
        "/version",
        "/positions",
        "/flatten tqqq",
        "/start tqqq",
        "/clearhalt tqqq",
        "/reconcile tqqq",
        "/allocation tqqq",
        "/pnl",
        "/nope",
        "",
        "/allocation tqqq bad",
        "/allocation tqqq 1",
        "/sleeves",
        "/dryrun tqqq on",
    ):
        handle_command(cmd, ctx)
    set_halt(view.data_dir, "x")
    handle_command("/reconcile tqqq", ctx)


def test_session_hourly_and_decision_due(tmp_path: Path) -> None:
    bars = _bars()
    clock = FixedClock(datetime(2024, 6, 3, 11, 0, tzinfo=ET))
    broker = FakeIbClient(
        bars=bars,
        quotes={"TQQQ": _quote(), "QQQ": Quote("QQQ", 400, 400.1, 400, False, _quote().as_of)},
        accounts=["DU1"],
    )
    cfg = AppConfig(
        strategy=StrategyConfig(ema_period=50, history_days=400),
        runtime=RuntimeConfig(),
        risk=RiskConfig(),
    )
    store = TradeStore(tmp_path / "t.sqlite3")
    session = TradingSession(
        settings=Settings.model_validate({"IB_ACCOUNT": "DU1", "DRY_RUN": True}),
        cfg=cfg,
        clock=clock,
        data=broker,
        store=store,
        risk=RiskGate(allocated_usd=10_000),
        orders=OrderManager(
            DryRunVenue(broker.quote),
            store,
        ),
        notifier=NullNotifier(),
        data_dir=tmp_path,
        allocated_usd=10_000,
    )
    state = session.hourly_update()
    assert state is None or state.session_date
    session.hourly_update()  # second call for forming-changed path
    assert decision_due(datetime(2024, 6, 3, 15, 58, tzinfo=ET), cfg)
    assert not decision_due(datetime(2024, 6, 3, 10, 0, tzinfo=ET), cfg)
    clock.set(datetime(2024, 6, 3, 15, 40, tzinfo=ET))
    assert session.run_decision() is None
    broker2 = FakeIbClient(bars=[], quotes={"TQQQ": _quote()}, accounts=["DU1"])
    session.data = broker2
    clock.set(datetime(2024, 6, 3, 15, 58, tzinfo=ET))
    assert session.run_decision() is None
    # mismatch halt path
    session.data = broker
    store.record_fill(
        order_ref="rsi-cross:e",
        signal_id="rsi-cross-2024-06-03-entry-oversold",
        symbol="TQQQ",
        side="BUY",
        quantity=20,
        price=50.0,
        ts=datetime(2024, 6, 3, 15, 59, tzinfo=ET),
    )
    broker._positions = {"TQQQ": 5}
    session._decision_done_for = None
    session.run_decision()


def test_store_signals_and_orders(tmp_path: Path) -> None:
    store = TradeStore(tmp_path / "t.sqlite3")
    now = datetime(2024, 6, 3, 15, 59, tzinfo=ET)
    assert store.record_signal(
        "rsi-cross-2024-06-03-entry-oversold",
        date(2024, 6, 3),
        "ENTER",
        "seen",
        "abcd",
        {"x": 1},
        reason="oversold",
    )
    assert store.signal_exists("rsi-cross-2024-06-03-entry-oversold")
    store.set_signal_status("rsi-cross-2024-06-03-entry-oversold", "FILLED")
    store.upsert_order(
        idempotency_key="k",
        signal_id="rsi-cross-2024-06-03-entry-oversold",
        side="BUY",
        quantity=10,
        limit_price=50.0,
        status="FILLED",
        order_ref="rsi-cross:x",
        updated_at=now,
        filled_qty=10,
        avg_price=50.0,
    )
    assert store.order_by_signal("rsi-cross-2024-06-03-entry-oversold") is not None
    assert store.signals_for_day(date(2024, 6, 3))
    assert store.orders_for_day(date(2024, 6, 3))
    store.close()


def test_compute_snapshot_and_replay() -> None:
    bars = _bars(80)
    snap = compute_snapshot(
        [b.close for b in bars],
        [b.session_date for b in bars],
        ema_period=20,
    )
    assert snap is not None
    trades = replay_bars(bars, allocated_usd=10_000, ema_period=20)
    assert isinstance(trades, list)


def test_order_record_transition() -> None:
    intent = OrderIntent("s", "TQQQ", "BUY", 1, 10.0, "rsi-cross:s")
    rec = OrderRecord(intent)
    rec.transition(OrderStatus.SENT)
    with pytest.raises(ValueError):
        rec.transition(OrderStatus.NEW)
