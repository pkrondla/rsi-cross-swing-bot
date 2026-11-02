"""Always-on serve loop: hourly forming updates + end-of-day decision."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from qqq_rsi_bot.app.context import AppContext
from qqq_rsi_bot.core.clock import ET, SystemClock
from qqq_rsi_bot.core.signal_id import order_ref
from qqq_rsi_bot.execution.models import OrderIntent
from qqq_rsi_bot.runtime.arming import configured_mode_label
from qqq_rsi_bot.runtime.calendar import decision_datetime, next_wake
from qqq_rsi_bot.runtime.guard import run_startup_checks
from qqq_rsi_bot.runtime.notify import build_notifier
from qqq_rsi_bot.runtime.session import TradingSession, decision_due
from qqq_rsi_bot.runtime.telegram_commands import CommandContext, handle_command, poll_updates


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
    notifier.send(f"qqq-rsi-bot serve started ({configured_mode_label(ctx.settings)})")
    tg_offset = 0
    token = ctx.settings.telegram_bot_token.get_secret_value()

    def status_text() -> str:
        from qqq_rsi_bot.app.health import status_report

        return status_report(ctx)

    def positions_text() -> str:
        pos = ctx.store.bot_position(ctx.cfg.strategy.execution_symbol)
        return f"{pos.symbol} bot_qty={pos.quantity} avg={pos.avg_price:.4f}"

    def flatten() -> str:
        return flatten_bot_qty(ctx)

    cmd_ctx = CommandContext(
        data_dir=ctx.data_dir,
        reply=notifier.send,
        status_text=status_text,
        positions_text=positions_text,
        flatten=flatten,
        get_allocated=lambda: ctx.allocated_usd,
        risk_min=ctx.cfg.risk.min_allocated_usd,
        risk_max=ctx.cfg.risk.max_allocated_usd,
        today=lambda: clock.now().astimezone(ET).date(),
    )

    while True:
        now = clock.now().astimezone(ET)
        if token and ctx.settings.telegram_chat_id:
            tg_offset, messages = poll_updates(token, tg_offset)
            for chat_id, text in messages:
                if chat_id != ctx.settings.telegram_chat_id:
                    continue
                handle_command(text, cmd_ctx)

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
        # Near decision time, poll more often.
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


def flatten_bot_qty(ctx: AppContext) -> str:
    """Sell only this bot's remaining shares (manual /flatten)."""
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
    signal_id = f"qqq-rsi-{day.isoformat()}-flatten"
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
