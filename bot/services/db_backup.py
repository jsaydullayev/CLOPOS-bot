"""Daily pg_dump of the database, sent to the private archive channel."""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy.engine import make_url

from bot.config import Settings
from bot.services.notify import Notifier
from bot.texts import t
from bot.utils.text import html

logger = logging.getLogger(__name__)

# Bots can upload files up to 50 MB.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def seconds_until(hour: int, tz: ZoneInfo, now: datetime | None = None) -> float:
    now = now or datetime.now(tz)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def dump_database(database_url: str) -> bytes:
    url = make_url(database_url)
    args = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges"]
    if url.host:
        args += ["--host", url.host]
    if url.port:
        args += ["--port", str(url.port)]
    if url.username:
        args += ["--username", url.username]
    args.append(url.database or "")

    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip()
        raise RuntimeError(message or f"pg_dump exited with code {process.returncode}")
    return stdout


async def send_backup(bot: Bot, settings: Settings) -> None:
    data = await dump_database(settings.database_url)
    if len(data) > MAX_UPLOAD_BYTES:
        raise RuntimeError(t("backup_too_big", size=f"{len(data) / 1024 / 1024:.1f}"))
    now = datetime.now(ZoneInfo(settings.timezone))
    await bot.send_document(
        chat_id=settings.backup_channel_id,
        document=BufferedInputFile(data, filename=f"backup-{now:%Y-%m-%d}.dump"),
        caption=t("backup_caption", date=f"{now:%Y-%m-%d %H:%M}"),
    )
    logger.info("Database backup sent (%d bytes)", len(data))


async def backup_loop(bot: Bot, settings: Settings, notifier: Notifier) -> None:
    tz = ZoneInfo(settings.timezone)
    while True:
        await asyncio.sleep(seconds_until(settings.db_backup_hour, tz))
        try:
            await send_backup(bot, settings)
        except Exception as error:
            logger.exception("Database backup failed")
            await notifier.notify(t("backup_failed", error=html(str(error)[:300])), key="db-backup")
