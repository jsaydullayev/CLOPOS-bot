import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Hashable
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from typing import Any
from weakref import WeakValueDictionary

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.base import BaseEventIsolation, StorageKey
from aiogram.types import CallbackQuery, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import User
from bot.utils import clock
from bot.utils.recent import RecentKeys

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]

# The last activity is written at most this often: most taps then cost no write at all,
# and «📈 Foydalanuvchilar» counts are still right to a few minutes.
ACTIVITY_STEP = timedelta(minutes=5)


class KeyedLocks:
    """One lock per key. A lock lives only while an update holds or waits for it,
    so the table does not grow with every user ever seen."""

    def __init__(self) -> None:
        self._locks: WeakValueDictionary[Hashable, asyncio.Lock] = WeakValueDictionary()

    def __call__(self, key: Hashable) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock


class UserIsolation(BaseEventIsolation):
    """Handle one update per user in a chat at a time, so fast repeated taps run in order.

    aiogram takes this lock before it reads the FSM state, so a message sent right
    after a button press already sees the state that press set.
    """

    def __init__(self) -> None:
        self._locks = KeyedLocks()

    @asynccontextmanager
    async def lock(self, key: StorageKey) -> AsyncGenerator[None, None]:
        async with self._locks(key):
            yield

    async def close(self) -> None:
        pass


class ChannelQueueMiddleware(BaseMiddleware):
    """Channel posts have no user, so UserIsolation does not queue them: they are queued
    per channel here, and videos posted one after another are added in the same order."""

    def __init__(self) -> None:
        self._locks = KeyedLocks()

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        chat = data.get("event_chat")
        if data.get("event_from_user") is not None or chat is None:
            return await handler(event, data)
        async with self._locks(chat.id):
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
        now = clock.now()
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
            # Only changed values are written: a name rarely, the activity time once in a while.
            user.first_name = tg_user.first_name
            user.username = tg_user.username
            if now - clock.as_utc(user.last_active_at) >= ACTIVITY_STEP:
                user.last_active_at = now
        data["db_user"] = user
        return await handler(event, data)


class StaleCallbackMiddleware(BaseMiddleware):
    """Ignores taps on a message the bot has just replaced (a double click)."""

    def __init__(self, replaced: RecentKeys) -> None:
        self.replaced = replaced

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if isinstance(event, CallbackQuery) and event.message is not None:
            if (event.message.chat.id, event.message.message_id) in self.replaced:
                with suppress(TelegramAPIError):
                    await event.answer()
                return None
        return await handler(event, data)
