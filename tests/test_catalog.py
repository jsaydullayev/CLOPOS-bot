import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import Category, Video
from bot.services.catalog import (
    CatalogError,
    add_video,
    create_category,
    remove_category,
    remove_video,
    validate_description,
    validate_name,
)


async def new_category(session: AsyncSession, title: str, parent_id: int | None = None, max_depth: int = 3) -> Category:
    return await create_category(session, parent_id=parent_id, raw_title=title, admin_id=1, max_depth=max_depth)


async def new_video(session: AsyncSession, category_id: int, title: str, unique_id: str | None = None) -> Video:
    unique_id = unique_id or title
    return await add_video(
        session,
        category_id=category_id,
        title=title,
        description=None,
        file_id=f"file-{unique_id}",
        file_unique_id=unique_id,
        media_type="video",
        admin_id=1,
    )


async def test_category_names_are_cleaned_and_checked(session: AsyncSession) -> None:
    category = await new_category(session, "  🧾 Kassa  ")
    assert category.title == "Kassa"
    assert category.depth == 1

    with pytest.raises(CatalogError) as error:
        await new_category(session, "K")
    assert error.value.key == "error_name_length"

    with pytest.raises(CatalogError) as error:
        await new_category(session, "k" * 41)
    assert error.value.key == "error_name_length"

    with pytest.raises(CatalogError) as error:
        await new_category(session, "KASSA")
    assert error.value.key == "error_category_exists"

    # Names that would be the same section in a channel caption are the same name.
    await new_category(session, "O‘quv kurslar")
    with pytest.raises(CatalogError) as error:
        await new_category(session, "Oʻquv-kurslar")
    assert (error.value.key, error.value.params) == ("error_category_exists", {"title": "O‘quv kurslar"})


async def test_same_name_is_allowed_in_different_parents(session: AsyncSession) -> None:
    kassa = await new_category(session, "Kassa")
    ombor = await new_category(session, "Ombor")
    await new_category(session, "Sozlash", kassa.id)
    sub = await new_category(session, "Sozlash", ombor.id)
    assert sub.depth == 2


async def test_depth_is_limited(session: AsyncSession) -> None:
    level1 = await new_category(session, "Bir")
    level2 = await new_category(session, "Ikki", level1.id)
    level3 = await new_category(session, "Uch", level2.id)
    assert level3.depth == 3
    with pytest.raises(CatalogError) as error:
        await new_category(session, "To‘rt", level3.id)
    assert error.value.key == "error_max_depth"


async def test_a_category_holds_either_categories_or_videos(session: AsyncSession) -> None:
    with_videos = await new_category(session, "Videolar")
    await new_video(session, with_videos.id, "Birinchi")
    with pytest.raises(CatalogError) as error:
        await new_category(session, "Ichki", with_videos.id)
    assert error.value.key == "error_category_has_videos"

    with_children = await new_category(session, "Bo‘limlar")
    await new_category(session, "Ichki", with_children.id)
    with pytest.raises(CatalogError) as error:
        await new_video(session, with_children.id, "Video")
    assert error.value.key == "error_category_has_children"


async def test_new_videos_go_to_the_end(session: AsyncSession) -> None:
    category = await new_category(session, "Kassa")
    first = await new_video(session, category.id, "Birinchi")
    second = await new_video(session, category.id, "Ikkinchi")
    assert second.position > first.position
    assert [video.title for video in await repo.list_videos(session, category.id)] == ["Birinchi", "Ikkinchi"]


async def test_deleting_a_category_removes_everything_inside(session: AsyncSession) -> None:
    kassa = await new_category(session, "Kassa")
    sozlash = await new_category(session, "Sozlash", kassa.id)
    printer = await new_category(session, "Printer", sozlash.id)
    await new_video(session, printer.id, "Ulash")
    ombor = await new_category(session, "Ombor")
    await new_video(session, ombor.id, "Qoldiq")
    await session.commit()

    deleted = await remove_category(session, kassa.id)
    await session.commit()

    assert deleted is not None and deleted.title == "Kassa"
    assert await session.scalar(select(func.count(Category.id))) == 1
    assert [video.title for video in await session.scalars(select(Video))] == ["Qoldiq"]
    assert await remove_category(session, kassa.id) is None


async def test_removing_a_video_returns_its_category(session: AsyncSession) -> None:
    category = await new_category(session, "Kassa")
    video = await new_video(session, category.id, "Birinchi")
    await session.commit()
    assert await remove_video(session, video.id) == category.id
    assert await remove_video(session, video.id) is None


async def test_duplicates_are_found_by_file_unique_id(session: AsyncSession) -> None:
    category = await new_category(session, "Kassa")
    await new_video(session, category.id, "Birinchi", unique_id="same")
    found = await repo.find_video_by_file(session, "same")
    assert found is not None and found.title == "Birinchi"
    assert await repo.find_video_by_file(session, "other") is None


def test_title_and_description_rules() -> None:
    assert validate_name("🎬 Kassani ochish", 60) == "Kassani ochish"
    with pytest.raises(CatalogError) as error:
        validate_name("x" * 61, 60)
    assert error.value.params == {"min": 2, "max": 60}
    assert validate_description("   ") is None
    assert validate_description(" Qisqa ") == "Qisqa"
    with pytest.raises(CatalogError):
        validate_description("x" * 301)
