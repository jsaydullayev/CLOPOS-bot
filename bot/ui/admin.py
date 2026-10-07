"""Admin panel screens."""

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton

from bot.db.models import Video
from bot.services.content import TEXT_MAX, Attachment
from bot.services.tree import CatalogTree, CategoryNode, Kind
from bot.texts import t
from bot.ui.callbacks import (
    ADMIN_PANEL,
    CHANNEL_GUIDE,
    AdminAddVideoCb,
    AdminCategoryCb,
    AdminDeleteCategoryCb,
    AdminDeleteVideoCb,
    AdminFlowCb,
    AdminIntroCb,
    AdminNewCategoryCb,
    AdminPickCb,
    AdminTextEditCb,
    AdminTextResetCb,
    AdminTextsCb,
    AdminVideoCb,
    SectionCodesCb,
)
from bot.ui.client import attachment_media, section_header, video_caption, video_list, video_media
from bot.ui.screen import COLUMNS, PAGE_SIZE, Screen, button, grid, keyboard, page_row, paginate
from bot.utils.text import format_path, html

# Full paths can be long: fewer lines per page keep the message under Telegram's 4096 characters.
CODES_PAGE_SIZE = 15


def admin_panel() -> Screen:
    buttons = [
        button(t("btn_admin_categories"), AdminCategoryCb()),
        button(t("btn_admin_add_video"), AdminPickCb()),
        button(t("btn_admin_texts"), AdminTextsCb()),
        button(t("btn_channel_guide"), CHANNEL_GUIDE),
    ]
    return Screen(text=t("admin_panel"), markup=keyboard(grid(buttons, COLUMNS)))


def channel_guide() -> Screen:
    """How to post videos in the channel so they land in the right section."""
    rows = [[button(t("btn_section_codes"), SectionCodesCb()), button(t("btn_admin_panel"), ADMIN_PANEL)]]
    return Screen(text=t("channel_guide"), markup=keyboard(rows))


def section_codes(tree: CatalogTree, page: int) -> Screen:
    """Every section with its code for channel captions, in the order of the section list."""
    chunk, page, pages = paginate(tree.walk(), page, CODES_PAGE_SIZE)
    lines = []
    for node in chunk:
        # Sections that hold sections take no videos: marked, so their code is used only with › +New.
        key = "section_code_parent" if tree.kind(node.id) is Kind.CATEGORIES else "section_code"
        lines.append(t(key, code=node.id, path=html(format_path(tree.path(node.id), limit=None))))
    text = t("section_codes_title") + "\n\n" + ("\n".join(lines) if lines else t("section_codes_empty"))
    rows = [page_row(page, pages, lambda p: SectionCodesCb(page=p)), [button(t("btn_back"), CHANNEL_GUIDE)]]
    return Screen(text=text, markup=keyboard(rows))


def admin_category(
    tree: CatalogTree,
    category_id: int | None,
    videos: Sequence[Video],
    page: int,
    max_depth: int,
    *,
    intro: str | None = None,
) -> Screen:
    """A category as the admin sees it: empty categories too, with add, text and delete buttons."""
    node = tree.get(category_id)
    if node is None:
        return _admin_root(tree, page)

    kind = tree.kind(node.id)
    rows: list[list[InlineKeyboardButton]] = []
    listing = ""
    note = None
    if kind is Kind.CATEGORIES:
        children = tree.children(node.id)
        chunk, page, pages = paginate(children, page)
        rows += grid([button(_category_label(tree, child), AdminCategoryCb(id=child.id)) for child in chunk], COLUMNS)
    elif kind is Kind.VIDEOS:
        # The same layout the client sees: titles in the text, numbers on the buttons.
        chunk_videos, page, pages = paginate(videos, page)
        listing, video_rows = video_list(chunk_videos, page * PAGE_SIZE, lambda video: AdminVideoCb(id=video.id))
        rows += video_rows
    else:
        pages = 1
        note = t("admin_empty_note")
    rows.append(page_row(page, pages, lambda p: AdminCategoryCb(id=node.id, page=p)))

    actions = []
    if tree.can_add_child(node.id, max_depth):
        actions.append(button(t("btn_new_subcategory"), AdminNewCategoryCb(parent=node.id)))
    if tree.can_add_video(node.id):
        actions.append(button(t("btn_new_video"), AdminAddVideoCb(category=node.id)))
    actions.append(button(t("btn_edit_intro"), AdminIntroCb(id=node.id)))
    actions.append(button(t("btn_delete"), AdminDeleteCategoryCb(id=node.id)))
    rows += grid(actions, COLUMNS)
    rows.append([button(t("btn_back"), AdminCategoryCb(id=node.parent_id or 0))])
    text = section_header(tree, node.id, intro, note)
    if listing:
        text += "\n\n" + listing
    return Screen(text=text, markup=keyboard(rows))


def _admin_root(tree: CatalogTree, page: int) -> Screen:
    children = tree.children(None)
    chunk, page, pages = paginate(children, page)
    rows = grid([button(_category_label(tree, child), AdminCategoryCb(id=child.id)) for child in chunk], COLUMNS)
    rows.append(page_row(page, pages, lambda p: AdminCategoryCb(page=p)))
    rows.append([button(t("btn_new_category"), AdminNewCategoryCb()), button(t("btn_admin_panel"), ADMIN_PANEL)])
    text = t("admin_root") if children else t("admin_root_empty")
    return Screen(text=text, markup=keyboard(rows))


