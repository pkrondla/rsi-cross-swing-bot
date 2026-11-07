"""rsi-bot check and status helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from rsi_cross_swing_bot.app.context import AppContext
from rsi_cross_swing_bot.core.clock import SystemClock
from rsi_cross_swing_bot.engine.signal_engine import compute_snapshot
from rsi_cross_swing_bot.runtime.arming import configured_mode_label
from rsi_cross_swing_bot.runtime.dry_run_switch import effective_dry_run
from rsi_cross_swing_bot.runtime.halt import halt_reason, is_halted


@dataclass
class CheckStep:
    name: str
    ok: bool
    detail: str


def run_checks(ctx: AppContext) -> list[CheckStep]:
    steps: list[CheckStep] = []
    sig = ctx.cfg.strategy.signal_symbol
    exe = ctx.cfg.strategy.execution_symbol
    try:
        accounts = ctx.broker.accounts()
        steps.append(CheckStep("gateway", True, f"accounts={accounts}"))
        if ctx.settings.ib_account and ctx.settings.ib_account not in accounts:
            steps.append(
                CheckStep(
                    "account",
                    False,
                    f"{ctx.settings.ib_account} not in session {accounts}",
                )
            )
        else:
            steps.append(CheckStep("account", True, ctx.settings.ib_account or "(unset)"))
    except Exception as exc:  # noqa: BLE001
        steps.append(CheckStep("gateway", False, str(exc)))
        return steps

    today = SystemClock().now().date()
    try:
        bars = ctx.broker.daily_bars(sig, today, 400)
        snap = compute_snapshot(
            [b.close for b in bars],
            [b.session_date for b in bars],
            rsi_period=ctx.cfg.strategy.rsi_period,
            rsi_ma_period=ctx.cfg.strategy.rsi_ma_period,
            ema_period=ctx.cfg.strategy.ema_period,
        )
        ok = snap is not None and len(bars) >= ctx.cfg.strategy.ema_period
        steps.append(
            CheckStep(
                f"{sig.lower()}_history",
                ok,
                f"bars={len(bars)}" + (f" RSI={snap.rsi:.2f}" if snap else ""),
            )
        )
    except Exception as exc:  # noqa: BLE001
        steps.append(CheckStep(f"{sig.lower()}_history", False, str(exc)))

    try:
        q = ctx.broker.quote(exe)
        steps.append(
            CheckStep(
                f"{exe.lower()}_quote",
                not q.delayed and q.ask > 0,
                f"bid={q.bid} ask={q.ask} delayed={q.delayed}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        steps.append(CheckStep(f"{exe.lower()}_quote", False, str(exc)))

    steps.append(
        CheckStep(
            "telegram",
            ctx.settings.has_telegram(),
            "configured" if ctx.settings.has_telegram() else "disabled",
        )
    )
    steps.append(
        CheckStep(
            "database",
            ctx.database_path.parent.exists(),
            str(ctx.database_path),
        )
    )
    steps.append(
        CheckStep(
            "allocation",
            ctx.allocated_usd > 0,
            f"{ctx.allocated_usd:.2f}",
        )
    )
    steps.append(
        CheckStep(
            "sleeve",
            True,
            f"{ctx.sleeve_id} client_id={ctx.ib_client_id} {sig}->{exe}",
        )
    )
    return steps


def status_report(ctx: AppContext, day: date | None = None) -> str:
    day = day or SystemClock().now().date()
    pos = ctx.store.bot_position(ctx.cfg.strategy.execution_symbol)
    dry = effective_dry_run(ctx.data_dir, ctx.settings.dry_run)
    lines = [
        f"sleeve={ctx.sleeve_id}",
        f"pair={ctx.cfg.strategy.signal_symbol}->{ctx.cfg.strategy.execution_symbol}",
        f"mode={configured_mode_label(ctx.settings)} dry_run={dry}",
        f"allocated_usd={ctx.allocated_usd:.2f}",
        f"bot_qty={pos.quantity} avg={pos.avg_price:.4f}",
        f"halted={is_halted(ctx.data_dir)} {halt_reason(ctx.data_dir)}",
        f"client_id={ctx.ib_client_id}",
        f"day={day.isoformat()}",
    ]
    return "\n".join(lines)
