"""Dead-man watchdog: alert if the serve heartbeat goes stale."""

from __future__ import annotations

import time
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from qqq_rsi_bot.app.context import AppContext
from qqq_rsi_bot.runtime.heartbeat import read_heartbeat
from qqq_rsi_bot.runtime.notify import build_notifier

ET = ZoneInfo("America/New_York")


def watchdog(
    ctx: AppContext,
    *,
    max_age: timedelta = timedelta(hours=2),
    sleep_fn: Callable[[float], None] = time.sleep,
    once: bool = False,
) -> int:
    notifier = build_notifier(ctx.settings)
    path = ctx.data_dir / ctx.cfg.runtime.heartbeat_path
    alerted = False
    while True:
        now = datetime.now(ET)
        hb = read_heartbeat(path)
        stale = hb is None or (now - hb.astimezone(ET)) > max_age
        if stale and not alerted:
            notifier.send(
                f"WATCHDOG: heartbeat stale or missing at {path} "
                f"(last={hb.isoformat() if hb else 'none'})"
            )
            alerted = True
        if not stale:
            alerted = False
            _ping(ctx.settings.healthcheck_url)
        if once:
            return 1 if stale else 0
        sleep_fn(60)


def _ping(url: str) -> None:
    if not url:
        return
    try:
        urllib.request.urlopen(url, timeout=10).read()
    except Exception:  # noqa: BLE001
        return


def heartbeat_path(data_dir: Path, name: str = "heartbeat.json") -> Path:
    return data_dir / name
