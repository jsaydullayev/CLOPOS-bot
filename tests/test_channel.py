"""Videos added by posting them in the private video channel."""

import pytest
from aiogram.methods import EditMessageText, SendMessage, SendVideo, SetMessageReaction
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import Category, Video
from bot.services.catalog import CatalogError, add_video, create_category
from bot.services.channel import PostMedia, import_post, parse_caption, post_caption
from bot.ui.callbacks import CHANNEL_GUIDE, SectionCodesCb
from tests.conftest import ADMIN_ID, CHANNEL_ID, Harness, file_id_of


def media(unique_id: str) -> PostMedia:
    return PostMedia(file_id=file_id_of(unique_id), file_unique_id=unique_id, media_type="video")


async def import_(session: AsyncSession, message_id: int, caption: str, unique_id: str, max_depth: int = 3):  # type: ignore[no-untyped-def]
    return await import_post(
        session, message_id=message_id, caption=caption, media=media(unique_id), max_depth=max_depth
    )


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model))


# ── caption format ─────────────────────────────────────────────


def test_caption_with_path_title_and_description() -> None:
    parsed = parse_caption("Бек офис › Финансы\nОтчёты\nOylik hisobot\nikkinchi qator")
    assert parsed.path == ("Бек офис", "Финансы")
    assert parsed.title == "Отчёты"
    assert parsed.description == "Oylik hisobot\nikkinchi qator"


def test_caption_accepts_greater_than_and_extra_blank_lines() -> None:
    parsed = parse_caption("\n  Бек офис>Финансы  \n\n  🎬 Отчёты \n")
    assert parsed.path == ("Бек офис", "Финансы")
    assert parsed.title == "Отчёты"
    assert parsed.description is None


@pytest.mark.parametrize(
    ("caption", "key"),
    [
        (None, "channel_no_caption"),
        ("   ", "channel_no_caption"),
        (" › ", "channel_no_caption"),
        ("Финансы", "channel_no_title"),
        ("Финансы\n\n", "channel_no_title"),
        ("Ф › Отчёты\nNom", "channel_bad_section"),
        ("Финансы\nX", "channel_bad_title"),
        ("Финансы\nOtchet\n" + "x" * 301, "error_description_length"),
    ],
)
def test_bad_captions(caption: str | None, key: str) -> None:
    with pytest.raises(CatalogError) as error:
        parse_caption(caption)
    assert error.value.key == key


def test_caption_with_a_code_and_new_sections() -> None:
    parsed = parse_caption("#12 › +Ombor › Qoldiq\nVideo")
    assert (parsed.code, parsed.path, parsed.new_from) == (12, ("Ombor", "Qoldiq"), 0)
    assert parse_caption("#7\nVideo").path == ()
    assert parse_caption("Kassa › + Smena\nVideo").new_from == 1
    assert parse_caption("Kassa › Smena\nVideo").new_from is None


def test_the_bot_writes_captions_it_can_read_back() -> None:
    caption = post_caption(["Бек офис", "Финансы"], "Отчёты", "Tavsif")
    assert caption == "Бек офис › Финансы\nОтчёты\nTavsif"
    assert parse_caption(caption) == parse_caption("Бек офис > Финансы\nОтчёты\nTavsif")


# ── adding and updating ────────────────────────────────────────


async def test_post_creates_sections_marked_with_a_plus_and_the_video(session: AsyncSession) -> None:
    result = await import_(session, 10, "+Бек офис › Финансы\nОтчёты", "a")
    assert result.created
    assert result.new_sections == ["Бек офис", "Бек офис › Финансы"]
    assert (result.video.title, result.video.backup_message_id) == ("Отчёты", 10)

    # The same sections are found again, whatever the letter case.
    second = await import_(session, 11, "бек офис › ФИНАНСЫ\nКасса", "b")
    assert second.new_sections == []
    assert second.video.category_id == result.video.category_id
    assert second.video.position > result.video.position
    assert await count(session, Category) == 2


