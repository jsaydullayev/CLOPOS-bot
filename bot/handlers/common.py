from contextlib import suppress

from aiogram import F
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

from bot.services.catalog import CatalogError
from bot.texts import t
from bot.utils.text import html

# Commands in dialogs are not taken as input: /start and /admin still work.
NOT_COMMAND = ~F.text.startswith("/")


async def answer(callback: CallbackQuery, text: str | None = None) -> None:
    """Remove the loading indicator on the button, optionally with a short notice."""
    with suppress(TelegramAPIError):
        await callback.answer(text)


def render_error(error: CatalogError) -> str:
    return t(error.key, **{name: html(value) for name, value in error.params.items()})
