from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.services.tree import Kind
from bot.ui.admin import admin_category
from bot.ui.screen import Screen


async def render_category(session: AsyncSession, settings: Settings, category_id: int | None, page: int = 0) -> Screen:
    """The admin screen of a category; None or a deleted id gives the top level."""
    tree = await repo.load_tree(session)
    if tree.get(category_id) is None:
        category_id = None
    videos = []
    intro = None
    if category_id is not None:
        if tree.kind(category_id) is Kind.VIDEOS:
            videos = await repo.list_videos(session, category_id)
        category = await repo.get_category(session, category_id)
        intro = category.intro if category is not None else None
    return admin_category(tree, category_id, videos, page, settings.max_depth, intro=intro)