async def test_rejected_post_leaves_nothing_behind(session: AsyncSession) -> None:
    await import_(session, 10, "+Финансы\nОтчёты", "a")  # Финансы now holds videos
    await session.commit()
    with pytest.raises(CatalogError) as error:
        await import_(session, 11, "Финансы › Касса › Смена\nОткрытие", "b")
    assert error.value.key == "channel_section_has_videos"
    assert error.value.params == {"title": "Финансы"}
    # Checked before any write: nothing was added even without a rollback.
    assert await count(session, Category) == 1
    assert await count(session, Video) == 1


async def test_video_cannot_go_into_a_section_with_sections(session: AsyncSession) -> None:
    await import_(session, 10, "+Бек офис › Финансы\nОтчёты", "a")
    with pytest.raises(CatalogError) as error:
        await import_(session, 11, "Бек офис\nКасса", "b")
    assert (error.value.key, error.value.params) == ("channel_section_has_children", {"title": "Бек офис"})


async def test_depth_limit_and_duplicates(session: AsyncSession) -> None:
    with pytest.raises(CatalogError) as error:
        await import_(session, 10, "A1 › B1 › C1 › D1\nVideo", "a", max_depth=3)
    assert error.value.key == "error_max_depth"

    await import_(session, 11, "+Финансы\nОтчёты", "same")
    with pytest.raises(CatalogError) as error:
        await import_(session, 12, "+Касса\nОтчёты 2", "same")
    assert error.value.key == "channel_duplicate"
    assert error.value.params == {"title": "Отчёты", "path": "Финансы"}


async def test_edited_post_updates_and_moves_the_video(session: AsyncSession) -> None:
    first = await import_(session, 10, "+Финансы\nОтчёты", "a")
    await import_(session, 11, "+Касса\nСмена", "b")
    video_id = first.video.id

    edited = await import_(session, 10, "Касса\nОтчёты за день\nTavsif", "a")
    assert not edited.created
    video = await repo.get_video(session, video_id)
    assert (video.title, video.description) == ("Отчёты за день", "Tavsif")
    kassa = await session.scalar(select(Category).where(Category.title == "Касса"))
    assert video.category_id == kassa.id
    assert [v.title for v in await repo.list_videos(session, kassa.id)] == ["Смена", "Отчёты за день"]
    assert await count(session, Video) == 2


async def test_section_names_cannot_contain_separators(session: AsyncSession) -> None:
    with pytest.raises(CatalogError) as error:
        await create_category(session, parent_id=None, raw_title="Kirim > chiqim", admin_id=1, max_depth=3)
    assert error.value.key == "error_name_separator"


# ── finding the right section ──────────────────────────────────


async def test_unknown_section_is_not_created_without_a_plus(session: AsyncSession) -> None:
    await import_(session, 10, "+Videodarsliklar › Finans\nHisobot", "a")

    with pytest.raises(CatalogError) as error:
        await import_(session, 11, "Videodarsliklar › Ombor\nQoldiq", "b")
    assert (error.value.key, error.value.params) == ("channel_section_not_found", {"title": "Ombor"})

    # Too far for a typo, but close enough to be suggested.
    with pytest.raises(CatalogError) as error:
        await import_(session, 12, "Videodarsliklar › Finanslar\nQoldiq", "b")
    assert (error.value.key, error.value.params) == (
        "channel_section_not_found_similar",
        {"title": "Finanslar", "options": "«Finans»"},
    )
    assert await count(session, Category) == 2


async def test_small_differences_and_typos_find_the_existing_section(session: AsyncSession) -> None:
    first = await import_(session, 10, "+O‘quv videolar › Finans\nHisobot", "a")
    finans = first.video.category_id

    # Case, spaces, apostrophes and Cyrillic look-alike letters (а, о) are not even typos.
    same = await import_(session, 11, "oʻquv  VIDEOLAR › Finаns\nKassa", "b")
    assert (same.video.category_id, same.corrected) == (finans, [])

    # A missing, extra or swapped letter is a typo; the admins are told what it was taken for.
    for message_id, name in [(12, "Finas"), (13, "Finanss"), (14, "Fianns")]:
        result = await import_(session, message_id, f"O'quv videolar › {name}\nVideo {name}", name)
        assert (result.video.category_id, result.corrected) == (finans, [(name, "Finans")])
    assert await count(session, Category) == 2


