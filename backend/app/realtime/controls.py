"""Small process-local defensive controls for the WebSocket boundary."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable
from uuid import UUID


class CommandRateLimiter:
    """Allow a bounded burst of commands on one authenticated connection."""

    def __init__(self, *, limit: int = 20, window_seconds: float = 1.0) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("rate limiter settings must be positive")
        self._limit = limit
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._limit:
            return False
        self._timestamps.append(now)
        return True


class RoomRetryLimiter:
    """Process-wide paid-retry allowance keyed by (room, host).

    A per-connection limiter resets on every reconnect or extra socket,
    multiplying the paid-retry allowance. This limiter is shared across all
    connections in the process so sequential reconnect cycles stay bounded.
    Durable row/lease coalescing still handles simultaneous requests.
    Entries expire after the window (bounded TTL cleanup); the table itself
    is capped to bound memory. Limitation: the allowance is process-local,
    not DB-durable across replicas/restarts.
    """

    def __init__(
        self,
        *,
        limit: int = 2,
        window_seconds: float = 30.0,
        max_keys: int = 4096,
    ) -> None:
        if limit < 1 or window_seconds <= 0 or max_keys < 1:
            raise ValueError("rate limiter settings must be positive")
        self._limit = limit
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._buckets: dict[tuple[UUID, UUID], deque[float]] = {}

    def allow(self, room_id: UUID, user_id: UUID) -> bool:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        key = (room_id, user_id)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = deque()
            self._buckets[key] = bucket
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(now)
        if len(self._buckets) > self._max_keys:
            # Bounded TTL cleanup: drop fully expired buckets first.
            expired = [
                known
                for known, stamps in self._buckets.items()
                if not stamps or stamps[-1] <= cutoff
            ]
            for known in expired:
                self._buckets.pop(known, None)
            while len(self._buckets) > self._max_keys:
                self._buckets.pop(next(iter(self._buckets)))
        return True


def origin_is_allowed(
    origin: str | None,
    allowed_origins: Iterable[str],
) -> bool:
    """Allow native clients with no Origin and configured browser origins."""

    if origin is None:
        return True
    return origin in frozenset(allowed_origins)

