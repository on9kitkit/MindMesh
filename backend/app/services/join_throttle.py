"""A bounded process-local failed room-code join throttle."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from math import ceil
import threading
import time
from uuid import UUID

JOIN_FAILURE_LIMIT = 8
JOIN_FAILURE_WINDOW_SECONDS = 60.0
JOIN_FAILURE_COOLDOWN_SECONDS = 10.0


class JoinFailureThrottle:
    """Throttle failed code joins by authenticated StudyRoom identity.

    State is intentionally process-local. StudyRoom's current runtime
    contract is one FastAPI process/replica, and no raw room code is stored.
    """

    def __init__(
        self,
        *,
        limit: int = JOIN_FAILURE_LIMIT,
        window_seconds: float = JOIN_FAILURE_WINDOW_SECONDS,
        cooldown_seconds: float = JOIN_FAILURE_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window_seconds <= 0 or cooldown_seconds <= 0:
            raise ValueError("join throttle settings must be positive")
        self._limit = limit
        self._window_seconds = window_seconds
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._attempts: dict[UUID, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, user_id: UUID) -> tuple[bool, int | None]:
        """Return whether another failed-code attempt may be made."""

        now = self._clock()
        with self._lock:
            attempts = self._prune(user_id, now)
            if len(attempts) < self._limit:
                return True, None
            oldest = attempts[0]
            retry_after = max(
                self._cooldown_seconds,
                self._window_seconds - (now - oldest),
            )
            return False, max(1, ceil(retry_after))

    def record_failure(self, user_id: UUID) -> None:
        now = self._clock()
        with self._lock:
            attempts = self._prune(user_id, now)
            attempts.append(now)

    def record_success(self, user_id: UUID) -> None:
        with self._lock:
            self._attempts.pop(user_id, None)

    def _prune(self, user_id: UUID, now: float) -> deque[float]:
        attempts = self._attempts.setdefault(user_id, deque())
        cutoff = now - self._window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            self._attempts.pop(user_id, None)
            attempts = self._attempts.setdefault(user_id, deque())
        return attempts
