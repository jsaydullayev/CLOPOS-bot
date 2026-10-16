"""Admin: the list of admins, adding one and taking the rights away."""

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import Admin, User
from bot.handlers.client import menu_screen
from bot.handlers.common import NOT_COMMAND, answer, render_error
from bot.services.admins import Admins
from bot.services.catalog import CatalogError
from bot.services.commands import remove_admin_commands, set_admin_commands
from bot.services.people import find_person, person_name
from bot.texts import t
from bot.ui.admin import AdminEntry, add_admin_prompt, admins_screen, confirm_remove_admin
from bot.ui.callbacks import ADD_ADMIN, ADMINS, AdminRemoveCb
from bot.ui.display import Display
from bot.utils.text import html


class AdminForm(StatesGroup):
    user = State()


async def admin_entries(session: AsyncSession, admins: Admins) -> list[AdminEntry]:
    """The owners first, then the admins added in the panel, in the order they were added."""
    added = {admin.user_id: admin for admin in await repo.list_admins(session)}
    ids = sorted(admins.owners) + [user_id for user_id in added if not admins.is_owner(user_id)]
    users = await repo.get_users(session, ids)
    return [
        AdminEntry(user_id, _display_name(user_id, users.get(user_id), added.get(user_id)), admins.is_owner(user_id))
        for user_id in ids
    ]


def _display_name(user_id: int, user: User | None, admin: Admin | None) -> str:
    first_name = (user.first_name if user is not None else None) or (admin.name if admin is not None else None)
    return person_name(user_id, first_name, user.username if user is not None else None)


async def open_admins(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User, display: Display, admins: Admins
) -> None:
    await state.clear()
    await answer(callback)
    await display.show(db_user, admins_screen(await admin_entries(session, admins)), source=callback.message)


async def ask_new_admin(callback: CallbackQuery, state: FSMContext, db_user: User, display: Display) -> None:
    await answer(callback)
    await state.set_state(AdminForm.user)
    await display.show(db_user, add_admin_prompt(), source=callback.message)


async def receive_new_admin(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    db_user: User,
    display: Display,
    admins: Admins,
) -> None:
    await display.delete(message.chat.id, message.message_id)
    try:
        candidate = await find_person(session, message)
        if candidate.is_bot:
            raise CatalogError("error_admin_bot")
        if candidate.user_id in admins:
            users = await repo.get_users(session, [candidate.user_id])
            name = _display_name(candidate.user_id, users.get(candidate.user_id), None)
            raise CatalogError("error_admin_exists", name=name)
    except CatalogError as error:
        await display.show(db_user, add_admin_prompt(render_error(error)))
        return

    await admins.add(session, candidate.user_id, name=candidate.name, added_by=db_user.id)
    await state.clear()
    await set_admin_commands(bot, candidate.user_id)
    with suppress(TelegramAPIError):
        # Reaches them only if they have started the bot; /admin works either way once they do.
        await bot.send_message(chat_id=candidate.user_id, text=t("admin_welcome"))
    entries = await admin_entries(session, admins)
    name = next(entry.name for entry in entries if entry.user_id == candidate.user_id)
    await display.show(db_user, admins_screen(entries, notice=t("admin_added", name=html(name))))


async def ask_remove(
    callback: CallbackQuery,
    callback_data: AdminRemoveCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    admins: Admins,
) -> None:
    await state.clear()
    entries = await admin_entries(session, admins)
    entry = _removable(entries, callback_data.user_id)
    if entry is None:
        await answer(callback, t("admin_not_found"))
        await display.show(db_user, admins_screen(entries), source=callback.message)
        return
    await answer(callback)
    await display.show(db_user, confirm_remove_admin(entry), source=callback.message)


async def remove_confirmed(
    callback: CallbackQuery,
    callback_data: AdminRemoveCb,
    bot: Bot,
    session: AsyncSession,
    db_user: User,
    display: Display,
    admins: Admins,
) -> None:
    entries = await admin_entries(session, admins)
    entry = _removable(entries, callback_data.user_id)
    if entry is None or not await admins.remove(session, entry.user_id):
        # Another admin removed them a moment ago: the list is read again.
        await answer(callback, t("admin_not_found"))
        await display.show(db_user, admins_screen(await admin_entries(session, admins)), source=callback.message)
        return
    await answer(callback, t("admin_removed", name=entry.name))
    await remove_admin_commands(bot, entry.user_id)
    if entry.user_id == db_user.id:
        # They took their own rights away: the panel is closed for them now.
        await display.show(db_user, await menu_screen(session), source=callback.message)
        return
    notice = t("admin_removed", name=html(entry.name))
    left = [other for other in entries if other.user_id != entry.user_id]
    await display.show(db_user, admins_screen(left, notice), source=callback.message)


def _removable(entries: list[AdminEntry], user_id: int) -> AdminEntry | None:
    return next((entry for entry in entries if entry.user_id == user_id and not entry.owner), None)


def create_router() -> Router:
    router = Router(name="admin-admins")
    router.callback_query.register(open_admins, F.data == ADMINS)
    router.callback_query.register(ask_new_admin, F.data == ADD_ADMIN)
    router.message.register(receive_new_admin, AdminForm.user, NOT_COMMAND)
    router.callback_query.register(ask_remove, AdminRemoveCb.filter(~F.confirm))
    router.callback_query.register(remove_confirmed, AdminRemoveCb.filter(F.confirm))
    return router
