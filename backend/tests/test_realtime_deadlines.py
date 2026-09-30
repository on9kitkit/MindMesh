import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.domain.quiz import QuizSession, QuizSessionStatus
from app.realtime.deadlines import DeadlineCoordinator


SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")
ROOM_ID = UUID("22222222-2222-4222-8222-222222222222")


class ControlledSessionService:
    def __init__(self, *, overdue: bool) -> None:
        now = datetime.now(timezone.utc)
        self.session = QuizSession(
            id=SESSION_ID,
            room_id=ROOM_ID,
            question_bank_key="physics_sprint",
            status=QuizSessionStatus.QUESTION_OPEN,
            current_question_position=0,
            state_version=1,
            reveal_ends_at=None,
            started_at=now,
            finished_at=None,
        )
        self.deadline = now - timedelta(seconds=1) if overdue else now + timedelta(
            seconds=30
        )

    def list_active_sessions(self) -> tuple[QuizSession, ...]:
        if self.session.status == QuizSessionStatus.FINISHED:
            return ()
        return (self.session,)

    def get_session(self, session_id: UUID) -> QuizSession | None:
        return self.session if session_id == self.session.id else None

    def get_session_deadline(self, session_id: UUID) -> datetime | None:
        if session_id != self.session.id or self.session.status == QuizSessionStatus.FINISHED:
            return None
        return self.deadline

    def reconcile_session(self, *, session_id: UUID) -> QuizSession:
        assert session_id == self.session.id
        now = datetime.now(timezone.utc)
        if self.session.status == QuizSessionStatus.QUESTION_OPEN:
            self.session = replace(
                self.session,
                status=QuizSessionStatus.QUESTION_REVEAL,
                state_version=self.session.state_version + 1,
                reveal_ends_at=now + timedelta(seconds=0.01),
            )
            self.deadline = self.session.reveal_ends_at
        elif self.session.status == QuizSessionStatus.QUESTION_REVEAL:
            self.session = replace(
                self.session,
                status=QuizSessionStatus.FINISHED,
                state_version=self.session.state_version + 1,
                reveal_ends_at=None,
                finished_at=now,
            )
            self.deadline = None
        return self.session


def test_startup_recovery_reconciles_and_schedules_one_task() -> None:
    async def scenario() -> None:
        service = ControlledSessionService(overdue=True)
        transitions: list[tuple[UUID, int]] = []

        async def on_transition(
            room_id: UUID,
            previous: QuizSession | None,
            current: QuizSession,
        ) -> None:
            assert room_id == ROOM_ID
            assert previous is not None
            transitions.append((current.id, current.state_version))

        coordinator = DeadlineCoordinator(service, on_transition)
        await coordinator.startup_recovery()
        assert await coordinator.task_count() == 1
        await asyncio.sleep(0.05)
        assert service.session.status == QuizSessionStatus.FINISHED
        assert transitions == [(SESSION_ID, 2), (SESSION_ID, 3)]
        assert await coordinator.task_count() == 0
        await coordinator.shutdown()

    asyncio.run(scenario())


def test_replacing_and_cancelling_deadline_task_is_idempotent() -> None:
    async def scenario() -> None:
        service = ControlledSessionService(overdue=False)
        transitions: list[int] = []

        async def on_transition(
            room_id: UUID,
            previous: QuizSession | None,
            current: QuizSession,
        ) -> None:
            transitions.append(current.state_version)

        coordinator = DeadlineCoordinator(service, on_transition)
        await coordinator.schedule_session(SESSION_ID)
        await coordinator.schedule_session(SESSION_ID)
        assert await coordinator.task_count() == 1
        await coordinator.cancel_session(SESSION_ID)
        assert await coordinator.task_count() == 0
        assert transitions == []
        await coordinator.shutdown()

    asyncio.run(scenario())

