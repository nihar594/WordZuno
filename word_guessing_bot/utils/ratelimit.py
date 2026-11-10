"""Tiny in-memory rate limiter and duplicate-event filter."""
from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Hashable


class RateLimiter:
    def __init__(self, max_calls: int, per_seconds: float) -> None:
        self.max_calls = max_calls
        self.per = per_seconds
        self._hits: dict[Hashable, deque[float]] = {}

    def allow(self, key: Hashable) -> bool:
        now = time.monotonic()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > self.per:
            q.popleft()
        if len(q) >= self.max_calls:
            return False
        q.append(now)
        if len(self._hits) > 10_000:
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.per]:
                self._hits.pop(k, None)
        return True


class Dedup:
    """Remembers the last N keys; `seen()` is True when the key was already processed."""

    def __init__(self, size: int = 4096) -> None:
        self.size = size
        self._d: OrderedDict[Hashable, None] = OrderedDict()

    def seen(self, key: Hashable) -> bool:
        if key in self._d:
            return True
        self._d[key] = None
        if len(self._d) > self.size:
            self._d.popitem(last=False)
        return False
