from aiogram.filters import Filter
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser

from bot.services.admins import Admins


class IsAdmin(Filter):
    """Checks the sender against the admins (ADMIN_IDS and the panel) on every admin message and button."""

    async def __call__(
        self,
        event: TelegramObject,
        event_from_user: TgUser | None = None,
        admins: Admins | None = None,
    ) -> bool:
        return event_from_user is not None and admins is not None and event_from_user.id in admins
