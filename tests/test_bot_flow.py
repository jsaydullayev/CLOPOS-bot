"""End-to-end: updates go through middlewares, filters and handlers to Bot API calls."""

from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageMedia,
    EditMessageText,
    SendMessage,
    SendVideo,
)
from sqlalchemy import select

from bot.db.models import Category, Video
from bot.services.catalog import add_video, create_category
from bot.ui.callbacks import (
    ADMIN_PANEL,
    AdminAddVideoCb,
    AdminCategoryCb,
    AdminDeleteCategoryCb,
    AdminFlowCb,
    AdminNewCategoryCb,
    AdminPickCb,
    CategoryCb,
    MenuCb,
    VideoCb,
)
from tests.conftest import ADMIN_ID, CHANNEL_ID, CLIENT_ID, Harness, file_id_of


def last_text(harness: Harness) -> str:
    """Text of the last screen the bot sent or edited."""
    return harness.telegram.last_screen_text()


def button_texts(method: SendMessage | EditMessageText | SendVideo | EditMessageMedia) -> list[str]:
    return [button.text for row in method.reply_markup.inline_keyboard for button in row]


def toasts(harness: Harness) -> list[str | None]:
    return [call.text for call in harness.telegram.of(AnswerCallbackQuery)]


async def seed_catalog(harness: Harness) -> dict[str, int]:
    """Kassa › Sozlash with two videos, and Ombor with one."""
    async with harness.session_factory() as session:

        async def category(title: str, parent_id: int | None = None) -> int:
            created = await create_category(
                session, parent_id=parent_id, raw_title=title, admin_id=ADMIN_ID, max_depth=3
            )
            return created.id

        kassa = await category("Kassa")
        sozlash = await category("Sozlash", kassa)
        ombor = await category("Ombor")
        ids = {"kassa": kassa, "sozlash": sozlash, "ombor": ombor}
        videos = [("a", sozlash, "Printer"), ("b", sozlash, "Skaner"), ("c", ombor, "Qoldiq")]
        for key, category_id, title in videos:
            video = await add_video(
                session,
                category_id=category_id,
                title=title,
                description=None,
                file_id=file_id_of(key),
                file_unique_id=key,
                media_type="video",
                admin_id=ADMIN_ID,
            )
            ids[key] = video.id
        await session.commit()
    return ids


async def test_client_with_empty_catalog(harness: Harness) -> None:
    start_id = await harness.send_text(CLIENT_ID, "/start")

    sent = harness.telegram.of(SendMessage)
    assert [message.text for message in sent] == ["Xush kelibsiz! Hozircha videolar yo‘q — tez orada qo‘shiladi."]
    assert harness.telegram.of(DeleteMessage)[0].message_id == start_id
    assert await harness.active_message(CLIENT_ID) is not None


