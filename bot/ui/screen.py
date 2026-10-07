from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.texts import t
from bot.ui.callbacks import NOOP

PAGE_SIZE = 8
# Sections, menus and actions go two buttons per row.
COLUMNS = 2
# Every button is blue; Telegram apps that predate button styles show their default color.
BUTTON_STYLE = ButtonStyle.PRIMARY

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Media:
    file_id: str
    media_type: str
    caption: str
    file_unique_id: str | None = None


@dataclass(frozen=True, slots=True)
class Screen:
    """What the active message should show: text or a video with a caption."""

    text: str | None = None
    media: Media | None = None
    markup: InlineKeyboardMarkup | None = None
    # A text screen is usually shown under a photo when the message holds one. A plain screen must
    # look exactly as written (the admin's preview of a text clients see without a photo), even if
    # that takes a new message.
    plain: bool = False

    def __post_init__(self) -> None:
        if (self.text is None) == (self.media is None):
            raise ValueError("A screen shows either text or media")

    @property
    def is_media(self) -> bool:
        return self.media is not None


def button(text: str, data: CallbackData | str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=data.pack() if isinstance(data, CallbackData) else data,
        style=BUTTON_STYLE,
    )


def keyboard(rows: Iterable[Sequence[InlineKeyboardButton]]) -> InlineKeyboardMarkup | None:
    filled = [list(row) for row in rows if row]
    return InlineKeyboardMarkup(inline_keyboard=filled) if filled else None


def grid(buttons: Sequence[InlineKeyboardButton], columns: int) -> list[list[InlineKeyboardButton]]:
    """Lay buttons out left to right, `columns` in a row."""
    return [list(buttons[start : start + columns]) for start in range(0, len(buttons), columns)]


def paginate(items: Sequence[T], page: int, size: int = PAGE_SIZE) -> tuple[list[T], int, int]:
    """Slice one page. A negative or too large page means the last one."""
    pages = max(1, -(-len(items) // size))
    page = pages - 1 if page < 0 else min(page, pages - 1)
    start = page * size
    return list(items[start : start + size]), page, pages


def page_row(page: int, pages: int, make: Callable[[int], CallbackData]) -> list[InlineKeyboardButton]:
    """◀️ 1/2 ▶️ — the arrow is hidden on the first and last page."""
    if pages <= 1:
        return []
    row = []
    if page > 0:
        row.append(button(t("btn_page_prev"), make(page - 1)))
    row.append(button(t("btn_page", page=page + 1, pages=pages), NOOP))
    if page < pages - 1:
        row.append(button(t("btn_page_next"), make(page + 1)))
    return row
