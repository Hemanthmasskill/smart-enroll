"""
Smart Enroll — In-Memory Sliding Window Rate Limiter (Increment 15 / Hardening Task 4.1)

Enforces strict request throttling on sensitive endpoints to protect against
credential stuffing, brute-force attacks, and denial-of-service.
Supports automatic Retry-After calculation and configurable bypass in testing.
"""

from collections import defaultdict
import threading
import time
from fastapi import HTTPException, Request, status

from app.core.config import settings


class SlidingWindowRateLimiter:
    """
    Thread-safe in-memory sliding-window rate limiter.
    """

    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        """
        Check whether an action under key exceeds max_requests within window_seconds.
        Returns (is_allowed, retry_after_seconds).
        """
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return True, 0

        now = time.monotonic()
        with self._lock:
            timestamps = self._requests[key]
            cutoff = now - window_seconds
            # Retain only timestamps within the current sliding window
            valid = [ts for ts in timestamps if ts > cutoff]
            if len(valid) >= max_requests:
                earliest = valid[0]
                retry_after = max(1, int(window_seconds - (now - earliest)))
                self._requests[key] = valid
                return False, retry_after

            valid.append(now)
            self._requests[key] = valid
            return True, 0

    def reset(self) -> None:
        """Clear all active rate-limiting windows."""
        with self._lock:
            self._requests.clear()


limiter = SlidingWindowRateLimiter()


def enforce_rate_limit(
    key: str,
    max_requests: int,
    window_seconds: int = 60,
    action_description: str = "requests",
) -> None:
    """
    Helper function to check rate limit and raise HTTP 429 if exceeded.
    """
    allowed, retry_after = limiter.check(
        key=key,
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many {action_description}. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

