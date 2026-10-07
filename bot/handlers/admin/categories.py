"""Admin: browse, create and delete categories."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.db.models import User
from bot.handlers.admin.common import render_category
from bot.handlers.common import NOT_COMMAND, answer, render_error
from bot.services.catalog import CatalogError, create_category, remove_category
from bot.services.tree import CatalogTree, Kind
from bot.texts import t
from bot.ui.admin import confirm_delete_category, prompt
from bot.ui.callbacks import AdminCategoryCb, AdminDeleteCategoryCb, AdminNewCategoryCb
from bot.ui.display import Display
from bot.ui.screen import Screen
from bot.utils.text import format_path, html


class CategoryForm(StatesGroup):
    name = State()


def name_prompt(tree: CatalogTree, parent_id: int | None, error: str | None = None) -> Screen:
    if parent_id is None:
        text = t("category_name_root")
    else:
        text = t("category_name_child", path=html(format_path(tree.path(parent_id))))
    return prompt(f"{error}\n\n{text}" if error else text)


async def browse(
    callback: CallbackQuery,
    callback_data: AdminCategoryCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await state.clear()
    category_id = callback_data.id or None
    page = callback_data.page
    if category_id is not None and await repo.get_category(session, category_id) is None:
        await answer(callback, t("category_deleted"))
        category_id, page = None, 0
    else:
        await answer(callback)
    await display.show(db_user, await render_category(session, settings, category_id, page), source=callback.message)


async def ask_name(
    callback: CallbackQuery,
    callback_data: AdminNewCategoryCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    tree = await repo.load_tree(session)
    parent_id = callback_data.parent or None
    if parent_id is not None and not tree.can_add_child(parent_id, settings.max_depth):
        if tree.get(parent_id) is None:
            notice = t("category_deleted")
        elif tree.kind(parent_id) is Kind.VIDEOS:
            notice = t("error_category_has_videos")
        else:
            notice = t("error_max_depth", max=settings.max_depth)
        await answer(callback, notice)
        await display.show(db_user, await render_category(session, settings, parent_id), source=callback.message)
        return

    await answer(callback)
    await state.set_state(CategoryForm.name)
    await state.update_data(parent_id=parent_id)
    await display.show(db_user, name_prompt(tree, parent_id), source=callback.message)


async def receive_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await display.delete(message.chat.id, message.message_id)
    parent_id = (await state.get_data()).get("parent_id")
    try:
        await create_category(
            session, parent_id=parent_id, raw_title=message.text, admin_id=db_user.id, max_depth=settings.max_depth
        )
    except CatalogError as error:
        if error.key == "category_deleted":
            await state.clear()
            await display.show(db_user, await render_category(session, settings, None))
            return
        tree = await repo.load_tree(session)
        await display.show(db_user, name_prompt(tree, parent_id, render_error(error)))
        return

    await state.clear()
    # Back to the list the category was added to, on its last page where the new one is.
    await display.show(db_user, await render_category(session, settings, parent_id, page=-1))


async def name_not_text(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User, display: Display
) -> None:
    await display.delete(message.chat.id, message.message_id)
    parent_id = (await state.get_data()).get("parent_id")
    tree = await repo.load_tree(session)
    await display.show(db_user, name_prompt(tree, parent_id, t("error_expected_text")))


async def ask_delete(
    callback: CallbackQuery,
    callback_data: AdminDeleteCategoryCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await state.clear()
    tree = await repo.load_tree(session)
    node = tree.get(callback_data.id)
    if node is None:
        await answer(callback, t("category_deleted"))
        await display.show(db_user, await render_category(session, settings, None), source=callback.message)
        return
    await answer(callback)
    await display.show(db_user, confirm_delete_category(tree, node), source=callback.message)


async def delete_confirmed(
    callback: CallbackQuery,
    callback_data: AdminDeleteCategoryCb,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    deleted = await remove_category(session, callback_data.id)
    if deleted is None:
        await answer(callback, t("category_deleted"))
        await display.show(db_user, await render_category(session, settings, None), source=callback.message)
        return
    await answer(callback, t("category_deleted_done"))
    await display.show(db_user, await render_category(session, settings, deleted.parent_id), source=callback.message)


def create_router() -> Router:
    router = Router(name="admin-categories")
    router.callback_query.register(browse, AdminCategoryCb.filter())
    router.callback_query.register(ask_name, AdminNewCategoryCb.filter())
    router.message.register(receive_name, CategoryForm.name, F.text, NOT_COMMAND)
    router.message.register(name_not_text, CategoryForm.name, NOT_COMMAND)
    router.callback_query.register(ask_delete, AdminDeleteCategoryCb.filter(~F.confirm))
    router.callback_query.register(delete_confirmed, AdminDeleteCategoryCb.filter(F.confirm))
    return router
