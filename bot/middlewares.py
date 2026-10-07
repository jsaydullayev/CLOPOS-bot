import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import User
from bot.ui.display import ReplacedRegistry

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class UserLockMiddleware(BaseMiddleware):
    """Handle one update per user at a time, so fast repeated taps run in order.

    Channel posts have no user: they are queued per channel, so videos posted
    one after another are added in the same order.
    """

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        key = user.id if user is not None else chat.id if chat is not None else None
        if key is None:
            return await handler(event, data)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await handler(event, data)


class DbSessionMiddleware(BaseMiddleware):
    """One database session per update, committed when the handler succeeds."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            result = await handler(event, data)
            await session.commit()
            return result


class UserMiddleware(BaseMiddleware):
    """Registers the user on first contact and records the last activity."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        tg_user = data.get("event_from_user")
        chat = data.get("event_chat")
        if tg_user is None or tg_user.is_bot or chat is None or chat.type != ChatType.PRIVATE:
            data["db_user"] = None
            return await handler(event, data)

        session: AsyncSession = data["session"]
        now = datetime.now(UTC)
        user = await session.get(User, tg_user.id)
        if user is None:
            user = User(
                id=tg_user.id,
                first_name=tg_user.first_name,
                username=tg_user.username,
                created_at=now,
                last_active_at=now,
            )
            session.add(user)
        else:
            user.first_name = tg_user.first_name
            user.username = tg_user.username
            user.last_active_at = now
        data["db_user"] = user
        return await handler(event, data)


class StaleCallbackMiddleware(BaseMiddleware):
    """Ignores taps on a message the bot has just replaced (a double click)."""

    def __init__(self, registry: ReplacedRegistry) -> None:
        self.registry = registry

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        message = event.message if isinstance(event, CallbackQuery) else None
        if message is not None and self.registry.is_recent(message.chat.id, message.message_id):
            with suppress(TelegramAPIError):
                await event.answer()
            return None
        return await handler(event, data)
