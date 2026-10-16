from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bot.config import Settings
from bot.db.models import MEDIA_PHOTO
from bot.handlers import create_routers
from bot.handlers.errors import on_error
from bot.lifecycle import on_shutdown, on_startup
from bot.middlewares import (
    ChannelQueueMiddleware,
    DbSessionMiddleware,
    StaleCallbackMiddleware,
    UserIsolation,
    UserMiddleware,
)
from bot.services.admins import Admins
from bot.services.archive import ArchiveService
from bot.services.background import Background
from bot.services.content import attachment_for
from bot.services.notify import Notifier
from bot.services.support import SupportDesk
from bot.ui.display import Display, replaced_messages
from bot.ui.tickets import channel_card


def create_dispatcher(
    settings: Settings,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    engine: AsyncEngine | None = None,
) -> Dispatcher:
    admins = Admins(settings.admin_ids)
    notifier = Notifier(bot, admins)
    replaced = replaced_messages()

    async def greeting_photo() -> str | None:
        # Text screens shown in place of a video go under the greeting photo, like the main menu.
        # A greeting video or GIF plays on the main menu only: elsewhere the plain cover is quieter.
        async with session_factory() as session:
            attachment = await attachment_for(session, "main_menu")
        return attachment.file_id if attachment is not None and attachment.media_type == MEDIA_PHOTO else None

    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        events_isolation=UserIsolation(),
        settings=settings,
        admins=admins,
        session_factory=session_factory,
        display=Display(bot, replaced, protect_content=settings.protect_content, cover=greeting_photo),
        archive=ArchiveService(bot, session_factory, settings.backup_channel_id, notifier),
        notifier=notifier,
        support=SupportDesk(bot, settings, notifier, channel_card),
        background=Background(),
        engine=engine,
    )

    # Order matters: the locks (UserIsolation above, the channel queue here) wrap the database
    # session and the user record.
    dispatcher.update.outer_middleware(ChannelQueueMiddleware())
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_factory))
    dispatcher.update.outer_middleware(UserMiddleware())
    dispatcher.callback_query.outer_middleware(StaleCallbackMiddleware(replaced))

    dispatcher.include_routers(*create_routers())
    dispatcher.errors.register(on_error)
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    return dispatcher
