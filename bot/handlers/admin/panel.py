from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import User
from bot.handlers.common import answer
from bot.texts import t
from bot.ui.admin import admin_panel, admin_pick, channel_guide, section_codes
from bot.ui.callbacks import ADMIN_PANEL, CHANNEL_GUIDE, AdminPickCb, SectionCodesCb
from bot.ui.display import Display


async def panel_command(message: Message, state: FSMContext, db_user: User, display: Display) -> None:
    await state.clear()
    await display.delete(message.chat.id, message.message_id)
    await display.show(db_user, admin_panel(), edit=False)


async def open_panel(callback: CallbackQuery, state: FSMContext, db_user: User, display: Display) -> None:
    await state.clear()
    await answer(callback)
    await display.show(db_user, admin_panel(), source=callback.message)


async def pick_category(
    callback: CallbackQuery,
    callback_data: AdminPickCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
) -> None:
    await state.clear()
    tree = await repo.load_tree(session)
    category_id = callback_data.id or None
    page = callback_data.page
    if category_id is not None and tree.get(category_id) is None:
        await answer(callback, t("category_deleted"))
        category_id, page = None, 0
    else:
        await answer(callback)
    await display.show(db_user, admin_pick(tree, category_id, page), source=callback.message)


async def open_channel_guide(callback: CallbackQuery, state: FSMContext, db_user: User, display: Display) -> None:
    await state.clear()
    await answer(callback)
    await display.show(db_user, channel_guide(), source=callback.message)


async def open_section_codes(
    callback: CallbackQuery,
    callback_data: SectionCodesCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
) -> None:
    await state.clear()
    await answer(callback)
    tree = await repo.load_tree(session)
    await display.show(db_user, section_codes(tree, callback_data.page), source=callback.message)


def create_router() -> Router:
    router = Router(name="admin-panel")
    router.message.register(panel_command, Command("admin"))
    router.callback_query.register(open_panel, F.data == ADMIN_PANEL)
    router.callback_query.register(pick_category, AdminPickCb.filter())
    router.callback_query.register(open_channel_guide, F.data == CHANNEL_GUIDE)
    router.callback_query.register(open_section_codes, SectionCodesCb.filter())
    return router
