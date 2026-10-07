from bot.services.tree import CatalogTree, CategoryNode, Kind


def build_tree() -> CatalogTree:
    # Kassa (1) › Sozlash (2) › Printer (3) with 2 videos; Kassa › Bo‘sh (4)
    # Ombor (5) with 1 video; Arxiv (6) empty
    nodes = [
        CategoryNode(id=1, parent_id=None, title="Kassa", depth=1, position=1),
        CategoryNode(id=2, parent_id=1, title="Sozlash", depth=2, position=1),
        CategoryNode(id=3, parent_id=2, title="Printer", depth=3, position=1),
        CategoryNode(id=4, parent_id=1, title="Bo‘sh", depth=2, position=2),
        CategoryNode(id=5, parent_id=None, title="Ombor", depth=1, position=2),
        CategoryNode(id=6, parent_id=None, title="Arxiv", depth=1, position=3),
    ]
    return CatalogTree(nodes, {3: 2, 5: 1})


def test_totals_count_videos_on_every_level() -> None:
    tree = build_tree()
    assert tree.total(1) == 2
    assert tree.total(2) == 2
    assert tree.total(4) == 0
    assert tree.video_count == 3
    assert tree.category_count == 6


def test_empty_categories_are_hidden_from_clients() -> None:
    tree = build_tree()
    assert [node.title for node in tree.visible_children(None)] == ["Kassa", "Ombor"]
    assert [node.title for node in tree.visible_children(1)] == ["Sozlash"]
    assert [node.title for node in tree.children(None)] == ["Kassa", "Ombor", "Arxiv"]


def test_kind_follows_the_either_categories_or_videos_rule() -> None:
    tree = build_tree()
    assert tree.kind(None) is Kind.CATEGORIES
    assert tree.kind(1) is Kind.CATEGORIES
    assert tree.kind(3) is Kind.VIDEOS
    assert tree.kind(6) is Kind.EMPTY


def test_path_and_subtree_stats() -> None:
    tree = build_tree()
    assert tree.path(3) == ["Kassa", "Sozlash", "Printer"]
    assert tree.subtree_stats(1) == (3, 2)
    assert tree.subtree_stats(6) == (0, 0)


def test_what_can_be_added_where() -> None:
    tree = build_tree()
    assert tree.can_add_child(None, max_depth=3)
    assert tree.can_add_child(1, max_depth=3)
    assert not tree.can_add_child(3, max_depth=5)  # holds videos
    assert not tree.can_add_child(3, max_depth=3)  # at the depth limit
    assert tree.can_add_child(6, max_depth=3)
    assert tree.can_add_video(3)
    assert tree.can_add_video(6)
    assert not tree.can_add_video(1)  # holds categories
    assert not tree.can_add_video(99)
