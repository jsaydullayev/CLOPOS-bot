"""The command menu: /start for everyone, /admin only in admins' chats."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot.config import Settings
from bot.texts import t

logger = logging.getLogger(__name__)


async def set_default_commands(bot: Bot, settings: Settings) -> None:
    try:
        await bot.set_my_commands(
            commands=[BotCommand(command="start", description=t("cmd_start"))],
            scope=BotCommandScopeDefault(),
        )
    except TelegramAPIError as error:
        logger.warning("Default commands were not set: %s", error)
    for admin_id in settings.admin_ids:
        await set_admin_commands(bot, admin_id)


async def set_admin_commands(bot: Bot, chat_id: int) -> None:
    try:
        await bot.set_my_commands(
            commands=[
                BotCommand(command="start", description=t("cmd_start")),
                BotCommand(command="admin", description=t("cmd_admin")),
            ],
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    except TelegramAPIError as error:
        # Fails until the admin has pressed /start in the bot; /start sets it again.
        logger.info("Admin commands were not set for %s: %s", chat_id, error)
