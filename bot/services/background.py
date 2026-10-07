import asyncio
from collections.abc import Coroutine
from typing import Any


class Background:
    """Long-running tasks started with the bot and cancelled on shutdown."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def start(self, coroutine: Coroutine[Any, Any, Any], *, name: str | None = None) -> None:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def stop(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
