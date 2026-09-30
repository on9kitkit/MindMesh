"""Advisory deadline wakeups for PostgreSQL-authoritative quiz sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import UUID

from app.domain.errors import QuizSessionError
from app.domain.quiz import QuizSession, QuizSessionStatus
from app.services.sessions import SessionService

TransitionCallback = Callable[
    [UUID, QuizSession | None, QuizSession],
    Awaitable[bool | None],
]


class DeadlineCoordinator:
    """Wake the service at durable deadlines without keeping DB sessions open."""

    def __init__(
        self,
        session_service: SessionService,
        on_transition: TransitionCallback,
    ) -> None:
        self._session_service = session_service
        self._on_transition = on_transition
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._started = False

    async def startup_recovery(self) -> None:
        """Reconcile every active row once, then schedule its next deadline."""

        self._started = True
        active_sessions = await asyncio.to_thread(
            self._session_service.list_active_sessions
        )
        for discovered in active_sessions:
            try:
                reconciled = await asyncio.to_thread(
                    self._session_service.reconcile_session,
                    session_id=discovered.id,
                )
            except QuizSessionError:
                continue
            if reconciled is None:
                continue
            if reconciled.state_version != discovered.state_version:
                await self._publish_transition(discovered, reconciled)
            if reconciled.status != QuizSessionStatus.FINISHED:
                await self.schedule_session(reconciled.id)

    async def schedule_session(self, session_id: UUID) -> None:
        """Replace any older advisory task for this durable session."""

        if not self._started:
            self._started = True
        async with self._lock:
            previous = self._tasks.get(session_id)
            if previous is not None and not previous.done():
                previous.cancel()
            self._tasks[session_id] = asyncio.create_task(
                self._run_session(session_id),
                name=f"studyroom-deadline-{session_id}",
            )

    async def cancel_session(self, session_id: UUID) -> None:
        async with self._lock:
            task = self._tasks.pop(session_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        self._started = False
        async with self._lock:
            tasks = tuple(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def task_count(self) -> int:
        async with self._lock:
            return sum(not task.done() for task in self._tasks.values())

    async def _run_session(self, session_id: UUID) -> None:
        current_task = asyncio.current_task()
        try:
            while True:
                deadline = await asyncio.to_thread(
                    self._session_service.get_session_deadline,
                    session_id,
                )
                if deadline is None:
                    return
                delay = _seconds_until(deadline)
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    await asyncio.sleep(0)

                previous = await asyncio.to_thread(
                    self._session_service.get_session,
                    session_id,
                )
                if previous is None or previous.status == QuizSessionStatus.FINISHED:
                    return
                try:
                    reconciled = await asyncio.to_thread(
                        self._session_service.reconcile_session,
                        session_id=session_id,
                    )
                except QuizSessionError:
                    return
                if reconciled is None:
                    return
                if reconciled.state_version != previous.state_version:
                    await self._publish_transition(previous, reconciled)
                if reconciled.status == QuizSessionStatus.FINISHED:
                    return
        finally:
            if current_task is not None:
                await self._forget_task(session_id, current_task)

    async def _publish_transition(
        self,
        previous: QuizSession,
        current: QuizSession,
    ) -> None:
        try:
            await self._on_transition(current.room_id, previous, current)
        except Exception:
            # A dead or malformed realtime client must not stop durable timers.
            # The next reconnect receives the authoritative snapshot.
            return

    async def _forget_task(
        self,
        session_id: UUID,
        task: asyncio.Task[None],
    ) -> None:
        async with self._lock:
            if self._tasks.get(session_id) is task:
                self._tasks.pop(session_id, None)


def _seconds_until(deadline: datetime) -> float:
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return (deadline - datetime.now(timezone.utc)).total_seconds()
