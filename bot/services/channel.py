"""Adding and editing videos through posts in the private video channel.

Admins drop a video into the channel with a caption; the bot adds it to the
catalog. PostgreSQL stays the catalog the bot reads from: the Bot API does not
let a bot read a channel's history or learn about deleted posts, so only the
posts the bot sees arriving (new and edited ones) are taken in.

Caption format:
    Бек офис › Финансы        1st line: sections, separated by › or >
    Отчёты                    2nd line: video title
    Oylik hisobot             3rd line on: description (optional)
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import Video
from bot.services.catalog import (
    CATEGORY_NAME_MAX,
    NAME_MIN,
    PATH_SEPARATORS,
    VIDEO_TITLE_MAX,
    CatalogError,
    add_video,
    create_category,
    validate_description,
    validate_name,
)
from bot.services.tree import CatalogTree, CategoryNode, Kind
from bot.utils.text import clean_name, format_path

_SEPARATOR = re.compile("|".join(re.escape(separator) for separator in PATH_SEPARATORS))


@dataclass(frozen=True, slots=True)
class PostCaption:
    path: tuple[str, ...]
    title: str
    description: str | None


@dataclass(frozen=True, slots=True)
class PostMedia:
    file_id: str
    file_unique_id: str
    media_type: str


@dataclass(slots=True)
class ImportResult:
    video: Video
    created: bool  # False when an existing video was updated from an edited post
    new_sections: list[str] = field(default_factory=list)


def parse_caption(caption: str | None) -> PostCaption:
    lines = _without_leading_blanks([line.strip() for line in (caption or "").splitlines()])
    if not lines:
        raise CatalogError("channel_no_caption")

    path = tuple(name for name in (clean_name(part) for part in _SEPARATOR.split(lines[0])) if name)
    if not path:
        raise CatalogError("channel_no_caption")
    for name in path:
        if not NAME_MIN <= len(name) <= CATEGORY_NAME_MAX:
            raise CatalogError("channel_bad_section", title=name, min=NAME_MIN, max=CATEGORY_NAME_MAX)

    rest = _without_leading_blanks(lines[1:])
    if not rest:
        raise CatalogError("channel_no_title")
    title = validate_name(rest[0], VIDEO_TITLE_MAX, error_key="channel_bad_title")
    description = validate_description("\n".join(rest[1:]))
    return PostCaption(path=path, title=title, description=description)


def post_caption(path: Sequence[str], title: str, description: str | None) -> str:
    """The caption format, as the bot writes it on channel copies of admin-panel videos."""
    lines = [format_path(path, limit=None), title]
    if description:
        lines.append(description)
    return "\n".join(lines)


async def import_post(
    session: AsyncSession,
    *,
    message_id: int,
    caption: str | None,
    media: PostMedia,
    max_depth: int,
) -> ImportResult:
    """Add the video of a channel post, or update it when the post was edited.

    Every rule is checked before anything is written, so a rejected post
    leaves no half-created sections behind.
    """
    parsed = parse_caption(caption)
    if len(parsed.path) > max_depth:
        raise CatalogError("error_max_depth", max=max_depth)

    tree = await repo.load_tree(session)
    video = await repo.find_video_by_post(session, message_id)

    parent: CategoryNode | None = None
    missing: list[str] = []
    for name in parsed.path:
        found = None if missing else _find_child(tree, parent.id if parent else None, name)
        if found is None:
            missing.append(name)
        else:
            parent = found
    if missing and parent is not None and tree.kind(parent.id) is Kind.VIDEOS:
        raise CatalogError("channel_section_has_videos", title=parent.title)
    if not missing and parent is not None and tree.kind(parent.id) is Kind.CATEGORIES:
        raise CatalogError("channel_section_has_children", title=parent.title)

    duplicate = await repo.find_video_by_file(
        session, media.file_unique_id, exclude_id=video.id if video is not None else None
    )
    if duplicate is not None:
        raise CatalogError(
            "channel_duplicate",
            title=duplicate.title,
            path=format_path(tree.path(duplicate.category_id), limit=None),
        )

    category_id = parent.id if parent is not None else None
    new_sections: list[str] = []
    created_path = [*tree.path(category_id)] if category_id is not None else []
    for name in missing:
        category = await create_category(
            session, parent_id=category_id, raw_title=name, admin_id=None, max_depth=max_depth
        )
        category_id = category.id
        created_path.append(category.title)
        new_sections.append(format_path(created_path, limit=None))
    assert category_id is not None  # the path has at least one section

    if video is None:
        video = await add_video(
            session,
            category_id=category_id,
            title=parsed.title,
            description=parsed.description,
            file_id=media.file_id,
            file_unique_id=media.file_unique_id,
            media_type=media.media_type,
            admin_id=None,
            backup_message_id=message_id,
        )
        return ImportResult(video=video, created=True, new_sections=new_sections)

    if video.category_id != category_id:
        # The section in the caption changed: the video moves to the end of the new one.
        video.category_id = category_id
        video.position = await repo.next_video_position(session, category_id)
    video.title = parsed.title
    video.description = parsed.description
    video.file_id = media.file_id
    video.file_unique_id = media.file_unique_id
    video.media_type = media.media_type
    await session.flush()
    return ImportResult(video=video, created=False, new_sections=new_sections)


def _find_child(tree: CatalogTree, parent_id: int | None, name: str) -> CategoryNode | None:
    folded = name.casefold()
    return next((child for child in tree.children(parent_id) if child.title.casefold() == folded), None)


def _without_leading_blanks(lines: list[str]) -> list[str]:
    index = 0
    while index < len(lines) and not lines[index]:
        index += 1
    return lines[index:]
