from aiogram import Router

from bot.handlers import admin, channel, client, fallback


def create_routers() -> list[Router]:
    # Channel posts are their own update type. Among messages: admin first (its
    # dialogs catch text), then the client, then the catch-all.
    return [channel.create_router(), admin.create_router(), client.create_router(), fallback.create_router()]
