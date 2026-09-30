"""Fail-fast process-local generation admission shared by HTTP and WebSocket work.

This bounds local in-flight tasks, not distributed spend or remote billing.
"""

from threading import Lock
from uuid import UUID


class GenerationAdmission:
    def __init__(self, capacity: int = 4) -> None:
        if capacity < 1:
            raise ValueError("Generation capacity must be positive")
        self._capacity = capacity
        self._hosts: set[UUID] = set()
        self._lock = Lock()

    def acquire(self, host_id: UUID) -> bool:
        with self._lock:
            if host_id in self._hosts or len(self._hosts) >= self._capacity:
                return False
            self._hosts.add(host_id)
            return True

    def release(self, host_id: UUID) -> None:
        with self._lock:
            self._hosts.remove(host_id)


generation_admission = GenerationAdmission()
