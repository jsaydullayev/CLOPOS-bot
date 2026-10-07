"""Startup, shutdown and the webhook endpoint, wired the way production runs them."""

import asyncio
import time
from typing import Any

from aiogram import Bot
from aiogram.methods import SendMessage, SetMyCommands, SetWebhook
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bot.__main__ import build_webhook_app
from bot.app import create_dispatcher
from tests.conftest import CLIENT_ID, FakeTelegram, make_settings

WEBHOOK_SETTINGS = {"webhook_url": "https://bot.example.uz/webhook", "webhook_secret": "secret-123"}


async def wait_for(condition: Any, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition was not met in time"
        await asyncio.sleep(0.01)


async def test_startup_sets_commands_and_webhook(
    bot: Bot, telegram: FakeTelegram, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = make_settings(str(engine.url), **WEBHOOK_SETTINGS)
    dispatcher = create_dispatcher(settings, bot, session_factory)
    workflow = {"dispatcher": dispatcher, "bots": [bot], **dispatcher.workflow_data}

    await dispatcher.emit_startup(bot=bot, **workflow)
    try:
        scopes = [call.scope.type for call in telegram.of(SetMyCommands)]
        assert scopes == ["default", "chat"]
        webhook = telegram.of(SetWebhook)[0]
        assert (webhook.url, webhook.secret_token) == (WEBHOOK_SETTINGS["webhook_url"], "secret-123")
        assert set(webhook.allowed_updates) == {"message", "callback_query", "channel_post", "edited_channel_post"}
    finally:
        await dispatcher.emit_shutdown(bot=bot, **workflow)


async def test_webhook_accepts_only_telegram_requests(
    bot: Bot, telegram: FakeTelegram, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    settings = make_settings(str(engine.url), **WEBHOOK_SETTINGS)
    dispatcher = create_dispatcher(settings, bot, session_factory)
    app = build_webhook_app(dispatcher, bot, settings)
    update = {
        "update_id": 1,
        "message": {
            "message_id": 5,
            "date": 1_790_000_000,
            "chat": {"id": CLIENT_ID, "type": "private"},
            "from": {"id": CLIENT_ID, "is_bot": False, "first_name": "Ali"},
            "text": "/start",
        },
    }

    async with TestClient(TestServer(app)) as client:
        forged = await client.post("/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
        assert forged.status == 401

        response = await client.post("/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "secret-123"})
        assert response.status == 200
        await wait_for(lambda: telegram.of(SendMessage))

    assert telegram.of(SendMessage)[0].text == "Xush kelibsiz! Hozircha videolar yo‘q — tez orada qo‘shiladi."
