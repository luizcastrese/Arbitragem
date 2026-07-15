from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class SlidingWindowRateLimiter:
    def __init__(self, default_limit: int, window_seconds: int = 60):
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int | None = None) -> bool:
        now = monotonic()
        cutoff = now - self.window_seconds
        maximum = limit or self.default_limit
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= maximum:
                return False
            events.append(now)
            return True
