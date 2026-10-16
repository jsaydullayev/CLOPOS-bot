"""Admin: «📈 Foydalanuvchilar» — who uses the bot, one user's card, finding and deleting a user."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import User
from bot.handlers.common import NOT_COMMAND, answer, render_error
from bot.services.admins import Admins
from bot.services.catalog import CatalogError
from bot.services.people import find_person, person_name
from bot.services.support import SupportDesk
from bot.texts import t
from bot.ui.admin import USERS_PAGE_SIZE, confirm_delete_user, find_user_prompt, user_screen, users_screen
from bot.ui.callbacks import FIND_USER, UserCb, UserDeleteCb, UsersCb
from bot.ui.display import Display
from bot.ui.screen import Screen, page_of
from bot.utils import clock
from bot.utils.text import html


class FindUserForm(StatesGroup):
    query = State()


async def render_users(session: AsyncSession, support: SupportDesk, page: int = 0, notice: str | None = None) -> Screen:
    today = support.today()
    counts = await repo.user_counts(session, clock.day_bounds(today, support.tz)[0], clock.now())
    page, pages = page_of(counts.total, page, USERS_PAGE_SIZE)
    users = await repo.recent_users(session, offset=page * USERS_PAGE_SIZE, limit=USERS_PAGE_SIZE)
    return users_screen(counts, users, page, pages, support.tz, today, notice)


async def open_users(
    callback: CallbackQuery,
    callback_data: UsersCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    await state.clear()
    await answer(callback)
    await display.show(db_user, await render_users(session, support, callback_data.page), source=callback.message)


async def open_user(
    callback: CallbackQuery,
    callback_data: UserCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    admins: Admins,
    support: SupportDesk,
) -> None:
    await state.clear()
    user = await repo.get_user(session, callback_data.id)
    if user is None:
        await answer(callback, t("user_not_found"))
        await display.show(db_user, await render_users(session, support, callback_data.page), source=callback.message)
        return
    await answer(callback)
    screen = user_screen(user, callback_data.page, support.tz, admin=user.id in admins)
    await display.show(db_user, screen, source=callback.message)


async def delete_user(
    callback: CallbackQuery,
    callback_data: UserDeleteCb,
    bot: Bot,
    session: AsyncSession,
    db_user: User,
    display: Display,
    admins: Admins,
    support: SupportDesk,
    fsm_storage: BaseStorage,
) -> None:
    """«🗑 O‘chirish», then «🗑 Ha, o‘chirish»: the user's record goes, their tickets stay in the reports."""
    page = callback_data.page
    user = await repo.get_user(session, callback_data.id)
    if user is None:
        await answer(callback, t("user_not_found"))
        await display.show(db_user, await render_users(session, support, page), source=callback.message)
        return
    if user.id in admins:
        # Admin rights are taken away in «👥 Adminlar» first, so nobody deletes an owner or themselves.
        await answer(callback, t("user_is_admin_alert"), alert=True)
        return
    if not callback_data.confirm:
        await answer(callback)
        await display.show(db_user, confirm_delete_user(user, page), source=callback.message)
        return

    name = person_name(user.id, user.first_name, user.username)
    await repo.delete_user(session, user)
    # A dialog they were in ends, so their next message is not taken for its answer.
    await FSMContext(fsm_storage, StorageKey(bot_id=bot.id, chat_id=user.id, user_id=user.id)).clear()
    await answer(callback, t("user_deleted", name=name))
    notice = t("user_deleted", name=html(name))
    await display.show(db_user, await render_users(session, support, page, notice), source=callback.message)


async def ask_user(callback: CallbackQuery, state: FSMContext, db_user: User, display: Display) -> None:
    await answer(callback)
    await state.set_state(FindUserForm.query)
    await display.show(db_user, find_user_prompt(), source=callback.message)


async def receive_user(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    admins: Admins,
    support: SupportDesk,
) -> None:
    """@username, an ID, a forwarded message or a contact: the user's card opens."""
    await display.delete(message.chat.id, message.message_id)
    try:
        person = await find_person(session, message)
        user = await repo.get_user(session, person.user_id)
        if user is None:
            raise CatalogError("error_user_unknown")
    except CatalogError as error:
        await display.show(db_user, find_user_prompt(render_error(error)))
        return
    await state.clear()
    await display.show(db_user, user_screen(user, 0, support.tz, admin=user.id in admins))


def create_router() -> Router:
    router = Router(name="admin-users")
    router.callback_query.register(open_users, UsersCb.filter())
    router.callback_query.register(open_user, UserCb.filter())
    router.callback_query.register(delete_user, UserDeleteCb.filter())
    router.callback_query.register(ask_user, F.data == FIND_USER)
    router.message.register(receive_user, FindUserForm.query, NOT_COMMAND)
    return router
