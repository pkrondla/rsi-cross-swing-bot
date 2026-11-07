"""Command line: `rsi-bot <command> [--sleeve NAME]`."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, timedelta

from rsi_cross_swing_bot import __version__
from rsi_cross_swing_bot.app.context import load_context
from rsi_cross_swing_bot.app.health import run_checks, status_report
from rsi_cross_swing_bot.app.replay import replay_bars
from rsi_cross_swing_bot.app.serve import flatten_bot_qty, serve
from rsi_cross_swing_bot.app.telegram_control import telegram_control
from rsi_cross_swing_bot.app.watchdog import watchdog
from rsi_cross_swing_bot.config.settings import list_sleeve_ids
from rsi_cross_swing_bot.core.clock import SystemClock


def _sleeve(args: argparse.Namespace) -> str | None:
    return getattr(args, "sleeve", None)


def cmd_check(args: argparse.Namespace) -> int:
    ctx = load_context(sleeve=_sleeve(args))
    steps = run_checks(ctx)
    failed = 0
    for step in steps:
        mark = "OK" if step.ok else "FAIL"
        print(f"[{mark}] {step.name}: {step.detail}")
        if not step.ok and step.name != "telegram":
            failed += 1
    return 1 if failed else 0


def cmd_status(args: argparse.Namespace) -> int:
    if getattr(args, "all_sleeves", False):
        for sid in list_sleeve_ids():
            print(status_report(load_context(sleeve=sid)))
            print("---")
        return 0
    ctx = load_context(sleeve=_sleeve(args))
    print(status_report(ctx))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    ctx = load_context(sleeve=_sleeve(args))
    return serve(ctx, once=bool(args.once))


def cmd_watchdog(args: argparse.Namespace) -> int:
    return watchdog(once=bool(args.once))


def cmd_telegram(args: argparse.Namespace) -> int:
    return telegram_control(once=bool(args.once))


def cmd_flatten(args: argparse.Namespace) -> int:
    ctx = load_context(sleeve=_sleeve(args))
    print(flatten_bot_qty(ctx))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    ctx = load_context(sleeve=_sleeve(args))
    day = date.fromisoformat(args.date) if args.date else SystemClock().now().date()
    signals = ctx.store.signals_for_day(day)
    orders = ctx.store.orders_for_day(day)
    print(
        f"sleeve={ctx.sleeve_id} day={day.isoformat()} "
        f"signals={len(signals)} orders={len(orders)}"
    )
    for row in signals:
        print(f"  signal {row['signal_id']} {row['action']} {row['status']}")
    for row in orders:
        print(
            f"  order {row['signal_id']} {row['side']} qty={row['quantity']} "
            f"filled={row['filled_qty']} {row['status']}"
        )
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    ctx = load_context(sleeve=_sleeve(args))
    end = SystemClock().now().date()
    bars = ctx.broker.daily_bars(ctx.cfg.strategy.signal_symbol, end, int(args.last) + 400)
    trades = replay_bars(
        bars,
        allocated_usd=ctx.allocated_usd,
        slippage_bps=ctx.cfg.strategy.slippage_bps,
        oversold_rsi_max=ctx.cfg.strategy.oversold_rsi_max,
        rsi_period=ctx.cfg.strategy.rsi_period,
        rsi_ma_period=ctx.cfg.strategy.rsi_ma_period,
        ema_period=ctx.cfg.strategy.ema_period,
        sleeve_id=ctx.sleeve_id,
    )
    cutoff = end - timedelta(days=int(args.last) * 2)
    shown = [t for t in trades if t.day >= cutoff]
    print(f"sleeve={ctx.sleeve_id} replay trades={len(shown)} (from {len(bars)} bars)")
    for t in shown:
        print(
            f"  {t.day.isoformat()} {t.action} qty={t.quantity} "
            f"px={t.price:.2f} reason={t.reason} id={t.signal_id}"
        )
    return 0


def cmd_sleeves(_: argparse.Namespace) -> int:
    for sid in list_sleeve_ids():
        print(sid)
    return 0


def _add_sleeve_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--sleeve",
        default=None,
        help="Sleeve id from config/sleeves.yaml (default: env SLEEVE or tqqq)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rsi-bot",
        description="RSI cross swing bot (multi-sleeve; QQQ→TQQQ, GOOG, …)",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="Gateway, history, quote, telegram, database")
    _add_sleeve_arg(check_p)

    status_p = sub.add_parser("status", help="Mode, allocation, bot position")
    _add_sleeve_arg(status_p)
    status_p.add_argument("--all", dest="all_sleeves", action="store_true")

    serve_p = sub.add_parser("serve", help="Always-on session loop for one sleeve")
    _add_sleeve_arg(serve_p)
    serve_p.add_argument("--once", action="store_true", help="One iteration then exit")

    watch_p = sub.add_parser("watchdog", help="Dead-man heartbeat alert for all sleeves")
    watch_p.add_argument("--once", action="store_true")

    tg_p = sub.add_parser("telegram", help="Telegram control process (sole getUpdates poller)")
    tg_p.add_argument("--once", action="store_true")

    flat_p = sub.add_parser("flatten", help="Sell only this sleeve's bot quantity")
    _add_sleeve_arg(flat_p)

    sum_p = sub.add_parser("summary", help="Signals and orders for a day")
    _add_sleeve_arg(sum_p)
    sum_p.add_argument("date", nargs="?", default="")

    rep = sub.add_parser("replay", help="Offline signal replay on IB daily bars")
    _add_sleeve_arg(rep)
    rep.add_argument("--last", type=int, default=60)

    sub.add_parser("sleeves", help="List configured sleeve ids")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handlers = {
        "check": cmd_check,
        "status": cmd_status,
        "serve": cmd_serve,
        "watchdog": cmd_watchdog,
        "telegram": cmd_telegram,
        "flatten": cmd_flatten,
        "summary": cmd_summary,
        "replay": cmd_replay,
        "sleeves": cmd_sleeves,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
