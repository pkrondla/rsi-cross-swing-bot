"""Always-on serve loop for one sleeve: hourly forming updates + EOD decision."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from rsi_cross_swing_bot.app.context import AppContext, refresh_venue
from rsi_cross_swing_bot.core.clock import ET, SystemClock
from rsi_cross_swing_bot.core.signal_id import flatten_signal_id, order_ref
from rsi_cross_swing_bot.execution.models import OrderIntent
from rsi_cross_swing_bot.runtime.arming import configured_mode_label
from rsi_cross_swing_bot.runtime.calendar import decision_datetime, next_wake
from rsi_cross_swing_bot.runtime.dry_run_switch import write_dry_run_override
from rsi_cross_swing_bot.runtime.guard import run_startup_checks
from rsi_cross_swing_bot.runtime.inbox import drain_commands
from rsi_cross_swing_bot.runtime.notify import build_notifier
from rsi_cross_swing_bot.runtime.session import TradingSession, decision_due


def serve(
    ctx: AppContext, *, once: bool = False, sleep_fn: Callable[[float], None] = time.sleep
) -> int:
    run_startup_checks(ctx.settings, ctx.allocated_usd)
    clock = SystemClock()
    notifier = build_notifier(ctx.settings)
    session = TradingSession(
        settings=ctx.settings,
        cfg=ctx.cfg,
        clock=clock,
        data=ctx.broker,
        store=ctx.store,
        risk=ctx.risk,
        orders=ctx.orders,
        notifier=notifier,
        data_dir=ctx.data_dir,
        allocated_usd=ctx.allocated_usd,
    )
    notifier.send(
        f"[{ctx.sleeve_id}] rsi-cross-swing-bot serve started "
        f"({configured_mode_label(ctx.settings)}) client_id={ctx.ib_client_id}"
    )

    while True:
        refresh_venue(ctx)
        session.orders = ctx.orders
        for cmd in drain_commands(ctx.data_dir):
            _handle_inbox(ctx, cmd.name, cmd.payload, notifier.send)

        now = clock.now().astimezone(ET)
        if decision_due(now, ctx.cfg):
            session.run_decision()
        else:
            session.hourly_update()

        if once:
            return 0

        wake = next_wake(
            now,
            session_open=ctx.cfg.runtime.session_open,
            decision_time=ctx.cfg.runtime.decision_time,
            early_close_decision_time=ctx.cfg.runtime.early_close_decision_time,
        )
        decide = decision_datetime(
            now.date(),
            decision_time=ctx.cfg.runtime.decision_time,
            early_close_decision_time=ctx.cfg.runtime.early_close_decision_time,
        )
        if now.date() == decide.date() and abs((decide - now).total_seconds()) < 600:
            delay = min(30, max(1, int((wake - now).total_seconds())))
        else:
            delay = max(1, int((wake - now).total_seconds()))
            delay = min(delay, 3600)
        sleep_fn(delay)


def _handle_inbox(
    ctx: AppContext,
    name: str,
    payload: dict[str, object],
    reply: Callable[[str], None],
) -> None:
    if name == "flatten":
        reply(f"[{ctx.sleeve_id}] {flatten_bot_qty(ctx)}")
        return
    if name == "dryrun":
        value = payload.get("value")
        if not isinstance(value, bool):
            reply(f"[{ctx.sleeve_id}] dryrun inbox missing bool value")
            return
        write_dry_run_override(ctx.data_dir, value)
        refresh_venue(ctx)
        reply(f"[{ctx.sleeve_id}] dry_run set to {value}")
        return
    if name == "reconcile":
        from rsi_cross_swing_bot.runtime.halt import halt_reason, is_halted

        if is_halted(ctx.data_dir):
            reply(f"[{ctx.sleeve_id}] Still halted: {halt_reason(ctx.data_dir)}")
        else:
            reply(f"[{ctx.sleeve_id}] No halt; bot ledger is the sell source of truth")
        return
    reply(f"[{ctx.sleeve_id}] unknown inbox command {name}")


def flatten_bot_qty(ctx: AppContext) -> str:
    """Sell only this sleeve's remaining shares (manual /flatten)."""
    symbol = ctx.cfg.strategy.execution_symbol
    pos = ctx.store.bot_position(symbol)
    if pos.quantity <= 0:
        return "flat"
    account_qty = ctx.broker.position_qty(ctx.settings.ib_account, symbol)
    if account_qty < pos.quantity:
        return f"refused: account {account_qty} < bot {pos.quantity}"
    quote = ctx.broker.quote(symbol)
    limit = round(quote.bid * (1.0 - ctx.cfg.strategy.slippage_bps / 10_000.0), 2)
    day = SystemClock().now().astimezone(ET).date()
    signal_id = flatten_signal_id(day, sleeve_id=ctx.sleeve_id)
    intent = OrderIntent(
        signal_id=signal_id,
        symbol=symbol,
        side="SELL",
        quantity=pos.quantity,
        limit_price=limit,
        order_ref=order_ref(signal_id, ctx.cfg.strategy.order_ref_prefix),
    )
    record = ctx.orders.submit(intent, datetime.now(ET))
    return f"flatten {record.status.value}: sold up to {pos.quantity}"
