"""Database queries."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    TICKET_DONE,
    TICKET_NEW,
    TICKET_NOT_DONE,
    Admin,
    BotText,
    Category,
    Ticket,
    User,
    Video,
)
from bot.services.tree import CatalogTree, CategoryNode


async def load_tree(session: AsyncSession) -> CatalogTree:
    rows = await session.execute(
        select(Category.id, Category.parent_id, Category.title, Category.depth, Category.position, Category.emoji)
    )
    counts = await session.execute(
        select(Video.category_id, func.count(Video.id)).group_by(Video.category_id)
    )
    nodes = [
        CategoryNode(
            id=row.id,
            parent_id=row.parent_id,
            title=row.title,
            depth=row.depth,
            position=row.position,
            emoji=row.emoji,
        )
        for row in rows
    ]
    return CatalogTree(nodes, dict(counts.tuples().all()))


async def get_category(session: AsyncSession, category_id: int | None) -> Category | None:
    """None for a missing id too: dialogs pass what they kept in their data."""
    return None if category_id is None else await session.get(Category, category_id)


async def get_video(session: AsyncSession, video_id: int) -> Video | None:
    return await session.get(Video, video_id)


async def video_ids(session: AsyncSession, category_id: int) -> list[int]:
    """The section's videos in their order: enough for Previous / Next and the list page."""
    result = await session.scalars(
        select(Video.id).where(Video.category_id == category_id).order_by(Video.position, Video.id)
    )
    return list(result)


async def list_videos(session: AsyncSession, category_id: int) -> list[Video]:
    result = await session.scalars(
        select(Video).where(Video.category_id == category_id).order_by(Video.position, Video.id)
    )
    return list(result)


async def find_video_by_file(
    session: AsyncSession, file_unique_id: str, *, exclude_id: int | None = None
) -> Video | None:
    query = select(Video).where(Video.file_unique_id == file_unique_id)
    if exclude_id is not None:
        query = query.where(Video.id != exclude_id)
    return await session.scalar(query.order_by(Video.id).limit(1))


async def find_video_by_post(session: AsyncSession, message_id: int) -> Video | None:
    """The video whose copy in the video channel is this post."""
    return await session.scalar(select(Video).where(Video.backup_message_id == message_id).limit(1))


async def next_category_position(session: AsyncSession, parent_id: int | None) -> int:
    condition = Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id
    current = await session.scalar(select(func.max(Category.position)).where(condition))
    return (current or 0) + 1


async def next_video_position(session: AsyncSession, category_id: int) -> int:
    current = await session.scalar(select(func.max(Video.position)).where(Video.category_id == category_id))
    return (current or 0) + 1


async def delete_category(session: AsyncSession, category_id: int) -> None:
    # Child categories and their videos go with it (ON DELETE CASCADE).
    await session.execute(delete(Category).where(Category.id == category_id))


async def delete_video(session: AsyncSession, video_id: int) -> None:
    await session.execute(delete(Video).where(Video.id == video_id))


async def get_custom_text(session: AsyncSession, key: str) -> BotText | None:
    return await session.get(BotText, key)


async def custom_text_keys(session: AsyncSession) -> set[str]:
    return set(await session.scalars(select(BotText.key)))


async def update_custom_text(
    session: AsyncSession,
    key: str,
    admin_id: int | None,
    *,
    value: str | None = None,
    media: tuple[str, str, str] | None = None,
) -> None:
    """Change the text, the media (file_id, file_unique_id, media_type) or both; what is not given stays."""
    row = await session.get(BotText, key)
    if row is None:
        row = BotText(key=key)
        session.add(row)
    if value is not None:
        row.value = value
    if media is not None:
        row.media_file_id, row.media_unique_id, row.media_type = media
    row.updated_by = admin_id
    await session.flush()


async def remove_custom_media(session: AsyncSession, key: str) -> None:
    row = await session.get(BotText, key)
    if row is None:
        return
    if row.value is None:
        await session.delete(row)
    else:
        row.media_file_id = row.media_unique_id = row.media_type = None
    await session.flush()


async def reset_custom_text(session: AsyncSession, key: str) -> None:
    """Back to the standard text; a photo or video the admin set stays."""
    row = await session.get(BotText, key)
    if row is None:
        return
    if row.media_file_id is None:
        await session.delete(row)
    else:
        row.value = None
    await session.flush()


