"""Admin: tickets (the daily report, the waiting and the not done ones, answering and marking)."""

import re
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import TICKET_NEW, TICKET_NOT_DONE, Ticket, User
from bot.handlers.common import NOT_COMMAND, answer
from bot.services.support import SupportDesk, message_content
from bot.texts import t
from bot.ui.callbacks import (
    TICKET_LINK,
    NotDoneCb,
    SupportReportCb,
    TicketCb,
    TicketFileCb,
    TicketMarkCb,
    TicketReplyCb,
    WaitingCb,
)
from bot.ui.display import Display
from bot.ui.screen import PAGE_SIZE, Screen, page_of
from bot.ui.tickets import not_done_screen, reply_prompt, support_report, ticket_screen, waiting_screen

# How far back the daily report goes.
REPORT_DAYS = 365


class ReplyForm(StatesGroup):
    answer = State()


async def render_report(session: AsyncSession, support: SupportDesk, days_ago: int = 0) -> Screen:
    day = support.today() - timedelta(days=days_ago)
    counts = await support.report(session, day)
    waiting = await repo.count_tickets(session, TICKET_NEW)
    not_done = await repo.count_tickets(session, TICKET_NOT_DONE)
    return support_report(counts, day, days_ago, waiting, not_done)


async def tickets_page(session: AsyncSession, status: str, page: int) -> tuple[list[Ticket], int, int, int]:
    """One page of the tickets in a status: the tickets, the page, the number of pages and the total."""
    total = await repo.count_tickets(session, status)
    page, pages = page_of(total, page)
    tickets = await repo.list_tickets(session, status, offset=page * PAGE_SIZE, limit=PAGE_SIZE)
    return tickets, page, pages, total


async def render_ticket(
    session: AsyncSession, support: SupportDesk, ticket: Ticket, notice: str | None = None
) -> Screen:
    names = await support.names(session, [ticket.answered_by, ticket.resolved_by])
    return ticket_screen(ticket, names, support.tz, notice)


async def open_report(
    callback: CallbackQuery,
    callback_data: SupportReportCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    await state.clear()
    await answer(callback)
    days_ago = min(max(callback_data.days_ago, 0), REPORT_DAYS)
    await display.show(db_user, await render_report(session, support, days_ago), source=callback.message)


async def open_waiting(
    callback: CallbackQuery,
    callback_data: WaitingCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    await state.clear()
    await answer(callback)
    tickets, page, pages, total = await tickets_page(session, TICKET_NEW, callback_data.page)
    screen = waiting_screen(tickets, page, pages, total, support.tz, support.today())
    await display.show(db_user, screen, source=callback.message)


async def open_not_done(
    callback: CallbackQuery,
    callback_data: NotDoneCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    """«❌ Bajarilmaganlar»: who was left without help; each ticket opens to be answered again."""
    await state.clear()
    await answer(callback)
    tickets, page, pages, total = await tickets_page(session, TICKET_NOT_DONE, callback_data.page)
    names = await support.names(session, [ticket.resolved_by for ticket in tickets])
    screen = not_done_screen(tickets, names, page, pages, total, support.tz, support.today())
    await display.show(db_user, screen, source=callback.message)


async def open_ticket(
    callback: CallbackQuery,
    callback_data: TicketCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    await state.clear()
    ticket = await repo.get_ticket(session, callback_data.id)
    if ticket is None:
        await answer(callback, t("ticket_not_found"))
        await display.show(db_user, await render_report(session, support), source=callback.message)
        return
    await answer(callback)
    await display.show(db_user, await render_ticket(session, support, ticket), source=callback.message)


async def open_ticket_link(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    """«✍️ Javob berish» on a card in the support channel opens the bot here: /start t<id>."""
    await state.clear()
    await display.delete(message.chat.id, message.message_id)
    match = re.fullmatch(TICKET_LINK, command.args or "")
    ticket = await repo.get_ticket(session, int(match.group(1))) if match else None
    if ticket is None:
        await display.show(db_user, await render_report(session, support), edit=False)
        return
    await display.show(db_user, await render_ticket(session, support, ticket), edit=False)


async def ask_reply(
    callback: CallbackQuery,
    callback_data: TicketReplyCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    ticket = await repo.get_ticket(session, callback_data.id)
    if ticket is None:
        await answer(callback, t("ticket_not_found"))
        await display.show(db_user, await render_report(session, support), source=callback.message)
        return
    await answer(callback)
    await state.set_state(ReplyForm.answer)
    await state.update_data(ticket_id=ticket.id)
    await display.show(db_user, reply_prompt(ticket), source=callback.message)


async def receive_reply(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    support: SupportDesk,
) -> None:
    """The admin's answer goes to the client from the bot; then the ticket can be marked."""
    ticket = await repo.get_ticket(session, (await state.get_data()).get("ticket_id"))
    if ticket is None:
        await state.clear()
        await display.delete(message.chat.id, message.message_id)
        await display.show(db_user, await render_report(session, support))
        return
    if message_content(message) is None:
        await display.delete(message.chat.id, message.message_id)
        await display.show(db_user, reply_prompt(ticket, t("error_expected_message")))
        return
    delivered = await support.reply(session, ticket, message, db_user.id)
    # Copied to the client (or not): the admin's message leaves the chat like any typed input.
    await display.delete(message.chat.id, message.message_id)
    await state.clear()
    notice = t("reply_sent") if delivered else t("reply_not_delivered")
    await display.show(db_user, await render_ticket(session, support, ticket, notice))


async def mark_ticket(
    callback: CallbackQuery,
    callback_data: TicketMarkCb,
    session: AsyncSession,
    db_user: User | None,
    display: Display,
    support: SupportDesk,
) -> None:
    """«✅ Bajarildi» / «❌ Bajarilmadi», on a card in the channel or in the bot: only after an answer."""
    ticket = await repo.get_ticket(session, callback_data.id)
    if ticket is None:
        await answer(callback, t("ticket_not_found"), alert=True)
        return
    if not await support.mark(session, ticket, done=callback_data.done, admin_id=callback.from_user.id):
        await answer(callback, t("ticket_needs_answer"), alert=True)
        return
    marked = t("ticket_marked_done") if callback_data.done else t("ticket_marked_not_done")
    await answer(callback, marked)
    if db_user is not None:  # in the bot; in the channel the card has already changed
        await display.show(db_user, await render_ticket(session, support, ticket, marked), source=callback.message)


async def send_file(
    callback: CallbackQuery, callback_data: TicketFileCb, session: AsyncSession, support: SupportDesk
) -> None:
    """The client's voice note, file or video message, sent under the ticket."""
    ticket = await repo.get_ticket(session, callback_data.id)
    if ticket is None or ticket.file_id is None:
        await answer(callback, t("ticket_not_found"))
        return
    await answer(callback)
    await support.send_file(callback.from_user.id, ticket)


def create_router() -> Router:
    router = Router(name="admin-tickets")
    router.message.register(open_ticket_link, CommandStart(deep_link=True, magic=F.args.regexp(TICKET_LINK)))
    router.callback_query.register(open_report, SupportReportCb.filter())
    router.callback_query.register(open_waiting, WaitingCb.filter())
    router.callback_query.register(open_not_done, NotDoneCb.filter())
    router.callback_query.register(open_ticket, TicketCb.filter())
    router.callback_query.register(ask_reply, TicketReplyCb.filter())
    router.message.register(receive_reply, ReplyForm.answer, NOT_COMMAND)
    router.callback_query.register(mark_ticket, TicketMarkCb.filter())
    router.callback_query.register(send_file, TicketFileCb.filter())
    return router
