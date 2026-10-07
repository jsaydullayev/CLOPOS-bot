"""Catalog rules for creating and deleting categories and videos."""

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import Category, Video
from bot.services.tree import CategoryNode, Kind
from bot.utils.text import clean_name

NAME_MIN = 2
CATEGORY_NAME_MAX = 40
VIDEO_TITLE_MAX = 60
DESCRIPTION_MAX = 300
# They separate sections in channel captions, so a section name cannot contain them.
PATH_SEPARATORS = ("›", ">")


class CatalogError(Exception):
    """A broken rule. `key` is a text key in locales, `params` fill its placeholders."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def validate_name(raw: str | None, maximum: int, *, error_key: str = "error_name_length") -> str:
    name = clean_name(raw or "")
    if not NAME_MIN <= len(name) <= maximum:
        raise CatalogError(error_key, min=NAME_MIN, max=maximum)
    return name


def validate_description(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if len(text) > DESCRIPTION_MAX:
        raise CatalogError("error_description_length", max=DESCRIPTION_MAX)
    return text or None


async def create_category(
    session: AsyncSession,
    *,
    parent_id: int | None,
    raw_title: str | None,
    admin_id: int | None,
    max_depth: int,
) -> Category:
    title = validate_name(raw_title, CATEGORY_NAME_MAX)
    if any(separator in title for separator in PATH_SEPARATORS):
        raise CatalogError("error_name_separator")
    tree = await repo.load_tree(session)

    depth = 1
    if parent_id is not None:
        parent = tree.get(parent_id)
        if parent is None:
            raise CatalogError("category_deleted")
        if tree.kind(parent_id) is Kind.VIDEOS:
            raise CatalogError("error_category_has_videos")
        if parent.depth >= max_depth:
            raise CatalogError("error_max_depth", max=max_depth)
        depth = parent.depth + 1

    folded = title.casefold()
    if any(sibling.title.casefold() == folded for sibling in tree.children(parent_id)):
        raise CatalogError("error_category_exists", title=title)

    category = Category(
        parent_id=parent_id,
        title=title,
        depth=depth,
        position=await repo.next_category_position(session, parent_id),
        created_by=admin_id,
    )
    session.add(category)
    await session.flush()
    return category


async def remove_category(session: AsyncSession, category_id: int) -> CategoryNode | None:
    """Delete a category with everything inside. Returns what was deleted, or None."""
    category = await repo.get_category(session, category_id)
    if category is None:
        return None
    node = CategoryNode(
        id=category.id,
        parent_id=category.parent_id,
        title=category.title,
        depth=category.depth,
        position=category.position,
    )
    await repo.delete_category(session, category_id)
    return node


async def add_video(
    session: AsyncSession,
    *,
    category_id: int,
    title: str,
    description: str | None,
    file_id: str,
    file_unique_id: str,
    media_type: str,
    admin_id: int | None,
    backup_message_id: int | None = None,
) -> Video:
    tree = await repo.load_tree(session)
    if tree.get(category_id) is None:
        raise CatalogError("category_deleted")
    if not tree.can_add_video(category_id):
        raise CatalogError("error_category_has_children")

    video = Video(
        category_id=category_id,
        title=title,
        description=description,
        file_id=file_id,
        file_unique_id=file_unique_id,
        media_type=media_type,
        backup_message_id=backup_message_id,
        position=await repo.next_video_position(session, category_id),
        created_by=admin_id,
    )
    session.add(video)
    await session.flush()
    return video


async def remove_video(session: AsyncSession, video_id: int) -> int | None:
    """Delete a video. Returns its category id, or None if it was already gone.

    The copy in the archive channel is kept.
    """
    video = await repo.get_video(session, video_id)
    if video is None:
        return None
    category_id = video.category_id
    await repo.delete_video(session, video_id)
    return category_id
