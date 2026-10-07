"""Telegram notifications to admins about serious errors."""

import logging
import time
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, bot: Bot, admin_ids: Iterable[int], *, cooldown: float = 300.0) -> None:
        self.bot = bot
        self.admin_ids = tuple(sorted(admin_ids))
        self.cooldown = cooldown
        self._sent_at: dict[str, float] = {}

    async def notify(self, text: str, *, key: str | None = None) -> None:
        """Send text to every admin; the same key is sent at most once per cooldown."""
        key = key or text
        now = time.monotonic()
        last = self._sent_at.get(key)
        if last is not None and now - last < self.cooldown:
            return
        self._sent_at[key] = now
        for admin_id in self.admin_ids:
            try:
                await self.bot.send_message(chat_id=admin_id, text=text)
            except TelegramAPIError as error:
                logger.warning("Could not notify admin %s: %s", admin_id, error)