async def test_numbers_and_short_names_must_match_exactly(session: AsyncSession) -> None:
    await import_(session, 10, "+Kurs › 1-dars\nKirish", "a")
    with pytest.raises(CatalogError) as error:
        await import_(session, 11, "Kurs › 2-dars\nDavomi", "b")
    assert (error.value.key, error.value.params["options"]) == ("channel_section_not_found_similar", "«1-dars»")

    result = await import_(session, 12, "Kurs › +2-dars\nDavomi", "b")
    assert result.new_sections == ["Kurs › 2-dars"]

    with pytest.raises(CatalogError) as error:
        await import_(session, 13, "Kurz › 1-dars\nVideo", "c")  # «Kurs» has 4 letters: no typo allowed
    assert error.value.key == "channel_section_not_found_similar"


async def test_a_typo_equally_close_to_two_sections_is_not_guessed(session: AsyncSession) -> None:
    await import_(session, 10, "+Ombor\nA video", "a")
    await import_(session, 11, "+Ombar\nB video", "b")  # with a +, a near name is a new section
    with pytest.raises(CatalogError) as error:
        await import_(session, 12, "Ombir\nC video", "c")
    assert (error.value.key, error.value.params) == (
        "channel_section_ambiguous",
        {"title": "Ombir", "options": "«Ombor», «Ombar»"},
    )


async def test_a_code_puts_the_video_into_that_exact_section(session: AsyncSession) -> None:
    first = await import_(session, 10, "+Videodarsliklar › Finans\nHisobot", "a")
    finans = await session.get(Category, first.video.category_id)

    by_code = await import_(session, 11, f"#{finans.id}\nKassa", "b")
    assert by_code.video.category_id == finans.id

    below = await import_(session, 12, f"#{finans.parent_id} › +Ombor\nQoldiq", "c")
    assert below.new_sections == ["Videodarsliklar › Ombor"]

    with pytest.raises(CatalogError) as error:
        await import_(session, 13, "#999\nX video", "d")
    assert (error.value.key, error.value.params) == ("channel_unknown_code", {"code": 999})

    with pytest.raises(CatalogError) as error:
        await import_(session, 14, f"#{finans.parent_id}\nY video", "e")
    assert error.value.key == "channel_section_has_children"


# ── through the bot ────────────────────────────────────────────


def reactions(harness: Harness) -> list[tuple[int, str]]:
    return [
        (call.message_id, call.reaction[0].emoji) for call in harness.telegram.of(SetMessageReaction)
    ]


async def test_channel_posts_through_the_bot(harness: Harness) -> None:
    telegram = harness.telegram

    await harness.post_in_channel(100, unique_id="a", caption="+Бек офис › Финансы\nОтчёты")
    assert reactions(harness) == [(100, "👍")]
    notices = [call.text for call in telegram.of(SendMessage)]
    assert notices == ["ℹ️ Kanal posti bo‘yicha yangi bo‘lim yaratildi:\nБек офис\nБек офис › Финансы\n"
                       "Post: https://t.me/c/1000/100\n\n"
                       "Nom xato yozilgan bo‘lsa, postni tahrirlang va ortiqcha bo‘limni admin paneldan o‘chiring."]
    assert telegram.of(SendMessage)[0].chat_id == ADMIN_ID

    # A caption without a title is rejected and the admins learn why.
    telegram.reset()
    await harness.post_in_channel(101, unique_id="b", caption="Бек офис › Финансы")
    assert reactions(harness) == [(101, "👎")]
    notice = telegram.of(SendMessage)[0].text
    assert notice.startswith("⚠️ Video nomi yo‘q — uni captionning 2-qatoriga yozing.\nPost: https://t.me/c/1000/101")

    # Fixing the caption in the channel adds the video.
    telegram.reset()
    await harness.post_in_channel(101, unique_id="b", caption="Бек офис › Финансы\nКасса", edited=True)
    assert reactions(harness) == [(101, "👍")]
    assert telegram.of(SendMessage) == []

    # The client sees both videos, in the order they were posted.
    await harness.send_text(2, "/start")
    async with harness.session_factory() as session:
        titles = [video.title for video in await session.scalars(select(Video).order_by(Video.position))]
    assert titles == ["Отчёты", "Касса"]


