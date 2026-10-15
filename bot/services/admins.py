"""Who is an admin: the owners in ADMIN_IDS (.env) and the admins added in the admin panel.

The owners cannot be removed from the panel, so the bot always keeps someone who
can open it. Asked on every admin message and button, the set lives in memory:
loaded from the database at startup and changed together with it.
"""

from collections.abc import Iterable, Iterator

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo


class Admins:
    def __init__(self, owners: Iterable[int]) -> None:
        self.owners = frozenset(owners)
        self._added: set[int] = set()

    def __contains__(self, user_id: object) -> bool:
        return user_id in self.owners or user_id in self._added

    def __iter__(self) -> Iterator[int]:
        return iter(sorted(self.owners | self._added))

    def is_owner(self, user_id: int) -> bool:
        return user_id in self.owners

    async def load(self, session: AsyncSession) -> None:
        self._added = {admin.user_id for admin in await repo.list_admins(session)}

    async def add(self, session: AsyncSession, user_id: int, *, name: str | None, added_by: int) -> None:
        """Make the user an admin; the caller has checked they are not one yet."""
        await repo.add_admin(session, user_id, name=name, added_by=added_by)
        await session.commit()
        self._added.add(user_id)

    async def remove(self, session: AsyncSession, user_id: int) -> bool:
        """Take the admin rights away. Owners keep them: they are set in .env."""
        if self.is_owner(user_id):
            return False
        removed = await repo.delete_admin(session, user_id)
        await session.commit()
        self._added.discard(user_id)
        return removed
