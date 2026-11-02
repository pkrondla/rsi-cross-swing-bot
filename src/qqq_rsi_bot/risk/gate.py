"""Pre-trade risk gate: size, window, ownership, and idempotency vetoes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import floor

from qqq_rsi_bot.core.models import SignalAction
from qqq_rsi_bot.engine.signal_engine import SignalDecision


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    quantity: int
    limit_price: float | None
    reason: str
    cash_cut: bool = False


def share_count(
    allocated_usd: float, limit_price: float, available_cash: float
) -> tuple[int, bool]:
    """Whole shares from the sleeve, capped by cash. Returns (qty, cash_was_cut)."""
    if limit_price <= 0:
        return 0, False
    budget = min(allocated_usd, available_cash)
    cash_cut = available_cash < allocated_usd
    return max(0, int(floor(budget / limit_price))), cash_cut


class RiskGate:
    def __init__(
        self,
        *,
        allocated_usd: float,
        min_shares: int = 1,
        slippage_bps: float = 10.0,
    ) -> None:
        self.allocated_usd = allocated_usd
        self.min_shares = min_shares
        self.slippage_bps = slippage_bps

    def evaluate(
        self,
        decision: SignalDecision,
        *,
        now: datetime,
        in_decision_window: bool,
        bot_qty: int,
        account_tqqq_qty: int,
        available_cash: float,
        ask: float,
        bid: float,
        signal_already_used: bool,
        stopped_for_day: bool,
        halted: bool,
        delayed_data: bool,
        bar_is_today: bool,
    ) -> RiskDecision:
        if halted:
            return RiskDecision(False, 0, None, "halted")
        if stopped_for_day:
            return RiskDecision(False, 0, None, "stopped_for_day")
        if not in_decision_window:
            return RiskDecision(False, 0, None, "outside_decision_window")
        if delayed_data:
            return RiskDecision(False, 0, None, "delayed_data")
        if not bar_is_today:
            return RiskDecision(False, 0, None, "bar_not_today")
        if decision.action is SignalAction.HOLD or decision.signal_id is None:
            return RiskDecision(False, 0, None, "hold")
        if signal_already_used:
            return RiskDecision(False, 0, None, "signal_already_used")

        if decision.action is SignalAction.ENTER:
            if bot_qty > 0:
                return RiskDecision(False, 0, None, "already_long")
            if ask <= 0:
                return RiskDecision(False, 0, None, "bad_ask")
            limit = ask * (1.0 + self.slippage_bps / 10_000.0)
            qty, cash_cut = share_count(self.allocated_usd, limit, available_cash)
            if qty < self.min_shares:
                return RiskDecision(False, 0, limit, "shares_below_min")
            return RiskDecision(True, qty, round(limit, 2), "ok", cash_cut=cash_cut)

        # EXIT
        if bot_qty <= 0:
            return RiskDecision(False, 0, None, "flat")
        if account_tqqq_qty < bot_qty:
            return RiskDecision(False, 0, None, "account_qty_below_bot")
        if bid <= 0:
            return RiskDecision(False, 0, None, "bad_bid")
        limit = bid * (1.0 - self.slippage_bps / 10_000.0)
        return RiskDecision(True, bot_qty, round(limit, 2), "ok")
