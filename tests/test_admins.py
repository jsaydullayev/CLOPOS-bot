"""Admins: the owners in ADMIN_IDS and the ones added in the admin panel."""

from datetime import UTC, datetime

from aiogram import Bot
from aiogram.methods import DeleteMyCommands, SendMessage, SetMyCommands
from aiogram.types import Contact, MessageOriginHiddenUser, MessageOriginUser
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import Admin, User
from bot.services.admins import Admins
from bot.services.notify import Notifier
from bot.texts import t
from bot.ui.callbacks import ADD_ADMIN, ADMINS, AdminRemoveCb
from tests.conftest import ADMIN_ID, CLIENT_ID, FakeTelegram, Harness, last_buttons, last_text, toasts

MENU = t("main_menu_empty")


async def start_adding(harness: Harness) -> None:
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, ADMINS)
    await harness.press(ADMIN_ID, ADD_ADMIN)


async def test_an_admin_added_by_id_can_open_the_panel(harness: Harness) -> None:
    await harness.send_text(CLIENT_ID, "/admin")
    assert last_text(harness) == MENU  # not an admin yet

    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, ADMINS)
    assert last_text(harness).startswith("<b>👥 Adminlar</b>")
    assert last_text(harness).endswith("\n\n👑 User1")
    assert last_buttons(harness) == ["➕ Admin qo‘shish", "⬅️ Admin panel"]  # the owner has no remove button

    await harness.press(ADMIN_ID, ADD_ADMIN)
    assert "• Telegram ID raqami" in last_text(harness)
    harness.telegram.reset()
    await harness.send_text(ADMIN_ID, str(CLIENT_ID))
    assert last_text(harness).startswith("✅ User2 admin qilindi.")
    assert last_text(harness).endswith("👑 User1\n👤 User2")
    assert last_buttons(harness) == ["🗑 User2", "➕ Admin qo‘shish", "⬅️ Admin panel"]

    # The new admin gets the /admin command and a word about it.
    commands = [call for call in harness.telegram.of(SetMyCommands) if call.scope.chat_id == CLIENT_ID]
    assert [command.command for command in commands[0].commands] == ["start", "admin"]
    welcome = [call.text for call in harness.telegram.of(SendMessage) if call.chat_id == CLIENT_ID]
    assert welcome == ["👋 Siz bu botda admin qilindingiz. Admin panel: /admin"]

    await harness.send_text(CLIENT_ID, "/admin")
    assert last_text(harness) == "<b>Admin panel</b>"


