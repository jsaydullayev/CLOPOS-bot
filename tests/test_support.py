"""«📞 Bog‘lanish va yordam»: a client leaves a problem, every admin gets it."""

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import AnswerCallbackQuery, CopyMessage, SendMessage
from aiogram.types import PhotoSize

from bot.texts import t
from bot.ui.callbacks import CONTACTS, WRITE_PROBLEM, MenuCb
from tests.conftest import ADMIN_ID, CLIENT_ID, Harness, last_text

SENT = "✅ <b>Murojaatingiz yuborildi!</b> Mutaxassislarimiz tez orada siz bilan bog‘lanadi."


def to_admin(harness: Harness) -> list[str]:
    return [call.text for call in harness.telegram.of(SendMessage) if call.chat_id == ADMIN_ID]


async def open_problem(harness: Harness) -> None:
    await harness.send_text(CLIENT_ID, "/start")
    await harness.press(CLIENT_ID, CONTACTS)
    await harness.press(CLIENT_ID, WRITE_PROBLEM)


async def test_a_problem_reaches_the_admins_with_who_wrote_it(harness: Harness) -> None:
    await open_problem(harness)
    assert last_text(harness).startswith("✍️ <b>Muammoingizni yozing</b>")

    harness.telegram.reset()
    problem_id = await harness.send_text(CLIENT_ID, "Printer chek chiqarmayapti. +998 90 111 22 33")

    # The admin gets who wrote, with a link to the profile, then the message itself.
    assert to_admin(harness) == [
        f'📩 <b>Yangi murojaat</b>\n👤 User{CLIENT_ID}\n🆔 <a href="tg://user?id={CLIENT_ID}">{CLIENT_ID}</a>'
        " — profilni ochish"
    ]
    copy = harness.telegram.of(CopyMessage)[0]
    assert (copy.chat_id, copy.from_chat_id, copy.message_id) == (ADMIN_ID, CLIENT_ID, problem_id)

    # The client is told, under the contacts; their message is cleared from the chat after the copy.
    assert last_text(harness) == SENT + "\n\n" + t("contacts")
    calls = [type(call).__name__ for call in harness.telegram.calls]
    assert calls.index("CopyMessage") < calls.index("DeleteMessage")


async def test_photos_and_videos_are_copied_too(harness: Harness) -> None:
    await open_problem(harness)
    harness.telegram.reset()
    photo = [PhotoSize(file_id="file-screen", file_unique_id="screen", width=1, height=1)]
    await harness.send(CLIENT_ID, photo=photo, caption="Shu xato chiqyapti")
    assert len(harness.telegram.of(CopyMessage)) == 1
    assert last_text(harness).startswith(SENT)


async def test_one_problem_a_minute(harness: Harness) -> None:
    await open_problem(harness)
    await harness.send_text(CLIENT_ID, "Birinchi")

    harness.telegram.reset()
    await harness.press(CLIENT_ID, WRITE_PROBLEM)
    toast = harness.telegram.of(AnswerCallbackQuery)[-1].text
    assert toast.startswith("⏳ Keyingi murojaatni ") and toast.endswith(" soniyadan keyin yuborishingiz mumkin.")
    assert harness.telegram.of(CopyMessage) == []


async def test_when_no_admin_can_be_reached_the_client_is_told_to_call(harness: Harness) -> None:
    await open_problem(harness)
    harness.telegram.fail_once(SendMessage, TelegramForbiddenError(method=None, message="Forbidden: bot was blocked"))
    await harness.send_text(CLIENT_ID, "Yordam kerak")
    assert last_text(harness) == t("problem_not_sent") + "\n\n" + t("contacts")

    # Nothing was delivered, so the client may try again right away.
    await harness.press(CLIENT_ID, WRITE_PROBLEM)
    assert last_text(harness).startswith("✍️ <b>Muammoingizni yozing</b>")


async def test_leaving_the_dialog_does_not_send_later_messages(harness: Harness) -> None:
    await open_problem(harness)
    await harness.press(CLIENT_ID, CONTACTS)  # «Bekor qilish»
    await harness.send_text(CLIENT_ID, "salom")
    assert harness.telegram.of(CopyMessage) == []

    await harness.press(CLIENT_ID, WRITE_PROBLEM)
    await harness.press(CLIENT_ID, MenuCb())  # went elsewhere instead of writing
    await harness.send_text(CLIENT_ID, "tasodifiy xabar")
    assert harness.telegram.of(CopyMessage) == []
    assert last_text(harness) == t("main_menu_empty")  # typed text brings the menu back, as everywhere
