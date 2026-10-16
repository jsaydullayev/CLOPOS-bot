"""Texts the admin writes in the bot: the greeting and section introductions.

A text is kept as Telegram HTML (message.html_text), so the bold, italic and
links the admin used survive. A text the admin never changed comes from
locales/uz.toml. The greeting can also carry a photo or a GIF (a video is made one).
"""

import logging
import re
from contextlib import suppress
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, Message
from aiogram.types import Video as TgVideo
from aiohttp import ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import MEDIA_ANIMATION, MEDIA_PHOTO, MEDIA_VIDEO
from bot.services.catalog import CatalogError
from bot.texts import t

logger = logging.getLogger(__name__)

# Photo and video captions are limited to 1024 characters, so a text must fit under them.
TEXT_MAX = 1000
# The largest file Telegram lets a bot download.
DOWNLOAD_MAX = 20 * 1024 * 1024

# The phone, usernames and links behind the «📞 Bog‘lanish va yordam» button.
CONTACTS_TEXT = "contacts"

# Texts the admin can change in «✏️ Matnlar», with the text key of their label.
EDITABLE_TEXTS: dict[str, str] = {
    "main_menu": "text_label_main_menu",
    "main_menu_empty": "text_label_main_menu_empty",
    CONTACTS_TEXT: "text_label_contacts",
}
# Texts that can be shown with a photo or video.
MEDIA_TEXTS = frozenset({"main_menu"})

# Bots cannot always send premium custom emoji; keep the ordinary emoji it stands for.
_CUSTOM_EMOJI = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Attachment:
    """A photo, video or animation shown with a text."""

    file_id: str
    file_unique_id: str
    media_type: str = MEDIA_PHOTO


async def text_for(session: AsyncSession, key: str) -> str:
    row = await repo.get_custom_text(session, key)
    return row.value if row is not None and row.value else t(key)


async def is_written(session: AsyncSession, key: str) -> bool:
    """The admin has written this text (a photo or video alone does not count)."""
    row = await repo.get_custom_text(session, key)
    return row is not None and bool(row.value)


async def attachment_for(session: AsyncSession, key: str) -> Attachment | None:
    row = await repo.get_custom_text(session, key)
    if row is None or not row.media_file_id or not row.media_unique_id:
        return None
    return Attachment(row.media_file_id, row.media_unique_id, row.media_type or MEDIA_PHOTO)


def text_from_message(message: Message) -> str:
    """The admin's text (or photo caption) as HTML, checked for length."""
    plain = message.text if message.text is not None else message.caption
    if not plain or not plain.strip():
        raise CatalogError("error_expected_text")
    if len(plain) > TEXT_MAX:
        raise CatalogError("error_text_length", max=TEXT_MAX)
    return _CUSTOM_EMOJI.sub(r"\1", message.html_text).strip()


def attachment_from_message(message: Message) -> Attachment | None:
    """The photo (its largest size), video or animation in the message."""
    if message.photo:
        largest = message.photo[-1]
        return Attachment(largest.file_id, largest.file_unique_id, MEDIA_PHOTO)
    if message.video is not None:
        return Attachment(message.video.file_id, message.video.file_unique_id, MEDIA_VIDEO)
    if message.animation is not None:
        # A silent video may arrive as an animation (GIF).
        return Attachment(message.animation.file_id, message.animation.file_unique_id, MEDIA_ANIMATION)
    return None


async def video_as_gif(bot: Bot, chat_id: int, video: TgVideo) -> Attachment:
    """The video uploaded again as an animation. Telegram shows a video with ▶️ until it is tapped;
    an animation plays by itself, silent and looped, like a GIF.

    The upload is a message in chat_id, deleted at once. CatalogError when it cannot be done.
    """
    if video.file_size is not None and video.file_size > DOWNLOAD_MAX:
        raise CatalogError("error_gif_too_big")
    try:
        data = await bot.download(video.file_id)
        assert data is not None  # without a destination the file comes back in memory
        upload = BufferedInputFile(data.read(), filename="greeting.mp4")
        sent = await bot.send_animation(chat_id=chat_id, animation=upload, disable_notification=True)
    except (TelegramAPIError, ClientError, TimeoutError) as error:
        logger.warning("Video %s was not made a GIF: %s", video.file_unique_id, error)
        raise CatalogError("error_gif_failed") from error
    with suppress(TelegramAPIError):
        await bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
    if sent.animation is None:
        # Telegram kept it a video, for example for its sound.
        raise CatalogError("error_gif_failed")
    return Attachment(sent.animation.file_id, sent.animation.file_unique_id, MEDIA_ANIMATION)


def is_media_file(message: Message) -> bool:
    """A picture or video sent as a file (document): it has to be sent again as a photo or video."""
    if message.document is None:
        return False
    return (message.document.mime_type or "").startswith(("image/", "video/"))
