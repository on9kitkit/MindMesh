"""Room and solo must share permits before either leases written answers."""

import asyncio

from app.generator.fake_adapter import FakeQuizContentGenerator
from app.generator.verification.fixtures import FakeQuizContentVerifier
from app.grading.coordinator import GradingCoordinator
from app.grading.fake_grader import FakeWrittenAnswerGrader
from app.learning_companions.solo_grading_admission import GradingAdmission
from app.learning_companions.solo_service import SoloService


class _RoomClaims:
    def __init__(self) -> None:
        self.claim_limits: list[int] = []

    def claim_due_written_submissions(self, *, limit: int, lease_seconds: int):
        assert lease_seconds == 30
        self.claim_limits.append(limit)
        return tuple(range(limit))


class _SoloClaims:
    def __init__(self) -> None:
        self.claim_limits: list[int] = []

    def claim_due_ai(self, *, limit: int, lease_seconds: int):
        assert lease_seconds == 30
        self.claim_limits.append(limit)
        return ()


def test_room_leases_hold_shared_slots_until_all_room_work_finishes() -> None:
    async def run() -> None:
        permits = GradingAdmission(capacity=4)
        room = _RoomClaims()
        solo = _SoloClaims()
        grader = FakeWrittenAnswerGrader()
        coordinator = GradingCoordinator(room, grader, grading_permits=permits)
        solo_service = SoloService(
            solo,
            FakeQuizContentGenerator(),
            FakeQuizContentVerifier(),
            grader,
            grading_permits=permits,
        )
        entered = asyncio.Event()
        release = asyncio.Event()
        active = 0

        async def blocked_room_grade(_claim: int) -> None:
            nonlocal active
            active += 1
            if active == 4:
                entered.set()
            await release.wait()

        coordinator._evaluate_and_commit_submission = blocked_room_grade
        room_batch = asyncio.create_task(coordinator.process_due_submissions())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert permits.available == 0
            assert room.claim_limits == [4]
            assert await solo_service.process_due_ai() == 0
            assert solo.claim_limits == []  # no solo DB lease behind room work
        finally:
            release.set()
        assert await room_batch == 4
        assert permits.available == 4
        assert await solo_service.process_due_ai() == 0
        assert solo.claim_limits == [4]
        assert permits.available == 4
        await solo_service.shutdown()

    asyncio.run(run())
