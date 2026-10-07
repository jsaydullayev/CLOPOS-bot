import os
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ChatType, ParseMode
from aiogram.methods import (
    DeleteMessage,
    EditMessageMedia,
    ForwardMessage,
    SendAnimation,
    SendDocument,
    SendMessage,
    SendPhoto,
    SendVideo,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Dice, Document, Message, MessageEntity, PhotoSize, Update
from aiogram.types import User as TgUser
from aiogram.types import Video as TgVideo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bot.app import create_dispatcher
from bot.config import Settings
from bot.db.models import Base, User
from bot.db.session import create_engine, create_session_factory

ADMIN_ID = 1
CLIENT_ID = 2
CHANNEL_ID = -1001000
BOT_TOKEN = "42:TEST"


def file_id_of(unique_id: str) -> str:
    return f"file-{unique_id}"


class FakeTelegram(BaseSession):
    """Records Bot API calls and answers them the way Telegram would."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.media: dict[int, str] = {}  # message id -> file_id of the video in it
        self.forwarded: dict[int, TgVideo] = {}  # archive post id -> video returned by ForwardMessage
        self._errors: list[tuple[type, Exception]] = []
        self._message_ids = count(1000)

    def fail_once(self, method_type: type, error: Exception) -> None:
        self._errors.append((method_type, error))

    def of(self, *types: type) -> list[Any]:
        return [call for call in self.calls if isinstance(call, types)]

    def calls_with_markup(self) -> list[Any]:
        """Calls that showed buttons: sent or edited screens of any kind."""
        return [call for call in self.calls if getattr(call, "reply_markup", None) is not None]

    def reset(self) -> None:
        self.calls.clear()

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:  # pragma: no cover
        raise NotImplementedError
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.calls.append(method)
        for index, (method_type, error) in enumerate(self._errors):
            if isinstance(method, method_type):
                del self._errors[index]
                raise error

        if isinstance(method, (SendMessage, SendVideo, SendAnimation, SendPhoto, SendDocument, ForwardMessage)):
            message_id = next(self._message_ids)
            chat_type = ChatType.PRIVATE if method.chat_id > 0 else ChatType.CHANNEL
            video = None
            if isinstance(method, SendVideo):
                self.media[message_id] = method.video
            elif isinstance(method, SendAnimation):
                self.media[message_id] = method.animation
            elif isinstance(method, SendPhoto):
                self.media[message_id] = method.photo
            elif isinstance(method, ForwardMessage):
                video = self.forwarded.get(method.message_id)
            return Message(
                message_id=message_id,
                date=datetime.now(UTC),
                chat=Chat(id=method.chat_id, type=chat_type),
                video=video,
            )
        if isinstance(method, EditMessageMedia):
            self.media[method.message_id] = method.media.media
        if isinstance(method, DeleteMessage):
            self.media.pop(method.message_id, None)
        return True


def database_url(tmp_path: Any) -> str:
    """SQLite by default; set TEST_DATABASE_URL to run the same tests on PostgreSQL."""
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"


@pytest.fixture
async def engine(tmp_path: Any) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url(tmp_path))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
async def bot(telegram: FakeTelegram) -> AsyncIterator[Bot]:
    bot = Bot(token=BOT_TOKEN, session=telegram, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    yield bot


def make_settings(database_url: str = "sqlite+aiosqlite://", **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "bot_token": BOT_TOKEN,
        "admin_ids": frozenset({ADMIN_ID}),
        "database_url": database_url,
        "backup_channel_id": CHANNEL_ID,
        "db_backup_enabled": False,
        "max_depth": 3,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class Harness:
    """Feeds updates to the dispatcher as if users were tapping in Telegram."""

    def __init__(
        self,
        bot: Bot,
        telegram: FakeTelegram,
        dispatcher: Dispatcher,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.bot = bot
        self.telegram = telegram
        self.dispatcher = dispatcher
        self.session_factory = session_factory
        self._update_ids = count(1)
        self._user_message_ids = count(1)
        self._callback_ids = count(1)

    async def _feed(self, **update: Any) -> None:
        await self.dispatcher.feed_update(self.bot, Update(update_id=next(self._update_ids), **update))

    def _message(self, user_id: int, **content: Any) -> Message:
        return Message(
            message_id=next(self._user_message_ids),
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type=ChatType.PRIVATE),
            from_user=TgUser(id=user_id, is_bot=False, first_name=f"User{user_id}"),
            **content,
        )

    async def send_text(self, user_id: int, text: str) -> int:
        message = self._message(user_id, text=text)
        await self._feed(message=message)
        return message.message_id

    async def send_video(self, user_id: int, unique_id: str, caption: str | None = None) -> int:
        video = TgVideo(file_id=file_id_of(unique_id), file_unique_id=unique_id, width=1, height=1, duration=1)
        message = self._message(user_id, video=video, caption=caption)
        await self._feed(message=message)
        return message.message_id

    async def send_photo(
        self,
        user_id: int,
        unique_id: str,
        caption: str | None = None,
        caption_entities: list[MessageEntity] | None = None,
    ) -> int:
        photo = [
            PhotoSize(file_id=f"small-{unique_id}", file_unique_id=f"small-{unique_id}", width=90, height=90),
            PhotoSize(file_id=file_id_of(unique_id), file_unique_id=unique_id, width=800, height=800),
        ]
        message = self._message(user_id, photo=photo, caption=caption, caption_entities=caption_entities)
        await self._feed(message=message)
        return message.message_id

    async def send_document(self, user_id: int, unique_id: str, mime_type: str | None = None) -> int:
        document = Document(file_id=file_id_of(unique_id), file_unique_id=unique_id, mime_type=mime_type)
        message = self._message(user_id, document=document)
        await self._feed(message=message)
        return message.message_id

    async def send_dice(self, user_id: int) -> int:
        message = self._message(user_id, dice=Dice(emoji="🎲", value=3))
        await self._feed(message=message)
        return message.message_id

    async def post_in_channel(
        self,
        message_id: int,
        *,
        unique_id: str | None = None,
        caption: str | None = None,
        edited: bool = False,
        chat_id: int = CHANNEL_ID,
        document: bool = False,
        text: str | None = None,
    ) -> None:
        """A post (or an edit of one) in a channel, as Telegram delivers it to an admin bot."""
        chat = Chat(id=chat_id, type=ChatType.CHANNEL, title="Videos")
        content: dict[str, Any] = {"caption": caption, "text": text}
        if unique_id is not None and document:
            content["document"] = Document(
                file_id=file_id_of(unique_id), file_unique_id=unique_id, mime_type="video/mp4"
            )
        elif unique_id is not None:
            content["video"] = TgVideo(
                file_id=file_id_of(unique_id), file_unique_id=unique_id, width=1, height=1, duration=1
            )
        now = datetime.now(UTC)
        message = Message(
            message_id=message_id,
            date=now,
            chat=chat,
            sender_chat=chat,
            edit_date=int(now.timestamp()) if edited else None,
            **content,
        )
        await self._feed(**{"edited_channel_post" if edited else "channel_post": message})

    async def press(self, user_id: int, data: Any, message_id: int | None = None) -> None:
        """Tap a button on a bot message (by default the user's active message)."""
        if message_id is None:
            message_id = await self.active_message(user_id)
        file_id = self.telegram.media.get(message_id)
        video = None
        if file_id is not None:
            unique_id = file_id.removeprefix("file-")
            video = TgVideo(file_id=file_id, file_unique_id=unique_id, width=1, height=1, duration=1)
        message = Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type=ChatType.PRIVATE),
            from_user=TgUser(id=42, is_bot=True, first_name="Bot"),
            text=None if video else "...",
            video=video,
        )
        callback = CallbackQuery(
            id=str(next(self._callback_ids)),
            from_user=TgUser(id=user_id, is_bot=False, first_name=f"User{user_id}"),
            chat_instance="test",
            message=message,
            data=data if isinstance(data, str) else data.pack(),
        )
        await self._feed(callback_query=callback)

    async def active_message(self, user_id: int) -> int | None:
        async with self.session_factory() as session:
            return await session.scalar(select(User.last_message_id).where(User.id == user_id))


@pytest.fixture
async def harness(
    bot: Bot,
    telegram: FakeTelegram,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> Harness:
    settings = make_settings(str(engine.url))
    dispatcher = create_dispatcher(settings, bot, session_factory)
    return Harness(bot, telegram, dispatcher, session_factory)
