"""Tickets: a client's problem goes to the support channel, an admin answers it in the bot and marks it."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import AnswerCallbackQuery, CopyMessage, EditMessageText, SendMessage, SendPhoto, SendVoice
from aiogram.types import Contact, PhotoSize, Sticker, Voice
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bot.app import create_dispatcher
from bot.db import repo
from bot.db.models import Ticket, User
from bot.texts import t
from bot.ui.callbacks import (
    CHANGE_PHONE,
    CONTACTS,
    WRITE_PROBLEM,
    MenuCb,
    SupportReportCb,
    TicketCb,
    TicketFileCb,
    TicketMarkCb,
    TicketReplyCb,
    UsersCb,
    WaitingCb,
)
from tests.conftest import (
    ADMIN_ID,
    BOT_USERNAME,
    CLIENT_ID,
    SUPPORT_CHANNEL_ID,
    FakeTelegram,
    Harness,
    button_texts,
    last_buttons,
    last_text,
    make_settings,
    toasts,
)

PROBLEM = "Printer chek chiqarmayapti."
PHONE = "90 123-45-67"


async def write_problem(harness: Harness, user_id: int, **content: Any) -> int:
    """The client opens «📞 Bog‘lanish va yordam» → «✍️ Muammoni yozib qoldirish», leaves the phone
    if asked, and sends a message."""
    await harness.send_text(user_id, "/start")
    await harness.press(user_id, CONTACTS)
    await harness.press(user_id, WRITE_PROBLEM)
    if last_text(harness) == t("phone_prompt"):
        await harness.send_text(user_id, PHONE)
    return await harness.send(user_id, **content)


async def stored(harness: Harness, ticket_id: int) -> Ticket:
    async with harness.session_factory() as session:
        ticket = await session.get(Ticket, ticket_id)
        assert ticket is not None
        return ticket


def card(harness: Harness) -> Any:
    """The last ticket card sent or edited in the support channel."""
    calls = harness.telegram.of(SendMessage, EditMessageText)
    return [call for call in calls if call.chat_id == SUPPORT_CHANNEL_ID][-1]


async def answer_ticket(harness: Harness, ticket_id: int, text: str = "Printerni qayta ulang.") -> None:
    await harness.send_text(ADMIN_ID, f"/start t{ticket_id}")
    await harness.press(ADMIN_ID, TicketReplyCb(id=ticket_id))
    await harness.send_text(ADMIN_ID, text)


async def test_a_problem_becomes_a_ticket_in_the_support_channel(harness: Harness) -> None:
    await harness.send_text(CLIENT_ID, "/start")
    await harness.press(CLIENT_ID, CONTACTS)
    await harness.press(CLIENT_ID, WRITE_PROBLEM)
    # The first time, the phone to call back on comes first.
    assert last_text(harness) == t("phone_prompt")
    await harness.send_text(CLIENT_ID, "ertaga qo‘ng‘iroq qiling")
    assert last_text(harness).startswith(t("error_phone"))
    await harness.send_text(CLIENT_ID, PHONE)
    assert last_text(harness).startswith("✍️ <b>Muammoingizni yozing</b>")
    assert "<b>+998 90 123 45 67</b>" in last_text(harness)
    assert last_buttons(harness) == ["📱 Raqamni o‘zgartirish", "❌ Bekor qilish"]

    harness.telegram.reset()
    problem_id = await harness.send_text(CLIENT_ID, PROBLEM)

    # The client's message is copied to the channel, and a card with the buttons goes under it.
    copy = harness.telegram.of(CopyMessage)[0]
    assert (copy.chat_id, copy.from_chat_id, copy.message_id) == (SUPPORT_CHANNEL_ID, CLIENT_ID, problem_id)
    posted = card(harness)
    assert posted.text.startswith(
        '📩 <b>Murojaat #1</b>\n👤 User2 · <a href="tg://user?id=2">profilni ochish</a>\n📱 +998 90 123 45 67\n'
    )
    assert posted.text.endswith("⏳ <b>Javob kutilmoqda</b>")
    assert posted.reply_parameters is not None
    answer_button = posted.reply_markup.inline_keyboard[0][0]
    assert answer_button.url == f"https://t.me/{BOT_USERNAME}?start=t1"
    assert button_texts(posted) == ["✍️ Javob berish", "✅ Bajarildi", "❌ Bajarilmadi"]

    # The client gets the ticket number; their message leaves the chat after the copy.
    assert last_text(harness) == t("problem_sent", id=1) + "\n\n" + t("contacts")
    names = [type(call).__name__ for call in harness.telegram.calls]
    assert names.index("CopyMessage") < names.index("DeleteMessage")

    ticket = await stored(harness, 1)
    assert (ticket.user_id, ticket.phone, ticket.text, ticket.status) == (CLIENT_ID, "+998901234567", PROBLEM, "new")
    assert ticket.channel_id == SUPPORT_CHANNEL_ID
    assert ticket.channel_copy_id is not None and ticket.channel_card_id is not None


async def test_an_admin_answers_in_the_bot_then_marks_the_ticket(harness: Harness) -> None:
    await write_problem(harness, CLIENT_ID, text=PROBLEM)
    card_id = (await stored(harness, 1)).channel_card_id

    # «✍️ Javob berish» in the channel opens the bot on the ticket.
    await harness.send_text(ADMIN_ID, "/start t1")
    assert last_text(harness).startswith("📩 <b>Murojaat #1</b>")
    assert last_text(harness).endswith(f"<blockquote>{PROBLEM}</blockquote>")
    assert last_buttons(harness) == ["✍️ Javob yozish", "⏳ Javobsizlar", "📨 Hisobot"]

    await harness.press(ADMIN_ID, TicketReplyCb(id=1))
    assert last_text(harness).startswith("✍️ <b>#1 · User2 ga javob</b>")

    harness.telegram.reset()
    reply_id = await harness.send_text(ADMIN_ID, "Printerni qayta ulang.")

    # The client gets a header, then the admin's message itself.
    to_client = [call.text for call in harness.telegram.of(SendMessage) if call.chat_id == CLIENT_ID]
    assert to_client == [t("reply_header", id=1)]
    copy = [call for call in harness.telegram.of(CopyMessage) if call.chat_id == CLIENT_ID][0]
    assert (copy.from_chat_id, copy.message_id) == (ADMIN_ID, reply_id)

    # The admin is asked to mark the ticket now; the card in the channel shows the answer.
    assert last_text(harness).startswith(t("reply_sent"))
    assert last_buttons(harness)[:3] == ["✍️ Yana javob yozish", "✅ Bajarildi", "❌ Bajarilmadi"]
    answered = card(harness)
    assert answered.message_id == card_id
    assert "💬 <b>Javob berildi</b> — User1, " in answered.text and answered.text.endswith("· 1 ta javob")

    await harness.press(ADMIN_ID, TicketMarkCb(id=1, done=True))
    assert toasts(harness)[-1] == "✅ Bajarildi deb belgilandi"
    assert "✅ <b>Bajarildi</b> — User1, " in last_text(harness)
    assert "✅ <b>Bajarildi</b> — User1, " in card(harness).text
    assert (await stored(harness, 1)).status == "done"

    # The card can be marked in the channel too.
    await harness.press(ADMIN_ID, TicketMarkCb(id=1, done=False), message_id=card_id, chat_id=SUPPORT_CHANNEL_ID)
    assert "❌ <b>Bajarilmadi</b> — User1, " in card(harness).text
    assert (await stored(harness, 1)).status == "not_done"


async def test_a_ticket_cannot_be_marked_before_an_answer(harness: Harness) -> None:
    await write_problem(harness, CLIENT_ID, text=PROBLEM)
    card_id = (await stored(harness, 1)).channel_card_id

    await harness.press(ADMIN_ID, TicketMarkCb(id=1, done=True), message_id=card_id, chat_id=SUPPORT_CHANNEL_ID)
    alert = harness.telegram.of(AnswerCallbackQuery)[-1]
    assert (alert.text, alert.show_alert) == (t("ticket_needs_answer"), True)
    assert (await stored(harness, 1)).status == "new"

    # In the bot the mark buttons only come after an answer.
    await harness.send_text(ADMIN_ID, "/start t1")
    assert "✅ Bajarildi" not in last_buttons(harness)


async def test_an_answer_that_cannot_reach_the_client(harness: Harness) -> None:
    await write_problem(harness, CLIENT_ID, text=PROBLEM)
    await harness.send_text(ADMIN_ID, "/start t1")
    await harness.press(ADMIN_ID, TicketReplyCb(id=1))
    harness.telegram.fail_once(SendMessage, TelegramForbiddenError(method=None, message="Forbidden: bot was blocked"))
    await harness.send_text(ADMIN_ID, "Javob")
    assert last_text(harness).startswith(t("reply_not_delivered"))
    assert (await stored(harness, 1)).status == "new"


async def test_a_header_without_its_answer_is_taken_back(harness: Harness) -> None:
    await write_problem(harness, CLIENT_ID, text=PROBLEM)
    await harness.send_text(ADMIN_ID, "/start t1")
    await harness.press(ADMIN_ID, TicketReplyCb(id=1))
    harness.telegram.reset()
    harness.telegram.fail_once(CopyMessage, TelegramForbiddenError(method=None, message="Forbidden: bot was blocked"))
    await harness.send_text(ADMIN_ID, "Javob")
    header, *_ = calls = harness.telegram.calls[:3]
    assert [(type(call).__name__, call.chat_id) for call in calls] == [
        ("SendMessage", CLIENT_ID),
        ("CopyMessage", CLIENT_ID),
        ("DeleteMessage", CLIENT_ID),
    ]
    assert header.text == t("reply_header", id=1)
    assert last_text(harness).startswith(t("reply_not_delivered"))


async def test_report_of_the_day_and_the_waiting_list(harness: Harness) -> None:
    for user_id in (CLIENT_ID, 5, 6):
        await write_problem(harness, user_id, text=f"Muammo {user_id}")
    await answer_ticket(harness, 1)
    async with harness.session_factory() as session:
        # A problem from yesterday nobody has answered.
        session.add(
            Ticket(
                user_id=7,
                user_name="Kecha",
                text="Eski muammo",
                status="new",
                replies=0,
                created_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        await session.commit()

    await harness.send_text(ADMIN_ID, "/admin")
    assert last_buttons(harness)[0] == "📨 Murojaatlar · 3"
    await harness.press(ADMIN_ID, SupportReportCb())
    report = last_text(harness)
    assert "📥 Kelgan: <b>3</b> ta (3 kishidan)" in report
    assert "💬 Javob berilgan: <b>1</b>" in report
    assert "⏳ Javobsiz qolgan: <b>2</b>" in report
    assert "⏳ Hozir javob kutayotganlar (barcha kunlar): <b>3</b>" in report
    assert last_buttons(harness) == ["⏳ Javob kutayotganlar · 3", "◀️ Oldingi kun", "⬅️ Admin panel"]

    await harness.press(ADMIN_ID, SupportReportCb(days_ago=1))
    assert "(kecha)" in last_text(harness) and "📥 Kelgan: <b>1</b> ta (1 kishidan)" in last_text(harness)
    assert "Keyingi kun ▶️" in last_buttons(harness)

    # The waiting ones, the oldest first; each opens to be answered.
    await harness.press(ADMIN_ID, WaitingCb())
    assert last_text(harness).startswith("⏳ <b>Javob kutayotgan murojaatlar</b> — 3 ta")
    assert last_buttons(harness) == ["#4 · Kecha", "#2 · User5", "#3 · User6", "📨 Hisobot"]
    await harness.press(ADMIN_ID, TicketCb(id=4))
    assert "<blockquote>Eski muammo</blockquote>" in last_text(harness)


async def test_nothing_waiting(harness: Harness) -> None:
    await harness.send_text(ADMIN_ID, "/admin")
    assert last_buttons(harness)[0] == "📨 Murojaatlar"
    await harness.press(ADMIN_ID, SupportReportCb())
    assert t("report_none") in last_text(harness) and t("report_all_answered") in last_text(harness)
    await harness.press(ADMIN_ID, WaitingCb())
    assert last_text(harness) == t("waiting_none")


async def test_photos_show_on_the_ticket_and_voice_notes_open_with_a_button(harness: Harness) -> None:
    photo = [PhotoSize(file_id="file-screen", file_unique_id="screen", width=1, height=1)]
    await write_problem(harness, CLIENT_ID, photo=photo, caption="Shu xato chiqyapti")
    await harness.send_text(ADMIN_ID, "/start t1")
    shown = harness.telegram.of(SendPhoto)[-1]
    assert shown.photo == "file-screen"
    assert "🖼 Rasm\n<blockquote>Shu xato chiqyapti</blockquote>" in shown.caption

    voice = Voice(file_id="file-voice", file_unique_id="voice", duration=3)
    await write_problem(harness, 5, voice=voice)
    await harness.send_text(ADMIN_ID, "/start t2")
    assert last_text(harness).endswith("🎤 Ovozli xabar")
    assert "📎 Ilovani ochish" in last_buttons(harness)
    await harness.press(ADMIN_ID, TicketFileCb(id=2))
    sent = harness.telegram.of(SendVoice)[-1]
    assert (sent.chat_id, sent.voice) == (ADMIN_ID, "file-voice")


async def test_what_a_client_may_send_and_how_often(harness: Harness) -> None:
    sticker = Sticker(
        file_id="s", file_unique_id="s", type="regular", width=1, height=1, is_animated=False, is_video=False
    )
    await write_problem(harness, CLIENT_ID, sticker=sticker)
    assert last_text(harness).startswith(t("error_expected_message"))

    await harness.send_text(CLIENT_ID, PROBLEM)
    await harness.press(CLIENT_ID, WRITE_PROBLEM)  # one problem a minute
    toast = toasts(harness)[-1]
    assert toast.startswith("⏳ Keyingi murojaatni ") and toast.endswith(" soniyadan keyin yuborishingiz mumkin.")


async def test_the_phone_is_asked_once_and_can_be_changed(harness: Harness) -> None:
    await harness.send_text(CLIENT_ID, "/start")
    await harness.press(CLIENT_ID, CONTACTS)
    await harness.press(CLIENT_ID, WRITE_PROBLEM)
    # A shared contact works too; Telegram gives its number without the +.
    await harness.send(CLIENT_ID, contact=Contact(phone_number="998901112233", first_name="Ali"))
    assert "<b>+998 90 111 22 33</b>" in last_text(harness)

    await harness.press(CLIENT_ID, CHANGE_PHONE)
    assert last_text(harness) == t("phone_prompt")
    await harness.send_text(CLIENT_ID, "+7 (916) 123-45-67")
    assert "<b>+79161234567</b>" in last_text(harness)

    # Next time the problem is asked for at once, with the number the client left.
    await harness.press(CLIENT_ID, CONTACTS)
    await harness.press(CLIENT_ID, WRITE_PROBLEM)
    assert last_text(harness).startswith("✍️ <b>Muammoingizni yozing</b>")
    await harness.send_text(CLIENT_ID, PROBLEM)
    assert "\n📱 +79161234567\n" in card(harness).text


async def test_leaving_the_dialog_does_not_send_later_messages(harness: Harness) -> None:
    await harness.send_text(CLIENT_ID, "/start")
    await harness.press(CLIENT_ID, CONTACTS)
    await harness.press(CLIENT_ID, WRITE_PROBLEM)
    await harness.press(CLIENT_ID, MenuCb())  # went elsewhere instead of writing
    await harness.send_text(CLIENT_ID, "tasodifiy xabar")
    assert harness.telegram.of(CopyMessage) == []
    assert last_text(harness) == t("main_menu_empty")  # typed text brings the menu back, as everywhere


async def test_an_album_is_one_ticket_with_every_photo_in_the_channel(harness: Harness) -> None:
    def shot(number: int) -> list[PhotoSize]:
        return [PhotoSize(file_id=f"shot-{number}", file_unique_id=f"shot-{number}", width=1, height=1)]

    # Telegram delivers an album as one message per photo; the caption comes with the first.
    await write_problem(harness, CLIENT_ID, photo=shot(1), media_group_id="album", caption=PROBLEM)
    for number in (2, 3):
        await harness.send(CLIENT_ID, photo=shot(number), media_group_id="album")

    copies = [call for call in harness.telegram.of(CopyMessage) if call.chat_id == SUPPORT_CHANNEL_ID]
    assert copies[0].reply_parameters is None
    # The other photos go under the first one, like the card.
    under = {copy.reply_parameters.message_id for copy in copies[1:]}
    assert len(copies) == 3 and under == {card(harness).reply_parameters.message_id}
    # One ticket, and the client still sees that it was received.
    async with harness.session_factory() as session:
        assert await repo.count_new_tickets(session) == 1
    assert last_text(harness).startswith(t("problem_sent", id=1))


async def test_a_message_sent_while_the_button_is_handled_waits_for_it(harness: Harness) -> None:
    # The message comes in while «✍️ Muammoni yozish» is still being handled: it waits for it
    # and is taken as the problem, instead of reading the state from before the press.
    await harness.send_text(CLIENT_ID, "/start")
    async with harness.session_factory() as session:
        await session.execute(update(User).where(User.id == CLIENT_ID).values(phone="+998901234567"))
        await session.commit()
    card = await harness.active_message(CLIENT_ID)
    await asyncio.gather(
        harness.press(CLIENT_ID, WRITE_PROBLEM, message_id=card),
        harness.send_text(CLIENT_ID, PROBLEM),
    )
    assert len(harness.telegram.of(CopyMessage)) == 1
    assert (await stored(harness, 1)).text == PROBLEM


async def test_clients_cannot_open_tickets(harness: Harness) -> None:
    await write_problem(harness, CLIENT_ID, text=PROBLEM)
    await harness.send_text(CLIENT_ID, "/start t1")
    assert last_text(harness) == t("main_menu_empty")
    await harness.press(CLIENT_ID, TicketMarkCb(id=1, done=True))
    assert (await stored(harness, 1)).status == "new"


async def test_without_a_support_channel_the_admins_get_a_notice(
    bot: Bot, telegram: FakeTelegram, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = make_settings(str(engine.url), support_channel_id=None)
    harness = Harness(bot, telegram, create_dispatcher(settings, bot, session_factory), session_factory)
    await write_problem(harness, CLIENT_ID, text=PROBLEM)
    notices = [call.text for call in telegram.of(SendMessage) if call.chat_id == ADMIN_ID]
    assert notices == [t("ticket_notice", id=1)]
    assert last_text(harness) == t("problem_sent", id=1) + "\n\n" + t("contacts")


async def test_active_users(harness: Harness) -> None:
    for user_id in (CLIENT_ID, 5):
        await harness.send_text(user_id, "/start")
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, UsersCb())
    text = last_text(harness)
    assert text.startswith("📈 <b>Foydalanuvchilar</b>")
    assert "👥 Jami: <b>3</b>" in text and "🟢 Bugun faol: <b>3</b>" in text and "🆕 Bugun qo‘shilgan: <b>3</b>" in text
    assert "\n1. User1 — " in text  # the admin, active last
    assert last_buttons(harness) == ["⬅️ Admin panel"]
