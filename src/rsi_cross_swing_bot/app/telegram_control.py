"""Sole Telegram getUpdates poller; fans out sleeve-targeted commands."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from rsi_cross_swing_bot import __version__
from rsi_cross_swing_bot.app.context import DB_NAME, load_context
from rsi_cross_swing_bot.config.settings import (
    AppConfig,
    Settings,
    list_sleeve_ids,
    load_config,
    sleeve_data_dir,
)
from rsi_cross_swing_bot.core.clock import ET, SystemClock
from rsi_cross_swing_bot.risk.limits import resolve_allocation
from rsi_cross_swing_bot.runtime.halt import halt_reason, is_halted
from rsi_cross_swing_bot.runtime.notify import build_notifier
from rsi_cross_swing_bot.runtime.telegram_commands import (
    OVERRIDE_FILE,
    ControlContext,
    SleeveView,
    handle_control_command,
    poll_updates,
)
from rsi_cross_swing_bot.runtime.watchlist import WATCH_DIR_NAME
from rsi_cross_swing_bot.storage.store import TradeStore


def _make_sleeve_view(
    sid: str,
    cfg: AppConfig,
    data_dir: Path,
    allocated: float,
    store: TradeStore,
) -> SleeveView:
    def status_text() -> str:
        pos = store.bot_position(cfg.strategy.execution_symbol)
        return (
            f"sleeve={sid}\n"
            f"pair={cfg.strategy.signal_symbol}->{cfg.strategy.execution_symbol}\n"
            f"allocated_usd={allocated:.2f}\n"
            f"bot_qty={pos.quantity} avg={pos.avg_price:.4f}\n"
            f"halted={is_halted(data_dir)} {halt_reason(data_dir)}"
        )

    def positions_text() -> str:
        pos = store.bot_position(cfg.strategy.execution_symbol)
        return f"[{sid}] {pos.symbol} bot_qty={pos.quantity} avg={pos.avg_price:.4f}"

    def get_allocated() -> float:
        return allocated

    return SleeveView(
        sleeve_id=sid,
        data_dir=data_dir,
        status_text=status_text,
        positions_text=positions_text,
        get_allocated=get_allocated,
        risk_min=cfg.risk.min_allocated_usd,
        risk_max=cfg.risk.max_allocated_usd,
    )


def telegram_control(
    *,
    once: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    settings = Settings()
    if not settings.has_telegram():
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required for telegram control")
    notifier = build_notifier(settings)
    clock = SystemClock()
    sleeve_ids = list_sleeve_ids(settings.sleeves_config_path)
    root = Path(settings.data_dir)
    root.mkdir(parents=True, exist_ok=True)

    def build_views() -> dict[str, SleeveView]:
        views: dict[str, SleeveView] = {}
        for sid in sleeve_ids:
            cfg = load_config(
                settings.strategy_config_path,
                settings.runtime_config_path,
                settings.risk_config_path,
                sleeves_path=settings.sleeves_config_path,
                sleeve_id=sid,
            )
            data_dir = sleeve_data_dir(root, sid)
            data_dir.mkdir(parents=True, exist_ok=True)
            store = TradeStore(data_dir / DB_NAME)
            allocated = resolve_allocation(
                cfg.risk,
                env_value=settings.allocated_usd if sid == settings.sleeve else None,
                override_path=data_dir / OVERRIDE_FILE,
            )
            views[sid] = _make_sleeve_view(sid, cfg, data_dir, allocated, store)
        return views

    views = build_views()
    ctrl = ControlContext(
        sleeves=views,
        reply=notifier.send,
        today=lambda: clock.now().astimezone(ET).date(),
        version=__version__,
        watch_dir=root / WATCH_DIR_NAME,
    )
    notifier.send(
        "rsi-cross-swing-bot telegram control started; "
        f"sleeves={', '.join(sorted(views)) or '(none; watch-only)'}"
    )
    token = settings.telegram_bot_token.get_secret_value()
    offset = 0
    while True:
        ctrl.sleeves = build_views()
        offset, messages = poll_updates(token, offset)
        for chat_id, text in messages:
            if chat_id != settings.telegram_chat_id:
                continue
            handle_control_command(text, ctrl)
        if once:
            return 0
        sleep_fn(2)


def status_for_sleeve(sleeve_id: str) -> str:
    ctx = load_context(sleeve=sleeve_id, fake=None)
    from rsi_cross_swing_bot.app.health import status_report

    return status_report(ctx)
