"""Process-local grading permits reserved before either source claims DB leases.

Room and solo coordinators must share one instance and the same grader. A
permit covers the source claim, provider call, and durable grading CAS so a
leased answer never waits behind another source's provider queue.
"""

from __future__ import annotations

from threading import Lock

from app.grading.protocol import MAX_CONCURRENT_GRADING_CALLS


class GradingAdmission:
    def __init__(self, capacity: int = MAX_CONCURRENT_GRADING_CALLS) -> None:
        if capacity < 1:
            raise ValueError("Grading capacity must be positive.")
        self._capacity = capacity
        self._available = capacity
        self._lock = Lock()

    def reserve_up_to(self, maximum: int) -> int:
        """Reserve available provider slots synchronously, before DB claim."""
        if maximum < 1:
            raise ValueError("Requested grading slots must be positive.")
        with self._lock:
            reserved = min(maximum, self._available)
            self._available -= reserved
            return reserved

    def release(self, count: int) -> None:
        """Return only slots this caller held, after durable work has stopped."""
        if count < 0:
            raise ValueError("Released grading slot count must be nonnegative.")
        with self._lock:
            if self._available + count > self._capacity:
                raise RuntimeError("Grading slots released more than once.")
            self._available += count

    @property
    def available(self) -> int:
        with self._lock:
            return self._available


grading_admission = GradingAdmission()
