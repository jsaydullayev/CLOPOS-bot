"""Admin: add a video step by step, view and delete videos."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, MaybeInaccessibleMessageUnion, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.db.models import MEDIA_ANIMATION, MEDIA_VIDEO, User
from bot.handlers.admin.common import render_category
from bot.handlers.admin.texts import render_text_preview
from bot.handlers.common import NOT_COMMAND, answer, render_error
from bot.services.archive import ArchiveService
from bot.services.catalog import (
    VIDEO_TITLE_MAX,
    CatalogError,
    add_video,
    remove_video,
    validate_description,
    validate_name,
)
from bot.services.tree import CatalogTree
from bot.texts import t
from bot.ui.admin import admin_panel, admin_video, prompt
from bot.ui.callbacks import AdminAddVideoCb, AdminCategoryCb, AdminDeleteVideoCb, AdminFlowCb, AdminVideoCb
from bot.ui.client import video_caption
from bot.ui.display import Display
from bot.ui.screen import Media, Screen, button, keyboard
from bot.utils.text import clean_name, first_line, format_path, html


class VideoForm(StatesGroup):
    video = State()
    duplicate = State()
    title = State()
    description = State()
    confirm = State()


def _path(tree: CatalogTree, category_id: int) -> str:
    return html(format_path(tree.path(category_id)))


def _with_error(text: str, error: str | None) -> str:
    return f"{error}\n\n{text}" if error else text


async def _flow(session: AsyncSession, state: FSMContext) -> tuple[CatalogTree, int] | None:
    """The tree and the target category of the running dialog, None if it is gone."""
    category_id = (await state.get_data()).get("category_id")
    tree = await repo.load_tree(session)
    if category_id is None or tree.get(category_id) is None:
        return None
    return tree, category_id


async def _abort(state: FSMContext, session: AsyncSession, settings: Settings, user: User, display: Display) -> None:
    """The category was deleted while the dialog was open."""
    await state.clear()
    await display.show(user, await render_category(session, settings, None))


async def _ask_video(
    state: FSMContext,
    tree: CatalogTree,
    category_id: int,
    user: User,
    display: Display,
    *,
    error: str | None = None,
    source: MaybeInaccessibleMessageUnion | None = None,
) -> None:
    await state.set_state(VideoForm.video)
    await display.show(user, prompt(_with_error(t("video_ask", path=_path(tree, category_id)), error)), source=source)


async def _ask_title(
    state: FSMContext,
    tree: CatalogTree,
    category_id: int,
    user: User,
    display: Display,
    *,
    error: str | None = None,
    source: MaybeInaccessibleMessageUnion | None = None,
) -> None:
    buttons = []
    if (await state.get_data()).get("caption_title"):
        buttons.append(button(t("btn_from_caption"), AdminFlowCb(action="caption")))
    await state.set_state(VideoForm.title)
    text = _with_error(t("video_ask_title", path=_path(tree, category_id)), error)
    await display.show(user, prompt(text, buttons), source=source)


async def _ask_description(
    state: FSMContext,
    tree: CatalogTree,
    category_id: int,
    user: User,
    display: Display,
    *,
    error: str | None = None,
    source: MaybeInaccessibleMessageUnion | None = None,
) -> None:
    await state.set_state(VideoForm.description)
    text = _with_error(t("video_ask_description", path=_path(tree, category_id)), error)
    await display.show(user, prompt(text, [button(t("btn_skip"), AdminFlowCb(action="skip"))]), source=source)


async def _show_preview(
    state: FSMContext,
    tree: CatalogTree,
    category_id: int,
    user: User,
    display: Display,
    *,
    source: MaybeInaccessibleMessageUnion | None = None,
) -> None:
    """The video exactly as clients will see it."""
    data = await state.get_data()
    await state.set_state(VideoForm.confirm)
    caption = video_caption(data["title"], data.get("description"))
    media = Media(
        file_id=data["file_id"],
        media_type=data["media_type"],
        caption=caption,
        file_unique_id=data["file_unique_id"],
    )
    rows = [[button(t("btn_save"), AdminFlowCb(action="save")), button(t("btn_cancel"), AdminFlowCb(action="cancel"))]]
    await display.show(user, Screen(media=media, markup=keyboard(rows)), source=source)


async def start_flow(
    callback: CallbackQuery,
    callback_data: AdminAddVideoCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    tree = await repo.load_tree(session)
    category_id = callback_data.category
    if not tree.can_add_video(category_id):
        exists = tree.get(category_id) is not None
        await answer(callback, t("error_category_has_children") if exists else t("category_deleted"))
        await state.clear()
        target = category_id if exists else None
        await display.show(db_user, await render_category(session, settings, target), source=callback.message)
        return

    await answer(callback)
    await state.clear()
    await state.update_data(category_id=category_id)
    await _ask_video(state, tree, category_id, db_user, display, source=callback.message)


async def receive_video(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await display.delete(message.chat.id, message.message_id)
    flow = await _flow(session, state)
    if flow is None:
        await _abort(state, session, settings, db_user, display)
        return
    tree, category_id = flow

    # A silent video may arrive as an animation (GIF); it is accepted as well.
    media = message.video or message.animation
    await state.update_data(
        file_id=media.file_id,
        file_unique_id=media.file_unique_id,
        media_type=MEDIA_VIDEO if message.video else MEDIA_ANIMATION,
        caption_title=clean_name(first_line(message.caption)),
    )

    existing = await repo.find_video_by_file(session, media.file_unique_id)
    if existing is not None:
        await state.set_state(VideoForm.duplicate)
        text = t(
            "video_duplicate",
            path=_path(tree, category_id),
            title=html(existing.title),
            where=_path(tree, existing.category_id),
        )
        await display.show(db_user, prompt(text, [button(t("btn_add_anyway"), AdminFlowCb(action="dup"))]))
        return
    await _ask_title(state, tree, category_id, db_user, display)


async def receive_not_video(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await display.delete(message.chat.id, message.message_id)
    flow = await _flow(session, state)
    if flow is None:
        await _abort(state, session, settings, db_user, display)
        return
    tree, category_id = flow
    error = t("error_send_as_video") if message.document else t("error_expected_video")
    await _ask_video(state, tree, category_id, db_user, display, error=error)


async def duplicate_confirmed(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await answer(callback)
    flow = await _flow(session, state)
    if flow is None:
        await _abort(state, session, settings, db_user, display)
        return
    tree, category_id = flow
    await _ask_title(state, tree, category_id, db_user, display, source=callback.message)


async def receive_title(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await display.delete(message.chat.id, message.message_id)
    flow = await _flow(session, state)
    if flow is None:
        await _abort(state, session, settings, db_user, display)
        return
    tree, category_id = flow
    try:
        title = validate_name(message.text, VIDEO_TITLE_MAX)
    except CatalogError as error:
        await _ask_title(state, tree, category_id, db_user, display, error=render_error(error))
        return
    await state.update_data(title=title)
    await _ask_description(state, tree, category_id, db_user, display)


async def title_from_caption(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await answer(callback)
    flow = await _flow(session, state)
    if flow is None:
        await _abort(state, session, settings, db_user, display)
        return
    tree, category_id = flow
    caption_title = (await state.get_data()).get("caption_title")
    try:
        title = validate_name(caption_title, VIDEO_TITLE_MAX, error_key="error_caption_title")
    except CatalogError as error:
        await state.update_data(caption_title="")
        await _ask_title(state, tree, category_id, db_user, display, error=render_error(error), source=callback.message)
        return
    await state.update_data(title=title)
    await _ask_description(state, tree, category_id, db_user, display, source=callback.message)


async def title_not_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await display.delete(message.chat.id, message.message_id)
    flow = await _flow(session, state)
    if flow is None:
        await _abort(state, session, settings, db_user, display)
        return
    tree, category_id = flow
    await _ask_title(state, tree, category_id, db_user, display, error=t("error_expected_text"))


async def receive_description(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await display.delete(message.chat.id, message.message_id)
    flow = await _flow(session, state)
    if flow is None:
        await _abort(state, session, settings, db_user, display)
        return
    tree, category_id = flow
    try:
        description = validate_description(message.text)
    except CatalogError as error:
        await _ask_description(state, tree, category_id, db_user, display, error=render_error(error))
        return
    await state.update_data(description=description)
    await _show_preview(state, tree, category_id, db_user, display)


async def skip_description(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await answer(callback)
    flow = await _flow(session, state)
    if flow is None:
        await _abort(state, session, settings, db_user, display)
        return
    tree, category_id = flow
    await state.update_data(description=None)
    await _show_preview(state, tree, category_id, db_user, display, source=callback.message)


async def description_not_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await display.delete(message.chat.id, message.message_id)
    flow = await _flow(session, state)
    if flow is None:
        await _abort(state, session, settings, db_user, display)
        return
    tree, category_id = flow
    await _ask_description(state, tree, category_id, db_user, display, error=t("error_expected_text"))


async def ignore_message(message: Message, display: Display) -> None:
    """Input while a button is expected: the message is just removed."""
    await display.delete(message.chat.id, message.message_id)


async def save_video(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    archive: ArchiveService,
    settings: Settings,
) -> None:
    data = await state.get_data()
    await state.clear()
    try:
        video = await add_video(
            session,
            category_id=data["category_id"],
            title=data["title"],
            description=data.get("description"),
            file_id=data["file_id"],
            file_unique_id=data["file_unique_id"],
            media_type=data["media_type"],
            admin_id=db_user.id,
        )
    except CatalogError as error:
        await answer(callback, render_error(error))
        await display.show(db_user, await render_category(session, settings, None), source=callback.message)
        return

    # Committed before archiving: the archive worker reads the video in its own session.
    await session.commit()
    archive.enqueue(video.id)
    await answer(callback)

    tree = await repo.load_tree(session)
    text = t("video_saved", title=html(video.title), path=_path(tree, video.category_id))
    rows = [
        [
            button(t("btn_add_more"), AdminAddVideoCb(category=video.category_id)),
            button(t("btn_to_category"), AdminCategoryCb(id=video.category_id, page=-1)),
        ],
    ]
    await display.show(db_user, Screen(text=text, markup=keyboard(rows)), source=callback.message)


async def cancel_flow(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    """Cancel in any dialog: back to the screen the dialog was started from."""
    data = await state.get_data()
    await state.clear()
    await answer(callback)
    if "text_key" in data:
        await display.show(db_user, await render_text_preview(session, data["text_key"]), source=callback.message)
        return
    category_id = data.get("category_id") or data.get("parent_id")
    await display.show(db_user, await render_category(session, settings, category_id), source=callback.message)


async def flow_expired(callback: CallbackQuery, state: FSMContext, db_user: User, display: Display) -> None:
    """A dialog button from a dialog that no longer runs (for example after a restart)."""
    await state.clear()
    await answer(callback, t("flow_expired"))
    await display.show(db_user, admin_panel(), source=callback.message)


async def show_video(
    callback: CallbackQuery,
    callback_data: AdminVideoCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await state.clear()
    await _show_admin_video(callback, callback_data.id, session, db_user, display, settings, confirm=False)


async def ask_delete_video(
    callback: CallbackQuery,
    callback_data: AdminDeleteVideoCb,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await _show_admin_video(callback, callback_data.id, session, db_user, display, settings, confirm=True)


async def _show_admin_video(
    callback: CallbackQuery,
    video_id: int,
    session: AsyncSession,
    user: User,
    display: Display,
    settings: Settings,
    *,
    confirm: bool,
) -> None:
    video = await repo.get_video(session, video_id)
    if video is None:
        await answer(callback, t("video_deleted"))
        await display.show(user, await render_category(session, settings, None), source=callback.message)
        return
    await answer(callback)
    tree = await repo.load_tree(session)
    siblings = await repo.list_videos(session, video.category_id)
    await display.show(user, admin_video(tree, video, siblings, confirm=confirm), source=callback.message)


async def delete_video_confirmed(
    callback: CallbackQuery,
    callback_data: AdminDeleteVideoCb,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    category_id = await remove_video(session, callback_data.id)
    await answer(callback, t("video_deleted_done") if category_id is not None else t("video_deleted"))
    await display.show(db_user, await render_category(session, settings, category_id), source=callback.message)


def create_router() -> Router:
    router = Router(name="admin-videos")
    router.callback_query.register(start_flow, AdminAddVideoCb.filter())

    router.message.register(receive_video, VideoForm.video, F.video | F.animation)
    router.message.register(receive_not_video, VideoForm.video, NOT_COMMAND)

    router.callback_query.register(duplicate_confirmed, VideoForm.duplicate, AdminFlowCb.filter(F.action == "dup"))
    router.message.register(ignore_message, VideoForm.duplicate, NOT_COMMAND)

    router.message.register(receive_title, VideoForm.title, F.text, NOT_COMMAND)
    router.callback_query.register(title_from_caption, VideoForm.title, AdminFlowCb.filter(F.action == "caption"))
    router.message.register(title_not_text, VideoForm.title, NOT_COMMAND)

    router.message.register(receive_description, VideoForm.description, F.text, NOT_COMMAND)
    router.callback_query.register(skip_description, VideoForm.description, AdminFlowCb.filter(F.action == "skip"))
    router.message.register(description_not_text, VideoForm.description, NOT_COMMAND)

    router.callback_query.register(save_video, VideoForm.confirm, AdminFlowCb.filter(F.action == "save"))
    router.message.register(ignore_message, VideoForm.confirm, NOT_COMMAND)

    router.callback_query.register(cancel_flow, AdminFlowCb.filter(F.action == "cancel"))
    router.callback_query.register(flow_expired, AdminFlowCb.filter())

    router.callback_query.register(show_video, AdminVideoCb.filter())
    router.callback_query.register(ask_delete_video, AdminDeleteVideoCb.filter(~F.confirm))
    router.callback_query.register(delete_video_confirmed, AdminDeleteVideoCb.filter(F.confirm))
    return router
