from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, ForwardMessage, SendMessage, SendVideo
from aiogram.types import Video as TgVideo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import Video
from bot.services.archive import ArchiveService
from bot.services.catalog import add_video, create_category
from bot.services.notify import Notifier
from scripts.restore_from_archive import restore_videos
from tests.conftest import ADMIN_ID, CHANNEL_ID, FakeTelegram


async def create_videos(session_factory: async_sessionmaker[AsyncSession], count: int) -> list[int]:
    async with session_factory() as session:
        category = await create_category(session, parent_id=None, raw_title="Kassa", admin_id=1, max_depth=3)
        ids = []
        for number in range(1, count + 1):
            video = await add_video(
                session,
                category_id=category.id,
                title=f"Video {number}",
                description=None,
                file_id=f"old-{number}",
                file_unique_id=f"u{number}",
                media_type="video",
                admin_id=1,
            )
            ids.append(video.id)
        await session.commit()
    return ids


async def test_archive_failure_is_reported_to_admins(
    bot: Bot, telegram: FakeTelegram, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    [video_id] = await create_videos(session_factory, 1)
    archive = ArchiveService(bot, session_factory, CHANNEL_ID, Notifier(bot, [ADMIN_ID]))
    telegram.fail_once(SendVideo, TelegramBadRequest(method=None, message="Bad Request: chat not found"))

    assert not await archive.archive(video_id)
    report = telegram.of(SendMessage)[-1]
    assert report.chat_id == ADMIN_ID
    assert "Video kanalga nusxalanmadi" in report.text

    # The next attempt (for example after a restart) succeeds.
    assert await archive.archive(video_id)
    assert not await archive.archive(video_id)  # already archived


async def test_restore_takes_new_file_ids_from_the_archive(
    bot: Bot, telegram: FakeTelegram, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first, second = await create_videos(session_factory, 2)
    async with session_factory() as session:
        (await session.get(Video, first)).backup_message_id = 501
        await session.commit()
    telegram.forwarded[501] = TgVideo(file_id="new-1", file_unique_id="u1", width=1, height=1, duration=1)

    report = await restore_videos(bot, session_factory, channel_id=CHANNEL_ID, chat_id=ADMIN_ID, pause=0)

    assert (report.restored, report.failed, report.missing) == (1, 0, 1)
    forward = telegram.of(ForwardMessage)[0]
    assert (forward.from_chat_id, forward.message_id) == (CHANNEL_ID, 501)
    assert telegram.of(DeleteMessage)  # the forwarded copy is removed
    async with session_factory() as session:
        assert (await session.get(Video, first)).file_id == "new-1"
        assert (await session.get(Video, second)).file_id == "old-2"
