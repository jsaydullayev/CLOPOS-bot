import logging
from contextlib import suppress

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from bot.services.notify import Notifier
from bot.texts import t
from bot.utils.text import html

logger = logging.getLogger(__name__)


async def on_error(event: ErrorEvent, notifier: Notifier) -> None:
    """Log the error and tell the admins (the same error at most once per 5 minutes)."""
    error = event.exception
    logger.error("Update %s failed", event.update.update_id, exc_info=error)
    await notifier.notify(
        t("error_notify", error=html(f"{type(error).__name__}: {error}"[:500])),
        key=type(error).__name__,
    )
    if event.update.callback_query is not None:
        with suppress(TelegramAPIError):
            await event.update.callback_query.answer()
