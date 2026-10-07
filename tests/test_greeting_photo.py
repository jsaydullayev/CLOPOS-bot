"""A photo on the greeting: set, changed, removed, and shown to clients."""

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, EditMessageMedia, EditMessageText, SendMessage, SendPhoto
from aiogram.types import MessageEntity

from bot.services.catalog import add_video, create_category
from bot.ui.callbacks import AdminTextEditCb, AdminTextResetCb, AdminTextsCb, CategoryCb, MenuCb, VideoCb
from tests.conftest import ADMIN_ID, CLIENT_ID, Harness, file_id_of


def last_text(harness: Harness) -> str:
    return harness.telegram.of(SendMessage, EditMessageText)[-1].text


def last_buttons(harness: Harness) -> list[str]:
    method = harness.telegram.calls_with_markup()[-1]
    return [button.text for row in method.reply_markup.inline_keyboard for button in row]


def call_names(harness: Harness) -> list[str]:
    return [type(call).__name__ for call in harness.telegram.calls]


async def seed(harness: Harness) -> tuple[int, int]:
    async with harness.session_factory() as session:
        section = await create_category(session, parent_id=None, raw_title="Finance", admin_id=1, max_depth=3)
        video = await add_video(
            session,
            category_id=section.id,
            title="Reports",
            description=None,
            file_id=file_id_of("r"),
            file_unique_id="r",
            media_type="video",
            admin_id=1,
        )
        await session.commit()
        return section.id, video.id


async def open_greeting(harness: Harness) -> None:
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, AdminTextsCb(key="main_menu"))


async def test_admin_puts_a_photo_on_the_greeting(harness: Harness) -> None:
    await seed(harness)
    await open_greeting(harness)
    assert "🖼 Rasm qo‘yish" in last_buttons(harness)

    # The photo button asks for a photo; a photo with a caption sets both.
    await harness.press(ADMIN_ID, AdminTextEditCb(key="main_menu", photo=True))
    assert last_text(harness).startswith("<b>Salomlashuv (bosh menyu)</b>\nRasmni yuboring")
    await harness.send_text(ADMIN_ID, "rasm o‘rniga matn")
    assert last_text(harness).startswith("⚠️ Rasm kutilmoqda.")
    bold = [MessageEntity(type="bold", offset=0, length=5)]
    await harness.send_photo(ADMIN_ID, "logo", caption="Salom! CLOPOS darslari", caption_entities=bold)

    # The admin sees the result as a photo, with the photo buttons now.
    preview = harness.telegram.of(SendPhoto)[-1]
    assert (preview.photo, preview.caption) == (file_id_of("logo"), "<b>Salom</b>! CLOPOS darslari")
    assert last_buttons(harness) == [
        "✏️ Matnni o‘zgartirish",
        "🖼 Rasmni almashtirish",
        "🗑 Rasmni olib tashlash",
        "↩️ Standart holatga qaytarish",
        "⬅️ Orqaga",
    ]

    harness.telegram.reset()
    await harness.send_text(CLIENT_ID, "/start")
    menu = harness.telegram.of(SendPhoto)[-1]
    assert menu.photo == file_id_of("logo")  # the largest size
    assert menu.caption == "<b>Salom</b>! CLOPOS darslari"
    assert [b.text for row in menu.reply_markup.inline_keyboard for b in row] == ["Finance"]

    # A new photo without a caption changes only the photo.
    await open_greeting(harness)
    await harness.press(ADMIN_ID, AdminTextEditCb(key="main_menu", photo=True))
    await harness.send_photo(ADMIN_ID, "logo2")
    harness.telegram.reset()
    await harness.send_text(CLIENT_ID, "/start")
    menu = harness.telegram.of(SendPhoto)[-1]
    assert (menu.photo, menu.caption) == (file_id_of("logo2"), "<b>Salom</b>! CLOPOS darslari")

    # Changing the text keeps the photo.
    await open_greeting(harness)
    await harness.press(ADMIN_ID, AdminTextEditCb(key="main_menu"))
    await harness.send_text(ADMIN_ID, "Yangi salom")
    harness.telegram.reset()
    await harness.send_text(CLIENT_ID, "/start")
    menu = harness.telegram.of(SendPhoto)[-1]
    assert (menu.photo, menu.caption) == (file_id_of("logo2"), "Yangi salom")

    # Removing the photo keeps the text.
    await open_greeting(harness)
    await harness.press(ADMIN_ID, AdminTextResetCb(key="main_menu", photo=True))
    assert last_text(harness).startswith("🗑 «Salomlashuv (bosh menyu)» rasmi olib tashlandi.")
    harness.telegram.reset()
    await harness.send_text(CLIENT_ID, "/start")
    assert harness.telegram.of(SendPhoto) == []
    assert last_text(harness) == "Yangi salom"


async def test_photo_greeting_while_walking_the_catalog(harness: Harness) -> None:
    section_id, video_id = await seed(harness)
    await open_greeting(harness)
    await harness.press(ADMIN_ID, AdminTextEditCb(key="main_menu", photo=True))
    await harness.send_photo(ADMIN_ID, "logo", caption="Salom")

    await harness.send_text(CLIENT_ID, "/start")

    # Photo -> text list: a new message, the photo is deleted.
    harness.telegram.reset()
    await harness.press(CLIENT_ID, CategoryCb(id=section_id))
    assert call_names(harness) == ["AnswerCallbackQuery", "SendMessage", "DeleteMessage"]

    # Video -> main menu: the photo replaces the video inside the same message.
    await harness.press(CLIENT_ID, VideoCb(id=video_id))
    harness.telegram.reset()
    await harness.press(CLIENT_ID, MenuCb())
    swap = harness.telegram.of(EditMessageMedia)[-1]
    assert (swap.media.type, swap.media.media, swap.media.caption) == ("photo", file_id_of("logo"), "Salom")
    assert harness.telegram.of(DeleteMessage) == []


async def test_menu_still_works_when_the_photo_cannot_be_sent(harness: Harness) -> None:
    await seed(harness)
    await open_greeting(harness)
    await harness.press(ADMIN_ID, AdminTextEditCb(key="main_menu", photo=True))
    await harness.send_photo(ADMIN_ID, "old-bot-photo", caption="Salom")

    harness.telegram.reset()
    harness.telegram.fail_once(SendPhoto, TelegramBadRequest(method=None, message="Bad Request: wrong file identifier"))
    await harness.send_text(CLIENT_ID, "/start")
    assert call_names(harness) == ["DeleteMessage", "SendPhoto", "SendMessage"]
    assert harness.telegram.of(SendMessage)[-1].text == "Salom"


async def test_photos_are_refused_where_they_do_not_belong(harness: Harness) -> None:
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, AdminTextsCb(key="main_menu_empty"))
    await harness.press(ADMIN_ID, AdminTextEditCb(key="main_menu_empty"))
    await harness.send_photo(ADMIN_ID, "x", caption="Salom")
    assert last_text(harness).startswith("⚠️ Bu matnga rasm qo‘shib bo‘lmaydi — faqat matn yuboring.")

    await harness.press(ADMIN_ID, AdminTextEditCb(key="main_menu", photo=True))
    await harness.send_document(ADMIN_ID, "logo.png", mime_type="image/png")
    assert last_text(harness).startswith("⚠️ Rasmni fayl sifatida emas, rasm sifatida yuboring.")
