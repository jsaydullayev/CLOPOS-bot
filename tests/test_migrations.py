import asyncio
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text

from bot.db.models import Base
from bot.db.session import create_engine
from tests.conftest import database_url

ROOT = Path(__file__).resolve().parent.parent


async def _drop_everything(url: str) -> None:
    engine = create_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()


async def _differences(url: str) -> list[Any]:
    engine = create_engine(url)
    async with engine.connect() as connection:
        differences = await connection.run_sync(
            lambda sync_connection: compare_metadata(MigrationContext.configure(sync_connection), Base.metadata)
        )
    await engine.dispose()
    return differences


async def _execute(url: str, sql: str) -> list[Any]:
    engine = create_engine(url)
    async with engine.begin() as connection:
        result = await connection.execute(text(sql))
        rows = list(result) if result.returns_rows else []
    await engine.dispose()
    return rows


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, str]:
    url = database_url(tmp_path)
    asyncio.run(_drop_everything(url))
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config, url


def test_migrations_match_the_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, url = _config(tmp_path, monkeypatch)
    command.upgrade(config, "head")
    assert asyncio.run(_differences(url)) == []
    command.downgrade(config, "base")


def test_a_greeting_photo_survives_the_move_to_greeting_media(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, url = _config(tmp_path, monkeypatch)
    command.upgrade(config, "0003")
    photo = "INSERT INTO bot_texts (key, value, photo_file_id, photo_unique_id) VALUES ('main_menu', 'Salom', 'f', 'u')"
    asyncio.run(_execute(url, photo))

    command.upgrade(config, "0004")
    rows = asyncio.run(_execute(url, "SELECT media_file_id, media_unique_id, media_type FROM bot_texts"))
    assert [tuple(row) for row in rows] == [("f", "u", "photo")]

    # Going back keeps photos; a video greeting is dropped, since only photos existed before.
    video = "INSERT INTO bot_texts (key, media_file_id, media_unique_id, media_type) VALUES ('x', 'v', 'w', 'video')"
    asyncio.run(_execute(url, video))
    command.downgrade(config, "0003")
    rows = asyncio.run(_execute(url, "SELECT key, photo_file_id FROM bot_texts ORDER BY key"))
    assert [tuple(row) for row in rows] == [("main_menu", "f")]
    command.downgrade(config, "base")
