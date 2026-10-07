"""Interface texts. Every user-facing string lives in locales/<language>.toml."""

import tomllib
from pathlib import Path
from typing import Any

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
DEFAULT_LANGUAGE = "uz"


class Texts:
    def __init__(self, path: Path) -> None:
        self.path = path
        with path.open("rb") as file:
            self._texts: dict[str, str] = tomllib.load(file)

    def __call__(self, key: str, /, **params: Any) -> str:
        try:
            template = self._texts[key]
        except KeyError:
            raise KeyError(f"Text '{key}' is missing in {self.path.name}") from None
        return template.format(**params) if params else template

    def keys(self) -> set[str]:
        return set(self._texts)


t = Texts(LOCALES_DIR / f"{DEFAULT_LANGUAGE}.toml")