def confirm_delete_category(tree: CatalogTree, node: CategoryNode) -> Screen:
    categories, videos = tree.subtree_stats(node.id)
    contents = []
    if categories:
        contents.append(t("count_categories", count=categories))
    if videos:
        contents.append(t("count_videos", count=videos))
    title = html(node.title)
    if contents:
        text = t("category_delete_full", title=title, contents=t("count_join").join(contents))
    else:
        text = t("category_delete_empty", title=title)
    rows = [
        [
            button(t("btn_delete_confirm"), AdminDeleteCategoryCb(id=node.id, confirm=True)),
            button(t("btn_cancel"), AdminCategoryCb(id=node.id)),
        ],
    ]
    return Screen(text=text, markup=keyboard(rows))


def admin_pick(tree: CatalogTree, category_id: int | None, page: int) -> Screen:
    """Walk the tree to the category a new video goes into."""
    children = tree.children(category_id)
    if category_id is None and not children:
        rows = [[button(t("btn_admin_categories"), AdminCategoryCb()), button(t("btn_admin_panel"), ADMIN_PANEL)]]
        return Screen(text=t("pick_category_none"), markup=keyboard(rows))

    chunk, page, pages = paginate(children, page)
    buttons = []
    for child in chunk:
        if tree.kind(child.id) is Kind.CATEGORIES:
            buttons.append(button(t("pick_category_nested", title=child.title), AdminPickCb(id=child.id)))
        else:
            buttons.append(button(child.title, AdminAddVideoCb(category=child.id)))
    rows = grid(buttons, COLUMNS)
    rows.append(page_row(page, pages, lambda p: AdminPickCb(id=category_id or 0, page=p)))

    node = tree.get(category_id)
    if node is None:
        rows.append([button(t("btn_admin_panel"), ADMIN_PANEL)])
        text = t("pick_category")
    else:
        rows.append([button(t("btn_back"), AdminPickCb(id=node.parent_id or 0))])
        text = t("pick_category_in", path=html(format_path(tree.path(node.id))))
    return Screen(text=text, markup=keyboard(rows))


def admin_video(tree: CatalogTree, video: Video, siblings: Sequence[Video], *, confirm: bool = False) -> Screen:
    ids = [sibling.id for sibling in siblings]
    index = ids.index(video.id)
    caption = video_caption(video.title, video.description)
    if confirm:
        caption += "\n\n" + t("video_delete_question")
        row = [
            button(t("btn_delete_confirm"), AdminDeleteVideoCb(id=video.id, confirm=True)),
            button(t("btn_cancel"), AdminVideoCb(id=video.id)),
        ]
    else:
        row = [
            button(t("btn_delete"), AdminDeleteVideoCb(id=video.id)),
            button(t("btn_back"), AdminCategoryCb(id=video.category_id, page=index // PAGE_SIZE)),
        ]
    return Screen(media=video_media(video, caption), markup=keyboard([row]))


def texts_screen(labels: dict[str, str], customized: set[str], notice: str | None = None) -> Screen:
    """«Salomlashuv va matnlar»: the texts the admin can change; labels maps a text key to its name."""
    rows = []
    for key, label in labels.items():
        shown = t("text_label_customized", label=label) if key in customized else label
        rows.append([button(shown, AdminTextsCb(key=key))])
    rows.append([button(t("btn_admin_panel"), ADMIN_PANEL)])
    text = t("texts_title")
    return Screen(text=f"{notice}\n\n{text}" if notice else text, markup=keyboard(rows))


def text_preview(
    key: str,
    label: str,
    text: str,
    attachment: Attachment | None,
    *,
    customized: bool,
    media_allowed: bool,
    notice: str | None = None,
) -> Screen:
    """The text (with its photo or video) exactly as the client sees it, with the admin's buttons under it."""
    rows = [[button(t("btn_edit_text"), AdminTextEditCb(key=key))]]
    if media_allowed:
        label_key = "btn_change_media" if attachment is not None else "btn_set_media"
        rows.append([button(t(label_key), AdminTextEditCb(key=key, media=True))])
    if attachment is not None:
        rows.append([button(t("btn_remove_media"), AdminTextResetCb(key=key, media=True))])
    if customized:
        rows.append([button(t("btn_reset_text"), AdminTextResetCb(key=key))])
    rows.append([button(t("btn_back"), AdminTextsCb())])
    if attachment is not None:
        return Screen(media=attachment_media(attachment, text), markup=keyboard(rows))
    body = t("text_preview_title", label=html(label)) + "\n\n" + text
    return Screen(text=f"{notice}\n\n{body}" if notice else body, markup=keyboard(rows), plain=True)


def text_edit_prompt(label: str, *, media: bool, error: str | None = None) -> Screen:
    text = t("media_prompt" if media else "text_prompt", label=html(label), max=TEXT_MAX)
    return prompt(f"{error}\n\n{text}" if error else text)


def intro_prompt(tree: CatalogTree, category_id: int, current: str | None, error: str | None = None) -> Screen:
    text = t(
        "intro_prompt",
        path=html(format_path(tree.path(category_id))),
        current=current or t("intro_none"),
        max=TEXT_MAX,
    )
    buttons = [button(t("btn_clear_intro"), AdminIntroCb(id=category_id, clear=True))] if current else []
    return prompt(f"{error}\n\n{text}" if error else text, buttons)


def prompt(text: str, buttons: Sequence[InlineKeyboardButton] = ()) -> Screen:
    """A step of an admin dialog: always ends with a cancel button."""
    cancel = button(t("btn_cancel"), AdminFlowCb(action="cancel"))
    return Screen(text=text, markup=keyboard(grid([*buttons, cancel], COLUMNS)))


def _category_label(tree: CatalogTree, node: CategoryNode) -> str:
    if tree.total(node.id):
        return node.title
    return t("admin_category_button_empty", title=node.title)
