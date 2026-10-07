"""Posts in the private video channel become videos in the bot."""

import logging
from contextlib import suppress

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Filter
from aiogram.types import Message, ReactionTypeEmoji
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import MEDIA_ANIMATION, MEDIA_VIDEO
from bot.handlers.common import render_error
from bot.services.catalog import CatalogError
from bot.services.channel import PostMedia, import_post
from bot.services.notify import Notifier
from bot.texts import t
from bot.utils.text import html

logger = logging.getLogger(__name__)

ACCEPTED = "👍"
REJECTED = "👎"


class FromVideoChannel(Filter):
    """Only the configured channel: posts from any other chat are ignored."""

    async def __call__(self, message: Message, settings: Settings | None = None) -> bool:
        return settings is not None and message.chat.id == settings.backup_channel_id


def post_link(chat_id: int, message_id: int) -> str:
    return f"https://t.me/c/{str(chat_id).removeprefix('-100')}/{message_id}"


def post_media(message: Message) -> PostMedia | None:
    if message.video is not None:
        return PostMedia(message.video.file_id, message.video.file_unique_id, MEDIA_VIDEO)
    if message.animation is not None:
        # A silent video may arrive as an animation (GIF).
        return PostMedia(message.animation.file_id, message.animation.file_unique_id, MEDIA_ANIMATION)
    return None


async def on_channel_post(
    message: Message, bot: Bot, session: AsyncSession, settings: Settings, notifier: Notifier
) -> None:
    """A new or edited post: add or update its video, answer with a reaction."""
    link = post_link(message.chat.id, message.message_id)
    try:
        media = post_media(message)
        if media is None:
            if message.document is not None and (message.document.mime_type or "").startswith("video/"):
                raise CatalogError("channel_not_video")
            return  # text, photos and other posts are not videos
        result = await import_post(
            session,
            message_id=message.message_id,
            caption=message.caption,
            media=media,
            max_depth=settings.max_depth,
        )
    except CatalogError as error:
        await session.rollback()
        logger.info("Channel post %s rejected: %s", message.message_id, error.key)
        await _react(bot, message, REJECTED)
        await notifier.notify(
            t("channel_post_failed", reason=render_error(error), link=link),
            key=f"channel:{message.message_id}:{error.key}",
        )
        return

    await session.commit()
    logger.info(
        "Channel post %s %s video %s",
        message.message_id,
        "added as" if result.created else "updated",
        result.video.id,
    )
    await _react(bot, message, ACCEPTED)
    if result.new_sections:
        # New sections come from the caption; a typo there would create a stray section.
        await notifier.notify(
            t("channel_sections_created", sections=html("\n".join(result.new_sections)), link=link),
            key=f"channel-sections:{message.message_id}",
        )
    if result.corrected:
        # A near-miss name was taken for an existing section: the admins see the guess.
        changes = "\n".join(
            t("channel_correction", written=html(written), section=html(section))
            for written, section in result.corrected
        )
        await notifier.notify(
            t("channel_sections_corrected", changes=changes, link=link),
            key=f"channel-corrected:{message.message_id}",
        )


async def _react(bot: Bot, message: Message, emoji: str) -> None:
    # Best effort: the channel may have reactions switched off.
    with suppress(TelegramAPIError):
        await bot.set_message_reaction(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )


def create_router() -> Router:
    router = Router(name="channel")
    router.channel_post.register(on_channel_post, FromVideoChannel())
    router.edited_channel_post.register(on_channel_post, FromVideoChannel())
    return router
