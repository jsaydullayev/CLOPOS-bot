"""The person an admin means: a shared contact, a forwarded message, @username or a numeric ID.

Used to add an admin and to find a user to open or delete.
"""

import re
from dataclasses import dataclass

from aiogram.types import Message, MessageOriginUser
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.services.catalog import CatalogError
from bot.texts import t

# @username or a t.me link to it.
_USERNAME = re.compile(r"(?:@|(?:https?://)?t\.me/)([A-Za-z][A-Za-z0-9_]{3,31})")
# Plain ASCII digits: str.isdigit() also passes «²», which int() refuses.
_USER_ID = re.compile(r"[0-9]{1,16}")
# Telegram user ids fit in 52 bits.
_MAX_USER_ID = 2**52


@dataclass(frozen=True, slots=True)
class Person:
    user_id: int
    name: str | None
    is_bot: bool = False


async def find_person(session: AsyncSession, message: Message) -> Person:
    if message.contact is not None:
        if message.contact.user_id is None:
            raise CatalogError("error_person_contact")
        name = " ".join(part for part in (message.contact.first_name, message.contact.last_name) if part)
        return Person(message.contact.user_id, name or None)
    origin = message.forward_origin
    if origin is not None:
        # A hidden sender, a chat or a channel gives no user id.
        if not isinstance(origin, MessageOriginUser):
            raise CatalogError("error_person_forward")
        sender = origin.sender_user
        return Person(sender.id, sender.full_name, sender.is_bot)
    text = (message.text or "").strip()
    if match := _USERNAME.fullmatch(text):
        # The Bot API cannot look a username up: only people who wrote to the bot are known.
        user = await repo.find_user_by_username(session, match.group(1))
        if user is None:
            raise CatalogError("error_person_username", username=match.group(1))
        return Person(user.id, user.first_name)
    if _USER_ID.fullmatch(text) and 0 < int(text) < _MAX_USER_ID:
        return Person(int(text), None)
    raise CatalogError("error_person_expected")


def person_name(user_id: int, first_name: str | None, username: str | None) -> str:
    """«Ali (@ali)», the first name or the @username alone, or «ID 123» when neither is known."""
    if first_name and username:
        return f"{first_name} (@{username})"
    return first_name or (f"@{username}" if username else t("admin_name_id", id=user_id))
