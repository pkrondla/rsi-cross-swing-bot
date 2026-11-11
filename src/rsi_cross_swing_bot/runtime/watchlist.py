"""Watchlist storage (edited via Telegram /watch) and alert state for rsi-bot watch.

Two files live under data/watchlist/, each with a single writer:
- watchlist.json: symbols, when each was added, and manual long/flat marks.
  Written only by the Telegram control process.
- state.json: per-symbol alert dedupe and confirmed virtual position.
  Written only by the watch process.

A manual mark seeds the position; it applies until a newer confirmed cross
moves the position (whichever timestamp is later wins). State is tied to the
entry's `added` timestamp, so remove + re-add starts fresh.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from rsi_cross_swing_bot.engine.signal_engine import IndicatorSnapshot

log = logging.getLogger("rsi.watchlist")

WATCH_DIR_NAME = "watchlist"
WATCHLIST_FILE = "watchlist.json"
STATE_FILE = "state.json"

Direction = Literal["bullish", "bearish"]
Mark = Literal["long", "flat"]

_SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.]{0,11}$")


@dataclass(frozen=True, slots=True)
class WatchEntry:
    symbol: str
    added: str = ""
    mark: Mark | None = None
    mark_ts: str = ""


@dataclass(frozen=True, slots=True)
class SymbolState:
    added: str = ""
    long: bool = False
    position_ts: str = ""
    last_bullish_day: str = ""
    last_bearish_day: str = ""
    last_confirmed_day: str = ""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_symbol(token: str) -> str | None:
    sym = token.strip().upper()
    return sym if _SYMBOL_RE.match(sym) else None


def ib_symbol(symbol: str) -> str:
    """IB spells share classes with a space (BRK B), users type BRK.B."""
    return symbol.replace(".", " ")


# --- watchlist.json (control process writes) --------------------------------


def load_entries(watch_dir: Path) -> list[WatchEntry]:
    raw = _read_json(watch_dir / WATCHLIST_FILE)
    if not isinstance(raw, dict):
        return []
    symbols = raw.get("symbols")
    if not isinstance(symbols, list):
        return []
    out: list[WatchEntry] = []
    for item in symbols:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            continue
        mark = item.get("mark")
        out.append(
            WatchEntry(
                symbol=symbol.upper(),
                added=str(item.get("added") or ""),
                mark=mark if mark in ("long", "flat") else None,
                mark_ts=str(item.get("mark_ts") or ""),
            )
        )
    return out


def save_entries(watch_dir: Path, entries: list[WatchEntry]) -> None:
    payload = {
        "symbols": [
            {"symbol": e.symbol, "added": e.added, "mark": e.mark, "mark_ts": e.mark_ts}
            for e in entries
        ]
    }
    _write_json(watch_dir / WATCHLIST_FILE, payload)


def add_entry(watch_dir: Path, symbol: str, *, now: str | None = None) -> tuple[bool, str]:
    symbol = symbol.upper()
    entries = load_entries(watch_dir)
    if any(e.symbol == symbol for e in entries):
        return False, f"[watch] {symbol} already on the watchlist"
    entries.append(WatchEntry(symbol=symbol, added=now or utc_now_iso()))
    entries.sort(key=lambda e: e.symbol)
    save_entries(watch_dir, entries)
    return True, f"[watch] {symbol} added"


def remove_entry(watch_dir: Path, symbol: str) -> tuple[bool, str]:
    symbol = symbol.upper()
    entries = load_entries(watch_dir)
    kept = [e for e in entries if e.symbol != symbol]
    if len(kept) == len(entries):
        return False, f"[watch] {symbol} not on the watchlist"
    save_entries(watch_dir, kept)
    return True, f"[watch] {symbol} removed"


def set_mark(
    watch_dir: Path, symbol: str, mark: Mark, *, now: str | None = None
) -> tuple[bool, str]:
    symbol = symbol.upper()
    entries = load_entries(watch_dir)
    for i, entry in enumerate(entries):
        if entry.symbol == symbol:
            entries[i] = replace(entry, mark=mark, mark_ts=now or utc_now_iso())
            save_entries(watch_dir, entries)
            return True, f"[watch] {symbol} marked {mark}"
    return False, f"[watch] {symbol} not on the watchlist"


# --- state.json (watch process writes) --------------------------------------


def load_state(watch_dir: Path) -> dict[str, SymbolState]:
    raw = _read_json(watch_dir / STATE_FILE)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, SymbolState] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        out[str(key).upper()] = SymbolState(
            added=str(value.get("added") or ""),
            long=bool(value.get("long", False)),
            position_ts=str(value.get("position_ts") or ""),
            last_bullish_day=str(value.get("last_bullish_day") or ""),
            last_bearish_day=str(value.get("last_bearish_day") or ""),
            last_confirmed_day=str(value.get("last_confirmed_day") or ""),
        )
    return out


def save_state(watch_dir: Path, state: dict[str, SymbolState]) -> None:
    payload = {
        symbol: {
            "added": s.added,
            "long": s.long,
            "position_ts": s.position_ts,
            "last_bullish_day": s.last_bullish_day,
            "last_bearish_day": s.last_bearish_day,
            "last_confirmed_day": s.last_confirmed_day,
        }
        for symbol, s in sorted(state.items())
    }
    _write_json(watch_dir / STATE_FILE, payload)


def state_for(entry: WatchEntry, states: dict[str, SymbolState]) -> SymbolState:
    """Stored state for this entry, or fresh state if the symbol was re-added."""
    stored = states.get(entry.symbol)
    if stored is None or stored.added != entry.added:
        return SymbolState(added=entry.added)
    return stored


# --- pure rules -------------------------------------------------------------


def effective_long(entry: WatchEntry, state: SymbolState) -> bool:
    """Newest wins: a manual mark, or the last confirmed cross after it."""
    if entry.mark is not None and _ts(entry.mark_ts) >= _ts(state.position_ts):
        return entry.mark == "long"
    return state.long


def cross_direction(snapshot: IndicatorSnapshot) -> Direction | None:
    """Raw RSI x SMA-of-RSI cross, no entry filter and no position gate."""
    if snapshot.prev_rsi <= snapshot.prev_rsi_ma and snapshot.rsi > snapshot.rsi_ma:
        return "bullish"
    if snapshot.prev_rsi >= snapshot.prev_rsi_ma and snapshot.rsi < snapshot.rsi_ma:
        return "bearish"
    return None


def already_alerted(state: SymbolState, day: date, direction: Direction) -> bool:
    """At most one alert per symbol per session date per direction."""
    last = state.last_bullish_day if direction == "bullish" else state.last_bearish_day
    return last == day.isoformat()


def record_alert(state: SymbolState, day: date, direction: Direction) -> SymbolState:
    if direction == "bullish":
        return replace(state, last_bullish_day=day.isoformat())
    return replace(state, last_bearish_day=day.isoformat())


def confirm_position(
    state: SymbolState, day: date, direction: Direction, *, now: str | None = None
) -> SymbolState:
    """Move the virtual position on a closed-bar cross, once per bar date."""
    if state.last_confirmed_day == day.isoformat():
        return state
    return replace(
        state,
        long=direction == "bullish",
        position_ts=now or utc_now_iso(),
        last_confirmed_day=day.isoformat(),
    )


def last_alert_text(state: SymbolState) -> str:
    parts = []
    if state.last_bullish_day:
        parts.append(f"buy={state.last_bullish_day}")
    if state.last_bearish_day:
        parts.append(f"sell={state.last_bearish_day}")
    return " ".join(parts)


# --- io ---------------------------------------------------------------------


def _ts(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        log.warning("ignoring corrupt json %s", path)
        return {}


def _write_json(path: Path, payload: object) -> None:
    """Write via temp file + rename so the other process never reads a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows refuses to replace a file another process has open for reading.
            if attempt == 4:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (attempt + 1))
