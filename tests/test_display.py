"""The single active message: edit when possible, otherwise send new and delete old."""

from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, EditMessageText
from aiogram.types import Chat, Message
from aiogram.types import Video as TgVideo

from bot.db.models import User
from bot.ui.display import Display, ReplacedRegistry
from bot.ui.screen import Media, Screen
from tests.conftest import FakeTelegram

CHAT = 7
TEXT = Screen(text="Menyu")
VIDEO_A = Screen(media=Media(file_id="file-a", media_type="video", caption="A", file_unique_id="a"))


def bot_message(message_id: int, unique_id: str | None = None) -> Message:
    video = None
    if unique_id is not None:
        video = TgVideo(file_id=f"file-{unique_id}", file_unique_id=unique_id, width=1, height=1, duration=1)
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=CHAT, type=ChatType.PRIVATE),
        text=None if video else "...",
        video=video,
    )


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


async def test_typed_input_leading_to_a_video_sends_it_as_a_new_message(
    display: Display, telegram: FakeTelegram
) -> None:
    user = User(id=CHAT, last_message_id=50)
    new_id = await display.show(user, VIDEO_A)
    assert calls(telegram) == ["SendVideo", "DeleteMessage"]
    assert telegram.of(DeleteMessage)[0].message_id == 50
    assert user.last_message_id == new_id


async def test_start_sends_a_fresh_message_and_removes_the_old_one(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=50)
    new_id = await display.show(user, TEXT, edit=False)
    assert calls(telegram) == ["SendMessage", "DeleteMessage"]
    assert telegram.of(DeleteMessage)[0].message_id == 50
    assert user.last_message_id == new_id


async def test_list_to_video_sends_the_video_first_then_deletes_the_list(
    display: Display, telegram: FakeTelegram
) -> None:
    user = User(id=CHAT, last_message_id=50)
    await display.show(user, VIDEO_A, source=bot_message(50))
    assert calls(telegram) == ["SendVideo", "DeleteMessage"]
    assert display.registry.is_recent(CHAT, 50)


async def test_next_video_is_swapped_inside_the_same_message(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=60)
    await display.show(user, VIDEO_A, source=bot_message(60, unique_id="b"))
    assert calls(telegram) == ["EditMessageMedia"]
    assert user.last_message_id == 60


async def test_same_video_only_changes_caption(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=60)
    await display.show(user, VIDEO_A, source=bot_message(60, unique_id="a"))
    assert calls(telegram) == ["EditMessageCaption"]


async def test_video_to_list_sends_text_then_deletes_the_video(display: Display, telegram: FakeTelegram) -> None:
    user = User(id=CHAT, last_message_id=60)
    await display.show(user, TEXT, source=bot_message(60, unique_id="a"))
    assert calls(telegram) == ["SendMessage", "DeleteMessage"]


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
