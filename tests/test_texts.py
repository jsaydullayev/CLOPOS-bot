import re
from pathlib import Path

from bot.texts import t

ROOT = Path(__file__).resolve().parent.parent
# t("key"), CatalogError("key") and error_key="key" all name a text in locales/uz.toml.
KEY_PATTERN = re.compile(r"""(?:\bt\(|\bCatalogError\(|\berror_key\s*[:=][^"'\n]*)\s*["']([a-z0-9_]+)["']""")


def sources() -> list[Path]:
    return [*ROOT.joinpath("bot").rglob("*.py"), *ROOT.joinpath("scripts").rglob("*.py")]


def test_every_text_used_in_code_exists() -> None:
    used = set()
    for path in sources():
        used.update(KEY_PATTERN.findall(path.read_text(encoding="utf-8")))
    missing = used - t.keys()
    assert not missing, f"missing in locales/uz.toml: {sorted(missing)}"


def test_every_text_in_the_file_is_used() -> None:
    code = "\n".join(path.read_text(encoding="utf-8") for path in sources())
    unused = {key for key in t.keys() if f'"{key}"' not in code}
    assert not unused, f"not used anywhere: {sorted(unused)}"
