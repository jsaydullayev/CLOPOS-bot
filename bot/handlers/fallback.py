"""Anything nobody else handled: keep the chat clean and show the main menu."""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.handlers.client import menu_screen
from bot.handlers.common import answer
from bot.ui.display import Display


async def unknown_message(message: Message, session: AsyncSession, db_user: User, display: Display) -> None:
    """Text, stickers, photos, unknown commands: the message is deleted, the menu comes back."""
    await display.delete(message.chat.id, message.message_id)
    await display.show(db_user, await menu_screen(session))


async def unknown_callback(callback: CallbackQuery) -> None:
    await answer(callback)


def create_router() -> Router:
    router = Router(name="fallback")
    router.message.register(unknown_message, F.chat.type == ChatType.PRIVATE, StateFilter(None))
    router.callback_query.register(unknown_callback)
    return router
