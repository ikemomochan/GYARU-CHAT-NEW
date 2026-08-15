from __future__ import annotations

import threading
import time
from math import ceil
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("chat rate limit exceeded")


class SlidingWindowRateLimiter:
    """Small in-memory limiter for the single-instance public web service."""

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def acquire(self, key: str) -> None:
        now = self.clock()
        cutoff = now - self.window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self.limit:
                retry_after = max(
                    1,
                    ceil(requests[0] + self.window_seconds - now),
                )
                raise RateLimitExceeded(retry_after)
            requests.append(now)

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
