from unittest.mock import patch

from aiogram.exceptions import TelegramNetworkError

from bot.services.retry import until_reachable


async def test_start_up_call_is_repeated_until_telegram_answers() -> None:
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TelegramNetworkError(method=None, message="Cannot connect to host api.telegram.org")
        return "ok"

    with patch("bot.services.retry.asyncio.sleep") as sleep:
        assert await until_reachable(flaky, what="test") == "ok"
    assert attempts == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]