async def test_admin_builds_the_catalog(harness: Harness) -> None:
    telegram = harness.telegram

    await harness.send_text(ADMIN_ID, "/admin")
    assert last_text(harness) == "<b>Admin panel</b>"

    await harness.press(ADMIN_ID, AdminCategoryCb())
    assert "Hali birorta bo‘lim yo‘q." in last_text(harness)

    await harness.press(ADMIN_ID, AdminNewCategoryCb())
    assert "Bo‘lim nomini yozing" in last_text(harness)
    await harness.send_text(ADMIN_ID, "🧾 Kassa")
    assert "Kassa · bo‘sh" in button_texts(telegram.of(EditMessageText)[-1])

    async with harness.session_factory() as session:
        kassa = await session.scalar(select(Category).where(Category.title == "Kassa"))
    assert kassa is not None

    # A sub-category inside Kassa.
    await harness.press(ADMIN_ID, AdminCategoryCb(id=kassa.id))
    assert button_texts(telegram.of(EditMessageText)[-1])[:2] == ["➕ Ichki bo‘lim", "➕ Video"]
    await harness.press(ADMIN_ID, AdminNewCategoryCb(parent=kassa.id))
    await harness.send_text(ADMIN_ID, "K")
    assert last_text(harness).startswith("⚠️ Nom 2–40 belgi bo‘lishi kerak.")
    await harness.send_text(ADMIN_ID, "Sozlash")
    async with harness.session_factory() as session:
        sozlash = await session.scalar(select(Category).where(Category.title == "Sozlash"))
    assert sozlash is not None and sozlash.parent_id == kassa.id and sozlash.depth == 2

    # Kassa now holds a category, so it takes no videos.
    await harness.press(ADMIN_ID, AdminAddVideoCb(category=kassa.id))
    assert toasts(harness)[-1] == "⚠️ Bu bo‘limda ichki bo‘limlar bor — video qo‘shib bo‘lmaydi."

    # Adding a video through the admin panel picker.
    await harness.press(ADMIN_ID, AdminPickCb())
    assert button_texts(telegram.of(EditMessageText)[-1])[0] == "Kassa ›"
    await harness.press(ADMIN_ID, AdminPickCb(id=kassa.id))
    await harness.press(ADMIN_ID, AdminAddVideoCb(category=sozlash.id))
    assert last_text(harness) == "<b>Kassa › Sozlash</b>\nVideoni yuboring."

    await harness.send_document(ADMIN_ID, "doc")
    assert last_text(harness).startswith("⚠️ Videoni fayl sifatida emas, video sifatida yuboring.")

    await harness.send_video(ADMIN_ID, "v1", caption="🎬 Printerni ulash\nbatafsil")
    assert "Video nomini yozing" in last_text(harness)
    assert button_texts(telegram.of(EditMessageText)[-1])[0] == "Captiondan olish"

    await harness.press(ADMIN_ID, AdminFlowCb(action="caption"))
    assert "Qisqa tavsif yozing" in last_text(harness)

    # The preview appears in the same message as the dialog.
    dialog_id = await harness.active_message(ADMIN_ID)
    telegram.reset()
    await harness.send_text(ADMIN_ID, "USB kabel bilan")
    preview = telegram.of(EditMessageMedia)[-1]
    assert (preview.message_id, preview.media.media) == (dialog_id, file_id_of("v1"))
    assert preview.media.caption == "<b>Printerni ulash</b>\nUSB kabel bilan"

    telegram.reset()
    await harness.press(ADMIN_ID, AdminFlowCb(action="save"))
    assert last_text(harness) == "✅ Video saqlandi: «Printerni ulash»\nKassa › Sozlash"
    assert telegram.of(DeleteMessage) == []
    assert await harness.active_message(ADMIN_ID) == dialog_id

    async with harness.session_factory() as session:
        video = await session.scalar(select(Video))
    assert video is not None
    assert (video.title, video.description, video.category_id) == ("Printerni ulash", "USB kabel bilan", sozlash.id)

    # The archive worker copies the saved video to the private channel.
    archive = harness.dispatcher["archive"]
    assert archive._queue.get_nowait() == video.id
    telegram.reset()
    assert await archive.archive(video.id)
    copy = telegram.of(SendVideo)[-1]
    assert copy.chat_id == CHANNEL_ID and copy.video == file_id_of("v1")
    async with harness.session_factory() as session:
        assert (await session.get(Video, video.id)).backup_message_id is not None

    # Adding the same file again gives a warning first.
    await harness.press(ADMIN_ID, AdminAddVideoCb(category=sozlash.id))
    await harness.send_video(ADMIN_ID, "v1")
    assert "Bu video allaqachon bor: «Printerni ulash»" in last_text(harness)
    await harness.press(ADMIN_ID, AdminFlowCb(action="cancel"))
    assert last_text(harness) == "<b>Kassa › Sozlash</b>\n\n1. Printerni ulash"


