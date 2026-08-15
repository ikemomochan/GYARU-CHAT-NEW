from __future__ import annotations

import pytest

from app.core.rate_limit import RateLimitExceeded, SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_rate_limiter_blocks_until_window_expires() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, clock=clock)

    limiter.acquire("user-a")
    limiter.acquire("user-a")
    with pytest.raises(RateLimitExceeded) as error:
        limiter.acquire("user-a")

    assert error.value.retry_after_seconds == 60

    clock.value = 60
    limiter.acquire("user-a")


def test_rate_limiter_tracks_clients_independently() -> None:
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60)

    limiter.acquire("user-a")
    limiter.acquire("user-b")

    with pytest.raises(RateLimitExceeded):
        limiter.acquire("user-a")
