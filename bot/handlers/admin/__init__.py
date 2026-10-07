from aiogram import F, Router
from aiogram.enums import ChatType

from bot.filters import IsAdmin
from bot.handlers.admin import categories, panel, texts, videos


def create_router() -> Router:
    router = Router(name="admin")
    router.message.filter(F.chat.type == ChatType.PRIVATE, IsAdmin())
    router.callback_query.filter(IsAdmin())
    router.include_routers(
        panel.create_router(), categories.create_router(), texts.create_router(), videos.create_router()
    )
    return router
