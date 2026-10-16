"""Admin panel screens."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton

from bot.db.models import User, Video
from bot.db.repo import UserCounts
from bot.services.content import TEXT_MAX, Attachment
from bot.services.tree import CatalogTree, CategoryNode, Kind
from bot.texts import t
from bot.ui.callbacks import (
    ADD_ADMIN,
    ADMIN_PANEL,
    ADMINS,
    CHANNEL_GUIDE,
    AdminAddVideoCb,
    AdminCategoryCb,
    AdminDeleteCategoryCb,
    AdminDeleteVideoCb,
    AdminEmojiCb,
    AdminFlowCb,
    AdminIntroCb,
    AdminNewCategoryCb,
    AdminPickCb,
    AdminRemoveCb,
    AdminTextEditCb,
    AdminTextResetCb,
    AdminTextsCb,
    AdminVideoCb,
    SectionCodesCb,
    SupportReportCb,
    UsersCb,
)
from bot.ui.client import (
    attachment_media,
    section_emoji,
    section_header,
    section_label,
    video_caption,
    video_list,
    video_media,
    video_page,
)
from bot.ui.screen import (
    ACCENT_STYLE,
    COLUMNS,
    Screen,
    button,
    grid,
    keyboard,
    page_row,
    paginate,
    with_notice,
)
from bot.utils import clock
from bot.utils.text import format_path, html, shorten

# Full paths can be long: fewer lines per page keep the message under Telegram's 4096 characters.
CODES_PAGE_SIZE = 15
# A page of codes fits one message (4096 characters) however deep the sections go.
CODES_PATH_MAX = 200
USERS_PAGE_SIZE = 10
# Longer names are cut on the remove buttons, which go two in a row.
BUTTON_NAME_MAX = 24


@dataclass(frozen=True, slots=True)
class AdminEntry:
    user_id: int
    name: str  # first name and @username as far as the bot knows them, or the ID
    owner: bool  # set in ADMIN_IDS (.env): cannot be removed in the panel


def admin_panel(waiting: int = 0) -> Screen:
    """waiting: tickets nobody has answered yet, shown on «📨 Murojaatlar» (green while there are any)."""
    support = (
        button(t("btn_support_waiting", count=waiting), SupportReportCb(), style=ACCENT_STYLE)
        if waiting
        else button(t("btn_support"), SupportReportCb())
    )
    buttons = [
        support,
        button(t("btn_users"), UsersCb()),
        button(t("btn_admin_categories"), AdminCategoryCb()),
        button(t("btn_admin_add_video"), AdminPickCb()),
        button(t("btn_admin_texts"), AdminTextsCb()),
        button(t("btn_channel_guide"), CHANNEL_GUIDE),
        button(t("btn_admins"), ADMINS),
    ]
    return Screen(text=t("admin_panel"), markup=keyboard(grid(buttons, COLUMNS)))


def users_screen(counts: UserCounts, users: Sequence[User], page: int, pages: int, tz: ZoneInfo, today: date) -> Screen:
    """«📈 Foydalanuvchilar»: how many use the bot, and who was active last."""
    lines = [
        t("users_title"),
        "",
        t("users_total", count=counts.total),
        t("users_today", count=counts.today),
        t("users_week", count=counts.week),
        t("users_month", count=counts.month),
        t("users_joined_today", count=counts.joined_today),
    ]
    if users:
        lines += ["", t("users_recent")]
    for number, user in enumerate(users, start=page * USERS_PAGE_SIZE + 1):
        name = html(shorten(user.first_name or t("admin_name_id", id=user.id), BUTTON_NAME_MAX))
        if user.username:
            name += f" (@{html(user.username)})"
        lines.append(t("users_item", number=number, name=name, time=clock.short_stamp(user.last_active_at, tz, today)))
    rows = [page_row(page, pages, lambda p: UsersCb(page=p)), [button(t("btn_admin_panel"), ADMIN_PANEL)]]
    return Screen(text="\n".join(lines), markup=keyboard(rows))


def admins_screen(entries: Sequence[AdminEntry], notice: str | None = None) -> Screen:
    """Everyone who can open the admin panel; the ones added here have a remove button."""
    lines = [t("admins_owner_line" if entry.owner else "admins_line", name=html(entry.name)) for entry in entries]
    text = t("admins_title") + "\n\n" + "\n".join(lines)
    removable = [
        button(t("btn_remove_admin", name=shorten(entry.name, BUTTON_NAME_MAX)), AdminRemoveCb(user_id=entry.user_id))
        for entry in entries
        if not entry.owner
    ]
    rows = grid(removable, COLUMNS)
    rows.append([button(t("btn_add_admin"), ADD_ADMIN), button(t("btn_admin_panel"), ADMIN_PANEL)])
    return Screen(text=with_notice(text, notice), markup=keyboard(rows))


def confirm_remove_admin(entry: AdminEntry) -> Screen:
    rows = [
        [
            button(t("btn_remove_admin_confirm"), AdminRemoveCb(user_id=entry.user_id, confirm=True)),
            button(t("btn_cancel"), ADMINS),
        ],
    ]
    return Screen(text=t("admin_remove_question", name=html(entry.name)), markup=keyboard(rows))


def add_admin_prompt(error: str | None = None) -> Screen:
    return prompt(with_notice(t("admin_add_prompt"), error), cancel=ADMINS)


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
        lines.append(t(key, code=node.id, path=html(format_path(tree.path(node.id), limit=CODES_PATH_MAX))))
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
    text = section_header(tree, node.id, intro, t("admin_empty_note") if kind is Kind.EMPTY else None)
    pages = 1
    if kind is Kind.CATEGORIES:
        children = tree.children(node.id)
        chunk, page, pages = paginate(children, page)
        rows += grid([button(_category_label(tree, child), AdminCategoryCb(id=child.id)) for child in chunk], COLUMNS)
    elif kind is Kind.VIDEOS:
        # The same layout the client sees: every video in one message, titles in the text, numbers on the buttons.
        text += "\n\n"
        listing, video_rows, page, pages = video_list(
            videos, page, lambda video: AdminVideoCb(id=video.id), above=text
        )
        text += listing
        rows += video_rows
    rows.append(page_row(page, pages, lambda p: AdminCategoryCb(id=node.id, page=p)))

    actions = []
    if tree.can_add_child(node.id, max_depth):
        actions.append(button(t("btn_new_subcategory"), AdminNewCategoryCb(parent=node.id)))
    if tree.can_add_video(node.id):
        actions.append(button(t("btn_new_video"), AdminAddVideoCb(category=node.id)))
    actions.append(button(t("btn_edit_intro"), AdminIntroCb(id=node.id)))
    actions.append(button(t("btn_section_emoji"), AdminEmojiCb(id=node.id)))
    actions.append(button(t("btn_delete"), AdminDeleteCategoryCb(id=node.id)))
    rows += grid(actions, COLUMNS)
    rows.append([button(t("btn_back"), AdminCategoryCb(id=node.parent_id or 0))])
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


def admin_video(video: Video, ids: Sequence[int], *, confirm: bool = False) -> Screen:
    """ids: the section's videos in order, to come back to the list page with this one."""
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
            button(t("btn_back"), AdminCategoryCb(id=video.category_id, page=video_page(ids, video.id))),
        ]
    return Screen(media=video_media(video, caption), markup=keyboard([row]))


