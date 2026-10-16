from aiogram import F, Router
from aiogram.enums import ChatType

from bot.filters import IsAdmin
from bot.handlers.admin import admins, categories, panel, texts, tickets, users, videos


def create_router() -> Router:
    router = Router(name="admin")
    router.message.filter(F.chat.type == ChatType.PRIVATE, IsAdmin())
    # Buttons are checked by who pressed them, wherever they are: the ticket cards sit in the support channel.
    router.callback_query.filter(IsAdmin())
    router.include_routers(
        panel.create_router(),
        tickets.create_router(),
        users.create_router(),
        categories.create_router(),
        texts.create_router(),
        videos.create_router(),
        admins.create_router(),
    )
    return router
