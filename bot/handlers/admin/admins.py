"""Admin: the list of admins, adding one and taking the rights away."""

import re
from contextlib import suppress
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, MessageOriginUser
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import Admin, User
from bot.handlers.client import menu_screen
from bot.handlers.common import NOT_COMMAND, answer, render_error
from bot.services.admins import Admins
from bot.services.catalog import CatalogError
from bot.services.commands import remove_admin_commands, set_admin_commands
from bot.texts import t
from bot.ui.admin import AdminEntry, add_admin_prompt, admins_screen, confirm_remove_admin
from bot.ui.callbacks import ADD_ADMIN, ADMINS, AdminRemoveCb
from bot.ui.display import Display
from bot.utils.text import html

# @username or a t.me link to it.
_USERNAME = re.compile(r"(?:@|(?:https?://)?t\.me/)([A-Za-z][A-Za-z0-9_]{3,31})")
# Plain ASCII digits: str.isdigit() also passes «²», which int() refuses.
_USER_ID = re.compile(r"[0-9]{1,16}")
# Telegram user ids fit in 52 bits.
_MAX_USER_ID = 2**52


class AdminForm(StatesGroup):
    user = State()


@dataclass(frozen=True, slots=True)
class Candidate:
    user_id: int
    name: str | None


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
    username = user.username if user is not None else None
    if first_name and username:
        return f"{first_name} (@{username})"
    return first_name or (f"@{username}" if username else t("admin_name_id", id=user_id))


async def _candidate(session: AsyncSession, message: Message) -> Candidate:
    """Who the admin means: a shared contact, a forwarded message, @username or a numeric ID."""
    if message.contact is not None:
        if message.contact.user_id is None:
            raise CatalogError("error_admin_contact")
        name = " ".join(part for part in (message.contact.first_name, message.contact.last_name) if part)
        return Candidate(message.contact.user_id, name or None)
    origin = message.forward_origin
    if origin is not None:
        # A hidden sender, a chat or a channel gives no user id.
        if not isinstance(origin, MessageOriginUser):
            raise CatalogError("error_admin_forward")
        if origin.sender_user.is_bot:
            raise CatalogError("error_admin_bot")
        return Candidate(origin.sender_user.id, origin.sender_user.full_name)
    text = (message.text or "").strip()
    if match := _USERNAME.fullmatch(text):
        # The Bot API cannot look a username up: only people who wrote to the bot are known.
        user = await repo.find_user_by_username(session, match.group(1))
        if user is None:
            raise CatalogError("error_admin_username", username=match.group(1))
        return Candidate(user.id, user.first_name)
    if _USER_ID.fullmatch(text) and 0 < int(text) < _MAX_USER_ID:
        return Candidate(int(text), None)
    raise CatalogError("error_admin_expected")


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
        candidate = await _candidate(session, message)
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
