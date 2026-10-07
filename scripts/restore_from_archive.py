"""Restore video file_ids from the archive channel after the bot is replaced.

A file_id works only for the bot that received it. With a new BOT_TOKEN the
new bot forwards every archived post by backup_message_id, takes the fresh
file_id from the forwarded message and deletes the forward.

Before running: add the new bot to the archive channel as an admin and press
/start in it from the admin account that receives the forwards.

    python -m scripts.restore_from_archive            # forwards to the first admin
    python -m scripts.restore_from_archive --chat 123 # forwards to another chat
"""

import argparse
import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import get_settings
from bot.db.models import Video
from bot.db.session import create_engine, create_session_factory

logger = logging.getLogger("restore")

# About one message a second per chat keeps clear of flood limits.
PAUSE = 1.1


@dataclass
class RestoreReport:
    restored: int = 0
    failed: int = 0
    missing: int = 0


async def forward(bot: Bot, chat_id: int, channel_id: int, message_id: int) -> Message | None:
    while True:
        try:
            return await bot.forward_message(chat_id=chat_id, from_chat_id=channel_id, message_id=message_id)
        except TelegramRetryAfter as error:
            await asyncio.sleep(error.retry_after + 1)
        except TelegramAPIError as error:
            logger.warning("Archive post %s could not be forwarded: %s", message_id, error)
            return None


async def restore_videos(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel_id: int,
    chat_id: int,
    pause: float = PAUSE,
) -> RestoreReport:
    report = RestoreReport()
    async with session_factory() as session:
        videos = list(await session.scalars(select(Video).order_by(Video.id)))
        for video in videos:
            if video.backup_message_id is None:
                report.missing += 1
                logger.warning("Video %s (%s) has no archive copy", video.id, video.title)
                continue
            message = await forward(bot, chat_id, channel_id, video.backup_message_id)
            media = message and (message.video or message.animation or message.document)
            if message is None or media is None:
                report.failed += 1
                continue
            if media.file_unique_id != video.file_unique_id:
                logger.warning("Video %s: the archive post holds a different file", video.id)
            video.file_id = media.file_id
            await session.commit()
            with suppress(TelegramAPIError):
                await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            report.restored += 1
            await asyncio.sleep(pause)
    return report


async def restore(chat_id: int | None) -> None:
    settings = get_settings()
    target = chat_id or min(settings.admin_ids, default=None)
    if target is None:
        raise SystemExit("ADMIN_IDS is empty: pass --chat CHAT_ID")

    bot = Bot(token=settings.bot_token)
    engine = create_engine(settings.database_url)
    try:
        report = await restore_videos(
            bot, create_session_factory(engine), channel_id=settings.backup_channel_id, chat_id=target
        )
    finally:
        await bot.session.close()
        await engine.dispose()
    logger.info(
        "Restored: %s, failed: %s, without archive copy: %s", report.restored, report.failed, report.missing
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chat", type=int, help="chat that receives the forwards (default: first admin)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(restore(args.chat))


if __name__ == "__main__":
    main()
