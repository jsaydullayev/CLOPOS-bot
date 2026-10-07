"""Keeps exactly one active bot message per chat, and every screen is shown in it.

Moving between screens edits that one message, whatever the screens hold:
a text list becomes a video in place (Telegram can add media to a text message),
and a video becomes the cover with the list as its caption. A message with media
cannot turn back into plain text, so a text screen on it goes under the cover:
the greeting's photo or video, or assets/cover.png when the admin has not set one.
Only when Telegram cannot edit (a message older than 48 hours, a text too long for
a caption) is a new message sent and the old one deleted.
"""

import html
import logging
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    MaybeInaccessibleMessageUnion,
    Message,
)

from bot.db.models import MEDIA_ANIMATION, MEDIA_PHOTO, MEDIA_VIDEO, User
from bot.services.content import Attachment
from bot.ui.screen import Media, Screen

logger = logging.getLogger(__name__)

# A second tap on a message that was just replaced is a double click, not a request.
REPLACED_TTL = 10.0
# Telegram's limit for a photo or video caption.
CAPTION_MAX = 1024
DEFAULT_COVER = Path(__file__).resolve().parents[2] / "assets" / "cover.png"
_TAG = re.compile(r"<[^>]+>")


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


@dataclass(frozen=True, slots=True)
class Shown:
    """What a bot message holds now: text (media_type None), a photo, a video or an animation."""

    media_type: str | None = None
    unique_id: str | None = None


def shown_in(message: MaybeInaccessibleMessageUnion) -> Shown:
    if getattr(message, "video", None) is not None:
        return Shown(MEDIA_VIDEO, message.video.file_unique_id)
    if getattr(message, "animation", None) is not None:
        return Shown(MEDIA_ANIMATION, message.animation.file_unique_id)
    if getattr(message, "photo", None):
        return Shown(MEDIA_PHOTO, message.photo[-1].file_unique_id)
    return Shown()


