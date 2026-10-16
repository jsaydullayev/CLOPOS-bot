"""«📞 Bog‘lanish va yordam»: the contacts, and a problem the client leaves for the admins."""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.handlers.common import NOT_COMMAND, answer
from bot.services.content import CONTACTS_TEXT, text_for
from bot.services.support import SupportDesk
from bot.texts import t
from bot.ui.callbacks import CONTACTS, WRITE_PROBLEM
from bot.ui.client import contacts_screen, problem_prompt
from bot.ui.display import Display


class SupportForm(StatesGroup):
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
    await state.set_state(SupportForm.problem)
    await display.show(db_user, problem_prompt(), source=callback.message)


async def receive_problem(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    """Any message: text, a photo or video with a caption, a voice note. It is copied to the
    admins first, then removed from the chat like everything else the client sends."""
    wait = support.wait_left(db_user.id)
    if wait:
        await display.delete(message.chat.id, message.message_id)
        await display.show(db_user, problem_prompt(t("problem_too_soon", seconds=wait)))
        return
    delivered = await support.deliver(message)
    await display.delete(message.chat.id, message.message_id)
    await state.clear()
    notice = t("problem_sent") if delivered else t("problem_not_sent")
    await display.show(db_user, contacts_screen(await text_for(session, CONTACTS_TEXT), notice))


def create_router() -> Router:
    router = Router(name="support")
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    router.callback_query.register(open_contacts, F.data == CONTACTS)
    router.callback_query.register(ask_problem, F.data == WRITE_PROBLEM)
    router.message.register(receive_problem, SupportForm.problem, NOT_COMMAND)
    return router
