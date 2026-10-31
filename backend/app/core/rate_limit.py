"""
Smart Enroll — In-Memory Sliding Window Rate Limiter (Increment 15 / Hardening Task 4.1)

Enforces strict request throttling on sensitive endpoints to protect against
credential stuffing, brute-force attacks, and denial-of-service.
Supports automatic Retry-After calculation, trusted proxy resolution,
bounded/expiring storage to prevent memory exhaustion, and configurable bypass in testing.
"""

import threading
import time
from fastapi import HTTPException, Request, status

from app.core.config import settings


def get_client_ip(request: Request) -> str:
    """
    Extract the real client IP address from the request.
    If the direct connection peer is in settings.TRUSTED_PROXIES, inspect the
    X-Forwarded-For header and return the originating client IP.
    Otherwise, return the direct connection IP without trusting spoofable proxy headers.
    """
    if not request.client:
        return "unknown"

    direct_ip = request.client.host
    trusted = getattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1"])
    if isinstance(trusted, str):
        trusted_set = {ip.strip() for ip in trusted.split(",") if ip.strip()}
    else:
        trusted_set = set(trusted or [])

    if direct_ip in trusted_set:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ips = [ip.strip() for ip in forwarded_for.split(",") if ip.strip()]
            if ips:
                return ips[0]

    return direct_ip


class SlidingWindowRateLimiter:
    """
    Thread-safe in-memory sliding-window rate limiter with bounded and expiring storage.
    """

    def __init__(self, max_keys: int = 10000):
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def prune(self, max_idle_seconds: float = 300.0) -> int:
        """
        Prune keys that have had no requests in the last max_idle_seconds or are empty.
        Returns the number of keys removed.
        """
        now = time.monotonic()
        cutoff = now - max_idle_seconds
        removed_count = 0
        with self._lock:
            stale_keys = [
                k for k, timestamps in self._requests.items()
                if not timestamps or timestamps[-1] < cutoff
            ]
            for k in stale_keys:
                self._requests.pop(k, None)
                removed_count += 1
        return removed_count

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
        cutoff = now - window_seconds

        with self._lock:
            # Enforce bounded storage capacity
            if len(self._requests) >= self._max_keys:
                stale_keys = [
                    k for k, timestamps in self._requests.items()
                    if not timestamps or timestamps[-1] < cutoff
                ]
                for k in stale_keys:
                    self._requests.pop(k, None)

                # If still at or over capacity, drop the oldest keys (FIFO eviction)
                if len(self._requests) >= self._max_keys:
                    excess = len(self._requests) - self._max_keys + 1
                    keys_to_evict = list(self._requests.keys())[:excess]
                    for k in keys_to_evict:
                        self._requests.pop(k, None)

            timestamps = self._requests.get(key, [])
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