class Display:
    def __init__(
        self,
        bot: Bot,
        registry: ReplacedRegistry,
        *,
        protect_content: bool = False,
        cover: Callable[[], Awaitable[Attachment | None]] | None = None,
    ) -> None:
        """cover: loads the photo or video text screens go under once the message holds a video."""
        self.bot = bot
        self.registry = registry
        self.protect_content = protect_content
        self._load_cover = cover
        self._default_cover_id: str | None = None  # file_id of assets/cover.png once uploaded

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
        if target is not None:
            message_id = await self._edit(chat_id, target, screen, shown_in(source) if source is not None else None)
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

    async def _edit(self, chat_id: int, message_id: int, screen: Screen, shown: Shown | None) -> int | None:
        """Turn the message into the screen. None when Telegram cannot; shown None: what it holds is unknown."""
        try:
            if screen.media is not None:
                if shown is not None and shown.unique_id == screen.media.file_unique_id:
                    # Same video or photo: only the caption and buttons change.
                    await self._edit_caption(chat_id, message_id, screen.media.caption, screen.markup)
                else:
                    # Works on a text message too: Telegram adds the media to it.
                    await self._edit_media(chat_id, message_id, _input_media(screen.media), screen.markup)
                return message_id

            assert screen.text is not None
            if shown is None or shown.media_type is None:
                try:
                    await self.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id, text=screen.text, reply_markup=screen.markup
                    )
                    return message_id
                except TelegramBadRequest as error:
                    # An unknown message without text holds media: the screen can still go in its caption.
                    if shown is not None or "no text" not in error.message.lower():
                        raise
            if screen.plain or _caption_length(screen.text) > CAPTION_MAX:
                return None
            if shown is not None and shown.media_type == MEDIA_PHOTO:
                # The photo stays (the greeting or the cover), the text goes into its caption.
                await self._edit_caption(chat_id, message_id, screen.text, screen.markup)
                return message_id
            cover = await self._load_cover() if self._load_cover is not None else None
            if shown is not None and cover is not None and shown.unique_id == cover.file_unique_id:
                # The greeting video is already there.
                await self._edit_caption(chat_id, message_id, screen.text, screen.markup)
            else:
                await self._edit_to_cover(chat_id, message_id, screen.text, screen.markup, cover)
            return message_id
        except TelegramBadRequest as error:
            if "not modified" in error.message.lower():
                return message_id
            logger.debug("Message %s was not edited (%s), sending a new one", message_id, error.message)
            return None

    async def _edit_caption(
        self, chat_id: int, message_id: int, caption: str, markup: InlineKeyboardMarkup | None
    ) -> None:
        await self.bot.edit_message_caption(
            chat_id=chat_id, message_id=message_id, caption=caption, reply_markup=markup
        )

    async def _edit_media(
        self,
        chat_id: int,
        message_id: int,
        media: InputMediaVideo | InputMediaAnimation | InputMediaPhoto,
        markup: InlineKeyboardMarkup | None,
    ) -> Message | bool:
        return await self.bot.edit_message_media(
            chat_id=chat_id, message_id=message_id, media=media, reply_markup=markup
        )

    async def _edit_to_cover(
        self,
        chat_id: int,
        message_id: int,
        caption: str,
        markup: InlineKeyboardMarkup | None,
        cover: Attachment | None,
    ) -> None:
        """A video message cannot become text again: the text goes under the cover."""
        if cover is not None:
            media = _input_media(Media(cover.file_id, cover.media_type, caption, cover.file_unique_id))
            await self._edit_media(chat_id, message_id, media, markup)
            return
        cover = self._default_cover_id or FSInputFile(DEFAULT_COVER)
        result = await self._edit_media(
            chat_id, message_id, InputMediaPhoto(media=cover, caption=caption, parse_mode=ParseMode.HTML), markup
        )
        if isinstance(result, Message) and result.photo:
            # Uploaded once; later edits reuse Telegram's copy.
            self._default_cover_id = result.photo[-1].file_id

    async def _send(self, chat_id: int, screen: Screen) -> Message:
        # protect_content is set when a message is sent and stays through every edit.
        if screen.media is None:
            return await self.bot.send_message(
                chat_id=chat_id, text=screen.text, reply_markup=screen.markup, protect_content=self.protect_content
            )
        try:
            return await self._send_media(chat_id, screen.media, screen.markup)
        except TelegramBadRequest as error:
            if not screen.media.optional:
                raise
            # The greeting's photo or video is decoration: if it cannot be sent (for example
            # its file_id belonged to a previous bot), the menu goes out without it.
            logger.warning("Media %s was not sent (%s), sending text only", screen.media.file_id, error.message)
            return await self.bot.send_message(
                chat_id=chat_id,
                text=screen.media.caption,
                reply_markup=screen.markup,
                protect_content=self.protect_content,
            )

    async def _send_media(self, chat_id: int, media: Media, markup: InlineKeyboardMarkup | None) -> Message:
        if media.media_type == MEDIA_PHOTO:
            return await self.bot.send_photo(
                chat_id=chat_id,
                photo=media.file_id,
                caption=media.caption,
                reply_markup=markup,
                protect_content=self.protect_content,
            )
        if media.media_type == MEDIA_ANIMATION:
            return await self.bot.send_animation(
                chat_id=chat_id,
                animation=media.file_id,
                caption=media.caption,
                reply_markup=markup,
                protect_content=self.protect_content,
            )
        return await self.bot.send_video(
            chat_id=chat_id,
            video=media.file_id,
            caption=media.caption,
            reply_markup=markup,
            protect_content=self.protect_content,
        )


def _caption_length(text: str) -> int:
    """Characters Telegram counts in a caption: the visible text, without the HTML tags."""
    return len(html.unescape(_TAG.sub("", text)))


def _input_media(media: Media) -> InputMediaVideo | InputMediaAnimation | InputMediaPhoto:
    if media.media_type == MEDIA_PHOTO:
        return InputMediaPhoto(media=media.file_id, caption=media.caption, parse_mode=ParseMode.HTML)
    if media.media_type == MEDIA_ANIMATION:
        return InputMediaAnimation(media=media.file_id, caption=media.caption, parse_mode=ParseMode.HTML)
    return InputMediaVideo(media=media.file_id, caption=media.caption, parse_mode=ParseMode.HTML)
