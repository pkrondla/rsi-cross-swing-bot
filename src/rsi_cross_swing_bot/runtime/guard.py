"""Startup safety checks. Real orders need mode + armed + dry_run=false + matching IB account."""

from __future__ import annotations

from rsi_cross_swing_bot.config.settings import Settings
from rsi_cross_swing_bot.core.errors import SafetyViolationError


class SafetyError(SafetyViolationError, RuntimeError):
    pass


def assert_order_config(settings: Settings) -> None:
    if settings.dry_run:
        return
    if not settings.live_armed:
        raise SafetyError("DRY_RUN=false needs LIVE_ARMED=true.")
    if not settings.ib_account.strip():
        raise SafetyError("DRY_RUN=false needs IB_ACCOUNT.")
    account = settings.ib_account.strip()
    if settings.live_mode == "paper":
        if not account.startswith("DU"):
            raise SafetyError("Paper mode needs an IB paper account id starting with DU.")
        if settings.ib_port not in {7497, 4002}:
            raise SafetyError(
                f"Paper mode expects IB port 7497 (TWS) or 4002 (Gateway); got {settings.ib_port}."
            )
    elif settings.live_mode == "live":
        if account.startswith("DU"):
            raise SafetyError("Live mode refuses a DU paper account id.")
        if settings.ib_port not in {7496, 4001}:
            raise SafetyError(
                f"Live mode expects IB port 7496 (TWS) or 4001 (Gateway); got {settings.ib_port}."
            )
    else:
        raise SafetyError(f"Unknown LIVE_MODE {settings.live_mode!r}.")


def assert_allocated(settings: Settings, allocated_usd: float) -> None:
    if allocated_usd <= 0:
        raise SafetyError("ALLOCATED_USD must be positive.")


def run_startup_checks(settings: Settings, allocated_usd: float) -> None:
    assert_order_config(settings)
    assert_allocated(settings, allocated_usd)
