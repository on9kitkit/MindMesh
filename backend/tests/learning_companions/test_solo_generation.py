"""Shared verified generation checks; no provider, database, or room runtime."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.generator.fake_adapter import FakeQuizContentGenerator
from app.generator.protocol import GenerationRequest
from app.generator.verified_runner import VerifiedGenerationFailure, generate_verified_quiz
from app.generator.verification.fixtures import FakeQuizContentVerifier
from app.generator.verification.protocol import VerifiedQuizSet


def _deadline() -> tuple[datetime, float]:
    return datetime.now(timezone.utc) + timedelta(seconds=165), asyncio.get_running_loop().time() + 165


def test_verified_runner_returns_only_typed_verified_content_and_renews_before_verification() -> None:
    async def run() -> None:
        generator = FakeQuizContentGenerator()
        verifier = FakeQuizContentVerifier()
        request = GenerationRequest("GCSE", "physics", "forces", 5)
        deadline_at, deadline_monotonic = _deadline()
        renewals: list[int] = []

        async def renew(seconds: int) -> bool:
            renewals.append(seconds)
            return True

        verified = await generate_verified_quiz(
            request=request, generator=generator, verifier=verifier,
            deadline_at=deadline_at, deadline_monotonic=deadline_monotonic,
            renew_lease=renew,
        )
        assert type(verified) is VerifiedQuizSet
        assert sum(q.max_marks for q in verified.candidate_questions) == 5
        assert generator.call_count == 1
        assert len(verifier.calls) == 1
        assert renewals and all(0 < seconds <= 75 for seconds in renewals)

    asyncio.run(run())


def test_verified_runner_fails_closed_before_verifier_without_lease() -> None:
    async def run() -> None:
        generator = FakeQuizContentGenerator()
        verifier = FakeQuizContentVerifier()
        deadline_at, deadline_monotonic = _deadline()

        async def refuse_renewal(_seconds: int) -> bool:
            return False

        with pytest.raises(VerifiedGenerationFailure, match="ai_generation_unavailable"):
            await generate_verified_quiz(
                request=GenerationRequest("GCSE", "physics", "forces", 5),
                generator=generator, verifier=verifier,
                deadline_at=deadline_at, deadline_monotonic=deadline_monotonic,
                renew_lease=refuse_renewal,
            )
        assert generator.call_count == 1
        assert not verifier.solver.calls
        assert not verifier.assessor.calls

    asyncio.run(run())


def test_verified_runner_never_spends_when_deadline_already_elapsed() -> None:
    async def run() -> None:
        generator = FakeQuizContentGenerator()
        verifier = FakeQuizContentVerifier()

        async def renew(_seconds: int) -> bool:
            raise AssertionError("No lease renewal may occur")

        with pytest.raises(VerifiedGenerationFailure, match="timeout"):
            await generate_verified_quiz(
                request=GenerationRequest("GCSE", "physics", "forces", 5),
                generator=generator, verifier=verifier,
                deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                deadline_monotonic=asyncio.get_running_loop().time() - 1,
                renew_lease=renew,
            )
        assert generator.call_count == 0
        assert not verifier.calls

    asyncio.run(run())
