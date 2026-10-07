"""Entry point: python -m bot

With WEBHOOK_URL set the bot serves a webhook (production); without it, it
uses long polling, which is handy for a local test run.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from bot.app import create_dispatcher
from bot.config import Settings, get_settings
from bot.db.session import create_engine, create_session_factory
from bot.services.retry import until_reachable


def build_webhook_app(dispatcher: Dispatcher, bot: Bot, settings: Settings) -> web.Application:
    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dispatcher, bot=bot, secret_token=settings.webhook_secret or None
    ).register(app, path=settings.webhook_path)
    setup_application(app, dispatcher, bot=bot)
    return app


def run_webhook(dispatcher: Dispatcher, bot: Bot, settings: Settings) -> None:
    app = build_webhook_app(dispatcher, bot, settings)
    web.run_app(app, host=settings.web_server_host, port=settings.web_server_port)


async def run_polling(dispatcher: Dispatcher, bot: Bot) -> None:
    await until_reachable(lambda: bot.delete_webhook(drop_pending_updates=False), what="delete webhook")
    await dispatcher.start_polling(bot)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    engine = create_engine(settings.database_url)
    dispatcher = create_dispatcher(settings, bot, create_session_factory(engine), engine=engine)
    if settings.webhook_url:
        run_webhook(dispatcher, bot, settings)
    else:
        asyncio.run(run_polling(dispatcher, bot))


if __name__ == "__main__":
    main()
