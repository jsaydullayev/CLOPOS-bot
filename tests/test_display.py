"""The single active message: every screen is shown by editing it; a new one only when Telegram cannot edit."""

from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, EditMessageMedia, EditMessageText
from aiogram.types import Chat, FSInputFile, Message, PhotoSize
from aiogram.types import Video as TgVideo

from bot.db.models import User
from bot.services.content import Photo
from bot.ui.display import Display, ReplacedRegistry
from bot.ui.screen import Media, Screen
from tests.conftest import FakeTelegram

CHAT = 7
TEXT = Screen(text="Menyu")
VIDEO_A = Screen(media=Media(file_id="file-a", media_type="video", caption="A", file_unique_id="a"))


def bot_message(message_id: int, unique_id: str | None = None, *, photo: bool = False) -> Message:
    content: dict = {"text": "..."}
    if unique_id is not None and photo:
        content = {"photo": [PhotoSize(file_id=f"file-{unique_id}", file_unique_id=unique_id, width=1, height=1)]}
    elif unique_id is not None:
        content = {
            "video": TgVideo(file_id=f"file-{unique_id}", file_unique_id=unique_id, width=1, height=1, duration=1)
        }
    return Message(message_id=message_id, date=datetime.now(UTC), chat=Chat(id=CHAT, type=ChatType.PRIVATE), **content)


@pytest.fixture
def display(bot: Bot) -> Display:
    return Display(bot, ReplacedRegistry())


def calls(telegram: FakeTelegram) -> list[str]:
    return [type(call).__name__ for call in telegram.calls]


async def test_first_screen_is_sent(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=None)
    message_id = await display.show(user, TEXT)
    assert calls(telegram) == ["SendMessage"]
    assert user.last_message_id == message_id


async def test_typed_input_edits_the_active_message(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=50)
    assert await display.show(user, TEXT) == 50
    assert calls(telegram) == ["EditMessageText"]


async def test_typed_input_leading_to_a_video_puts_it_into_the_active_message(
    display: Display, telegram: FakeTelegram
) -> None:
    user = User(id=CHAT, last_message_id=50)
    assert await display.show(user, VIDEO_A) == 50
    assert calls(telegram) == ["EditMessageMedia"]


async def test_start_sends_a_fresh_message_and_removes_the_old_one(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=50)
    new_id = await display.show(user, TEXT, edit=False)
    assert calls(telegram) == ["SendMessage", "DeleteMessage"]
    assert telegram.of(DeleteMessage)[0].message_id == 50
    assert user.last_message_id == new_id


async def test_list_to_video_turns_the_list_message_into_the_video(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=50)
    assert await display.show(user, VIDEO_A, source=bot_message(50)) == 50
    assert calls(telegram) == ["EditMessageMedia"]
    assert telegram.of(EditMessageMedia)[0].media.media == "file-a"


async def test_next_video_is_swapped_inside_the_same_message(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=60)
    await display.show(user, VIDEO_A, source=bot_message(60, unique_id="b"))
    assert calls(telegram) == ["EditMessageMedia"]
    assert user.last_message_id == 60


async def test_same_video_only_changes_caption(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=60)
    await display.show(user, VIDEO_A, source=bot_message(60, unique_id="a"))
    assert calls(telegram) == ["EditMessageCaption"]


async def test_video_to_list_puts_the_list_under_the_default_cover(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=60)
    assert await display.show(user, TEXT, source=bot_message(60, unique_id="a")) == 60
    assert calls(telegram) == ["EditMessageMedia"]
    media = telegram.of(EditMessageMedia)[0].media
    assert (media.type, media.caption) == ("photo", "Menyu")
    assert isinstance(media.media, FSInputFile)  # assets/cover.png, uploaded


async def test_the_greeting_photo_is_the_cover_when_there_is_one(bot: Bot, telegram: FakeTelegram) -> None:
    async def greeting() -> Photo:
        return Photo("file-greeting", "greeting")

    display = Display(bot, ReplacedRegistry(), cover=greeting)
    await display.show(User(id=CHAT, last_message_id=60), TEXT, source=bot_message(60, unique_id="a"))
    assert telegram.of(EditMessageMedia)[0].media.media == "file-greeting"


async def test_text_on_a_photo_only_changes_the_caption(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=60)
    await display.show(user, TEXT, source=bot_message(60, unique_id="greeting", photo=True))
    assert calls(telegram) == ["EditMessageCaption"]


async def test_typed_input_on_a_media_message_goes_under_the_cover(display: Display, telegram: FakeTelegram) -> None:
    telegram.media[60] = ("video", "file-a")  # Telegram refuses to edit text there
    user = User(id=CHAT, last_message_id=60)
    assert await display.show(user, TEXT) == 60
    assert calls(telegram) == ["EditMessageText", "EditMessageMedia"]


async def test_text_too_long_for_a_caption_is_sent_as_a_new_message(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=60)
    long_text = Screen(text="<b>" + "x" * 1025 + "</b>")
    new_id = await display.show(user, long_text, source=bot_message(60, unique_id="a"))
    assert calls(telegram) == ["SendMessage", "DeleteMessage"]
    assert user.last_message_id == new_id != 60

    # The tags do not count: the visible text fits.
    telegram.reset()
    user = User(id=CHAT, last_message_id=60)
    await display.show(user, Screen(text="<b>" + "x" * 1024 + "</b>"), source=bot_message(60, unique_id="a"))
    assert calls(telegram) == ["EditMessageMedia"]


async def test_not_modified_is_ignored(display: Display, telegram: FakeTelegram) -> None:
    telegram.fail_once(EditMessageText, TelegramBadRequest(method=None, message="Bad Request: message is not modified"))
    user = User(id=CHAT, last_message_id=50)
    assert await display.show(user, TEXT, source=bot_message(50)) == 50
    assert calls(telegram) == ["EditMessageText"]


async def test_message_that_cannot_be_edited_is_replaced(display: Display, telegram: FakeTelegram) -> None:
    telegram.fail_once(EditMessageText, TelegramBadRequest(method=None, message="Bad Request: message can't be edited"))
    user = User(id=CHAT, last_message_id=50)
    new_id = await display.show(user, TEXT)
    assert calls(telegram) == ["EditMessageText", "SendMessage", "DeleteMessage"]
    assert user.last_message_id == new_id != 50


async def test_old_message_button_keeps_only_one_active_message(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=70)
    await display.show(user, TEXT, source=bot_message(40))
    assert calls(telegram) == ["EditMessageText", "DeleteMessage"]
    assert telegram.of(DeleteMessage)[0].message_id == 70
    assert user.last_message_id == 40


async def test_undeletable_old_message_is_not_an_error(display: Display, telegram: FakeTelegram) -> None:
    telegram.fail_once(
        DeleteMessage, TelegramBadRequest(method=None, message="Bad Request: message can't be deleted for everyone")
    )
    user = User(id=CHAT, last_message_id=50)
    await display.show(user, TEXT, edit=False)
    assert calls(telegram) == ["SendMessage", "DeleteMessage"]