async def test_an_admin_can_be_named_by_username_contact_or_forward(harness: Harness) -> None:
    async with harness.session_factory() as session:
        session.add(User(id=8, first_name="Ali", username="Ali_Bek"))
        await session.commit()
    await start_adding(harness)

    # @username: only people who have written to the bot are known.
    await harness.send_text(ADMIN_ID, "@nobody_here")
    assert last_text(harness).startswith("⚠️ @nobody_here topilmadi")
    await harness.send_text(ADMIN_ID, "@ali_bek")
    assert last_text(harness).startswith("✅ Ali (@Ali_Bek) admin qilindi.")

    # A contact from the phone book, if the person has a Telegram account.
    await harness.press(ADMIN_ID, ADD_ADMIN)
    await harness.send(ADMIN_ID, contact=Contact(phone_number="+998901234567", first_name="Vali"))
    assert last_text(harness).startswith("⚠️ Bu kontaktning Telegram akkaunti yo‘q.")
    contact = Contact(phone_number="+998901234567", first_name="Vali", last_name="Karimov", user_id=9)
    await harness.send(ADMIN_ID, contact=contact)
    assert last_text(harness).startswith("✅ Vali Karimov admin qilindi.")

    # A forwarded message, unless the sender hides behind it.
    await harness.press(ADMIN_ID, ADD_ADMIN)
    now = datetime.now(UTC)
    hidden = MessageOriginHiddenUser(date=now, sender_user_name="Yashirin")
    await harness.send(ADMIN_ID, text="salom", forward_origin=hidden)
    assert last_text(harness).startswith("⚠️ Bu forward’dan odamni aniqlab bo‘lmadi")
    bot_origin = MessageOriginUser(date=now, sender_user=TgUser(id=10, is_bot=True, first_name="Bot"))
    await harness.send(ADMIN_ID, text="salom", forward_origin=bot_origin)
    assert last_text(harness).startswith("⚠️ Botni admin qilib bo‘lmaydi.")
    person = MessageOriginUser(date=now, sender_user=TgUser(id=11, is_bot=False, first_name="Gulnora"))
    await harness.send(ADMIN_ID, text="salom", forward_origin=person)
    assert last_text(harness).startswith("✅ Gulnora admin qilindi.")

    # Someone who is an admin already, and text that names nobody.
    await harness.press(ADMIN_ID, ADD_ADMIN)
    await harness.send_text(ADMIN_ID, str(ADMIN_ID))
    assert last_text(harness).startswith("⚠️ User1 allaqachon admin.")
    await harness.send_text(ADMIN_ID, "Ali")
    assert last_text(harness).startswith("⚠️ Kontakt, forward qilingan xabar, @username yoki ID raqami kutilmoqda.")

    async with harness.session_factory() as session:
        assert [admin.user_id for admin in await repo.list_admins(session)] == [8, 9, 11]


async def test_a_removed_admin_loses_the_panel(harness: Harness) -> None:
    await start_adding(harness)
    await harness.send_text(ADMIN_ID, str(CLIENT_ID))  # has never written to the bot: known by the ID only
    assert last_text(harness).startswith("✅ ID 2 admin qilindi.")

    await harness.press(ADMIN_ID, AdminRemoveCb(user_id=CLIENT_ID))
    assert last_text(harness) == "ID 2 adminlikdan olinsinmi? U admin panelga kira olmay qoladi."
    harness.telegram.reset()
    await harness.press(ADMIN_ID, AdminRemoveCb(user_id=CLIENT_ID, confirm=True))
    assert last_text(harness).startswith("🗑 ID 2 adminlikdan olindi.")
    assert harness.telegram.of(DeleteMyCommands)[0].scope.chat_id == CLIENT_ID

    # The owner stays, even with a made-up button.
    await harness.press(ADMIN_ID, AdminRemoveCb(user_id=ADMIN_ID, confirm=True))
    assert toasts(harness)[-1] == "Bu admin allaqachon olib tashlangan"

    await harness.send_text(CLIENT_ID, "/admin")
    assert last_text(harness) == MENU


async def test_an_added_admin_may_give_the_rights_up(harness: Harness) -> None:
    await start_adding(harness)
    await harness.send_text(ADMIN_ID, str(CLIENT_ID))

    await harness.send_text(CLIENT_ID, "/admin")
    await harness.press(CLIENT_ID, ADMINS)
    await harness.press(CLIENT_ID, AdminRemoveCb(user_id=CLIENT_ID, confirm=True))
    assert last_text(harness) == MENU  # the panel is closed for them now
    await harness.press(CLIENT_ID, ADMINS)
    assert last_text(harness) == MENU


async def test_added_admins_are_loaded_at_startup_and_get_notices(
    session: AsyncSession, bot: Bot, telegram: FakeTelegram
) -> None:
    session.add(Admin(user_id=9, name="Vali", added_by=1))
    await session.commit()
    admins = Admins([1])
    assert 9 not in admins
    await admins.load(session)
    assert list(admins) == [1, 9]

    await Notifier(bot, admins).notify("⚠️ Xato")
    assert [call.chat_id for call in telegram.of(SendMessage)] == [1, 9]

    assert not await admins.remove(session, 1)  # an owner
    assert await admins.remove(session, 9)
    assert 9 not in admins
