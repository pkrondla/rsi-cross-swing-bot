"""Deterministic signal ids so a restart never double-trades."""

from __future__ import annotations

from datetime import date

from qqq_rsi_bot.core.models import EntryReason


def entry_signal_id(day: date, reason: EntryReason) -> str:
    return f"qqq-rsi-{day.isoformat()}-entry-{reason.value}"


def exit_signal_id(day: date) -> str:
    return f"qqq-rsi-{day.isoformat()}-exit"


def order_ref(signal_id: str, prefix: str = "qqq-rsi:") -> str:
    """IB orderRef used to attribute fills to this bot only."""
    return f"{prefix}{signal_id}"
