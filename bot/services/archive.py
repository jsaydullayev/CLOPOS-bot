"""Copies videos added in the admin panel to the private video channel.

Videos posted in the channel are already there. The copy uses the same caption
format as posts (see services/channel.py), so the channel holds the whole
catalog, and editing a copy's caption edits the video. file_id belongs to one
bot only, so the channel is also what lets the videos be restored if the bot is
ever replaced (see scripts/restore_from_archive.py).
"""

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db import repo
from bot.db.models import MEDIA_ANIMATION, Video
from bot.services.channel import post_caption
from bot.services.notify import Notifier
from bot.texts import t
from bot.utils.text import html

logger = logging.getLogger(__name__)

# Telegram allows about 20 messages a minute into one group or channel.
SEND_INTERVAL = 3.2
MAX_ATTEMPTS = 10


class ArchiveService:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        channel_id: int,
        notifier: Notifier,
        *,
        interval: float = SEND_INTERVAL,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.channel_id = channel_id
        self.notifier = notifier
        self.interval = interval
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def enqueue(self, video_id: int) -> None:
        self._queue.put_nowait(video_id)

    async def start(self) -> None:
        """Queue videos that were never archived and start the worker."""
        async with self.session_factory() as session:
            for video_id in await repo.video_ids_without_backup(session):
                self.enqueue(video_id)
        self._task = asyncio.create_task(self._run(), name="archive-worker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            video_id = await self._queue.get()
            try:
                await self.archive(video_id)
            except Exception:
                logger.exception("Archiving video %s failed", video_id)
            finally:
                self._queue.task_done()
            await asyncio.sleep(self.interval)

    async def archive(self, video_id: int) -> bool:
        """Copy one video to the channel. Returns True when a copy was made."""
        async with self.session_factory() as session:
            video = await repo.get_video(session, video_id)
            if video is None or video.backup_message_id is not None:
                return False
            tree = await repo.load_tree(session)
            caption = post_caption(tree.path(video.category_id), video.title, video.description)
            try:
                message = await self._send(video, caption)
            except TelegramAPIError as error:
                logger.error("Video %s was not archived: %s", video.id, error)
                await self.notifier.notify(
                    t("archive_failed", title=html(video.title), id=video.id, error=html(error)),
                    key=f"archive:{type(error).__name__}",
                )
                return False
            video.backup_message_id = message.message_id
            await session.commit()
            return True

    async def _send(self, video: Video, caption: str) -> Message:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                # Plain text, so the caption reads back exactly as written.
                if video.media_type == MEDIA_ANIMATION:
                    return await self.bot.send_animation(
                        chat_id=self.channel_id, animation=video.file_id, caption=caption, parse_mode=None
                    )
                return await self.bot.send_video(
                    chat_id=self.channel_id, video=video.file_id, caption=caption, parse_mode=None
                )
            except TelegramRetryAfter as error:
                if attempt == MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(error.retry_after + 1)
        raise AssertionError("unreachable")