def texts_screen(labels: dict[str, str], customized: set[str], notice: str | None = None) -> Screen:
    """«Salomlashuv va matnlar»: the texts the admin can change; labels maps a text key to its name."""
    rows = []
    for key, label in labels.items():
        shown = t("text_label_customized", label=label) if key in customized else label
        rows.append([button(shown, AdminTextsCb(key=key))])
    rows.append([button(t("btn_admin_panel"), ADMIN_PANEL)])
    return Screen(text=with_notice(t("texts_title"), notice), markup=keyboard(rows))


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
    return Screen(text=with_notice(body, notice), markup=keyboard(rows), plain=True)


def text_edit_prompt(label: str, *, media: bool, error: str | None = None) -> Screen:
    text = t("media_prompt" if media else "text_prompt", label=html(label), max=TEXT_MAX)
    return prompt(with_notice(text, error))


def intro_prompt(tree: CatalogTree, category_id: int, current: str | None, error: str | None = None) -> Screen:
    text = t(
        "intro_prompt",
        path=html(format_path(tree.path(category_id))),
        current=current or t("intro_none"),
        max=TEXT_MAX,
    )
    buttons = [button(t("btn_clear_intro"), AdminIntroCb(id=category_id, clear=True))] if current else []
    return prompt(with_notice(text, error), buttons)


def prompt(
    text: str,
    buttons: Sequence[InlineKeyboardButton] = (),
    *,
    cancel: CallbackData | str | None = None,
) -> Screen:
    """A step of an admin dialog: always ends with a cancel button (by default, back where it began)."""
    cancel_button = button(t("btn_cancel"), cancel or AdminFlowCb(action="cancel"))
    return Screen(text=text, markup=keyboard(grid([*buttons, cancel_button], COLUMNS)))


def emoji_prompt(tree: CatalogTree, category_id: int, error: str | None = None) -> Screen:
    node = tree.get(category_id)
    assert node is not None  # the handlers have just found the category
    current = node.emoji or t("emoji_standard", emoji=section_emoji(tree, node))
    text = t("emoji_prompt", path=html(format_path(tree.path(node.id))), current=current)
    buttons = [button(t("btn_clear_emoji"), AdminEmojiCb(id=node.id, clear=True))] if node.emoji else []
    return prompt(with_notice(text, error), buttons)


def _category_label(tree: CatalogTree, node: CategoryNode) -> str:
    """The client's label with the emoji; an empty section, hidden from clients, is marked."""
    if tree.total(node.id):
        return section_label(tree, node)
    return t("admin_category_button_empty", emoji=section_emoji(tree, node), title=node.title)
