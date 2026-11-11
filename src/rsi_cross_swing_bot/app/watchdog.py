"""Dead-man watchdog: alert if any sleeve or the watchlist heartbeat goes stale."""

from __future__ import annotations

import time
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from rsi_cross_swing_bot.app.watch import WATCH_HEARTBEAT
from rsi_cross_swing_bot.config.settings import (
    Settings,
    list_sleeve_ids,
    load_config,
    sleeve_data_dir,
)
from rsi_cross_swing_bot.runtime.heartbeat import read_heartbeat
from rsi_cross_swing_bot.runtime.notify import build_notifier
from rsi_cross_swing_bot.runtime.watchlist import WATCH_DIR_NAME

ET = ZoneInfo("America/New_York")
_WATCH_KEY = ":watch"


def watchdog(
    *,
    max_age: timedelta = timedelta(hours=2),
    sleep_fn: Callable[[float], None] = time.sleep,
    once: bool = False,
) -> int:
    settings = Settings()
    notifier = build_notifier(settings)
    root = Path(settings.data_dir)
    sleeve_ids = list_sleeve_ids(settings.sleeves_config_path)
    alerted: set[str] = set()
    while True:
        now = datetime.now(ET)
        any_stale = False
        for sid in sleeve_ids:
            cfg = load_config(
                settings.strategy_config_path,
                settings.runtime_config_path,
                settings.risk_config_path,
                sleeves_path=settings.sleeves_config_path,
                sleeve_id=sid,
            )
            path = sleeve_data_dir(root, sid) / cfg.runtime.heartbeat_path
            hb = read_heartbeat(path)
            stale = hb is None or (now - hb.astimezone(ET)) > max_age
            if stale:
                any_stale = True
                if sid not in alerted:
                    notifier.send(
                        f"WATCHDOG [{sid}]: heartbeat stale or missing at {path} "
                        f"(last={hb.isoformat() if hb else 'none'})"
                    )
                    alerted.add(sid)
            elif sid in alerted:
                alerted.discard(sid)
        # Watchlist process: monitored once it has written its first heartbeat.
        watch_hb_path = root / WATCH_DIR_NAME / WATCH_HEARTBEAT
        if watch_hb_path.exists():
            hb = read_heartbeat(watch_hb_path)
            if hb is None or (now - hb.astimezone(ET)) > max_age:
                any_stale = True
                if _WATCH_KEY not in alerted:
                    notifier.send(
                        f"WATCHDOG [watch]: watchlist heartbeat stale at {watch_hb_path} "
                        f"(last={hb.isoformat() if hb else 'none'}); "
                        "IB data down or RsiCrossList stopped"
                    )
                    alerted.add(_WATCH_KEY)
            elif _WATCH_KEY in alerted:
                alerted.discard(_WATCH_KEY)
        if not any_stale:
            _ping(settings.healthcheck_url)
        if once:
            return 1 if any_stale else 0
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
