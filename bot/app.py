from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bot.config import Settings
from bot.handlers import create_routers
from bot.handlers.errors import on_error
from bot.lifecycle import on_shutdown, on_startup
from bot.middlewares import DbSessionMiddleware, StaleCallbackMiddleware, UserLockMiddleware, UserMiddleware
from bot.services.archive import ArchiveService
from bot.services.background import Background
from bot.services.content import Attachment, attachment_for
from bot.services.notify import Notifier
from bot.ui.display import Display, ReplacedRegistry


def create_dispatcher(
    settings: Settings,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    engine: AsyncEngine | None = None,
) -> Dispatcher:
    notifier = Notifier(bot, settings.admin_ids)
    registry = ReplacedRegistry()

    async def greeting_media() -> Attachment | None:
        # Text screens shown in place of a video go under the greeting's photo or video, like the main menu.
        async with session_factory() as session:
            return await attachment_for(session, "main_menu")

    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        settings=settings,
        display=Display(bot, registry, protect_content=settings.protect_content, cover=greeting_media),
        archive=ArchiveService(bot, session_factory, settings.backup_channel_id, notifier),
        notifier=notifier,
        background=Background(),
        engine=engine,
    )

    # Order matters: the per-user lock wraps the database session and the user record.
    dispatcher.update.outer_middleware(UserLockMiddleware())
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_factory))
    dispatcher.update.outer_middleware(UserMiddleware())
    dispatcher.callback_query.outer_middleware(StaleCallbackMiddleware(registry))

    dispatcher.include_routers(*create_routers())
    dispatcher.errors.register(on_error)
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    return dispatcher
