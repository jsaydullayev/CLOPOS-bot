"""Telegram notifications to admins about serious errors."""

import logging
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.utils.recent import RecentKeys

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, bot: Bot, admin_ids: Iterable[int], *, cooldown: float = 300.0) -> None:
        """admin_ids is read on every notice, so admins added in the panel get them too."""
        self.bot = bot
        self.admin_ids = admin_ids
        self._sent = RecentKeys(cooldown)

    async def notify(self, text: str, *, key: str | None = None) -> None:
        """Send text to every admin; the same key is sent at most once per cooldown."""
        key = key or text
        if key in self._sent:
            return
        self._sent.add(key)
        for admin_id in sorted(self.admin_ids):
            try:
                await self.bot.send_message(chat_id=admin_id, text=text)
            except TelegramAPIError as error:
                logger.warning("Could not notify admin %s: %s", admin_id, error)
