"""Keys seen in the last few seconds: what cooldowns and the double-click guard rely on."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from bot.db.models import User
from bot.middlewares import ACTIVITY_STEP
from bot.utils import clock
from bot.utils.recent import RecentKeys
from tests.conftest import CLIENT_ID, Harness


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def ticks(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr("bot.utils.recent.time.monotonic", fake)
    return fake


def test_a_key_is_recent_for_ttl_seconds(ticks: FakeClock) -> None:
    recent = RecentKeys(60)
    recent.add("a")
    ticks.now += 59
    assert "a" in recent and recent.left("a") == pytest.approx(1)
    ticks.now += 1
    assert "a" not in recent and recent.left("a") == 0


def test_adding_again_starts_over(ticks: FakeClock) -> None:
    recent = RecentKeys(60)
    recent.add("a")
    ticks.now += 50
    recent.add("a")
    ticks.now += 50
    assert "a" in recent


def test_expired_keys_are_dropped_so_memory_stays_small(ticks: FakeClock) -> None:
    recent = RecentKeys(10)
    for key in range(1000):
        recent.add(key)
        ticks.now += 1
    # Only the last ten seconds are kept, however many keys came before.
    assert len(recent) == 10


async def test_activity_is_written_once_in_a_while_not_on_every_tap(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def last_active() -> object:
        async with harness.session_factory() as session:
            return await session.scalar(select(User.last_active_at).where(User.id == CLIENT_ID))

    start = clock.now()
    monkeypatch.setattr("bot.middlewares.clock.now", lambda: start)
    await harness.send_text(CLIENT_ID, "/start")
    first = await last_active()

    monkeypatch.setattr("bot.middlewares.clock.now", lambda: start + ACTIVITY_STEP / 2)
    await harness.send_text(CLIENT_ID, "/start")
    assert await last_active() == first  # no write

    monkeypatch.setattr("bot.middlewares.clock.now", lambda: start + ACTIVITY_STEP + timedelta(seconds=1))
    await harness.send_text(CLIENT_ID, "/start")
    assert await last_active() != first
