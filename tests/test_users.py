"""«📈 Foydalanuvchilar»: the counts, one user's card, finding a user and deleting one."""

from aiogram.methods import CopyMessage
from sqlalchemy import update

from bot.db import repo
from bot.db.models import User
from bot.texts import t
from bot.ui.callbacks import CONTACTS, FIND_USER, WRITE_PROBLEM, UserCb, UserDeleteCb, UsersCb
from tests.conftest import ADMIN_ID, CLIENT_ID, Harness, last_buttons, last_text, toasts


async def stored(harness: Harness, user_id: int) -> User | None:
    async with harness.session_factory() as session:
        return await repo.get_user(session, user_id)


async def test_active_users(harness: Harness) -> None:
    for user_id in (CLIENT_ID, 5):
        await harness.send_text(user_id, "/start")
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, UsersCb())
    text = last_text(harness)
    assert text.startswith("📈 <b>Foydalanuvchilar</b>")
    assert "👥 Jami: <b>3</b>" in text and "🟢 Bugun faol: <b>3</b>" in text and "🆕 Bugun qo‘shilgan: <b>3</b>" in text
    assert "\n1. User1 — " in text  # the admin, active last
    # A number opens the user.
    assert last_buttons(harness) == ["1", "2", "3", "🔎 Topish", "⬅️ Admin panel"]


async def test_an_admin_deletes_a_user(harness: Harness) -> None:
    await harness.send_text(CLIENT_ID, "/start")
    async with harness.session_factory() as session:
        await session.execute(update(User).where(User.id == CLIENT_ID).values(phone="+998901234567"))
        await session.commit()
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, UsersCb())

    await harness.press(ADMIN_ID, UserCb(id=CLIENT_ID))
    card = last_text(harness)
    assert card.startswith('👤 <b>User2</b>\n🆔 <code>2</code> · <a href="tg://user?id=2">profilni ochish</a>')
    assert "\n📱 +998 90 123 45 67\n" in card
    assert last_buttons(harness) == ["🗑 O‘chirish", "⬅️ Orqaga"]

    await harness.press(ADMIN_ID, UserDeleteCb(id=CLIENT_ID))
    assert last_text(harness).startswith("🗑 User2 bazadan o‘chirilsinmi?")
    await harness.press(ADMIN_ID, UserDeleteCb(id=CLIENT_ID, confirm=True))
    assert last_text(harness).startswith("🗑 User2 bazadan o‘chirildi.")
    assert "👥 Jami: <b>1</b>" in last_text(harness)
    assert await stored(harness, CLIENT_ID) is None

    # A second tap on an old button finds them gone.
    await harness.press(ADMIN_ID, UserDeleteCb(id=CLIENT_ID, confirm=True))
    assert toasts(harness)[-1] == t("user_not_found")


async def test_admins_are_not_deleted_from_the_list(harness: Harness) -> None:
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, UserCb(id=ADMIN_ID))
    assert last_text(harness).endswith(t("user_is_admin"))
    assert last_buttons(harness) == ["⬅️ Orqaga"]
    await harness.press(ADMIN_ID, UserDeleteCb(id=ADMIN_ID, confirm=True))
    assert toasts(harness)[-1] == t("user_is_admin_alert")
    assert await stored(harness, ADMIN_ID) is not None


async def test_a_deleted_user_starts_afresh(harness: Harness) -> None:
    # Deleted while writing a problem: their next message is not taken for it.
    await harness.send_text(CLIENT_ID, "/start")
    await harness.press(CLIENT_ID, CONTACTS)
    await harness.press(CLIENT_ID, WRITE_PROBLEM)
    await harness.send_text(CLIENT_ID, "90 123 45 67")
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, UserDeleteCb(id=CLIENT_ID, confirm=True))

    await harness.send_text(CLIENT_ID, "Printer ishlamayapti")
    assert harness.telegram.of(CopyMessage) == []
    assert last_text(harness) == t("main_menu_empty")  # typed text brings the menu back, as everywhere
    user = await stored(harness, CLIENT_ID)
    assert user is not None and user.phone is None  # registered again, as a new user


async def test_finding_a_user(harness: Harness) -> None:
    await harness.send_text(CLIENT_ID, "/start")
    async with harness.session_factory() as session:
        await session.execute(update(User).where(User.id == CLIENT_ID).values(username="Pari_Ramazanova"))
        await session.commit()
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, UsersCb())
    await harness.press(ADMIN_ID, FIND_USER)
    assert last_text(harness).startswith("<b>🔎 Foydalanuvchini topish</b>")

    await harness.send_text(ADMIN_ID, "salom")
    assert last_text(harness).startswith(t("error_person_expected"))
    await harness.send_text(ADMIN_ID, "777")
    assert last_text(harness).startswith(t("error_user_unknown"))
    await harness.send_text(ADMIN_ID, "@pari_ramazanova")  # any letter case
    assert last_text(harness).startswith("👤 <b>User2 (@Pari_Ramazanova)</b>")
    assert last_buttons(harness) == ["🗑 O‘chirish", "⬅️ Orqaga"]
