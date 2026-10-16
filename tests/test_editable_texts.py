"""The admin writes the greeting and section introductions in the bot."""

from datetime import UTC, datetime

from aiogram.enums import ChatType
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, MessageEntity, Update
from aiogram.types import User as TgUser

from bot.services.catalog import add_video, create_category
from bot.texts import t
from bot.ui.callbacks import (
    ADMIN_PANEL,
    CONTACTS,
    AdminCategoryCb,
    AdminFlowCb,
    AdminIntroCb,
    AdminTextEditCb,
    AdminTextResetCb,
    AdminTextsCb,
    CategoryCb,
)
from tests.conftest import ADMIN_ID, CLIENT_ID, Harness, file_id_of, last_buttons, last_text


async def send_formatted(harness: Harness, user_id: int, text: str, entities: list[MessageEntity]) -> None:
    message = Message(
        message_id=900,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type=ChatType.PRIVATE),
        from_user=TgUser(id=user_id, is_bot=False, first_name="Admin"),
        text=text,
        entities=entities,
    )
    await harness.dispatcher.feed_update(harness.bot, Update(update_id=9000, message=message))


async def seed(harness: Harness) -> int:
    async with harness.session_factory() as session:
        section = await create_category(session, parent_id=None, raw_title="Finance", admin_id=1, max_depth=3)
        await add_video(
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
        return section.id


async def test_admin_changes_the_greeting(harness: Harness) -> None:
    await seed(harness)

    await harness.send_text(ADMIN_ID, "/admin")
    assert "✏️ Salomlashuv va matnlar" in last_buttons(harness)
    await harness.press(ADMIN_ID, AdminTextsCb())
    assert last_buttons(harness) == [
        "Salomlashuv (bosh menyu)",
        "Katalog bo‘sh bo‘lganda",
        "📞 Bog‘lanish va yordam",
        "⬅️ Admin panel",
    ]

    # The greeting as the client sees it, with the edit buttons under it.
    await harness.press(ADMIN_ID, AdminTextsCb(key="main_menu"))
    assert last_text(harness) == "<b>Salomlashuv (bosh menyu)</b> — mijoz shunday ko‘radi:\n\n" + t("main_menu")
    assert last_buttons(harness) == ["✏️ Matnni o‘zgartirish", "🖼 Rasm yoki video qo‘yish", "⬅️ Orqaga"]

    # Formatting the admin used is kept.
    await harness.press(ADMIN_ID, AdminTextEditCb(key="main_menu"))
    assert last_text(harness).startswith("<b>Salomlashuv (bosh menyu)</b>\nYangi matnni yuboring")
    welcome = "Assalomu alaykum! CLOPOS video darslariga xush kelibsiz."
    await send_formatted(harness, ADMIN_ID, welcome, [MessageEntity(type="bold", offset=0, length=17)])
    assert last_text(harness) == (
        "✅ «Salomlashuv (bosh menyu)» saqlandi.\n\n"
        "<b>Salomlashuv (bosh menyu)</b> — mijoz shunday ko‘radi:\n\n"
        "<b>Assalomu alaykum!</b> CLOPOS video darslariga xush kelibsiz."
    )
    assert "↩️ Standart holatga qaytarish" in last_buttons(harness)

    await harness.send_text(CLIENT_ID, "/start")
    assert last_text(harness) == "<b>Assalomu alaykum!</b> CLOPOS video darslariga xush kelibsiz."

    # Back to the text from the locales file.
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, AdminTextsCb())
    assert "Salomlashuv (bosh menyu) · o‘zgartirilgan" in last_buttons(harness)
    await harness.press(ADMIN_ID, AdminTextsCb(key="main_menu"))
    await harness.press(ADMIN_ID, AdminTextResetCb(key="main_menu"))
    assert last_text(harness).startswith("↩️ «Salomlashuv (bosh menyu)» standart holatga qaytdi.")
    await harness.send_text(CLIENT_ID, "/start")
    assert last_text(harness) == t("main_menu")


