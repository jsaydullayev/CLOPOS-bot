"""Client screens: main menu, category, video."""

from collections.abc import Callable, Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton

from bot.db.models import Video
from bot.services.content import Attachment
from bot.services.tree import CatalogTree, CategoryNode, Kind
from bot.texts import t
from bot.ui.callbacks import CONTACTS, CategoryCb, MenuCb, VideoCb
from bot.ui.screen import (
    ACCENT_STYLE,
    COLUMNS,
    PAGE_SIZE,
    Media,
    Screen,
    button,
    grid,
    keyboard,
    page_row,
    paginate,
)
from bot.utils.text import format_path, html

# Video lists show titles in the text and only their numbers on the buttons.
NUMBER_COLUMNS = 4


def main_menu(
    tree: CatalogTree,
    page: int = 0,
    *,
    greeting: str | None = None,
    empty_text: str | None = None,
    attachment: Attachment | None = None,
    contacts: bool = False,
) -> Screen:
    """greeting and empty_text are the admin's texts (HTML), by default the ones from locales.
    With a photo or video, the greeting becomes its caption. contacts: the admin has written
    them, so the «📞 Aloqa» button goes at the bottom, on its own row and in green."""
    contacts_row = [button(t("btn_contacts"), CONTACTS, style=ACCENT_STYLE)] if contacts else []
    categories = tree.visible_children(None)
    if not categories:
        return Screen(text=empty_text or t("main_menu_empty"), markup=keyboard([contacts_row]))
    chunk, page, pages = paginate(categories, page)
    rows = grid([_category_button(tree, node) for node in chunk], COLUMNS)
    rows.append(page_row(page, pages, lambda p: MenuCb(page=p)))
    rows.append(contacts_row)
    text = greeting or t("main_menu")
    if attachment is not None:
        return Screen(media=attachment_media(attachment, text), markup=keyboard(rows))
    return Screen(text=text, markup=keyboard(rows))


def contacts_screen(text: str) -> Screen:
    """The admin's contacts, links and usernames (HTML)."""
    return Screen(text=text, markup=keyboard([[button(t("btn_back"), MenuCb())]]))


def section_emoji(tree: CatalogTree, node: CategoryNode) -> str:
    """The admin's emoji for the section, or one by what it holds: sections 📂, videos 🎬."""
    if node.emoji:
        return node.emoji
    return t("emoji_sections") if tree.kind(node.id) is Kind.CATEGORIES else t("emoji_videos")


def section_label(tree: CatalogTree, node: CategoryNode) -> str:
    return t("category_button", emoji=section_emoji(tree, node), title=node.title, count=tree.total(node.id))


def attachment_media(attachment: Attachment, caption: str) -> Media:
    """The greeting's photo or video with the text under it; if it cannot be sent, the text goes alone."""
    return Media(
        file_id=attachment.file_id,
        media_type=attachment.media_type,
        caption=caption,
        file_unique_id=attachment.file_unique_id,
        optional=True,
    )


def category_screen(
    tree: CatalogTree,
    node: CategoryNode,
    videos: Sequence[Video],
    page: int = 0,
    *,
    intro: str | None = None,
) -> Screen:
    if tree.kind(node.id) is Kind.CATEGORIES:
        chunk, page, pages = paginate(tree.visible_children(node.id), page)
        rows = grid([_category_button(tree, child) for child in chunk], COLUMNS)
        # A short line on what to do here, under the admin's introduction.
        guide = t("hint_sections")
    else:
        chunk_videos, page, pages = paginate(videos, page)
        listing, rows = video_list(chunk_videos, page * PAGE_SIZE, lambda video: VideoCb(id=video.id))
        guide = t("hint_videos") + "\n" + listing
    rows.append(page_row(page, pages, lambda p: CategoryCb(id=node.id, page=p)))
    rows.append(_bottom_row(node))
    text = section_header(tree, node.id, intro) + "\n\n" + guide
    return Screen(text=text, markup=keyboard(rows))


def video_list(
    videos: Sequence[Video], offset: int, make: Callable[[Video], CallbackData]
) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """Numbered titles for the message text and number-only buttons under it.

    offset: how many videos come before this page, so numbers continue across pages.
    """
    lines = []
    buttons = []
    for number, video in enumerate(videos, start=offset + 1):
        lines.append(t("video_list_item", number=number, title=html(video.title)))
        buttons.append(button(t("video_number_button", number=number), make(video)))
    return "\n".join(lines), grid(buttons, NUMBER_COLUMNS)


def section_header(tree: CatalogTree, category_id: int, intro: str | None, note: str | None = None) -> str:
    """The section's emoji and path in bold, the admin's introduction, then a note (admins only)."""
    node = tree.get(category_id)
    emoji = section_emoji(tree, node) if node is not None else ""
    text = t("category_title", emoji=emoji, path=html(format_path(tree.path(category_id))))
    if intro:
        text += "\n" + intro
    if note:
        text += ("\n\n" if intro else "\n") + note
    return text


def video_caption(title: str, description: str | None) -> str:
    lines = [t("video_title", title=html(title))]
    if description:
        lines.append(html(description))
    return "\n".join(lines)


def video_screen(tree: CatalogTree, video: Video, siblings: Sequence[Video]) -> Screen:
    ids = [sibling.id for sibling in siblings]
    index = ids.index(video.id)

    switch_row = []
    if index > 0:
        switch_row.append(button(t("btn_video_prev"), VideoCb(id=ids[index - 1])))
    if index < len(ids) - 1:
        switch_row.append(button(t("btn_video_next"), VideoCb(id=ids[index + 1])))
    rows = [
        switch_row,
        [
            # Back opens the list on the page where the current video is.
            button(t("btn_back"), CategoryCb(id=video.category_id, page=index // PAGE_SIZE)),
            button(t("btn_home"), MenuCb()),
        ],
    ]
    return Screen(media=video_media(video, video_caption(video.title, video.description)), markup=keyboard(rows))


def video_media(video: Video, caption: str) -> Media:
    return Media(
        file_id=video.file_id,
        media_type=video.media_type,
        caption=caption,
        file_unique_id=video.file_unique_id,
    )


def _category_button(tree: CatalogTree, node: CategoryNode) -> InlineKeyboardButton:
    return button(section_label(tree, node), CategoryCb(id=node.id))


def _bottom_row(node: CategoryNode) -> list[InlineKeyboardButton]:
    if node.parent_id is None:
        # One level up is the main menu itself, so a second button would repeat it.
        return [button(t("btn_back"), MenuCb())]
    return [button(t("btn_back"), CategoryCb(id=node.parent_id)), button(t("btn_home"), MenuCb())]
