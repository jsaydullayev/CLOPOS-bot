from aiogram.filters import Filter
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser

from bot.config import Settings


class IsAdmin(Filter):
    """Checks the sender against ADMIN_IDS on every admin message and button."""

    async def __call__(
        self,
        event: TelegramObject,
        event_from_user: TgUser | None = None,
        settings: Settings | None = None,
    ) -> bool:
        return event_from_user is not None and settings is not None and settings.is_admin(event_from_user.id)
