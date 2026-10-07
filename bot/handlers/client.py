"""Client side: main menu, categories, videos."""

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.db.models import User
from bot.handlers.common import answer
from bot.services.commands import set_admin_commands
from bot.services.content import photo_for, text_for
from bot.services.tree import Kind
from bot.texts import t
from bot.ui.callbacks import NOOP, CategoryCb, MenuCb, VideoCb
from bot.ui.client import category_screen, main_menu, video_screen
from bot.ui.display import Display
from bot.ui.screen import Screen


async def menu_screen(session: AsyncSession, page: int = 0) -> Screen:
    """The main menu with the greeting (and photo) the admin set."""
    tree = await repo.load_tree(session)
    return main_menu(
        tree,
        page,
        greeting=await text_for(session, "main_menu"),
        empty_text=await text_for(session, "main_menu_empty"),
        photo=await photo_for(session, "main_menu"),
    )


async def start(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await state.clear()
    await display.delete(message.chat.id, message.message_id)
    await display.show(db_user, await menu_screen(session), edit=False)
    if settings.is_admin(db_user.id):
        await set_admin_commands(bot, db_user.id)


async def noop(callback: CallbackQuery) -> None:
    await answer(callback)


async def open_menu(
    callback: CallbackQuery, callback_data: MenuCb, session: AsyncSession, db_user: User, display: Display
) -> None:
    await answer(callback)
    await display.show(db_user, await menu_screen(session, callback_data.page), source=callback.message)


async def open_category(
    callback: CallbackQuery, callback_data: CategoryCb, session: AsyncSession, db_user: User, display: Display
) -> None:
    tree = await repo.load_tree(session)
    node = tree.get(callback_data.id)
    if node is None or tree.total(node.id) == 0:
        await answer(callback, t("category_deleted") if node is None else t("category_empty"))
        await display.show(db_user, await menu_screen(session), source=callback.message)
        return

    await answer(callback)
    videos = await repo.list_videos(session, node.id) if tree.kind(node.id) is Kind.VIDEOS else []
    category = await repo.get_category(session, node.id)
    screen = category_screen(tree, node, videos, callback_data.page, intro=category.intro if category else None)
    await display.show(db_user, screen, source=callback.message)


async def open_video(
    callback: CallbackQuery, callback_data: VideoCb, session: AsyncSession, db_user: User, display: Display
) -> None:
    """Opens a video from the list, or switches Previous/Next inside the video message."""
    video = await repo.get_video(session, callback_data.id)
    if video is None:
        await answer(callback, t("video_deleted"))
        await display.show(db_user, await menu_screen(session), source=callback.message)
        return

    await answer(callback)
    tree = await repo.load_tree(session)
    siblings = await repo.list_videos(session, video.category_id)
    await display.show(db_user, video_screen(tree, video, siblings), source=callback.message)


def create_router() -> Router:
    router = Router(name="client")
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    router.message.register(start, CommandStart())
    router.callback_query.register(noop, F.data == NOOP)
    router.callback_query.register(open_menu, MenuCb.filter())
    router.callback_query.register(open_category, CategoryCb.filter())
    router.callback_query.register(open_video, VideoCb.filter())
    return router
