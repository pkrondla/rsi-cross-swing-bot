"""Hourly forming updates and the one-shot end-of-day decision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from rsi_cross_swing_bot.config.fingerprint import strategy_hash
from rsi_cross_swing_bot.config.settings import AppConfig, Settings
from rsi_cross_swing_bot.core.clock import ET, Clock
from rsi_cross_swing_bot.core.models import Bar, Quote, SignalAction
from rsi_cross_swing_bot.core.signal_id import order_ref
from rsi_cross_swing_bot.engine.signal_engine import (
    IndicatorSnapshot,
    SignalDecision,
    compute_snapshot,
    evaluate,
)
from rsi_cross_swing_bot.execution.models import OrderIntent
from rsi_cross_swing_bot.execution.order_manager import OrderManager
from rsi_cross_swing_bot.risk.gate import RiskGate
from rsi_cross_swing_bot.runtime.calendar import (
    decision_datetime,
    in_decision_window,
    is_trading_day,
)
from rsi_cross_swing_bot.runtime.day_stop import is_stopped
from rsi_cross_swing_bot.runtime.halt import is_halted, set_halt
from rsi_cross_swing_bot.runtime.heartbeat import write_heartbeat
from rsi_cross_swing_bot.runtime.notify import Notifier
from rsi_cross_swing_bot.storage.store import TradeStore


class MarketSource(Protocol):
    def daily_bars(self, symbol: str, end: date, days: int) -> list[Bar]: ...

    def quote(self, symbol: str) -> Quote: ...

    def available_usd_cash(self, account: str) -> float: ...

    def position_qty(self, account: str, symbol: str) -> int: ...


@dataclass(slots=True)
class FormingState:
    session_date: date
    rsi: float
    rsi_ma: float
    close: float
    ema200: float
    bullish_cross: bool
    bearish_cross: bool
    action: SignalAction


class TradingSession:
    def __init__(
        self,
        *,
        settings: Settings,
        cfg: AppConfig,
        clock: Clock,
        data: MarketSource,
        store: TradeStore,
        risk: RiskGate,
        orders: OrderManager,
        notifier: Notifier,
        data_dir: Path,
        allocated_usd: float,
    ) -> None:
        self.settings = settings
        self.cfg = cfg
        self.clock = clock
        self.data = data
        self.store = store
        self.risk = risk
        self.orders = orders
        self.notifier = notifier
        self.data_dir = data_dir
        self.allocated_usd = allocated_usd
        self._last_forming: FormingState | None = None
        self._decision_done_for: date | None = None

    def hourly_update(self) -> FormingState | None:
        now = self.clock.now().astimezone(ET)
        write_heartbeat(self.data_dir / self.cfg.runtime.heartbeat_path, now, "hourly")
        if not is_trading_day(now.date()):
            return None
        snap = self._snapshot(now.date())
        if snap is None:
            return None
        bot_qty = self.store.bot_position(self.cfg.strategy.execution_symbol).quantity
        decision = evaluate(
            snap,
            bot_qty=bot_qty,
            oversold_rsi_max=self.cfg.strategy.oversold_rsi_max,
            sleeve_id=self.cfg.strategy.sleeve_id,
        )
        state = FormingState(
            session_date=snap.session_date,
            rsi=snap.rsi,
            rsi_ma=snap.rsi_ma,
            close=snap.close,
            ema200=snap.ema200,
            bullish_cross=decision.bullish_cross,
            bearish_cross=decision.bearish_cross,
            action=decision.action,
        )
        if self._forming_changed(state):
            sleeve = self.cfg.strategy.sleeve_id
            self.notifier.send(
                f"[{sleeve}] {now.strftime('%H:%M')} ET forming: RSI {state.rsi:.2f} / "
                f"MA {state.rsi_ma:.2f} close {state.close:.2f} EMA200 {state.ema200:.2f} "
                f"→ {state.action.value}"
            )
            self._last_forming = state
        return state

    def run_decision(self) -> SignalDecision | None:
        now = self.clock.now().astimezone(ET)
        write_heartbeat(self.data_dir / self.cfg.runtime.heartbeat_path, now, "decision")
        day = now.date()
        if self._decision_done_for == day:
            return None
        if not in_decision_window(
            now,
            decision_time=self.cfg.runtime.decision_time,
            early_close_decision_time=self.cfg.runtime.early_close_decision_time,
        ):
            return None

        snap = self._snapshot(day)
        if snap is None or snap.session_date != day:
            self.notifier.send(f"{now.strftime('%H:%M')} ET decision skipped: bar not ready")
            return None

        symbol = self.cfg.strategy.execution_symbol
        bot_pos = self.store.bot_position(symbol)
        decision = evaluate(
            snap,
            bot_qty=bot_pos.quantity,
            oversold_rsi_max=self.cfg.strategy.oversold_rsi_max,
            sleeve_id=self.cfg.strategy.sleeve_id,
        )
        quote = self.data.quote(symbol)
        account_qty = self.data.position_qty(self.settings.ib_account, symbol)
        cash = self.data.available_usd_cash(self.settings.ib_account)
        sleeve = self.cfg.strategy.sleeve_id

        if bot_pos.quantity > 0 and account_qty < bot_pos.quantity:
            set_halt(self.data_dir, "account_qty_below_bot")
            self.notifier.send(
                f"[{sleeve}] HALT: account {symbol} {account_qty} < bot qty {bot_pos.quantity}"
            )
            return decision

        risk = self.risk.evaluate(
            decision,
            now=now,
            in_decision_window=True,
            bot_qty=bot_pos.quantity,
            account_tqqq_qty=account_qty,
            available_cash=cash,
            ask=quote.ask,
            bid=quote.bid,
            signal_already_used=bool(
                decision.signal_id and self.store.signal_exists(decision.signal_id)
            ),
            stopped_for_day=is_stopped(self.data_dir, day),
            halted=is_halted(self.data_dir),
            delayed_data=quote.delayed,
            bar_is_today=snap.session_date == day,
        )

        self.notifier.send(
            f"[{sleeve}] {now.strftime('%H:%M')} ET decision: {decision.action.value} "
            f"RSI {snap.rsi:.2f}/{snap.rsi_ma:.2f} close {snap.close:.2f} "
            f"EMA200 {snap.ema200:.2f} risk={risk.reason}"
        )
        self.store.append_event(
            "decision",
            {
                "action": decision.action.value,
                "rsi": snap.rsi,
                "rsi_ma": snap.rsi_ma,
                "close": snap.close,
                "ema200": snap.ema200,
                "risk": risk.reason,
            },
            ts=now,
            signal_id=decision.signal_id,
        )

        if decision.signal_id:
            self.store.record_signal(
                decision.signal_id,
                day,
                decision.action.value,
                "seen" if not risk.allowed else "accepted",
                strategy_hash(self.cfg.strategy),
                {
                    "rsi": snap.rsi,
                    "rsi_ma": snap.rsi_ma,
                    "close": snap.close,
                    "ema200": snap.ema200,
                    "reason": decision.reason.value if decision.reason else None,
                },
                reason=decision.reason.value if decision.reason else None,
            )

        if risk.allowed and decision.signal_id and risk.limit_price is not None:
            if risk.cash_cut:
                self.notifier.send(
                    f"[{sleeve}] Cash below allocation; sized to {risk.quantity} shares"
                )
            side = "BUY" if decision.action is SignalAction.ENTER else "SELL"
            intent = OrderIntent(
                signal_id=decision.signal_id,
                symbol=symbol,
                side=side,
                quantity=risk.quantity,
                limit_price=risk.limit_price,
                order_ref=order_ref(
                    decision.signal_id, self.cfg.strategy.order_ref_prefix
                ),
            )
            # Venue is chosen at wiring time: DryRunVenue never placeOrder;
            # IbVenue places only when LIVE_ARMED and DRY_RUN=false.
            record = self.orders.submit(intent, now)
            self.notifier.send(
                f"[{sleeve}] Order {record.status.value}: {side} {risk.quantity} {symbol} "
                f"@ {risk.limit_price:.2f} ({decision.signal_id})"
            )
            self.store.set_signal_status(decision.signal_id, record.status.value)

        self._decision_done_for = day
        return decision

    def _snapshot(self, day: date) -> IndicatorSnapshot | None:
        bars = self.data.daily_bars(
            self.cfg.strategy.signal_symbol,
            day,
            self.cfg.strategy.history_days,
        )
        if not bars:
            return None
        closes = [b.close for b in bars]
        dates = [b.session_date for b in bars]
        return compute_snapshot(
            closes,
            dates,
            rsi_period=self.cfg.strategy.rsi_period,
            rsi_ma_period=self.cfg.strategy.rsi_ma_period,
            ema_period=self.cfg.strategy.ema_period,
        )

    def _forming_changed(self, state: FormingState) -> bool:
        prev = self._last_forming
        if prev is None:
            return True
        return (
            prev.action != state.action
            or prev.bullish_cross != state.bullish_cross
            or prev.bearish_cross != state.bearish_cross
            or round(prev.rsi, 2) != round(state.rsi, 2)
        )


def decision_due(now: datetime, cfg: AppConfig) -> bool:
    local = now.astimezone(ET)
    if not is_trading_day(local.date()):
        return False
    target = decision_datetime(
        local.date(),
        decision_time=cfg.runtime.decision_time,
        early_close_decision_time=cfg.runtime.early_close_decision_time,
    )
    return local >= target
