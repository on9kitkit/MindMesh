"""Shared bounded generation and verification after source-specific durable claim.

Callers acquire the same process-wide GenerationAdmission before their claim,
keep it until this runner AND the durable CAS write finish, and supply a lease
renewal callback that checks their own source token. This runner never trusts
unverified generated content as a READY result.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import logging

from app.generator.protocol import (
    GENERATION_LEASE_SECONDS,
    GENERATION_TIMEOUT_SECONDS,
    GenerationRequest,
    GeneratorError,
    GeneratorUnavailableError,
    GeneratorValidationError,
    QuizContentGenerator,
)
from app.generator.validation import validate_generated_quiz_set
from app.generator.verification.protocol import (
    QuizContentVerifier,
    VerificationInvalidError,
    VerificationRejectedError,
    VerificationTimeoutError,
    VerificationUnavailableError,
    VerifiedQuizSet,
)

logger = logging.getLogger(__name__)

LeaseRenewal = Callable[[int], Awaitable[bool]]


class VerifiedGenerationFailure(Exception):
    """Safe closed failure category for source-specific CAS persistence."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


async def generate_verified_quiz(
    *,
    request: GenerationRequest,
    generator: QuizContentGenerator,
    verifier: QuizContentVerifier,
    deadline_at: datetime,
    deadline_monotonic: float,
    renew_lease: LeaseRenewal,
    event_logger: logging.Logger | None = None,
) -> VerifiedQuizSet:
    """Run at most two content attempts and one verified-set gate.

    The caller owns the outer 165-second timeout. Each provider phase is
    bounded against the remaining monotonic deadline; the source lease is
    renewed before a second content call and before the verifier's paid phase.
    """
    loop = asyncio.get_running_loop()
    safe_logger = event_logger or logger

    def remaining_seconds() -> int:
        remaining = deadline_monotonic - loop.time()
        if remaining <= 1:
            return 0
        return min(GENERATION_LEASE_SECONDS, int(remaining))

    generated_questions = None
    failure_category = "generation_failed"
    for attempt_index in range(2):
        if datetime.now(timezone.utc) >= deadline_at:
            raise VerifiedGenerationFailure("timeout")
        if attempt_index == 1:
            lease_seconds = remaining_seconds()
            if lease_seconds <= 0:
                raise VerifiedGenerationFailure("timeout")
            if not await renew_lease(lease_seconds):
                safe_logger.warning("Generation lease renewal failed; aborting")
                raise VerifiedGenerationFailure("generation_lease_expired")

        try:
            phase_seconds = remaining_seconds()
            if phase_seconds <= 0:
                raise VerifiedGenerationFailure("timeout")
            async with asyncio.timeout(min(float(GENERATION_TIMEOUT_SECONDS), float(phase_seconds))):
                raw_questions = await generator.generate_quiz_questions(request)
        except (TimeoutError, asyncio.TimeoutError) as error:
            raise VerifiedGenerationFailure("timeout") from error
        except GeneratorUnavailableError as error:
            safe_logger.warning("Generator failed at provider boundary")
            raise VerifiedGenerationFailure(error.category) from error
        except GeneratorValidationError as error:
            failure_category = error.category
            safe_logger.warning("Generated questions failed validation on attempt %d", attempt_index + 1)
            continue
        except GeneratorError as error:
            safe_logger.warning("Generator failed at provider boundary")
            raise VerifiedGenerationFailure(error.category) from error
        except VerifiedGenerationFailure:
            raise
        except Exception as error:
            safe_logger.warning("Unexpected error in quiz generation")
            raise VerifiedGenerationFailure("internal_error") from error

        try:
            generated_questions = validate_generated_quiz_set(
                raw_questions,
                target_total_marks=request.target_total_marks,
                exclusion_prompts=request.exclusion_prompts,
            )
            break
        except GeneratorValidationError as error:
            failure_category = error.category
            safe_logger.warning("Generated questions failed validation on attempt %d", attempt_index + 1)

    if generated_questions is None:
        raise VerifiedGenerationFailure(failure_category)
    if datetime.now(timezone.utc) >= deadline_at:
        raise VerifiedGenerationFailure("timeout")

    async def before_paid_phase() -> None:
        lease_seconds = remaining_seconds()
        if lease_seconds <= 0:
            raise VerificationTimeoutError("Verification deadline exceeded.")
        if not await renew_lease(lease_seconds):
            raise VerificationUnavailableError("Lease renewal failed before verification.")

    try:
        return await verifier.verify_quiz_content(
            generated_questions,
            request,
            before_paid_phase=before_paid_phase,
            deadline_at=deadline_at,
        )
    except VerificationRejectedError as error:
        raise VerifiedGenerationFailure("verification_rejected") from error
    except VerificationInvalidError as error:
        raise VerifiedGenerationFailure("verification_invalid") from error
    except VerificationTimeoutError as error:
        raise VerifiedGenerationFailure("timeout") from error
    except VerificationUnavailableError as error:
        raise VerifiedGenerationFailure("ai_generation_unavailable") from error
    except Exception as error:
        safe_logger.warning("Unexpected verification error")
        raise VerifiedGenerationFailure("internal_error") from error