async def test_admins_learn_which_section_a_typo_was_taken_for(harness: Harness) -> None:
    await harness.post_in_channel(100, unique_id="a", caption="+Videodarsliklar › Finans\nHisobot")
    harness.telegram.reset()

    await harness.post_in_channel(101, unique_id="b", caption="Videodarsliklar › Finas\nKassa")
    assert reactions(harness) == [(101, "👍")]
    assert [call.text for call in harness.telegram.of(SendMessage)] == [
        "ℹ️ Kanal postidagi bo‘lim nomi tuzatildi:\n«Finas» → «Finans»\nPost: https://t.me/c/1000/101\n\n"
        "Noto‘g‘ri tushunilgan bo‘lsa, captionni tahrirlang."
    ]

    # An unknown name without a + is turned down with the nearest names.
    harness.telegram.reset()
    await harness.post_in_channel(102, unique_id="c", caption="Videodarsliklar › Finanslar\nOmbor")
    assert reactions(harness) == [(102, "👎")]
    assert harness.telegram.of(SendMessage)[0].text.startswith(
        "⚠️ «Finanslar» bo‘limi topilmadi. Shunga o‘xshash: «Finans».\n"
        "Yangi bo‘lim ochish uchun nomi oldiga + qo‘ying: +Finanslar\nPost: https://t.me/c/1000/102"
    )


async def test_admin_panel_has_the_channel_guide_and_section_codes(harness: Harness) -> None:
    await harness.post_in_channel(100, unique_id="a", caption="+Kassa › Smena\nOchish")
    async with harness.session_factory() as session:
        kassa = await session.scalar(select(Category).where(Category.title == "Kassa"))
        smena = await session.scalar(select(Category).where(Category.title == "Smena"))

    await harness.send_text(ADMIN_ID, "/admin")
    await harness.press(ADMIN_ID, CHANNEL_GUIDE)
    guide = harness.telegram.of(EditMessageText)[-1]
    assert guide.text.startswith("<b>📢 Kanalga video qo‘yish</b>")
    assert [button.text for row in guide.reply_markup.inline_keyboard for button in row] == [
        "📋 Bo‘lim kodlari",
        "⬅️ Admin panel",
    ]

    await harness.press(ADMIN_ID, SectionCodesCb())
    codes = harness.telegram.of(EditMessageText)[-1].text
    assert codes.endswith(f"<code>#{kassa.id}</code> Kassa 📂\n<code>#{smena.id}</code> Kassa › Smena")


async def test_other_posts_are_ignored_or_explained(harness: Harness) -> None:
    telegram = harness.telegram

    await harness.post_in_channel(200, text="Bugungi reja")  # plain text post
    await harness.post_in_channel(201, unique_id="x", caption="Финансы\nОтчёты", chat_id=-1009999)  # other channel
    assert telegram.calls == []

    await harness.post_in_channel(202, unique_id="y", caption="Финансы\nОтчёты", document=True)
    assert reactions(harness) == [(202, "👎")]
    assert telegram.of(SendMessage)[0].text.startswith("⚠️ Video fayl (hujjat) sifatida tashlangan")

    async with harness.session_factory() as session:
        assert await count(session, Video) == 0


async def test_admin_panel_videos_are_copied_in_the_same_format(harness: Harness) -> None:
    async with harness.session_factory() as session:
        section = await create_category(session, parent_id=None, raw_title="Касса", admin_id=1, max_depth=3)
        video = await add_video(
            session,
            category_id=section.id,
            title="Смена <1>",
            description="Tavsif",
            file_id=file_id_of("p"),
            file_unique_id="p",
            media_type="video",
            admin_id=1,
        )
        await session.commit()

    archive = harness.dispatcher["archive"]
    assert await archive.archive(video.id)
    copy = harness.telegram.of(SendVideo)[-1]
    assert (copy.chat_id, copy.caption, copy.parse_mode) == (CHANNEL_ID, "Касса\nСмена <1>\nTavsif", None)

    # Editing that copy's caption in the channel edits the video.
    async with harness.session_factory() as session:
        post_id = (await session.get(Video, video.id)).backup_message_id
    await harness.post_in_channel(post_id, unique_id="p", caption="Касса\nСмена", edited=True)
    async with harness.session_factory() as session:
        assert (await session.get(Video, video.id)).title == "Смена"
