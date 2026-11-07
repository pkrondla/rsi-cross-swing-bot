"""Deterministic signal ids so a restart never double-trades."""

from __future__ import annotations

from datetime import date

from rsi_cross_swing_bot.core.models import EntryReason


def entry_signal_id(day: date, reason: EntryReason, *, sleeve_id: str = "tqqq") -> str:
    return f"rsi-cross-{sleeve_id}-{day.isoformat()}-entry-{reason.value}"


def exit_signal_id(day: date, *, sleeve_id: str = "tqqq") -> str:
    return f"rsi-cross-{sleeve_id}-{day.isoformat()}-exit"


def flatten_signal_id(day: date, *, sleeve_id: str = "tqqq") -> str:
    return f"rsi-cross-{sleeve_id}-{day.isoformat()}-flatten"


def order_ref(signal_id: str, prefix: str = "rsi-cross:tqqq:") -> str:
    """IB orderRef used to attribute fills to this sleeve only."""
    return f"{prefix}{signal_id}"
