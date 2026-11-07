"""Telegram command parsing for the control process (sleeve-aware)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from rsi_cross_swing_bot.risk.limits import resolve_allocation, save_allocation_override
from rsi_cross_swing_bot.runtime.day_stop import set_stopped
from rsi_cross_swing_bot.runtime.dry_run_switch import write_dry_run_override
from rsi_cross_swing_bot.runtime.halt import clear_halt, halt_reason, is_halted
from rsi_cross_swing_bot.runtime.inbox import push_command

log = logging.getLogger("rsi.telegram")

OVERRIDE_FILE = "LIMITS_OVERRIDE.json"


@dataclass
class SleeveView:
    sleeve_id: str
    data_dir: Path
    status_text: Callable[[], str]
    positions_text: Callable[[], str]
    get_allocated: Callable[[], float]
    risk_min: float
    risk_max: float


@dataclass
class ControlContext:
    sleeves: dict[str, SleeveView]
    reply: Callable[[str], None]
    today: Callable[[], date]
    version: str


def handle_control_command(text: str, ctx: ControlContext) -> None:
    parts = text.strip().split()
    if not parts:
        return
    cmd = parts[0].split("@", 1)[0].lower()
    if cmd in {"/help", "help"}:
        ctx.reply(
            "Commands: /help /status [sleeve|all] /positions [sleeve] "
            "/allocation [sleeve] [usd] /stop [sleeve|all] /start [sleeve|all] "
            "/flatten [sleeve|all] /dryrun [sleeve] on|off /reconcile [sleeve] "
            "/clearhalt [sleeve] /version /sleeves"
        )
        return
    if cmd == "/version":
        ctx.reply(f"rsi-cross-swing-bot {ctx.version}")
        return
    if cmd == "/sleeves":
        ctx.reply("sleeves: " + ", ".join(sorted(ctx.sleeves)))
        return

    target = _resolve_targets(parts, ctx.sleeves)
    if target.error:
        ctx.reply(target.error)
        return

    if cmd in {"/status", "/mode"}:
        chunks = [ctx.sleeves[s].status_text() for s in target.ids]
        ctx.reply("\n---\n".join(chunks))
        return
    if cmd == "/positions":
        chunks = [ctx.sleeves[s].positions_text() for s in target.ids]
        ctx.reply("\n".join(chunks))
        return
    if cmd == "/flatten":
        for sid in target.ids:
            push_command(ctx.sleeves[sid].data_dir, "flatten")
        ctx.reply("flatten queued: " + ", ".join(target.ids))
        return
    if cmd == "/stop":
        for sid in target.ids:
            set_stopped(ctx.sleeves[sid].data_dir, ctx.today(), True)
        ctx.reply(f"Stopped {', '.join(target.ids)} for {ctx.today().isoformat()}")
        return
    if cmd == "/start":
        for sid in target.ids:
            set_stopped(ctx.sleeves[sid].data_dir, ctx.today(), False)
        ctx.reply(f"Started {', '.join(target.ids)} for {ctx.today().isoformat()}")
        return
    if cmd == "/clearhalt":
        for sid in target.ids:
            clear_halt(ctx.sleeves[sid].data_dir)
        ctx.reply("Halt cleared: " + ", ".join(target.ids))
        return
    if cmd == "/reconcile":
        for sid in target.ids:
            push_command(ctx.sleeves[sid].data_dir, "reconcile")
        lines = []
        for sid in target.ids:
            d = ctx.sleeves[sid].data_dir
            if is_halted(d):
                lines.append(f"[{sid}] halted: {halt_reason(d)}")
            else:
                lines.append(f"[{sid}] no halt")
        ctx.reply("\n".join(lines))
        return
    if cmd == "/allocation":
        if len(target.ids) != 1:
            ctx.reply("usage: /allocation <sleeve> [usd]")
            return
        sid = target.ids[0]
        view = ctx.sleeves[sid]
        # /allocation tqqq  OR  /allocation tqqq 20000  OR legacy /allocation 20000
        value_token = target.value_token
        if value_token is None:
            ctx.reply(f"[{sid}] allocated_usd={view.get_allocated():.2f}")
            return
        try:
            value = float(value_token)
        except ValueError:
            ctx.reply("usage: /allocation <sleeve> 10000")
            return
        if value < view.risk_min or value > view.risk_max:
            ctx.reply(f"refused: must be in [{view.risk_min}, {view.risk_max}]")
            return
        save_allocation_override(view.data_dir / OVERRIDE_FILE, value)
        ctx.reply(f"[{sid}] allocated_usd set to {value:.2f}")
        return
    if cmd == "/dryrun":
        if len(target.ids) != 1 or target.value_token is None:
            ctx.reply("usage: /dryrun <sleeve> on|off")
            return
        sid = target.ids[0]
        token = target.value_token.lower()
        if token not in {"on", "off", "true", "false", "1", "0"}:
            ctx.reply("usage: /dryrun <sleeve> on|off")
            return
        enabled = token in {"on", "true", "1"}
        write_dry_run_override(ctx.sleeves[sid].data_dir, enabled)
        push_command(ctx.sleeves[sid].data_dir, "dryrun", value=enabled)
        ctx.reply(f"[{sid}] dry_run -> {enabled}")
        return
    if cmd in {"/pnl", "/orders", "/signals"}:
        ctx.reply(f"{cmd}: see /status or rsi-bot summary --sleeve <id>")
        return
    ctx.reply(f"Unknown command {cmd}. /help")


@dataclass
class _Targets:
    ids: list[str]
    value_token: str | None = None
    error: str | None = None


def _resolve_targets(parts: list[str], sleeves: dict[str, SleeveView]) -> _Targets:
    """Parse optional sleeve / all and an optional trailing value token."""
    rest = parts[1:]
    if not rest:
        return _Targets(ids=sorted(sleeves.keys()))
    first = rest[0].lower()
    if first == "all":
        value = rest[1] if len(rest) > 1 else None
        return _Targets(ids=sorted(sleeves.keys()), value_token=value)
    if first in sleeves:
        value = rest[1] if len(rest) > 1 else None
        return _Targets(ids=[first], value_token=value)
    # Legacy: /allocation 10000 with implicit single sleeve if only one exists
    if len(sleeves) == 1 and _looks_numeric(first):
        only = next(iter(sleeves))
        return _Targets(ids=[only], value_token=first)
    if _looks_numeric(first) or first in {"on", "off", "true", "false"}:
        return _Targets(
            ids=[],
            error=f"specify sleeve: one of {', '.join(sorted(sleeves))}",
        )
    return _Targets(ids=[], error=f"unknown sleeve {first!r}")


def _looks_numeric(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False


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
    from rsi_cross_swing_bot.config.settings import RiskConfig

    return resolve_allocation(
        RiskConfig(
            allocated_usd=risk_yaml_value,
            min_allocated_usd=1,
            max_allocated_usd=1e12,
        ),
        env_value=env_value,
        override_path=data_dir / OVERRIDE_FILE,
    )


# Back-compat alias used by older unit tests during transition.
CommandContext = ControlContext


def handle_command(text: str, ctx: ControlContext) -> None:
    handle_control_command(text, ctx)
