import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram.exceptions import TelegramNetworkError

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def until_reachable(action: Callable[[], Awaitable[T]], *, what: str, max_delay: float = 60.0) -> T:
    """Repeat a start-up call while Telegram is unreachable, waiting 1, 2, 4 … up to max_delay seconds."""
    delay = 1.0
    while True:
        try:
            return await action()
        except TelegramNetworkError as error:
            logger.warning("%s: Telegram is unreachable (%s), retrying in %.0f s", what, error, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)
