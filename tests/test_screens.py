from types import SimpleNamespace

from bot.services.tree import CatalogTree, CategoryNode
from bot.ui.admin import admin_category, admin_panel, confirm_delete_category, section_codes
from bot.ui.callbacks import (
    AdminCategoryCb,
    AdminDeleteCategoryCb,
    AdminFlowCb,
    AdminNewCategoryCb,
    AdminPickCb,
    CategoryCb,
    MenuCb,
    VideoCb,
)
from bot.ui.client import category_screen, main_menu, video_screen
from bot.ui.screen import Screen


def texts(screen: Screen) -> list[list[str]]:
    assert screen.markup is not None
    return [[button.text for button in row] for row in screen.markup.inline_keyboard]


def datas(screen: Screen) -> list[list[str]]:
    assert screen.markup is not None
    return [[button.callback_data for button in row] for row in screen.markup.inline_keyboard]


def video(video_id: int, category_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=video_id,
        category_id=category_id,
        title=f"Video {video_id}",
        description=None,
        file_id=f"file-{video_id}",
        file_unique_id=str(video_id),
        media_type="video",
    )


def flat_tree(categories: int, videos_each: int = 1) -> CatalogTree:
    ids = range(1, categories + 1)
    nodes = [CategoryNode(id=i, parent_id=None, title=f"Bo‘lim {i}", depth=1, position=i) for i in ids]
    return CatalogTree(nodes, {i: videos_each for i in ids})


def test_main_menu_lists_categories_with_counts() -> None:
    screen = main_menu(flat_tree(2, videos_each=5))
    assert screen.text == "Xush kelibsiz! Kerakli bo‘limni tanlang."
    assert texts(screen) == [["Bo‘lim 1", "Bo‘lim 2"]]


def test_main_menu_is_paginated_by_eight_in_two_columns() -> None:
    tree = flat_tree(9)
    first = main_menu(tree, page=0)
    assert texts(first) == [
        ["Bo‘lim 1", "Bo‘lim 2"],
        ["Bo‘lim 3", "Bo‘lim 4"],
        ["Bo‘lim 5", "Bo‘lim 6"],
        ["Bo‘lim 7", "Bo‘lim 8"],
        ["1/2", "▶️"],
    ]
    last = main_menu(tree, page=1)
    assert texts(last) == [["Bo‘lim 9"], ["◀️", "2/2"]]


def test_sections_go_two_per_row_even_when_few() -> None:
    assert texts(main_menu(flat_tree(1))) == [["Bo‘lim 1"]]
    assert texts(main_menu(flat_tree(3))) == [["Bo‘lim 1", "Bo‘lim 2"], ["Bo‘lim 3"]]


def test_every_button_is_blue() -> None:
    screens = [main_menu(flat_tree(9)), admin_category(flat_tree(2), 1, [], 0, max_depth=3)]
    styles = [button.style for screen in screens for row in screen.markup.inline_keyboard for button in row]
    assert styles
    assert all(style == "primary" for style in styles)


def test_admin_panel_has_four_buttons_in_two_rows() -> None:
    assert texts(admin_panel()) == [
        ["📂 Bo‘limlar", "➕ Video qo‘shish"],
        ["✏️ Salomlashuv va matnlar", "📢 Kanal shabloni"],
    ]


def test_section_codes_are_paginated_in_list_order() -> None:
    nodes = [CategoryNode(1, None, "Kassa", 1, 1), CategoryNode(2, 1, "Sozlash", 2, 1)]
    nodes += [CategoryNode(i, None, f"Bo‘lim {i}", 1, i) for i in range(3, 18)]
    tree = CatalogTree(nodes, {})
    first = section_codes(tree, 0)
    assert "<code>#1</code> Kassa 📂\n<code>#2</code> Kassa › Sozlash\n<code>#3</code> Bo‘lim 3" in first.text
    assert texts(first) == [["1/2", "▶️"], ["⬅️ Orqaga"]]
    assert section_codes(tree, 1).text.endswith("<code>#16</code> Bo‘lim 16\n<code>#17</code> Bo‘lim 17")
    assert section_codes(CatalogTree([], {}), 0).text.endswith("Hali birorta bo‘lim yo‘q.")


def test_main_menu_without_videos() -> None:
    screen = main_menu(CatalogTree([CategoryNode(1, None, "Bo‘sh", 1, 1)], {}))
    assert screen.text == "Xush kelibsiz! Hozircha videolar yo‘q — tez orada qo‘shiladi."
    assert screen.markup is None


def test_video_list_numbers_continue_across_pages() -> None:
    tree = CatalogTree([CategoryNode(1, None, "Kassa", 1, 1)], {1: 10})
    videos = [video(i) for i in range(1, 11)]
    first = category_screen(tree, tree.get(1), videos, page=0)
    assert first.text == "<b>Kassa</b>\n\n" + "\n".join(f"{i}. Video {i}" for i in range(1, 9))
    assert texts(first) == [["1", "2", "3", "4"], ["5", "6", "7", "8"], ["1/2", "▶️"], ["⬅️ Orqaga"]]
    assert datas(first)[0][0] == VideoCb(id=1).pack()

    screen = category_screen(tree, tree.get(1), videos, page=1)
    assert screen.text == "<b>Kassa</b>\n\n9. Video 9\n10. Video 10"
    assert texts(screen) == [["9", "10"], ["◀️", "2/2"], ["⬅️ Orqaga"]]


