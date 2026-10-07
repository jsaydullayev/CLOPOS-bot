"""Keeps exactly one active bot message per chat.

Moving between screens edits that message. When the screen type changes
(a text list <-> a video or the greeting photo), the new message is sent first
and the old one is deleted, as the TZ requires (sections 4.5 and 6).
"""

import logging
import time
from contextlib import suppress

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    MaybeInaccessibleMessageUnion,
    Message,
)

from bot.db.models import MEDIA_ANIMATION, MEDIA_PHOTO, User
from bot.ui.screen import Media, Screen

logger = logging.getLogger(__name__)

# A second tap on a message that was just replaced is a double click, not a request.
REPLACED_TTL = 10.0


class ReplacedRegistry:
    """Messages the bot replaced a moment ago, to ignore double clicks on them."""

    def __init__(self, ttl: float = REPLACED_TTL) -> None:
        self.ttl = ttl
        self._replaced: dict[int, dict[int, float]] = {}

    def mark(self, chat_id: int, message_id: int) -> None:
        self._purge(chat_id)
        self._replaced.setdefault(chat_id, {})[message_id] = time.monotonic()

    def is_recent(self, chat_id: int, message_id: int) -> bool:
        self._purge(chat_id)
        return message_id in self._replaced.get(chat_id, {})

    def _purge(self, chat_id: int) -> None:
        messages = self._replaced.get(chat_id)
        if not messages:
            return
        deadline = time.monotonic() - self.ttl
        for message_id in [mid for mid, at in messages.items() if at < deadline]:
            del messages[message_id]
        if not messages:
            del self._replaced[chat_id]


def media_unique_id(message: MaybeInaccessibleMessageUnion | None) -> str | None:
    photos = getattr(message, "photo", None)
    media = getattr(message, "video", None) or getattr(message, "animation", None) or (photos[-1] if photos else None)
    return media.file_unique_id if media is not None else None


class Display:
    def __init__(self, bot: Bot, registry: ReplacedRegistry, *, protect_content: bool = False) -> None:
        self.bot = bot
        self.registry = registry
        self.protect_content = protect_content

    async def show(
        self,
        user: User,
        screen: Screen,
        *,
        source: MaybeInaccessibleMessageUnion | None = None,
        edit: bool = True,
    ) -> int:
        """Show the screen as the user's only active message and return its id.

        source: the message whose button was pressed. Without it, the user's
        last active message is edited (or replaced when edit=False).
        """
        chat_id = source.chat.id if source is not None else user.id
        previous = user.last_message_id
        target = source.message_id if source is not None else (previous if edit else None)

        message_id: int | None = None
        current_unique_id = media_unique_id(source)
        if source is None:
            # The type of the previous message is unknown. Editing text fails cleanly on a
            # video message, so it is safe to try; a video always goes out as a new message.
            same_type = not screen.is_media
        else:
            same_type = (current_unique_id is not None) == screen.is_media
        if target is not None and same_type:
            message_id = await self._edit(chat_id, target, screen, current_unique_id)
        if message_id is None:
            message_id = (await self._send(chat_id, screen)).message_id
            if target is not None:
                await self.delete(chat_id, target)
        if previous is not None and previous not in (message_id, target):
            await self.delete(chat_id, previous)
        user.last_message_id = message_id
        return message_id

    async def delete(self, chat_id: int, message_id: int) -> None:
        """Delete quietly: messages older than 48 hours cannot be deleted."""
        self.registry.mark(chat_id, message_id)
        with suppress(TelegramAPIError):
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)

    async def _edit(self, chat_id: int, message_id: int, screen: Screen, current_unique_id: str | None) -> int | None:
        try:
            if screen.media is None:
                await self.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=screen.text, reply_markup=screen.markup
                )
            elif current_unique_id is not None and current_unique_id == screen.media.file_unique_id:
                # Same video or photo: only the caption and buttons change.
                await self.bot.edit_message_caption(
                    chat_id=chat_id, message_id=message_id, caption=screen.media.caption, reply_markup=screen.markup
                )
            else:
                await self.bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=_input_media(screen.media),
                    reply_markup=screen.markup,
                )
        except TelegramBadRequest as error:
            if "not modified" in error.message.lower():
                return message_id
            logger.debug("Message %s was not edited (%s), sending a new one", message_id, error.message)
            return None
        return message_id

    async def _send(self, chat_id: int, screen: Screen) -> Message:
        if screen.media is None:
            return await self.bot.send_message(chat_id=chat_id, text=screen.text, reply_markup=screen.markup)
        if screen.media.media_type == MEDIA_PHOTO:
            try:
                return await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=screen.media.file_id,
                    caption=screen.media.caption,
                    reply_markup=screen.markup,
                )
            except TelegramBadRequest as error:
                # The greeting photo is decoration: if it cannot be sent (for example its
                # file_id belonged to a previous bot), the menu goes out without it.
                logger.warning("Photo %s was not sent (%s), sending text only", screen.media.file_id, error.message)
                return await self.bot.send_message(
                    chat_id=chat_id, text=screen.media.caption, reply_markup=screen.markup
                )
        if screen.media.media_type == MEDIA_ANIMATION:
            return await self.bot.send_animation(
                chat_id=chat_id,
                animation=screen.media.file_id,
                caption=screen.media.caption,
                reply_markup=screen.markup,
                protect_content=self.protect_content,
            )
        return await self.bot.send_video(
            chat_id=chat_id,
            video=screen.media.file_id,
            caption=screen.media.caption,
            reply_markup=screen.markup,
            protect_content=self.protect_content,
        )


def _input_media(media: Media) -> InputMediaVideo | InputMediaAnimation | InputMediaPhoto:
    if media.media_type == MEDIA_PHOTO:
        return InputMediaPhoto(media=media.file_id, caption=media.caption, parse_mode=ParseMode.HTML)
    if media.media_type == MEDIA_ANIMATION:
        return InputMediaAnimation(media=media.file_id, caption=media.caption, parse_mode=ParseMode.HTML)
    return InputMediaVideo(media=media.file_id, caption=media.caption, parse_mode=ParseMode.HTML)
