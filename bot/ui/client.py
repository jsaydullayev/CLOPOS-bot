"""Client screens: main menu, category, video."""

from collections.abc import Callable, Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton

from bot.db.models import Video
from bot.services.content import Attachment
from bot.services.tree import CatalogTree, CategoryNode, Kind
from bot.texts import t
from bot.ui.callbacks import CHANGE_PHONE, CONTACTS, WRITE_PROBLEM, CategoryCb, MenuCb, VideoCb
from bot.ui.screen import (
    ACCENT_STYLE,
    COLUMNS,
    Media,
    Screen,
    button,
    grid,
    keyboard,
    page_row,
    paginate,
    with_notice,
)
from bot.utils.phone import format_phone
from bot.utils.text import format_path, html, shorten, visible_length

# Video lists show titles in the text and only their numbers on the buttons.
NUMBER_COLUMNS = 4
# A section's videos all go into one message. Telegram puts about a hundred buttons on a message,
# so only a section with more videos than this goes on to a second page.
VIDEOS_PER_CARD = 90
# Telegram's limit for a message text (4096), with room for emoji, which it counts double.
TEXT_LIMIT = 4000
# A list too long for one message shortens its titles, but not below this.
TITLE_MIN = 12


def main_menu(
    tree: CatalogTree,
    page: int = 0,
    *,
    greeting: str | None = None,
    empty_text: str | None = None,
    attachment: Attachment | None = None,
) -> Screen:
    """greeting and empty_text are the admin's texts (HTML), by default the ones from locales.
    With a photo or video, the greeting becomes its caption. «📞 Bog‘lanish va yordam» is
    always at the bottom, on its own row and in green."""
    contacts_row = [button(t("btn_contacts"), CONTACTS, style=ACCENT_STYLE)]
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


def contacts_screen(contacts: str, notice: str | None = None) -> Screen:
    """The contacts (HTML, the admin can change them) and a way to leave a problem for the admins."""
    rows = [
        [button(t("btn_write_problem"), WRITE_PROBLEM, style=ACCENT_STYLE)],
        [button(t("btn_home"), MenuCb())],
    ]
    return Screen(text=with_notice(contacts, notice), markup=keyboard(rows))


def phone_prompt(error: str | None = None) -> Screen:
    """The phone the admins call back on, asked before the first problem."""
    cancel = [[button(t("btn_cancel"), CONTACTS)]]
    return Screen(text=with_notice(t("phone_prompt"), error), markup=keyboard(cancel))


def problem_prompt(phone: str, error: str | None = None) -> Screen:
    rows = [[button(t("btn_change_phone"), CHANGE_PHONE), button(t("btn_cancel"), CONTACTS)]]
    text = t("problem_prompt", phone=format_phone(phone))
    return Screen(text=with_notice(text, error), markup=keyboard(rows))


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
    # Under the admin's introduction, a short line on what to do here.
    text = section_header(tree, node.id, intro) + "\n\n"
    if tree.kind(node.id) is Kind.CATEGORIES:
        chunk, page, pages = paginate(tree.visible_children(node.id), page)
        rows = grid([_category_button(tree, child) for child in chunk], COLUMNS)
        text += t("hint_sections")
    else:
        text += t("hint_videos") + "\n"
        listing, rows, page, pages = video_list(videos, page, lambda video: VideoCb(id=video.id), above=text)
        text += listing
    rows.append(page_row(page, pages, lambda p: CategoryCb(id=node.id, page=p)))
    rows.append(_bottom_row(node))
    return Screen(text=text, markup=keyboard(rows))


def video_list(
    videos: Sequence[Video], page: int, make: Callable[[Video], CallbackData], *, above: str
) -> tuple[str, list[list[InlineKeyboardButton]], int, int]:
    """All the section's videos for one message: numbered titles for the text, number buttons under it.

    above: the text over the list. When the whole list does not fit in the message with it,
    the titles are shortened. Returns the list, the buttons, the page and the number of pages.
    """
    chunk, page, pages = paginate(videos, page, VIDEOS_PER_CARD)
    numbers = range(page * VIDEOS_PER_CARD + 1, page * VIDEOS_PER_CARD + len(chunk) + 1)
    limit = _title_limit([video.title for video in chunk], numbers, TEXT_LIMIT - visible_length(above))
    lines = [
        t("video_list_item", number=number, title=html(shorten(video.title, limit)))
        for number, video in zip(numbers, chunk, strict=True)
    ]
    buttons = [
        button(t("video_number_button", number=number), make(video))
        for number, video in zip(numbers, chunk, strict=True)
    ]
    return "\n".join(lines), grid(buttons, NUMBER_COLUMNS), page, pages


def video_page(ids: Sequence[int], video_id: int) -> int:
    """The page of the list a video is on, for «⬅️ Orqaga» from it."""
    return ids.index(video_id) // VIDEOS_PER_CARD


def _title_limit(titles: Sequence[str], numbers: Sequence[int], room: int) -> int:
    """The longest title length at which every line fits in room characters (a line: «12. Title\\n»)."""
    numbering = sum(len(t("video_list_item", number=number, title="")) + 1 for number in numbers)
    limit = max((len(title) for title in titles), default=0)
    while limit > TITLE_MIN and numbering + sum(min(len(title), limit) for title in titles) > room:
        limit -= 1
    return limit


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


def video_screen(video: Video, ids: Sequence[int]) -> Screen:
    """ids: the section's videos in order, for Previous / Next."""
    index = ids.index(video.id)

    switch_row = []
    if index > 0:
        switch_row.append(button(t("btn_video_prev"), VideoCb(id=ids[index - 1])))
    if index < len(ids) - 1:
        switch_row.append(button(t("btn_video_next"), VideoCb(id=ids[index + 1])))
    rows = [
        switch_row,
        [
            button(t("btn_back"), CategoryCb(id=video.category_id, page=video_page(ids, video.id))),
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
