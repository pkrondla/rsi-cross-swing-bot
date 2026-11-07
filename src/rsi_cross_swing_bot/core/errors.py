"""Error taxonomy: every failure belongs to a family with one reaction."""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar


class Reaction(StrEnum):
    RETRY = "retry"
    REJECT_SIGNAL = "reject_signal"
    STOP = "stop"
    HALT = "halt"


class BotError(Exception):
    reaction: ClassVar[Reaction] = Reaction.STOP


class DataUnavailableError(BotError):
    reaction: ClassVar[Reaction] = Reaction.RETRY


class TradePlanError(BotError):
    reaction: ClassVar[Reaction] = Reaction.REJECT_SIGNAL


class SafetyViolationError(BotError):
    reaction: ClassVar[Reaction] = Reaction.STOP


class ConfigurationError(BotError):
    reaction: ClassVar[Reaction] = Reaction.STOP


class BrokerRejectionError(BotError):
    reaction: ClassVar[Reaction] = Reaction.REJECT_SIGNAL


class RiskBreachError(BotError):
    reaction: ClassVar[Reaction] = Reaction.HALT


def reaction_for(exc: BaseException, default: Reaction = Reaction.STOP) -> Reaction:
    if isinstance(exc, BotError):
        return exc.reaction
    return default


def must_halt(exc: BaseException, default: Reaction = Reaction.RETRY) -> bool:
    return reaction_for(exc, default) in {Reaction.STOP, Reaction.HALT}
