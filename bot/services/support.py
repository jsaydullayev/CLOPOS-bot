"""Problems clients write in the bot («✍️ Muammoni yozib qoldirish») reach every admin."""

import logging
import time
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from bot.texts import t
from bot.utils.text import html

logger = logging.getLogger(__name__)

# One message a minute per client is plenty for a problem and keeps a flood away from the admins.
COOLDOWN = 60.0


class SupportDesk:
    def __init__(self, bot: Bot, admin_ids: Iterable[int], *, cooldown: float = COOLDOWN) -> None:
        """admin_ids is read on every message, so admins added in the panel get them too."""
        self.bot = bot
        self.admin_ids = admin_ids
        self.cooldown = cooldown
        self._sent_at: dict[int, float] = {}

    def wait_left(self, user_id: int) -> int:
        """Seconds before the client may write again; 0 when they may now."""
        sent_at = self._sent_at.get(user_id)
        if sent_at is None:
            return 0
        return max(0, round(self.cooldown - (time.monotonic() - sent_at)))

    async def deliver(self, message: Message) -> int:
        """Copy the client's message to every admin, after a line on who wrote it.

        Returns how many admins got it: 0 means nobody did, and the client is told
        to call or write instead.
        """
        user = message.from_user
        assert user is not None
        who = html(user.full_name) + (f" · @{user.username}" if user.username else "")
        header = t("problem_header", who=who, id=user.id)
        chat_id, message_id = message.chat.id, message.message_id
        delivered = 0
        for admin_id in sorted(self.admin_ids):
            try:
                await self.bot.send_message(chat_id=admin_id, text=header)
                await self.bot.copy_message(chat_id=admin_id, from_chat_id=chat_id, message_id=message_id)
            except TelegramAPIError as error:
                # An admin who never started the bot cannot be written to.
                logger.warning("Problem from %s did not reach admin %s: %s", user.id, admin_id, error)
                continue
            delivered += 1
        if delivered:
            self._sent_at[user.id] = time.monotonic()
        logger.info("Problem from %s reached %d admins", user.id, delivered)
        return delivered
