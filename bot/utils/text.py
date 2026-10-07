"""Text helpers: cleaning names and formatting category paths."""

import re
import unicodedata
from collections.abc import Sequence
from html import escape

PATH_SEPARATOR = " › "
PATH_LIMIT = 60
ELLIPSIS = "…"

_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F000, 0x1FAFF),  # pictographs, emoticons, transport, flags
    (0x2190, 0x21FF),  # arrows
    (0x2300, 0x23FF),  # technical symbols: ⌚ ⏩ ⏰
    (0x25A0, 0x25FF),  # geometric shapes: ▶ ◀
    (0x2600, 0x27BF),  # symbols and dingbats: ☀ ✅ ❌ ➕
    (0x2B00, 0x2BFF),  # arrows and stars: ⬅ ⭐
    (0xFE00, 0xFE0F),  # variation selectors
    (0x200D, 0x200D),  # zero width joiner
    (0x20E3, 0x20E3),  # combining keycap
    (0xE0020, 0xE007F),  # tag characters
)
_WHITESPACE = re.compile(r"\s+")
# For name_key: Cyrillic letters that look like Latin ones become Latin, so a name typed with a letter
# from the other alphabet still matches; the Uzbek apostrophes ʻ ʼ count as letters in Unicode, so they go.
_KEY_LETTERS = str.maketrans("аеёкмнорстухв", "aeekmhopctyxb", "ʻʼʹ")


def _is_emoji(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _EMOJI_RANGES)


def clean_name(raw: str) -> str:
    """Drop emoji and control characters and collapse whitespace."""
    kept: list[str] = []
    for char in raw:
        if _is_emoji(char):
            continue
        kept.append(" " if unicodedata.category(char) in ("Cc", "Cf") else char)
    return _WHITESPACE.sub(" ", "".join(kept)).strip()


def name_key(name: str) -> str:
    """A section name reduced for comparing: letter case, spaces, apostrophes (o‘ o' oʻ)
    and other punctuation do not matter, nor do Cyrillic letters that look like Latin ones."""
    folded = unicodedata.normalize("NFKC", name).casefold().translate(_KEY_LETTERS)
    return "".join(char for char in folded if char.isalnum()) or folded.strip()


def typo_distance(first: str, second: str) -> int:
    """Letters to add, remove, replace or swap with a neighbour to turn one string into the other."""
    before_previous: list[int] = []
    previous = list(range(len(second) + 1))
    for i, char in enumerate(first, start=1):
        current = [i] + [0] * len(second)
        for j, other in enumerate(second, start=1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char != other))
            if i > 1 and j > 1 and char == second[j - 2] and first[i - 2] == other:
                current[j] = min(current[j], before_previous[j - 2] + 1)
        before_previous, previous = previous, current
    return previous[-1]


def first_line(text: str | None) -> str:
    if not text:
        return ""
    return next((line for line in text.splitlines() if line.strip()), "")


def format_path(titles: Sequence[str], limit: int | None = PATH_LIMIT) -> str:
    """Join titles with › and cut the beginning off when the path is longer than limit."""
    parts = list(titles)
    path = PATH_SEPARATOR.join(parts)
    while limit is not None and len(path) > limit and len(parts) > 1:
        parts.pop(0)
        path = ELLIPSIS + PATH_SEPARATOR + PATH_SEPARATOR.join(parts)
    return path


def html(value: object) -> str:
    """Escape a value for Telegram HTML text."""
    return escape(str(value), quote=False)
