"""Keys seen within the last few seconds: cooldowns and double-click guards."""

import time
from collections import OrderedDict
from collections.abc import Hashable


class RecentKeys:
    """Remembers when each key was last added, for ttl seconds.

    Keys are kept in the order they were added, so the expired ones are always
    at the front and are dropped as new ones come: memory stays as small as the
    keys of the last ttl seconds, however long the bot runs. Every step is O(1)
    per key added or dropped.
    """

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._added: OrderedDict[Hashable, float] = OrderedDict()

    def add(self, key: Hashable) -> None:
        now = time.monotonic()
        self._added[key] = now
        self._added.move_to_end(key)  # the order stays the order of time
        self._drop_expired(now)

    def left(self, key: Hashable) -> float:
        """Seconds before the key expires; 0 when it is not recent."""
        now = time.monotonic()
        self._drop_expired(now)
        added = self._added.get(key)
        return 0.0 if added is None else self.ttl - (now - added)

    def __contains__(self, key: Hashable) -> bool:
        return self.left(key) > 0

    def __len__(self) -> int:
        return len(self._added)

    def _drop_expired(self, now: float) -> None:
        while self._added:
            _, added = next(iter(self._added.items()))
            if now - added < self.ttl:
                return
            self._added.popitem(last=False)
