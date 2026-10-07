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


def test_migrations_match_the_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = database_url(tmp_path)
    asyncio.run(_drop_everything(url))
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))

    command.upgrade(config, "head")
    assert asyncio.run(_differences(url)) == []
    command.downgrade(config, "base")
