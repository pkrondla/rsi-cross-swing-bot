"""Command line: `qqq-bot <command>`."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, timedelta

from qqq_rsi_bot import __version__
from qqq_rsi_bot.app.context import load_context
from qqq_rsi_bot.app.health import run_checks, status_report
from qqq_rsi_bot.app.replay import replay_bars
from qqq_rsi_bot.app.serve import flatten_bot_qty, serve
from qqq_rsi_bot.app.watchdog import watchdog
from qqq_rsi_bot.core.clock import SystemClock


def cmd_check(_: argparse.Namespace) -> int:
    ctx = load_context()
    steps = run_checks(ctx)
    failed = 0
    for step in steps:
        mark = "OK" if step.ok else "FAIL"
        print(f"[{mark}] {step.name}: {step.detail}")
        if not step.ok and step.name != "telegram":
            failed += 1
    return 1 if failed else 0


def cmd_status(_: argparse.Namespace) -> int:
    ctx = load_context()
    print(status_report(ctx))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    ctx = load_context()
    return serve(ctx, once=bool(args.once))


def cmd_watchdog(args: argparse.Namespace) -> int:
    ctx = load_context()
    return watchdog(ctx, once=bool(args.once))


def cmd_flatten(_: argparse.Namespace) -> int:
    ctx = load_context()
    print(flatten_bot_qty(ctx))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    ctx = load_context()
    day = date.fromisoformat(args.date) if args.date else SystemClock().now().date()
    signals = ctx.store.signals_for_day(day)
    orders = ctx.store.orders_for_day(day)
    print(f"day={day.isoformat()} signals={len(signals)} orders={len(orders)}")
    for row in signals:
        print(f"  signal {row['signal_id']} {row['action']} {row['status']}")
    for row in orders:
        print(
            f"  order {row['signal_id']} {row['side']} qty={row['quantity']} "
            f"filled={row['filled_qty']} {row['status']}"
        )
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    ctx = load_context()
    end = SystemClock().now().date()
    bars = ctx.broker.daily_bars(ctx.cfg.strategy.signal_symbol, end, int(args.last) + 400)
    # Keep last N trading bars for the report window after warmup.
    trades = replay_bars(
        bars,
        allocated_usd=ctx.allocated_usd,
        slippage_bps=ctx.cfg.strategy.slippage_bps,
        oversold_rsi_max=ctx.cfg.strategy.oversold_rsi_max,
        rsi_period=ctx.cfg.strategy.rsi_period,
        rsi_ma_period=ctx.cfg.strategy.rsi_ma_period,
        ema_period=ctx.cfg.strategy.ema_period,
    )
    cutoff = end - timedelta(days=int(args.last) * 2)
    shown = [t for t in trades if t.day >= cutoff]
    print(f"replay trades={len(shown)} (from {len(bars)} bars)")
    for t in shown:
        print(
            f"  {t.day.isoformat()} {t.action} qty={t.quantity} "
            f"px={t.price:.2f} reason={t.reason} id={t.signal_id}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qqq-bot", description="QQQ RSI → TQQQ bot")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Gateway, history, quote, telegram, database")
    sub.add_parser("status", help="Mode, allocation, bot position")
    serve_p = sub.add_parser("serve", help="Always-on session loop")
    serve_p.add_argument("--once", action="store_true", help="One iteration then exit")
    watch_p = sub.add_parser("watchdog", help="Dead-man heartbeat alert")
    watch_p.add_argument("--once", action="store_true")
    sub.add_parser("flatten", help="Sell only this bot's TQQQ quantity")
    sum_p = sub.add_parser("summary", help="Signals and orders for a day")
    sum_p.add_argument("date", nargs="?", default="")
    rep = sub.add_parser("replay", help="Offline signal replay on IB daily bars")
    rep.add_argument("--last", type=int, default=60)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handlers = {
        "check": cmd_check,
        "status": cmd_status,
        "serve": cmd_serve,
        "watchdog": cmd_watchdog,
        "flatten": cmd_flatten,
        "summary": cmd_summary,
        "replay": cmd_replay,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
