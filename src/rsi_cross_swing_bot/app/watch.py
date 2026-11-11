"""Read-only RSI-cross watchlist alerts. No orders, no venue, no Telegram polling.

Hourly through the NYSE session (same ticks as a sleeve's forming update) this
process pulls daily bars for every watched symbol and Telegrams the first
raw RSI x SMA-of-RSI cross per direction per day. The virtual position only
moves on a closed bar (the decision-time scan, or a prior session's bar), so
an intraday cross that fades does not flip it. Deploy alone with RsiCrossCtrl
for an alerts-only bot.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from rsi_cross_swing_bot.adapters.ib.client import IbClient
from rsi_cross_swing_bot.config.settings import (
    RuntimeConfig,
    Settings,
    load_indicator_config,
)
from rsi_cross_swing_bot.core.clock import ET, Clock, SystemClock
from rsi_cross_swing_bot.core.errors import DataUnavailableError
from rsi_cross_swing_bot.core.models import Bar
from rsi_cross_swing_bot.engine.signal_engine import compute_snapshot
from rsi_cross_swing_bot.runtime.calendar import (
    decision_datetime,
    is_trading_day,
    next_wake,
    session_dt,
)
from rsi_cross_swing_bot.runtime.heartbeat import write_heartbeat
from rsi_cross_swing_bot.runtime.notify import Notifier, build_notifier
from rsi_cross_swing_bot.runtime.watchlist import (
    WATCH_DIR_NAME,
    SymbolState,
    already_alerted,
    confirm_position,
    cross_direction,
    effective_long,
    ib_symbol,
    load_entries,
    load_state,
    record_alert,
    save_state,
    state_for,
)

log = logging.getLogger("rsi.watch")

WATCH_HEARTBEAT = "heartbeat.json"
# RSI/SMA alerts only need the 200-bar EMA warm-up that compute_snapshot requires.
WATCH_HISTORY_DAYS = 400
GATEWAY_RETRY_SEC = 300
MAX_SLEEP_SEC = 3600
SCAN_GRACE = timedelta(minutes=5)


class BarSource(Protocol):
    def daily_bars(self, symbol: str, end: date, days: int) -> list[Bar]: ...


@dataclass(frozen=True, slots=True)
class ScanResult:
    alerts: int
    gateway_error: str | None = None


def watch_dir_for(settings: Settings) -> Path:
    return Path(settings.data_dir) / WATCH_DIR_NAME


def in_scan_window(now: datetime, runtime: RuntimeConfig) -> bool:
    """Session open through a few minutes past the decision time, NYSE days only."""
    local = now.astimezone(ET)
    day = local.date()
    if not is_trading_day(day):
        return False
    start = session_dt(day, runtime.session_open)
    end = decision_datetime(
        day,
        decision_time=runtime.decision_time,
        early_close_decision_time=runtime.early_close_decision_time,
    )
    return start <= local <= end + SCAN_GRACE


def scan_once(
    *,
    now: datetime,
    runtime: RuntimeConfig,
    data: BarSource,
    watch_dir: Path,
    notifier: Notifier,
    rsi_period: int,
    rsi_ma_period: int,
    ema_period: int,
    history_days: int = WATCH_HISTORY_DAYS,
    warned: set[str] | None = None,
) -> ScanResult:
    """Scan every watched symbol once. Gateway failures abort the scan."""
    warned = warned if warned is not None else set()
    local = now.astimezone(ET)
    today = local.date()
    decide = decision_datetime(
        today,
        decision_time=runtime.decision_time,
        early_close_decision_time=runtime.early_close_decision_time,
    )
    entries = load_entries(watch_dir)
    stored = load_state(watch_dir)
    states: dict[str, SymbolState] = {e.symbol: state_for(e, stored) for e in entries}
    alerts = 0
    gateway_error: str | None = None

    for entry in entries:
        try:
            bars = data.daily_bars(ib_symbol(entry.symbol), today, history_days)
        except (DataUnavailableError, ConnectionError) as exc:
            gateway_error = str(exc)
            break
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the scan
            log.warning("watch: bars failed for %s: %s", entry.symbol, exc)
            bars = []
        if not bars:
            if entry.symbol not in warned:
                notifier.send(f"[watch] no daily bars for {entry.symbol} — check the symbol")
                warned.add(entry.symbol)
            continue
        warned.discard(entry.symbol)
        snap = compute_snapshot(
            [b.close for b in bars],
            [b.session_date for b in bars],
            rsi_period=rsi_period,
            rsi_ma_period=rsi_ma_period,
            ema_period=ema_period,
        )
        if snap is None:
            log.info("watch: indicators not ready for %s", entry.symbol)
            continue
        direction = cross_direction(snap)
        if direction is None:
            continue

        state = states[entry.symbol]
        closed = snap.session_date < today or local >= decide
        if not already_alerted(state, snap.session_date, direction):
            side = "BUY" if direction == "bullish" else "SELL"
            cross = "crossed above" if direction == "bullish" else "crossed below"
            before = "long" if effective_long(entry, state) else "flat"
            bar = "closing" if closed else "forming"
            notifier.send(
                f"[watch] {entry.symbol} {side} signal: RSI {snap.rsi:.2f} {cross} "
                f"MA {snap.rsi_ma:.2f}, close {snap.close:.2f}\n"
                f"{bar} bar {snap.session_date.isoformat()} @ {local.strftime('%H:%M')} ET; "
                f"position before signal: {before}"
            )
            state = record_alert(state, snap.session_date, direction)
            alerts += 1
        if closed:
            state = confirm_position(state, snap.session_date, direction)
        states[entry.symbol] = state

    if states != stored:
        save_state(watch_dir, states)
    return ScanResult(alerts=alerts, gateway_error=gateway_error)


def watch(
    *,
    once: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Clock | None = None,
    notifier: Notifier | None = None,
    data: BarSource | None = None,
    watch_dir: Path | None = None,
) -> int:
    settings = Settings()
    strategy, runtime = load_indicator_config(
        settings.strategy_config_path, settings.runtime_config_path
    )
    if notifier is None:
        notifier = build_notifier(settings)
    if data is None:
        data = IbClient(
            settings.ib_host, settings.ib_port, settings.watch_ib_client_id, readonly=True
        )
    if clock is None:
        clock = SystemClock()
    if watch_dir is None:
        watch_dir = watch_dir_for(settings)
    watch_dir.mkdir(parents=True, exist_ok=True)

    notifier.send("rsi-cross-swing-bot watch started (alerts only; no orders)")
    gateway_down = False
    warned: set[str] = set()
    while True:
        now = clock.now().astimezone(ET)
        healthy = True
        if in_scan_window(now, runtime):
            result = scan_once(
                now=now,
                runtime=runtime,
                data=data,
                watch_dir=watch_dir,
                notifier=notifier,
                rsi_period=strategy.rsi_period,
                rsi_ma_period=strategy.rsi_ma_period,
                ema_period=strategy.ema_period,
                warned=warned,
            )
            if result.gateway_error is not None:
                healthy = False
                if not gateway_down:
                    notifier.send(
                        f"[watch] IB data unavailable: {result.gateway_error}; "
                        f"retrying every {GATEWAY_RETRY_SEC // 60} min"
                    )
                    gateway_down = True
            elif gateway_down:
                notifier.send("[watch] IB data restored; scanning resumed")
                gateway_down = False
        if healthy:
            write_heartbeat(watch_dir / WATCH_HEARTBEAT, now, "watch")
        if once:
            return 0 if healthy else 1
        if not healthy:
            sleep_fn(GATEWAY_RETRY_SEC)
            continue
        wake = next_wake(
            now,
            session_open=runtime.session_open,
            decision_time=runtime.decision_time,
            early_close_decision_time=runtime.early_close_decision_time,
        )
        delay = (wake - clock.now().astimezone(ET)).total_seconds()
        sleep_fn(min(MAX_SLEEP_SEC, max(1, math.ceil(delay))))
