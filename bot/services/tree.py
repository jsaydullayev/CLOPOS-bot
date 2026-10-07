"""In-memory view of the category tree with video counts.

The whole tree is small (hundreds of categories at most), so it is loaded
with two queries per request and all tree rules are answered from memory.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class CategoryNode:
    id: int
    parent_id: int | None
    title: str
    depth: int
    position: int


class Kind(Enum):
    """A category holds either child categories or videos, never both."""

    CATEGORIES = "categories"
    VIDEOS = "videos"
    EMPTY = "empty"


class CatalogTree:
    def __init__(self, nodes: Iterable[CategoryNode], video_counts: Mapping[int, int]) -> None:
        self._nodes = {node.id: node for node in nodes}
        grouped: dict[int | None, list[CategoryNode]] = defaultdict(list)
        for node in self._nodes.values():
            grouped[node.parent_id].append(node)
        self._children = {
            parent: sorted(children, key=lambda node: (node.position, node.id))
            for parent, children in grouped.items()
        }
        self._direct = {category_id: count for category_id, count in video_counts.items() if count > 0}
        self._totals: dict[int, int] = {}

    @property
    def category_count(self) -> int:
        return len(self._nodes)

    @property
    def video_count(self) -> int:
        return sum(self._direct.values())

    def get(self, category_id: int | None) -> CategoryNode | None:
        return None if category_id is None else self._nodes.get(category_id)

    def children(self, parent_id: int | None) -> list[CategoryNode]:
        return list(self._children.get(parent_id, ()))

    def walk(self) -> list[CategoryNode]:
        """All categories depth-first: each one followed by its children, in their order."""
        order: list[CategoryNode] = []
        stack = self.children(None)[::-1]
        while stack:
            node = stack.pop()
            order.append(node)
            stack.extend(self.children(node.id)[::-1])
        return order

    def visible_children(self, parent_id: int | None) -> list[CategoryNode]:
        """Children that have at least one video somewhere inside."""
        return [node for node in self.children(parent_id) if self.total(node.id) > 0]

    def direct_videos(self, category_id: int) -> int:
        return self._direct.get(category_id, 0)

    def total(self, category_id: int) -> int:
        """Videos in the category and all of its descendants."""
        cached = self._totals.get(category_id)
        if cached is None:
            cached = self.direct_videos(category_id) + sum(
                self.total(child.id) for child in self._children.get(category_id, ())
            )
            self._totals[category_id] = cached
        return cached

    def kind(self, category_id: int | None) -> Kind:
        if self._children.get(category_id):
            return Kind.CATEGORIES
        if category_id is not None and self.direct_videos(category_id):
            return Kind.VIDEOS
        return Kind.EMPTY

    def path(self, category_id: int) -> list[str]:
        titles: list[str] = []
        node = self._nodes.get(category_id)
        while node is not None and len(titles) <= len(self._nodes):
            titles.append(node.title)
            node = self._nodes.get(node.parent_id) if node.parent_id is not None else None
        return titles[::-1]

    def subtree_stats(self, category_id: int) -> tuple[int, int]:
        """(descendant categories, videos) inside the category."""
        categories = 0
        stack = list(self._children.get(category_id, ()))
        while stack:
            node = stack.pop()
            categories += 1
            stack.extend(self._children.get(node.id, ()))
        return categories, self.total(category_id)

    def can_add_child(self, category_id: int | None, max_depth: int) -> bool:
        if category_id is None:
            return True
        node = self._nodes.get(category_id)
        return node is not None and node.depth < max_depth and self.kind(category_id) is not Kind.VIDEOS

    def can_add_video(self, category_id: int) -> bool:
        return category_id in self._nodes and self.kind(category_id) is not Kind.CATEGORIES
