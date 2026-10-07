"""Texts the admin writes in the bot: the greeting and section introductions.

A text is kept as Telegram HTML (message.html_text), so the bold, italic and
links the admin used survive. A text the admin never changed comes from
locales/uz.toml. The greeting can also carry a photo.
"""

import re
from dataclasses import dataclass

from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.services.catalog import CatalogError
from bot.texts import t

# Photo captions are limited to 1024 characters, so a text must fit under a photo.
TEXT_MAX = 1000

# Texts the admin can change in «✏️ Matnlar», with the text key of their label.
EDITABLE_TEXTS: dict[str, str] = {
    "main_menu": "text_label_main_menu",
    "main_menu_empty": "text_label_main_menu_empty",
}
# Texts that can be shown with a photo.
PHOTO_TEXTS = frozenset({"main_menu"})

# Bots cannot always send premium custom emoji; keep the ordinary emoji it stands for.
_CUSTOM_EMOJI = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Photo:
    file_id: str
    file_unique_id: str


async def text_for(session: AsyncSession, key: str) -> str:
    row = await repo.get_custom_text(session, key)
    return row.value if row is not None and row.value else t(key)


async def photo_for(session: AsyncSession, key: str) -> Photo | None:
    row = await repo.get_custom_text(session, key)
    if row is None or not row.photo_file_id or not row.photo_unique_id:
        return None
    return Photo(row.photo_file_id, row.photo_unique_id)


def text_from_message(message: Message) -> str:
    """The admin's text (or photo caption) as HTML, checked for length."""
    plain = message.text if message.text is not None else message.caption
    if not plain or not plain.strip():
        raise CatalogError("error_expected_text")
    if len(plain) > TEXT_MAX:
        raise CatalogError("error_text_length", max=TEXT_MAX)
    return _CUSTOM_EMOJI.sub(r"\1", message.html_text).strip()


def photo_from_message(message: Message) -> Photo | None:
    if not message.photo:
        return None
    largest = message.photo[-1]
    return Photo(largest.file_id, largest.file_unique_id)