async def test_client_walks_to_a_video_and_back(harness: Harness) -> None:
    ids = await seed_catalog(harness)
    telegram = harness.telegram

    await harness.send_text(CLIENT_ID, "/start")
    menu = telegram.of(SendMessage)[-1]
    assert button_texts(menu) == ["Kassa", "Ombor"]

    await harness.press(CLIENT_ID, CategoryCb(id=ids["kassa"]))
    assert last_text(harness) == "<b>Kassa</b>"
    assert button_texts(telegram.of(EditMessageText)[-1]) == ["Sozlash", "⬅️ Orqaga"]

    await harness.press(CLIENT_ID, CategoryCb(id=ids["sozlash"]))
    assert last_text(harness) == "<b>Kassa › Sozlash</b>\n\n1. Printer\n2. Skaner"
    assert button_texts(telegram.of(EditMessageText)[-1]) == ["1", "2", "⬅️ Orqaga", "🏠 Bosh menyu"]
    list_id = await harness.active_message(CLIENT_ID)

    # The video opens inside the list message: nothing is sent or deleted.
    telegram.reset()
    await harness.press(CLIENT_ID, VideoCb(id=ids["a"]))
    assert [type(call).__name__ for call in telegram.calls] == ["AnswerCallbackQuery", "EditMessageMedia"]
    video_message = telegram.of(EditMessageMedia)[-1]
    assert (video_message.message_id, video_message.media.media) == (list_id, file_id_of("a"))
    assert video_message.media.caption == "<b>Printer</b>"
    assert button_texts(video_message) == ["Keyingi ▶️", "⬅️ Orqaga", "🏠 Bosh menyu"]

    # A second tap on the same button does not send another video.
    telegram.reset()
    await harness.press(CLIENT_ID, VideoCb(id=ids["a"]), message_id=list_id)
    assert telegram.of(SendVideo, SendMessage, DeleteMessage) == []

    telegram.reset()
    await harness.press(CLIENT_ID, VideoCb(id=ids["b"]))
    switched = telegram.of(EditMessageMedia)[-1]
    assert switched.media.media == file_id_of("b")
    assert button_texts(switched) == ["◀️ Oldingi", "⬅️ Orqaga", "🏠 Bosh menyu"]

    # Back to the list: the video gives way to the cover photo with the list under it.
    telegram.reset()
    await harness.press(CLIENT_ID, CategoryCb(id=ids["sozlash"]))
    assert [type(call).__name__ for call in telegram.calls] == ["AnswerCallbackQuery", "EditMessageMedia"]
    back = telegram.of(EditMessageMedia)[-1]
    assert (back.message_id, back.media.type) == (list_id, "photo")
    assert back.media.caption == "<b>Kassa › Sozlash</b>\n\n1. Printer\n2. Skaner"

    # Further screens only change the caption under the photo.
    telegram.reset()
    await harness.press(CLIENT_ID, MenuCb())
    assert [type(call).__name__ for call in telegram.calls] == ["AnswerCallbackQuery", "EditMessageCaption"]
    assert await harness.active_message(CLIENT_ID) == list_id

    # Typing anything removes the message and brings the main menu back.
    telegram.reset()
    typed_id = await harness.send_text(CLIENT_ID, "salom")
    assert telegram.of(DeleteMessage)[0].message_id == typed_id
    assert last_text(harness) == "Xush kelibsiz! Kerakli bo‘limni tanlang."

    await harness.press(CLIENT_ID, MenuCb())
    await harness.send_dice(CLIENT_ID)
    assert last_text(harness) == "Xush kelibsiz! Kerakli bo‘limni tanlang."


async def test_client_cannot_open_the_admin_panel(harness: Harness) -> None:
    await seed_catalog(harness)
    telegram = harness.telegram

    await harness.send_text(CLIENT_ID, "/admin")
    assert "Admin panel" not in last_text(harness)
    assert last_text(harness) == "Xush kelibsiz! Kerakli bo‘limni tanlang."

    telegram.reset()
    await harness.press(CLIENT_ID, ADMIN_PANEL)
    await harness.press(CLIENT_ID, AdminDeleteCategoryCb(id=1, confirm=True))
    assert [type(call).__name__ for call in telegram.calls] == ["AnswerCallbackQuery", "AnswerCallbackQuery"]
    async with harness.session_factory() as session:
        assert await session.get(Category, 1) is not None


async def test_buttons_of_deleted_items(harness: Harness) -> None:
    ids = await seed_catalog(harness)

    await harness.send_text(CLIENT_ID, "/start")
    await harness.press(CLIENT_ID, CategoryCb(id=ids["sozlash"]))
    await harness.press(CLIENT_ID, VideoCb(id=ids["a"]))

    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, AdminDeleteCategoryCb(id=ids["kassa"]))
    assert last_text(harness) == "«Kassa» ichida 1 ta bo‘lim va 2 ta video bor. Hammasi bilan birga o‘chirilsinmi?"
    await harness.press(ADMIN_ID, AdminDeleteCategoryCb(id=ids["kassa"], confirm=True))
    assert toasts(harness)[-1] == "Bo‘lim o‘chirildi"

    # The client still looks at a video from the deleted category and taps Next.
    harness.telegram.reset()
    await harness.press(CLIENT_ID, VideoCb(id=ids["b"]))
    assert toasts(harness) == ["Bu video o‘chirilgan"]
    assert button_texts(harness.telegram.of(EditMessageMedia)[-1]) == ["Ombor"]

    harness.telegram.reset()
    await harness.press(CLIENT_ID, CategoryCb(id=ids["kassa"]))
    assert toasts(harness) == ["Bu bo‘lim o‘chirilgan"]


async def test_stale_dialog_button_after_restart(harness: Harness) -> None:
    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, AdminFlowCb(action="save"))
    assert toasts(harness)[-1] == "Bu amal eskirgan, qaytadan boshlang"
    assert last_text(harness).startswith("<b>Admin panel</b>")
