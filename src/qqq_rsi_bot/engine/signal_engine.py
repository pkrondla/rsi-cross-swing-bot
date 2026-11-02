"""Pure QQQ RSI-cross rules. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from qqq_rsi_bot.core.models import EntryReason, SignalAction
from qqq_rsi_bot.core.signal_id import entry_signal_id, exit_signal_id
from qqq_rsi_bot.indicators import ema, rsi_wilder, sma


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    session_date: date
    close: float
    rsi: float
    rsi_ma: float
    ema200: float
    prev_rsi: float
    prev_rsi_ma: float


@dataclass(frozen=True, slots=True)
class SignalDecision:
    action: SignalAction
    signal_id: str | None
    reason: EntryReason | None
    snapshot: IndicatorSnapshot
    bullish_cross: bool
    bearish_cross: bool


def compute_snapshot(
    closes: list[float],
    session_dates: list[date],
    *,
    rsi_period: int = 14,
    rsi_ma_period: int = 14,
    ema_period: int = 200,
) -> IndicatorSnapshot | None:
    """Build the latest forming-day snapshot, or None if indicators are not ready."""
    if len(closes) != len(session_dates) or not closes:
        raise ValueError("closes and session_dates must be the same non-empty length")
    rsi = rsi_wilder(closes, rsi_period)
    rsi_ma_series = _sma_of_optional(rsi, rsi_ma_period)
    ema_series = ema(closes, ema_period)

    i = len(closes) - 1
    if i < 1:
        return None
    cur_rsi, prev_rsi = rsi[i], rsi[i - 1]
    cur_ma, prev_ma = rsi_ma_series[i], rsi_ma_series[i - 1]
    cur_ema = ema_series[i]
    if cur_rsi is None or prev_rsi is None or cur_ma is None or prev_ma is None or cur_ema is None:
        return None
    return IndicatorSnapshot(
        session_date=session_dates[i],
        close=closes[i],
        rsi=cur_rsi,
        rsi_ma=cur_ma,
        ema200=cur_ema,
        prev_rsi=prev_rsi,
        prev_rsi_ma=prev_ma,
    )


def evaluate(
    snapshot: IndicatorSnapshot,
    *,
    bot_qty: int,
    oversold_rsi_max: float = 50.0,
) -> SignalDecision:
    """Decide ENTER / EXIT / HOLD from a confirmed daily snapshot and bot quantity."""
    bullish = snapshot.prev_rsi <= snapshot.prev_rsi_ma and snapshot.rsi > snapshot.rsi_ma
    bearish = snapshot.prev_rsi >= snapshot.prev_rsi_ma and snapshot.rsi < snapshot.rsi_ma

    if bot_qty > 0 and bearish:
        return SignalDecision(
            action=SignalAction.EXIT,
            signal_id=exit_signal_id(snapshot.session_date),
            reason=None,
            snapshot=snapshot,
            bullish_cross=bullish,
            bearish_cross=True,
        )

    if bot_qty <= 0 and bullish:
        oversold = snapshot.rsi < oversold_rsi_max
        trend = snapshot.close > snapshot.ema200
        if oversold or trend:
            if oversold and trend:
                reason = EntryReason.BOTH
            elif oversold:
                reason = EntryReason.OVERSOLD
            else:
                reason = EntryReason.TREND
            return SignalDecision(
                action=SignalAction.ENTER,
                signal_id=entry_signal_id(snapshot.session_date, reason),
                reason=reason,
                snapshot=snapshot,
                bullish_cross=True,
                bearish_cross=False,
            )

    return SignalDecision(
        action=SignalAction.HOLD,
        signal_id=None,
        reason=None,
        snapshot=snapshot,
        bullish_cross=bullish,
        bearish_cross=bearish,
    )


def _sma_of_optional(values: list[float | None], period: int) -> list[float | None]:
    """SMA over the non-None values, written back onto the original index grid."""
    out: list[float | None] = [None] * len(values)
    nums: list[float] = []
    idxs: list[int] = []
    for i, value in enumerate(values):
        if value is None:
            continue
        nums.append(value)
        idxs.append(i)
    for j, avg in enumerate(sma(nums, period)):
        if avg is not None:
            out[idxs[j]] = avg
    return out
