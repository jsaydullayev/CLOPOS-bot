"""Adding and editing videos through posts in the private video channel.

Admins drop a video into the channel with a caption; the bot adds it to the
catalog. PostgreSQL stays the catalog the bot reads from: the Bot API does not
let a bot read a channel's history or learn about deleted posts, so only the
posts the bot sees arriving (new and edited ones) are taken in.

Caption format:
    Бек офис › Финансы        1st line: sections, separated by › or >
    Отчёты                    2nd line: video title
    Oylik hisobot             3rd line on: description (optional)

On the first line #12 stands for the section with id 12 (`#12 › +New` goes on
below it), and a + before a name creates that section. Without a +, a name must
match an existing section: case, spaces, apostrophes and a typo or two are
forgiven, an unknown name is rejected. So a typo never creates a stray section.
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
from bot.utils.text import clean_name, format_path, name_key, typo_distance

_SEPARATOR = re.compile("|".join(re.escape(separator) for separator in PATH_SEPARATORS))
_CODE = re.compile(r"#(\d{1,9})")
NEW_MARK = "+"
# Typos forgiven in a section name, by the length of its name_key; names under 5 letters must be exact.
_TYPOS_BY_LENGTH = ((10, 2), (5, 1))
_SUGGESTIONS = 3


@dataclass(frozen=True, slots=True)
class PostCaption:
    path: tuple[str, ...]  # section names, without the + marks
    title: str
    description: str | None
    code: int | None = None  # #12 at the start of the path: the section with that id
    new_from: int | None = None  # index in path of the first name marked with +


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
    # (name in the caption, section it was taken for) when a typo was forgiven
    corrected: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class _Place:
    """Where a caption puts its video: an existing section, or new sections under it."""

    parent: CategoryNode | None = None
    missing: list[str] = field(default_factory=list)  # sections to create, top-down
    corrected: list[tuple[str, str]] = field(default_factory=list)


def parse_caption(caption: str | None) -> PostCaption:
    lines = _without_leading_blanks([line.strip() for line in (caption or "").splitlines()])
    if not lines:
        raise CatalogError("channel_no_caption")

    segments = [name for name in (clean_name(part) for part in _SEPARATOR.split(lines[0])) if name]
    code = None
    if segments and (match := _CODE.fullmatch(segments[0])):
        code = int(match.group(1))
        segments = segments[1:]
    path: list[str] = []
    new_from = None
    for segment in segments:
        name = segment
        if segment.startswith(NEW_MARK):
            name = segment.removeprefix(NEW_MARK).strip()
            if new_from is None:
                new_from = len(path)
        if not NAME_MIN <= len(name) <= CATEGORY_NAME_MAX:
            raise CatalogError("channel_bad_section", title=name, min=NAME_MIN, max=CATEGORY_NAME_MAX)
        path.append(name)
    if not path and code is None:
        raise CatalogError("channel_no_caption")

    rest = _without_leading_blanks(lines[1:])
    if not rest:
        raise CatalogError("channel_no_title")
    title = validate_name(rest[0], VIDEO_TITLE_MAX, error_key="channel_bad_title")
    description = validate_description("\n".join(rest[1:]))
    return PostCaption(path=tuple(path), title=title, description=description, code=code, new_from=new_from)


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
    if parsed.code is None and len(parsed.path) > max_depth:
        raise CatalogError("error_max_depth", max=max_depth)

    tree = await repo.load_tree(session)
    video = await repo.find_video_by_post(session, message_id)

    place = _place(tree, parsed)
    parent, missing = place.parent, place.missing
    if (parent.depth if parent is not None else 0) + len(missing) > max_depth:
        raise CatalogError("error_max_depth", max=max_depth)

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
        return ImportResult(video=video, created=True, new_sections=new_sections, corrected=place.corrected)

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
    return ImportResult(video=video, created=False, new_sections=new_sections, corrected=place.corrected)


def _place(tree: CatalogTree, parsed: PostCaption) -> _Place:
    place = _Place()
    if parsed.code is not None:
        place.parent = tree.get(parsed.code)
        if place.parent is None:
            raise CatalogError("channel_unknown_code", code=parsed.code)
    for index, name in enumerate(parsed.path):
        if place.missing:  # below a new section everything is new
            place.missing.append(name)
            continue
        parent = place.parent
        if parent is not None and tree.kind(parent.id) is Kind.VIDEOS:
            raise CatalogError("channel_section_has_videos", title=parent.title)
        siblings = tree.children(parent.id if parent is not None else None)
        marked_new = parsed.new_from is not None and index >= parsed.new_from
        found = _find_section(siblings, name, typos=not marked_new)
        if found is not None:
            if name_key(found.title) != name_key(name):
                place.corrected.append((name, found.title))
            place.parent = found
        elif marked_new:
            place.missing.append(name)
        else:
            raise _not_found(name, siblings)
    if not place.missing and place.parent is not None and tree.kind(place.parent.id) is Kind.CATEGORIES:
        raise CatalogError("channel_section_has_children", title=place.parent.title)
    return place


def _find_section(siblings: list[CategoryNode], name: str, *, typos: bool) -> CategoryNode | None:
    """The section a name stands for. With typos, a near miss counts too, unless two are equally near."""
    key = name_key(name)
    same = next((node for node in siblings if name_key(node.title) == key), None)
    if same is not None or not typos:
        return same
    allowed = next((count for length, count in _TYPOS_BY_LENGTH if len(key) >= length), 0)
    # Numbers are never a typo: «2-dars» is not «1-dars».
    near = [
        (distance, node)
        for distance, node in _ranked(siblings, key)
        if distance <= allowed and _digits(name_key(node.title)) == _digits(key)
    ]
    if not near:
        return None
    closest = [node for distance, node in near if distance == near[0][0]]
    if len(closest) > 1:
        raise CatalogError("channel_section_ambiguous", title=name, options=_quoted(closest))
    return closest[0]


def _not_found(name: str, siblings: list[CategoryNode]) -> CatalogError:
    key = name_key(name)
    limit = max(2, len(key) // 2)
    similar = [node for distance, node in _ranked(siblings, key) if distance <= limit][:_SUGGESTIONS]
    if similar:
        return CatalogError("channel_section_not_found_similar", title=name, options=_quoted(similar))
    return CatalogError("channel_section_not_found", title=name)


def _ranked(siblings: list[CategoryNode], key: str) -> list[tuple[int, CategoryNode]]:
    """Siblings by how many typos away from key their names are, nearest first."""
    return sorted(((typo_distance(key, name_key(node.title)), node) for node in siblings), key=lambda pair: pair[0])


def _digits(key: str) -> str:
    return "".join(char for char in key if char.isdigit())


def _quoted(nodes: list[CategoryNode]) -> str:
    return ", ".join(f"«{node.title}»" for node in nodes)


def _without_leading_blanks(lines: list[str]) -> list[str]:
    index = 0
    while index < len(lines) and not lines[index]:
        index += 1
    return lines[index:]
