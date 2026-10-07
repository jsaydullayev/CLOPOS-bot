"""Client screens: main menu, category, video."""

from collections.abc import Callable, Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton

from bot.db.models import MEDIA_PHOTO, Video
from bot.services.content import Photo
from bot.services.tree import CatalogTree, CategoryNode, Kind
from bot.texts import t
from bot.ui.callbacks import CategoryCb, MenuCb, VideoCb
from bot.ui.screen import COLUMNS, PAGE_SIZE, Media, Screen, button, grid, keyboard, page_row, paginate
from bot.utils.text import format_path, html

# Video lists show titles in the text and only their numbers on the buttons.
NUMBER_COLUMNS = 4


def main_menu(
    tree: CatalogTree,
    page: int = 0,
    *,
    greeting: str | None = None,
    empty_text: str | None = None,
    photo: Photo | None = None,
) -> Screen:
    """greeting and empty_text are the admin's texts (HTML), by default the ones from locales.
    With a photo, the greeting becomes its caption."""
    categories = tree.visible_children(None)
    if not categories:
        return Screen(text=empty_text or t("main_menu_empty"))
    chunk, page, pages = paginate(categories, page)
    rows = grid([_category_button(tree, node) for node in chunk], COLUMNS)
    rows.append(page_row(page, pages, lambda p: MenuCb(page=p)))
    text = greeting or t("main_menu")
    if photo is not None:
        media = Media(
            file_id=photo.file_id, media_type=MEDIA_PHOTO, caption=text, file_unique_id=photo.file_unique_id
        )
        return Screen(media=media, markup=keyboard(rows))
    return Screen(text=text, markup=keyboard(rows))


def category_screen(
    tree: CatalogTree,
    node: CategoryNode,
    videos: Sequence[Video],
    page: int = 0,
    *,
    intro: str | None = None,
) -> Screen:
    count_line = None
    listing = ""
    if tree.kind(node.id) is Kind.CATEGORIES:
        chunk, page, pages = paginate(tree.visible_children(node.id), page)
        rows = grid([_category_button(tree, child) for child in chunk], COLUMNS)
    else:
        chunk_videos, page, pages = paginate(videos, page)
        listing, rows = video_list(chunk_videos, page * PAGE_SIZE, lambda video: VideoCb(id=video.id))
        count_line = t("videos_count", count=len(videos))
    rows.append(page_row(page, pages, lambda p: CategoryCb(id=node.id, page=p)))
    rows.append(_bottom_row(node))
    text = section_header(tree, node.id, intro, count_line)
    if listing:
        text += "\n\n" + listing
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


def section_header(tree: CatalogTree, category_id: int, intro: str | None, count_line: str | None) -> str:
    """The section path in bold, the admin's introduction, then a count line."""
    text = t("category_title", path=html(format_path(tree.path(category_id))))
    if intro:
        text += "\n" + intro
    if count_line:
        text += ("\n\n" if intro else "\n") + count_line
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
    return button(t("category_button", title=node.title, count=tree.total(node.id)), CategoryCb(id=node.id))


def _bottom_row(node: CategoryNode) -> list[InlineKeyboardButton]:
    if node.parent_id is None:
        # One level up is the main menu itself, so a second button would repeat it.
        return [button(t("btn_back"), MenuCb())]
    return [button(t("btn_back"), CategoryCb(id=node.parent_id)), button(t("btn_home"), MenuCb())]
