"""«📞 Bog‘lanish va yordam»: the contacts, and a problem the client leaves for the admins
with a phone to call them back on."""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.handlers.common import NOT_COMMAND, answer
from bot.services.content import CONTACTS_TEXT, text_for
from bot.services.support import SupportDesk, message_content
from bot.texts import t
from bot.ui.callbacks import CHANGE_PHONE, CONTACTS, WRITE_PROBLEM
from bot.ui.client import contacts_screen, phone_prompt, problem_prompt
from bot.ui.display import Display
from bot.utils.phone import parse_phone


class SupportForm(StatesGroup):
    phone = State()
    problem = State()


async def open_contacts(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User, display: Display
) -> None:
    await state.clear()
    await answer(callback)
    await display.show(db_user, contacts_screen(await text_for(session, CONTACTS_TEXT)), source=callback.message)


async def ask_problem(
    callback: CallbackQuery, state: FSMContext, db_user: User, display: Display, support: SupportDesk
) -> None:
    wait = support.wait_left(db_user.id)
    if wait:
        await answer(callback, t("problem_too_soon", seconds=wait))
        return
    await answer(callback)
    if db_user.phone is None:
        # The first problem: the phone to call back on comes first, and is remembered.
        await state.set_state(SupportForm.phone)
        await display.show(db_user, phone_prompt(), source=callback.message)
        return
    await state.set_state(SupportForm.problem)
    await display.show(db_user, problem_prompt(db_user.phone), source=callback.message)


async def change_phone(callback: CallbackQuery, state: FSMContext, db_user: User, display: Display) -> None:
    await answer(callback)
    await state.set_state(SupportForm.phone)
    await display.show(db_user, phone_prompt(), source=callback.message)


async def receive_phone(message: Message, state: FSMContext, db_user: User, display: Display) -> None:
    """A typed number or a shared contact; then the problem itself."""
    await display.delete(message.chat.id, message.message_id)
    if message.contact is not None:
        # Telegram gives a contact's number with its country code, not always with the +.
        phone = parse_phone("+" + message.contact.phone_number.removeprefix("+"))
    else:
        phone = parse_phone(message.text or "")
    if phone is None:
        await display.show(db_user, phone_prompt(t("error_phone")))
        return
    db_user.phone = phone
    await state.set_state(SupportForm.problem)
    await display.show(db_user, problem_prompt(phone))


async def receive_problem(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    """Text, a photo or video with a caption, a voice note, a file. It becomes a ticket in the
    support channel first, then leaves the chat like everything else the client sends."""
    assert db_user.phone is not None  # the dialog gets here only once the phone is known
    wait = support.wait_left(db_user.id)
    error = t("problem_too_soon", seconds=wait) if wait else None
    if error is None and message_content(message) is None:
        error = t("error_expected_message")
    if error is not None:
        await display.delete(message.chat.id, message.message_id)
        await display.show(db_user, problem_prompt(db_user.phone, error))
        return
    ticket = await support.submit(session, message, db_user.phone)
    await display.delete(message.chat.id, message.message_id)
    await state.clear()
    notice = t("problem_sent", id=ticket.id)
    await display.show(db_user, contacts_screen(await text_for(session, CONTACTS_TEXT), notice))


def _album_part(message: Message, support: SupportDesk) -> bool:
    return support.is_album_part(message)


async def receive_album_part(message: Message, session: AsyncSession, display: Display, support: SupportDesk) -> None:
    """The rest of an album whose first photo became a ticket joins it in the support channel;
    the client keeps the confirmation on the screen."""
    await support.add_album_part(session, message)
    await display.delete(message.chat.id, message.message_id)


def create_router() -> Router:
    router = Router(name="support")
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    router.callback_query.register(open_contacts, F.data == CONTACTS)
    router.callback_query.register(ask_problem, F.data == WRITE_PROBLEM)
    router.callback_query.register(change_phone, F.data == CHANGE_PHONE)
    router.message.register(receive_phone, SupportForm.phone, NOT_COMMAND)
    router.message.register(receive_problem, SupportForm.problem, NOT_COMMAND)
    router.message.register(receive_album_part, _album_part)
    return router
