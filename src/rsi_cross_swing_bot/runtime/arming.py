"""Human-readable mode label for status and Telegram."""

from __future__ import annotations

from rsi_cross_swing_bot.config.settings import Settings


def configured_mode_label(settings: Settings) -> str:
    if settings.dry_run:
        return f"{settings.live_mode}/dry-run"
    if not settings.live_armed:
        return f"{settings.live_mode}/disarmed"
    return f"{settings.live_mode}/armed"
