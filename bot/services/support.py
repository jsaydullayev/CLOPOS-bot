"""Problems clients leave in «📞 Bog‘lanish va yordam» become tickets the admins answer.

A ticket is stored first, so it is never lost, then posted to the support channel:
a copy of the client's message and a card under it with the buttons. The admins
answer through the bot («✍️ Javob berish» opens the ticket there); the answer goes
to the client from the bot, and only then can the ticket be marked done or not done.
"""

import logging
import math
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import date
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message, ReplyParameters
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.db.models import TICKET_ANSWERED, TICKET_DONE, TICKET_NEW, TICKET_NOT_DONE, Ticket
from bot.services.notify import Notifier
from bot.texts import t
from bot.utils import clock
from bot.utils.recent import RecentKeys
from bot.utils.text import html

logger = logging.getLogger(__name__)

# One problem a minute per client is plenty and keeps a flood away from the admins.
COOLDOWN = 60.0
# Telegram delivers an album as separate messages, all within a few seconds.
ALBUM_WAIT = 30.0
# What a client or an admin may send: text, or one of these with an optional caption.
MEDIA_TYPES = ("photo", "video", "animation", "voice", "audio", "document", "video_note")

# Builds the channel card: (ticket, admin names, link to the ticket in the bot, time zone) -> (text, buttons).
CardRenderer = Callable[[Ticket, dict[int, str], str, ZoneInfo], tuple[str, InlineKeyboardMarkup | None]]


def message_content(message: Message) -> tuple[str | None, str | None, str | None] | None:
    """(text, media type, file_id) of a message that can be a ticket or an answer; None otherwise."""
    for media_type in MEDIA_TYPES:  # an animation also comes as a document: it is checked first
        media = getattr(message, media_type)
        if media:
            file_id = media[-1].file_id if media_type == "photo" else media.file_id
            return message.caption, media_type, file_id
    if message.text:
        return message.text, None, None
    return None


