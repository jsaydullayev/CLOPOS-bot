import logging

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.config import Settings
from bot.services.archive import ArchiveService
from bot.services.background import Background
from bot.services.commands import set_default_commands
from bot.services.db_backup import backup_loop
from bot.services.notify import Notifier
from bot.services.retry import until_reachable

logger = logging.getLogger(__name__)


async def on_startup(
    bot: Bot,
    dispatcher: Dispatcher,
    settings: Settings,
    archive: ArchiveService,
    notifier: Notifier,
    background: Background,
) -> None:
    await set_default_commands(bot, settings)
    await archive.start()
    if settings.db_backup_enabled:
        background.start(backup_loop(bot, settings, notifier), name="db-backup")
    if settings.webhook_url:
        await until_reachable(
            lambda: bot.set_webhook(
                url=settings.webhook_url,
                secret_token=settings.webhook_secret or None,
                allowed_updates=dispatcher.resolve_used_update_types(),
                drop_pending_updates=False,
            ),
            what="set webhook",
        )
    logger.info("Bot started in %s mode", "webhook" if settings.webhook_url else "polling")


async def on_shutdown(archive: ArchiveService, background: Background, engine: AsyncEngine | None = None) -> None:
    await archive.stop()
    await background.stop()
    if engine is not None:
        await engine.dispose()
    logger.info("Bot stopped")