def test_video_titles_in_the_list_are_escaped() -> None:
    tree = CatalogTree([CategoryNode(1, None, "Kassa", 1, 1)], {1: 1})
    item = video(1)
    item.title = "A <b> & C"
    screen = category_screen(tree, tree.get(1), [item])
    assert screen.text.endswith("\n\n1. A &lt;b&gt; &amp; C")


def test_nested_category_has_back_and_home() -> None:
    nodes = [CategoryNode(1, None, "Kassa", 1, 1), CategoryNode(2, 1, "Sozlash", 2, 1)]
    tree = CatalogTree(nodes, {2: 1})
    screen = category_screen(tree, tree.get(2), [video(5, category_id=2)])
    assert screen.text == "<b>Kassa › Sozlash</b>\n\n1. Video 5"
    assert datas(screen)[-1] == [CategoryCb(id=1).pack(), MenuCb().pack()]


def test_video_screen_hides_previous_on_first_and_next_on_last() -> None:
    tree = CatalogTree([CategoryNode(1, None, "Kassa", 1, 1)], {1: 10})
    videos = [video(i) for i in range(1, 11)]

    first = video_screen(tree, videos[0], videos)
    assert texts(first)[0] == ["Keyingi ▶️"]
    assert first.media is not None
    assert first.media.caption == "<b>Video 1</b>"

    last = video_screen(tree, videos[9], videos)
    assert texts(last)[0] == ["◀️ Oldingi"]
    # Back opens the second page, where video 10 is listed.
    assert datas(last)[1][0] == CategoryCb(id=1, page=1).pack()


def test_video_caption_escapes_html() -> None:
    tree = CatalogTree([CategoryNode(1, None, "A<B", 1, 1)], {1: 1})
    item = video(1)
    item.title = "Kassa & <printer>"
    item.description = "1 < 2"
    screen = video_screen(tree, item, [item])
    assert screen.media.caption == "<b>Kassa &amp; &lt;printer&gt;</b>\n1 &lt; 2"


def test_admin_sees_empty_categories_and_add_buttons() -> None:
    nodes = [CategoryNode(1, None, "Kassa", 1, 1), CategoryNode(2, None, "Yangi", 1, 2)]
    tree = CatalogTree(nodes, {1: 3})
    root = admin_category(tree, None, [], 0, max_depth=3)
    assert root.text == "<b>📂 Bo‘limlar</b>"
    assert texts(root) == [["Kassa", "Yangi · bo‘sh"], ["➕ Bo‘lim", "⬅️ Admin panel"]]

    empty = admin_category(tree, 2, [], 0, max_depth=3)
    assert texts(empty) == [["➕ Ichki bo‘lim", "➕ Video"], ["✏️ Bo‘lim matni", "🗑 O‘chirish"], ["⬅️ Orqaga"]]
    assert datas(empty)[0] == [AdminNewCategoryCb(parent=2).pack(), "av:2"]
    assert datas(empty)[-1] == [AdminCategoryCb(id=0).pack()]


def test_admin_cannot_nest_deeper_than_the_limit() -> None:
    nodes = [CategoryNode(1, None, "Bir", 1, 1), CategoryNode(2, 1, "Ikki", 2, 1)]
    tree = CatalogTree(nodes, {})
    screen = admin_category(tree, 2, [], 0, max_depth=2)
    assert texts(screen)[0] == ["➕ Video", "✏️ Bo‘lim matni"]


def test_delete_confirmation_names_what_is_inside() -> None:
    nodes = [
        CategoryNode(1, None, "Kassa", 1, 1),
        CategoryNode(2, 1, "Sozlash", 2, 1),
        CategoryNode(3, 1, "Printer", 2, 2),
    ]
    tree = CatalogTree(nodes, {2: 24})
    screen = confirm_delete_category(tree, tree.get(1))
    assert screen.text == "«Kassa» ichida 2 ta bo‘lim va 24 ta video bor. Hammasi bilan birga o‘chirilsinmi?"
    assert datas(screen) == [[AdminDeleteCategoryCb(id=1, confirm=True).pack(), AdminCategoryCb(id=1).pack()]]

    empty = confirm_delete_category(tree, tree.get(3))
    assert empty.text == "«Printer» bo‘limi o‘chirilsinmi?"


def test_button_payloads_fit_telegram_limit() -> None:
    big = 2**31 - 1
    payloads = [
        MenuCb(page=big),
        CategoryCb(id=big, page=big),
        VideoCb(id=big),
        AdminCategoryCb(id=big, page=-1),
        AdminDeleteCategoryCb(id=big, confirm=True),
        AdminPickCb(id=big, page=big),
        AdminFlowCb(action="caption"),
    ]
    for payload in payloads:
        assert len(payload.pack().encode()) <= 64
