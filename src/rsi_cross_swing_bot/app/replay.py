"""Offline replay of daily closes through the same signal engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from rsi_cross_swing_bot.core.models import Bar, SignalAction
from rsi_cross_swing_bot.engine.signal_engine import compute_snapshot, evaluate
from rsi_cross_swing_bot.risk.gate import share_count


@dataclass(frozen=True, slots=True)
class ReplayTrade:
    day: date
    action: str
    reason: str | None
    signal_id: str
    quantity: int
    price: float


def replay_bars(
    bars: list[Bar],
    *,
    allocated_usd: float = 10_000.0,
    slippage_bps: float = 10.0,
    oversold_rsi_max: float = 50.0,
    rsi_period: int = 14,
    rsi_ma_period: int = 14,
    ema_period: int = 200,
    sleeve_id: str = "tqqq",
) -> list[ReplayTrade]:
    trades: list[ReplayTrade] = []
    bot_qty = 0
    closes = [b.close for b in bars]
    dates = [b.session_date for b in bars]
    for i in range(len(bars)):
        snap = compute_snapshot(
            closes[: i + 1],
            dates[: i + 1],
            rsi_period=rsi_period,
            rsi_ma_period=rsi_ma_period,
            ema_period=ema_period,
        )
        if snap is None:
            continue
        decision = evaluate(
            snap,
            bot_qty=bot_qty,
            oversold_rsi_max=oversold_rsi_max,
            sleeve_id=sleeve_id,
        )
        if decision.action is SignalAction.HOLD or decision.signal_id is None:
            continue
        px = bars[i].close
        if decision.action is SignalAction.ENTER:
            limit = px * (1.0 + slippage_bps / 10_000.0)
            qty, _ = share_count(allocated_usd, limit, allocated_usd)
            if qty < 1:
                continue
            trades.append(
                ReplayTrade(
                    day=snap.session_date,
                    action="ENTER",
                    reason=decision.reason.value if decision.reason else None,
                    signal_id=decision.signal_id,
                    quantity=qty,
                    price=limit,
                )
            )
            bot_qty = qty
        elif decision.action is SignalAction.EXIT and bot_qty > 0:
            limit = px * (1.0 - slippage_bps / 10_000.0)
            trades.append(
                ReplayTrade(
                    day=snap.session_date,
                    action="EXIT",
                    reason=None,
                    signal_id=decision.signal_id,
                    quantity=bot_qty,
                    price=limit,
                )
            )
            bot_qty = 0
    return trades