class SupportDesk:
    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        notifier: Notifier,
        render_card: CardRenderer,
        *,
        cooldown: float = COOLDOWN,
    ) -> None:
        self.bot = bot
        self.channel_id = settings.support_channel_id
        self.tz = ZoneInfo(settings.timezone)
        self.notifier = notifier
        self.render_card = render_card
        self._written = RecentKeys(cooldown)  # clients who left a problem a moment ago
        self._albums = RecentKeys(ALBUM_WAIT)  # (client, media_group_id) of albums that became tickets

    def today(self) -> date:
        return clock.local(clock.now(), self.tz).date()

    def wait_left(self, user_id: int) -> int:
        """Seconds before the client may write again; 0 when they may now."""
        return math.ceil(self._written.left(user_id))

    async def link(self, ticket_id: int) -> str:
        """Opens the bot on the ticket: /start t<id>."""
        me = await self.bot.me()
        return f"https://t.me/{me.username}?start=t{ticket_id}"

    async def names(self, session: AsyncSession, ids: Iterable[int | None]) -> dict[int, str]:
        """First names of the admins who answered or marked tickets."""
        users = await repo.get_users(session, [user_id for user_id in ids if user_id is not None])
        return {user_id: user.first_name or t("admin_name_id", id=user_id) for user_id, user in users.items()}

    async def submit(self, session: AsyncSession, message: Message, phone: str | None) -> Ticket:
        """Store the client's problem with the phone they left, then post it to the support channel."""
        content = message_content(message)
        user = message.from_user
        assert content is not None and user is not None
        text, media_type, file_id = content
        ticket = await repo.add_ticket(
            session,
            Ticket(
                user_id=user.id,
                user_name=user.full_name[:255],
                username=user.username,
                phone=phone,
                text=text,
                media_type=media_type,
                file_id=file_id,
                status=TICKET_NEW,
                replies=0,
                created_at=clock.now(),
            ),
        )
        await session.commit()
        self._written.add(user.id)
        if message.media_group_id is not None:
            self._albums.add((user.id, message.media_group_id))
        await self._post(session, ticket, message)
        return ticket

    def is_album_part(self, message: Message) -> bool:
        """Another photo or video of an album whose first part became a ticket."""
        user = message.from_user
        return user is not None and (user.id, message.media_group_id) in self._albums

    async def add_album_part(self, session: AsyncSession, message: Message) -> None:
        """Copied to the support channel under the ticket, so the admins see the whole album."""
        assert message.from_user is not None
        ticket = await repo.last_ticket(session, message.from_user.id)
        if ticket is None or ticket.channel_id is None or ticket.channel_copy_id is None:
            return
        try:
            await self.bot.copy_message(
                chat_id=ticket.channel_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                reply_parameters=ReplyParameters(message_id=ticket.channel_copy_id),
            )
        except TelegramAPIError as error:
            logger.warning("A part of ticket %s's album was not posted: %s", ticket.id, error)

    async def _post(self, session: AsyncSession, ticket: Ticket, message: Message) -> None:
        if self.channel_id is None:
            await self.notifier.notify(t("ticket_notice", id=ticket.id), key=f"ticket:{ticket.id}")
            return
        text, markup = self.render_card(ticket, {}, await self.link(ticket.id), self.tz)
        try:
            copy = await self.bot.copy_message(
                chat_id=self.channel_id, from_chat_id=message.chat.id, message_id=message.message_id
            )
            card = await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                reply_markup=markup,
                reply_parameters=ReplyParameters(message_id=copy.message_id),
            )
        except TelegramAPIError as error:
            # The ticket is stored: the admins still find it in the panel.
            logger.warning("Ticket %s was not posted to the support channel: %s", ticket.id, error)
            await self.notifier.notify(
                t("ticket_post_failed", id=ticket.id, error=html(str(error))), key=f"ticket:{ticket.id}"
            )
            return
        ticket.channel_id = self.channel_id
        ticket.channel_copy_id, ticket.channel_card_id = copy.message_id, card.message_id
        await session.commit()

    async def reply(self, session: AsyncSession, ticket: Ticket, message: Message, admin_id: int) -> bool:
        """Send the admin's message to the client under a header. False when it cannot reach them."""
        header: Message | None = None
        try:
            header = await self.bot.send_message(chat_id=ticket.user_id, text=t("reply_header", id=ticket.id))
            await self.bot.copy_message(
                chat_id=ticket.user_id, from_chat_id=message.chat.id, message_id=message.message_id
            )
        except TelegramAPIError as error:
            # The client blocked the bot or deleted the account.
            logger.info("Answer to ticket %s did not reach the client: %s", ticket.id, error)
            if header is not None:
                # A header without the answer would only puzzle the client; the admin sends it again.
                with suppress(TelegramAPIError):
                    await self.bot.delete_message(chat_id=ticket.user_id, message_id=header.message_id)
            return False
        ticket.replies += 1
        ticket.answered_at, ticket.answered_by = clock.now(), admin_id
        if ticket.status == TICKET_NEW:
            ticket.status = TICKET_ANSWERED
        await session.commit()
        await self.refresh_card(session, ticket)
        return True

    async def mark(self, session: AsyncSession, ticket: Ticket, *, done: bool, admin_id: int) -> bool:
        """Done or not done, once the client has an answer. False while there is none."""
        if ticket.replies == 0:
            return False
        ticket.status = TICKET_DONE if done else TICKET_NOT_DONE
        ticket.resolved_at, ticket.resolved_by = clock.now(), admin_id
        await session.commit()
        await self.refresh_card(session, ticket)
        return True

    async def refresh_card(self, session: AsyncSession, ticket: Ticket) -> None:
        """Show the ticket's new state on its card in the channel."""
        if ticket.channel_id is None or ticket.channel_card_id is None:
            return
        names = await self.names(session, [ticket.answered_by, ticket.resolved_by])
        text, markup = self.render_card(ticket, names, await self.link(ticket.id), self.tz)
        try:
            await self.bot.edit_message_text(
                chat_id=ticket.channel_id, message_id=ticket.channel_card_id, text=text, reply_markup=markup
            )
        except TelegramAPIError as error:
            # Not modified (a second tap), or the card was deleted from the channel.
            logger.info("Card of ticket %s was not updated: %s", ticket.id, error)

    async def send_file(self, chat_id: int, ticket: Ticket) -> None:
        """The client's attachment as a message of its own: send_voice(voice=…), send_document(document=…)…"""
        assert ticket.media_type is not None and ticket.file_id is not None
        send = getattr(self.bot, f"send_{ticket.media_type}")
        await send(chat_id=chat_id, **{ticket.media_type: ticket.file_id})

    async def report(self, session: AsyncSession, day: date) -> repo.TicketCounts:
        start, end = clock.day_bounds(day, self.tz)
        return await repo.ticket_counts(session, start, end)