async def list_admins(session: AsyncSession) -> list[Admin]:
    """Admins added in the panel, in the order they were added."""
    return list(await session.scalars(select(Admin).order_by(Admin.created_at, Admin.user_id)))


async def add_admin(session: AsyncSession, user_id: int, *, name: str | None, added_by: int | None) -> None:
    session.add(Admin(user_id=user_id, name=name, added_by=added_by))
    await session.flush()


async def delete_admin(session: AsyncSession, user_id: int) -> bool:
    admin = await session.get(Admin, user_id)
    if admin is None:
        return False
    await session.delete(admin)
    return True


async def get_users(session: AsyncSession, user_ids: list[int]) -> dict[int, User]:
    if not user_ids:
        return {}
    users = await session.scalars(select(User).where(User.id.in_(user_ids)))
    return {user.id: user for user in users}


async def find_user_by_username(session: AsyncSession, username: str) -> User | None:
    """A user who has written to the bot, by @username (without the @, any letter case)."""
    query = select(User).where(func.lower(User.username) == username.lower())
    return await session.scalar(query.order_by(User.last_active_at.desc()).limit(1))


async def add_ticket(session: AsyncSession, ticket: Ticket) -> Ticket:
    session.add(ticket)
    await session.flush()
    return ticket


async def get_ticket(session: AsyncSession, ticket_id: int | None) -> Ticket | None:
    return None if ticket_id is None else await session.get(Ticket, ticket_id)


async def last_ticket(session: AsyncSession, user_id: int) -> Ticket | None:
    query = select(Ticket).where(Ticket.user_id == user_id).order_by(Ticket.id.desc()).limit(1)
    return await session.scalar(query)


async def list_new_tickets(session: AsyncSession, *, offset: int, limit: int) -> list[Ticket]:
    """Tickets nobody has answered yet, the oldest first."""
    query = (
        select(Ticket)
        .where(Ticket.status == TICKET_NEW)
        .order_by(Ticket.created_at, Ticket.id)
        .offset(offset)
        .limit(limit)
    )
    return list(await session.scalars(query))


async def count_new_tickets(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == TICKET_NEW)) or 0


@dataclass(frozen=True, slots=True)
class TicketCounts:
    total: int
    people: int  # how many clients wrote them
    waiting: int  # nobody has replied yet
    done: int
    not_done: int

    @property
    def replied(self) -> int:
        return self.total - self.waiting


async def ticket_counts(session: AsyncSession, start: datetime, end: datetime) -> TicketCounts:
    """Tickets written in [start, end), all the counts in one query."""
    row = (
        await session.execute(
            select(
                func.count(),
                func.count(distinct(Ticket.user_id)),
                func.count().filter(Ticket.status == TICKET_NEW),
                func.count().filter(Ticket.status == TICKET_DONE),
                func.count().filter(Ticket.status == TICKET_NOT_DONE),
            ).where(Ticket.created_at >= start, Ticket.created_at < end)
        )
    ).one()
    return TicketCounts(*row)


@dataclass(frozen=True, slots=True)
class UserCounts:
    total: int
    today: int  # active since the start of the day
    week: int  # in the last 7 days
    month: int  # in the last 30 days
    joined_today: int


async def user_counts(session: AsyncSession, day_start: datetime, now: datetime) -> UserCounts:
    """All the counts in one query: count(*) FILTER (WHERE …) for each."""
    row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(User.last_active_at >= day_start),
                func.count().filter(User.last_active_at >= now - timedelta(days=7)),
                func.count().filter(User.last_active_at >= now - timedelta(days=30)),
                func.count().filter(User.created_at >= day_start),
            ).select_from(User)
        )
    ).one()
    return UserCounts(*row)


async def recent_users(session: AsyncSession, *, offset: int, limit: int) -> list[User]:
    """Users by their last activity, the latest first."""
    query = select(User).order_by(User.last_active_at.desc(), User.id).offset(offset).limit(limit)
    return list(await session.scalars(query))


async def video_ids_without_backup(session: AsyncSession) -> list[int]:
    result = await session.scalars(select(Video.id).where(Video.backup_message_id.is_(None)).order_by(Video.id))
    return list(result)
