"""Notifier port and Telegram / null implementations."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Protocol

from rsi_cross_swing_bot.config.settings import Settings

log = logging.getLogger("rsi.notify")


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


class NullNotifier:
    def send(self, text: str) -> None:
        log.info("notify: %s", text)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    def send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        body = json.dumps(
            {"chat_id": self._chat_id, "text": text, "disable_web_page_preview": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
        except urllib.error.URLError as exc:
            log.warning("telegram send failed: %s", exc)


def build_notifier(settings: Settings) -> Notifier:
    if settings.has_telegram():
        return TelegramNotifier(
            settings.telegram_bot_token.get_secret_value(),
            settings.telegram_chat_id,
        )
    return NullNotifier()
