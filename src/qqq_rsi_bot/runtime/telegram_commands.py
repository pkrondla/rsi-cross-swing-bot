"""Minimal Telegram long-poll command handler."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from qqq_rsi_bot.risk.limits import resolve_allocation, save_allocation_override
from qqq_rsi_bot.runtime.day_stop import set_stopped
from qqq_rsi_bot.runtime.halt import clear_halt, halt_reason, is_halted

log = logging.getLogger("qqq.telegram")

OVERRIDE_FILE = "LIMITS_OVERRIDE.json"


@dataclass
class CommandContext:
    data_dir: Path
    reply: Callable[[str], None]
    status_text: Callable[[], str]
    positions_text: Callable[[], str]
    flatten: Callable[[], str]
    get_allocated: Callable[[], float]
    risk_min: float
    risk_max: float
    today: Callable[[], date]


def handle_command(text: str, ctx: CommandContext) -> None:
    parts = text.strip().split()
    if not parts:
        return
    cmd = parts[0].split("@", 1)[0].lower()
    if cmd in {"/help", "help"}:
        ctx.reply(
            "Commands: /help /status /mode /version /positions /pnl /orders /signals "
            "/allocation /stop /start /flatten /dryrun /reconcile /clearhalt"
        )
        return
    if cmd in {"/status", "/mode"}:
        ctx.reply(ctx.status_text())
        return
    if cmd == "/version":
        from qqq_rsi_bot import __version__

        ctx.reply(f"qqq-rsi-bot {__version__}")
        return
    if cmd == "/positions":
        ctx.reply(ctx.positions_text())
        return
    if cmd == "/flatten":
        ctx.reply(ctx.flatten())
        return
    if cmd == "/stop":
        set_stopped(ctx.data_dir, ctx.today(), True)
        ctx.reply(f"Stopped for {ctx.today().isoformat()}")
        return
    if cmd == "/start":
        set_stopped(ctx.data_dir, ctx.today(), False)
        ctx.reply(f"Started for {ctx.today().isoformat()}")
        return
    if cmd == "/clearhalt":
        clear_halt(ctx.data_dir)
        ctx.reply("Halt cleared")
        return
    if cmd == "/reconcile":
        if is_halted(ctx.data_dir):
            ctx.reply(f"Still halted: {halt_reason(ctx.data_dir)}")
        else:
            ctx.reply("No halt; bot ledger is the sell source of truth")
        return
    if cmd == "/allocation":
        if len(parts) == 1:
            ctx.reply(f"allocated_usd={ctx.get_allocated():.2f}")
            return
        try:
            value = float(parts[1])
        except ValueError:
            ctx.reply("usage: /allocation 10000")
            return
        if value < ctx.risk_min or value > ctx.risk_max:
            ctx.reply(f"refused: must be in [{ctx.risk_min}, {ctx.risk_max}]")
            return
        save_allocation_override(ctx.data_dir / OVERRIDE_FILE, value)
        ctx.reply(f"allocated_usd set to {value:.2f}")
        return
    if cmd in {"/pnl", "/orders", "/signals", "/dryrun"}:
        ctx.reply(f"{cmd}: see status / host logs (summary stored in SQLite)")
        return
    ctx.reply(f"Unknown command {cmd}. /help")


def poll_updates(token: str, offset: int) -> tuple[int, list[tuple[str, str]]]:
    """Return (new_offset, list of (chat_id, text))."""
    url = (
        f"https://api.telegram.org/bot{token}/getUpdates"
        f"?timeout=0&offset={offset}"
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        log.warning("telegram poll failed: %s", exc)
        return offset, []
    messages: list[tuple[str, str]] = []
    new_offset = offset
    for upd in payload.get("result", []):
        new_offset = max(new_offset, int(upd["update_id"]) + 1)
        msg = upd.get("message") or {}
        text = msg.get("text")
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if text and chat_id:
            messages.append((chat_id, text))
    return new_offset, messages


def load_allocated(data_dir: Path, risk_yaml_value: float, env_value: float | None) -> float:
    from qqq_rsi_bot.config.settings import RiskConfig

    return resolve_allocation(
        RiskConfig(
            allocated_usd=risk_yaml_value,
            min_allocated_usd=1,
            max_allocated_usd=1e12,
        ),
        env_value=env_value,
        override_path=data_dir / OVERRIDE_FILE,
    )