async def test_text_is_checked_and_can_be_cancelled(harness: Harness) -> None:
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, AdminTextsCb(key="main_menu_empty"))
    assert last_buttons(harness) == ["✏️ Matnni o‘zgartirish", "⬅️ Orqaga"]  # no photo for this text
    await harness.press(ADMIN_ID, AdminTextEditCb(key="main_menu_empty"))

    await harness.send_text(ADMIN_ID, "x" * 1001)
    assert last_text(harness).startswith("⚠️ Matn 1000 belgidan oshmasligi kerak.")
    await harness.send_dice(ADMIN_ID)
    assert last_text(harness).startswith("⚠️ Matn kutilmoqda.")

    await harness.press(ADMIN_ID, AdminFlowCb(action="cancel"))
    assert last_text(harness).startswith("<b>Katalog bo‘sh bo‘lganda</b> — mijoz shunday ko‘radi:")
    await harness.send_text(CLIENT_ID, "/start")
    assert last_text(harness) == t("main_menu_empty")


async def test_admin_writes_a_section_introduction(harness: Harness) -> None:
    section_id = await seed(harness)

    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, AdminCategoryCb(id=section_id))
    assert "✏️ Bo‘lim matni" in last_buttons(harness)
    await harness.press(ADMIN_ID, AdminIntroCb(id=section_id))
    assert "Hozirgi matn:\n— yo‘q —" in last_text(harness)

    intro = "Bu bo‘limda moliya hisobotlari haqida videolar."
    await harness.send_text(ADMIN_ID, intro)
    assert last_text(harness) == f"🎬 <b>Finance</b>\n{intro}\n\n1. Reports"  # the admin's view

    # The client gets the introduction under the title, then the short line on what to do.
    await harness.send_text(CLIENT_ID, "/start")
    await harness.press(CLIENT_ID, CategoryCb(id=section_id))
    assert last_text(harness) == f"🎬 <b>Finance</b>\n{intro}\n\n" + t("hint_videos") + "\n1. Reports"

    # Removing the introduction.
    await harness.press(ADMIN_ID, AdminIntroCb(id=section_id))
    assert "🗑 Matnni olib tashlash" in last_buttons(harness)
    await harness.press(ADMIN_ID, AdminIntroCb(id=section_id, clear=True))
    assert last_text(harness) == "🎬 <b>Finance</b>\n\n1. Reports"


async def test_clients_cannot_change_texts(harness: Harness) -> None:
    await harness.send_text(CLIENT_ID, "/start")
    harness.telegram.reset()
    await harness.press(CLIENT_ID, AdminTextsCb(key="main_menu"))
    await harness.send_text(CLIENT_ID, "Buzilgan salom")
    await harness.press(CLIENT_ID, ADMIN_PANEL)
    await harness.send_text(CLIENT_ID, "/start")
    assert last_text(harness) == t("main_menu_empty")


async def test_admin_changes_the_contacts(harness: Harness) -> None:
    await seed(harness)

    # Clients have the green button at the bottom from the start, with the standard contacts.
    await harness.send_text(CLIENT_ID, "/start")
    rows = harness.telegram.of(SendMessage)[-1].reply_markup.inline_keyboard
    assert [[button.text for button in row] for row in rows] == [["🎬 Finance"], ["📞 Bog‘lanish va yordam"]]
    assert (rows[0][0].style, rows[1][0].style) == ("primary", "success")
    await harness.press(CLIENT_ID, CONTACTS)
    assert "☎️ Telefon: +998 55 513 11 77\n💬 Telegram: @CloposYordam" in last_text(harness)

    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, AdminTextsCb(key="contacts"))
    await harness.press(ADMIN_ID, AdminTextEditCb(key="contacts"))
    await harness.send_text(ADMIN_ID, "☎️ +998 90 123 45 67\n💬 @clopos_support")

    await harness.press(CLIENT_ID, CONTACTS)
    assert last_text(harness) == "☎️ +998 90 123 45 67\n💬 @clopos_support"
    assert last_buttons(harness) == ["✍️ Muammoni yozib qoldirish", "🏠 Bosh menyu"]

    # Back to the standard contacts.
    await harness.press(ADMIN_ID, AdminTextResetCb(key="contacts"))
    await harness.press(CLIENT_ID, CONTACTS)
    assert last_text(harness) == t("contacts")
