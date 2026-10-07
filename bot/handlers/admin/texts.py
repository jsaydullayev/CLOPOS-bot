"""Admin: the greeting and other client texts, and section introductions."""

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.db.models import User
from bot.handlers.admin.common import render_category
from bot.handlers.common import NOT_COMMAND, answer, render_error
from bot.services.catalog import CatalogError
from bot.services.content import (
    EDITABLE_TEXTS,
    PHOTO_TEXTS,
    photo_for,
    photo_from_message,
    text_for,
    text_from_message,
)
from bot.texts import t
from bot.ui.admin import intro_prompt, text_edit_prompt, text_preview, texts_screen
from bot.ui.callbacks import AdminIntroCb, AdminTextEditCb, AdminTextResetCb, AdminTextsCb
from bot.ui.display import Display
from bot.ui.screen import Screen


class TextForm(StatesGroup):
    value = State()


class IntroForm(StatesGroup):
    value = State()


def _labels() -> dict[str, str]:
    return {key: t(label_key) for key, label_key in EDITABLE_TEXTS.items()}


async def render_texts(session: AsyncSession, notice: str | None = None) -> Screen:
    return texts_screen(_labels(), await repo.custom_text_keys(session), notice)


async def render_text_preview(session: AsyncSession, key: str, notice: str | None = None) -> Screen:
    return text_preview(
        key,
        _labels()[key],
        await text_for(session, key),
        await photo_for(session, key),
        customized=await repo.get_custom_text(session, key) is not None,
        photo_allowed=key in PHOTO_TEXTS,
        notice=notice,
    )


# ── «✏️ Salomlashuv va matnlar» ────────────────────────────────


async def open_texts(
    callback: CallbackQuery,
    callback_data: AdminTextsCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
) -> None:
    """The list of texts, or one of them as the client sees it with the edit buttons."""
    await state.clear()
    await answer(callback)
    key = callback_data.key
    screen = await render_text_preview(session, key) if key in EDITABLE_TEXTS else await render_texts(session)
    await display.show(db_user, screen, source=callback.message)


async def start_edit(
    callback: CallbackQuery,
    callback_data: AdminTextEditCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
) -> None:
    await answer(callback)
    key = callback_data.key
    if key not in EDITABLE_TEXTS or (callback_data.photo and key not in PHOTO_TEXTS):
        await display.show(db_user, await render_texts(session), source=callback.message)
        return
    await state.set_state(TextForm.value)
    await state.update_data(text_key=key, photo_mode=callback_data.photo)
    await display.show(db_user, text_edit_prompt(_labels()[key], photo=callback_data.photo), source=callback.message)


async def receive_text(
    message: Message, state: FSMContext, session: AsyncSession, db_user: User, display: Display
) -> None:
    await display.delete(message.chat.id, message.message_id)
    data = await state.get_data()
    key, photo_mode = data.get("text_key"), bool(data.get("photo_mode"))
    photo = photo_from_message(message)
    try:
        if photo is None and message.document is not None and (message.document.mime_type or "").startswith("image/"):
            raise CatalogError("error_send_as_photo" if key in PHOTO_TEXTS else "error_expected_text")
        if photo is None and photo_mode:
            raise CatalogError("error_expected_photo")
        if photo is not None and key not in PHOTO_TEXTS:
            raise CatalogError("error_photo_not_here")
        # A photo without a caption changes only the photo; the text stays.
        value = text_from_message(message) if photo is None or (message.caption or "").strip() else None
    except CatalogError as error:
        await display.show(db_user, text_edit_prompt(_labels()[key], photo=photo_mode, error=render_error(error)))
        return
    await repo.update_custom_text(
        session,
        key,
        db_user.id,
        value=value,
        photo=(photo.file_id, photo.file_unique_id) if photo is not None else None,
    )
    await state.clear()
    notice = t("text_saved", label=_labels()[key])
    await display.show(db_user, await render_text_preview(session, key, notice))


async def reset_text(
    callback: CallbackQuery,
    callback_data: AdminTextResetCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
) -> None:
    await state.clear()
    await answer(callback)
    key = callback_data.key
    if key not in EDITABLE_TEXTS:
        await display.show(db_user, await render_texts(session), source=callback.message)
        return
    if callback_data.photo:
        await repo.remove_custom_photo(session, key)
        notice = t("text_photo_removed", label=_labels()[key])
    else:
        await repo.delete_custom_text(session, key)
        notice = t("text_reset", label=_labels()[key])
    await display.show(db_user, await render_text_preview(session, key, notice), source=callback.message)


# ── Section introductions ──────────────────────────────────────


async def edit_intro(
    callback: CallbackQuery,
    callback_data: AdminIntroCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await state.clear()
    category = await repo.get_category(session, callback_data.id)
    if category is None:
        await answer(callback, t("category_deleted"))
        await display.show(db_user, await render_category(session, settings, None), source=callback.message)
        return
    await answer(callback)
    if callback_data.clear:
        category.intro = None
        await display.show(db_user, await render_category(session, settings, category.id), source=callback.message)
        return
    await state.set_state(IntroForm.value)
    await state.update_data(category_id=category.id)
    tree = await repo.load_tree(session)
    await display.show(db_user, intro_prompt(tree, category.id, category.intro), source=callback.message)


async def receive_intro(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    display: Display,
    settings: Settings,
) -> None:
    await display.delete(message.chat.id, message.message_id)
    category = await repo.get_category(session, (await state.get_data()).get("category_id"))
    if category is None:
        await state.clear()
        await display.show(db_user, await render_category(session, settings, None))
        return
    try:
        if message.photo:
            raise CatalogError("error_photo_not_here")
        category.intro = text_from_message(message)
    except CatalogError as error:
        tree = await repo.load_tree(session)
        await display.show(db_user, intro_prompt(tree, category.id, category.intro, render_error(error)))
        return
    await state.clear()
    await display.show(db_user, await render_category(session, settings, category.id))


def create_router() -> Router:
    router = Router(name="admin-texts")
    router.callback_query.register(open_texts, AdminTextsCb.filter())
    router.callback_query.register(start_edit, AdminTextEditCb.filter())
    router.callback_query.register(reset_text, AdminTextResetCb.filter())
    router.message.register(receive_text, TextForm.value, NOT_COMMAND)
    router.callback_query.register(edit_intro, AdminIntroCb.filter())
    router.message.register(receive_intro, IntroForm.value, NOT_COMMAND)
    return router
