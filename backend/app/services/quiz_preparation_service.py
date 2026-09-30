"""Service orchestrating the quiz preparation lifecycle outside database transactions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from uuid import UUID

from app.domain.errors import (
    AiGenerationUnavailableError,
    InvalidRoomDataError,
    PreparationConflictError,
    PreparationFailedError,
    RoomClosedError,
    RoomNotFoundError,
    RoomOwnerRequiredError,
)
from app.domain.quiz_preparation import QuizPreparation
from app.domain.room import Room
from app.generator.admission import GenerationAdmission, generation_admission
from app.generator.protocol import (
    GENERATION_LEASE_SECONDS,
    GenerationRequest,
    MODEL_ID_GPT_6_LUNA,
    QuizContentGenerator,
)
from app.generator.verified_runner import VerifiedGenerationFailure, generate_verified_quiz
from app.generator.verification.protocol import (
    TOTAL_PIPELINE_DEADLINE_SECONDS,
    QuizContentVerifier,
)
from app.repositories.quiz_preparations import QuizPreparationRepository
from app.repositories.rooms import RoomRepository

logger = logging.getLogger(__name__)

PreparationHook = Callable[[UUID, QuizPreparation], Awaitable[None]]
CLAIM_ACK_TIMEOUT_SECONDS: float = 10.0


class QuizPreparationService:
    """Manage durable quiz preparations and AI generation coordination."""

    def __init__(
        self,
        preparation_repository: QuizPreparationRepository,
        room_repository: RoomRepository,
        generator: QuizContentGenerator,
        verifier: QuizContentVerifier | None = None,
        on_claimed: PreparationHook | None = None,
        on_terminal: PreparationHook | None = None,
        admission: GenerationAdmission = generation_admission,
    ) -> None:
        self._preparation_repository = preparation_repository
        self._room_repository = room_repository
        self._generator = generator
        self._verifier = verifier
        self._on_claimed = on_claimed
        self._on_terminal = on_terminal
        self._admission = admission
        self._running: set[asyncio.Task[Any]] = set()
        self._active_db_futures: set[asyncio.Future[Any]] = set()
        self._pending_claims: dict[
            tuple[UUID, UUID], asyncio.Future[QuizPreparation]
        ] = {}

    def set_claimed_hook(self, hook: PreparationHook | None) -> None:
        """Attach the post-claim broadcast hook (wired by the app lifespan)."""
        self._on_claimed = hook

    def set_terminal_hook(self, hook: PreparationHook | None) -> None:
        """Attach the terminal completion broadcast hook (wired by the app lifespan)."""
        self._on_terminal = hook

    async def _run_in_thread(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute a database operation in the threadpool, tracking and shielding the worker future."""
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, lambda: func(*args, **kwargs))
        self._active_db_futures.add(future)

        def forget(completed: asyncio.Future[Any]) -> None:
            self._active_db_futures.discard(completed)

        # A cancelled awaiter must not make an executor operation disappear
        # from the shutdown/admission accounting before the DB thread stops.
        future.add_done_callback(forget)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError as initial_cancel:
            # Shield prevents cancellation from reaching the executor future;
            # drain the real operation before releasing the owning task. A
            # second cancellation must not let the owning task finish while
            # the DB thread is still running (which would release admission
            # too early during shutdown).
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise initial_cancel
        finally:
            if future.done():
                self._active_db_futures.discard(future)
                if not future.cancelled():
                    # A cancellation path may observe a completed executor
                    # future without awaiting its result; consume exceptions
                    # so a late DB error cannot become an unhandled warning.
                    future.exception()

    async def shutdown(self) -> None:
        """Bounded drain and cancellation of running tasks and database threads during application shutdown."""
        tasks = list(self._running)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._active_db_futures:
            await asyncio.gather(
                *[asyncio.wrap_future(f) for f in list(self._active_db_futures)],
                return_exceptions=True,
            )
            self._active_db_futures.clear()
    def get_preparation(
        self,
        room_id: UUID,
        request_id: UUID,
    ) -> QuizPreparation | None:
        """Fetch preparation by room and client request ID."""
        return self._preparation_repository.get_by_room_and_request_id(
            room_id=room_id,
            request_id=request_id,
        )

    def get_active_preparation(self, room_id: UUID) -> QuizPreparation | None:
        """Fetch active (GENERATING or READY) preparation for a room."""
        return self._preparation_repository.get_active_for_room(room_id)

    async def recover_expired_preparations(
        self,
        limit: int = 20,
    ) -> tuple[QuizPreparation, ...]:
        """CAS-mark dead GENERATING leases FAILED; fresh request UUIDs may retry."""
        return await self._run_in_thread(
            self._preparation_repository.fail_expired_generating_preparations,
            limit=limit,
        )

    async def prepare_quiz(
        self,
        room_id: UUID,
        request_id: UUID,
        user_id: UUID,
        *,
        wait_for_completion: bool = False,
    ) -> QuizPreparation:
        """Atomically claim/create a generation lease, run generator, verify, and persist via CAS.

        Enforces:
        - Strict verifier presence: no production fail-open default. Missing verifier fails unavailable.
        - Early 10s durable claim acknowledgment: the caller receives the durable GENERATING
          preparation within 10s while the background task continues across caller disconnect.
        - Host 1 / process 4 admission slot held until actual provider AND DB-thread completion.
        - Outer monotonic 165s pipeline deadline.
        """
        if self._verifier is None:
            raise AiGenerationUnavailableError("Quiz verification is unavailable: no verifier configured.")

        room = await self._run_in_thread(self._room_repository.get_by_id, room_id)
        if room is None:
            raise RoomNotFoundError
        if room.closed_at is not None:
            raise RoomClosedError
        if room.owner_id != user_id:
            raise RoomOwnerRequiredError
        if getattr(room, "quiz_mode", "LEGACY_PHYSICS") != "ADAPTIVE":
            raise InvalidRoomDataError("Quiz preparation requires an adaptive room.")

        existing = await self._run_in_thread(
            self._preparation_repository.get_by_room_and_request_id,
            room_id=room_id,
            request_id=request_id,
        )
        if existing is not None and (
            existing.status != "GENERATING"
            or (existing.lease_expires_at is not None
                and existing.lease_expires_at > datetime.now(timezone.utc))
        ):
            return existing

        pending_key = (room_id, request_id)
        pending_claim = self._pending_claims.get(pending_key)
        if pending_claim is not None:
            # A same-process concurrent request observes the first caller's
            # durable claim rather than competing for its token or provider
            # call. The acknowledgement remains bounded like the HTTP path.
            return await asyncio.wait_for(
                asyncio.shield(pending_claim), timeout=CLAIM_ACK_TIMEOUT_SECONDS
            )

        # Admission precedes the claim transaction; capacity waits never hold DB locks.
        if not self._admission.acquire(user_id):
            pending_claim = self._pending_claims.get(pending_key)
            if pending_claim is not None:
                return await asyncio.wait_for(
                    asyncio.shield(pending_claim), timeout=CLAIM_ACK_TIMEOUT_SECONDS
                )
            current = await self._run_in_thread(
                self._preparation_repository.get_by_room_and_request_id,
                room_id=room_id,
                request_id=request_id,
            )
            if current is not None:
                return current
            raise AiGenerationUnavailableError

        loop = asyncio.get_running_loop()
        claim_ack_deadline_monotonic = loop.time() + CLAIM_ACK_TIMEOUT_SECONDS
        claim_ack_future: asyncio.Future[QuizPreparation] = loop.create_future()
        claim_ack_abandoned = asyncio.Event()
        # Mark background claim failures as retrieved even if the initiating
        # caller disconnects before the bounded acknowledgement arrives.
        claim_ack_future.add_done_callback(
            lambda completed: (
                completed.exception() if not completed.cancelled() else None
            )
        )
        self._pending_claims[pending_key] = claim_ack_future

        pipeline_started_at = loop.time()
        pipeline_deadline_monotonic = pipeline_started_at + TOTAL_PIPELINE_DEADLINE_SECONDS
        pipeline_deadline = datetime.now(timezone.utc) + timedelta(
            seconds=TOTAL_PIPELINE_DEADLINE_SECONDS
        )

        task = asyncio.create_task(
            self._prepare_admitted(
                room,
                request_id,
                pipeline_deadline_monotonic,
                pipeline_deadline,
                claim_ack_future,
                claim_ack_deadline_monotonic,
                claim_ack_abandoned,
            )
        )
        self._running.add(task)

        def finished(completed: asyncio.Task[Any]) -> None:
            self._running.discard(completed)
            if self._pending_claims.get(pending_key) is claim_ack_future:
                self._pending_claims.pop(pending_key, None)
            self._admission.release(user_id)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)

        # Early 10s durable claim acknowledgment:
        # Bounded 10s wait for the durable claim transaction (GENERATING or existing terminal state).
        try:
            claim_ack = await asyncio.wait_for(
                asyncio.shield(claim_ack_future),
                timeout=max(0.0, claim_ack_deadline_monotonic - loop.time()),
            )
        except (TimeoutError, asyncio.TimeoutError):
            # Claim wait exceeded 10s: this initiating caller timed out while
            # waiting for a durable ACK. The retained task must fail a claim
            # that arrives late and must never start paid provider work.
            claim_ack_abandoned.set()
            raise
        except asyncio.CancelledError:
            # A disconnect before the durable ACK abandons the claim wait, but
            # a disconnect after the ACK is ordinary and must not stop work.
            if not claim_ack_future.done():
                claim_ack_abandoned.set()
            raise

        if not wait_for_completion:
            return claim_ack

        await asyncio.shield(task)
        return await self._authoritative_outcome(room_id, claim_ack.id)

    async def _prepare_admitted(
        self,
        room: Room,
        request_id: UUID,
        pipeline_deadline_monotonic: float,
        pipeline_deadline: datetime,
        claim_ack_future: asyncio.Future[QuizPreparation],
        claim_ack_deadline_monotonic: float,
        claim_ack_abandoned: asyncio.Event,
    ) -> None:
        """Background pipeline running generation and verification within the 165s deadline."""
        room_id = room.id
        prep: QuizPreparation | None = None
        claim_acquired = False
        claim_token: UUID | None = None

        try:
            # Use an absolute loop-clock deadline measured when admission was
            # granted. Task scheduling or DB-thread startup cannot extend the
            # 165-second operation budget.
            async with asyncio.timeout_at(pipeline_deadline_monotonic):
                claim_result = await self._run_in_thread(
                    self._preparation_repository.claim_or_create_preparation,
                    room_id=room_id,
                    request_id=request_id,
                    model_id=MODEL_ID_GPT_6_LUNA,
                    lease_seconds=GENERATION_LEASE_SECONDS,
                )
                prep, claim_acquired = claim_result
                claim_ack_completed_before_deadline = (
                    asyncio.get_running_loop().time() < claim_ack_deadline_monotonic
                )

                # Resolve early claim acknowledgment immediately with durable DB state
                if not claim_ack_future.done():
                    claim_ack_future.set_result(prep)

                if not claim_acquired:
                    # Existing READY, terminal, or live claim owned elsewhere
                    return

                claim_token = prep.claim_token
                attempt = prep.generation_attempt

                if claim_token is None:
                    raise PreparationConflictError

                async def _fail_late_claim_if_needed() -> bool:
                    if (
                        not claim_ack_abandoned.is_set()
                        and claim_ack_completed_before_deadline
                    ):
                        return False
                    await self._run_in_thread(
                        self._preparation_repository.mark_preparation_failed_cas,
                        preparation_id=prep.id,
                        request_id=request_id,
                        claim_token=claim_token,
                        error_category="claim_ack_timeout",
                    )
                    await self._notify_terminal(room_id, prep.id)
                    return True

                if await _fail_late_claim_if_needed():
                    return

                # Publish durable GENERATING phase immediately
                if self._on_claimed is not None:
                    try:
                        await self._on_claimed(room_id, prep)
                    except Exception:
                        logger.warning("Preparation claimed hook failed")

                if await _fail_late_claim_if_needed():
                    return

                # Gather repeat exclusions
                exclusion_prompts = await self._run_in_thread(
                    self._preparation_repository.get_recent_exclusion_prompts,
                    host_id=room.owner_id,
                    quiz_subject=getattr(room, "quiz_subject", "") or "physics",
                    quiz_topic=getattr(room, "quiz_topic", "") or "forces",
                    exclude_preparation_id=prep.id,
                )

                target_marks = getattr(room, "target_total_marks", None) or 20
                subject = getattr(room, "quiz_subject", None) or "physics"
                topic = getattr(room, "quiz_topic", None) or "forces"
                level = getattr(room, "education_level", None) or "GCSE"

                request = GenerationRequest(
                    education_level=level,
                    quiz_subject=subject,
                    quiz_topic=topic,
                    target_total_marks=target_marks,
                    exclusion_prompts=exclusion_prompts,
                )

                if await _fail_late_claim_if_needed():
                    return

                async def _renew_source_lease(lease_seconds: int) -> bool:
                    return await self._run_in_thread(
                        self._preparation_repository.renew_preparation_lease_cas,
                        preparation_id=prep.id,
                        request_id=request_id,
                        claim_token=claim_token,
                        lease_seconds=lease_seconds,
                    )

                try:
                    verified_set = await generate_verified_quiz(
                        request=request,
                        generator=self._generator,
                        verifier=self._verifier,
                        deadline_at=pipeline_deadline,
                        deadline_monotonic=pipeline_deadline_monotonic,
                        renew_lease=_renew_source_lease,
                        event_logger=logger,
                    )
                except VerifiedGenerationFailure as error:
                    await self._run_in_thread(
                        self._preparation_repository.mark_preparation_failed_cas,
                        preparation_id=prep.id,
                        request_id=request_id,
                        claim_token=claim_token,
                        error_category=error.category,
                    )
                    await self._notify_terminal(room_id, prep.id)
                    return

                # --- CAS Commit with Verification Proof ---
                await self._run_in_thread(
                    self._preparation_repository.store_generated_questions_cas,
                    preparation_id=prep.id,
                    request_id=request_id,
                    claim_token=claim_token,
                    attempt=attempt,
                    verified_quiz_set=verified_set,
                    operation_deadline=pipeline_deadline,
                )
                await self._notify_terminal(room_id, prep.id)

        except AiGenerationUnavailableError as exc:
            if not claim_ack_future.done():
                claim_ack_future.set_exception(exc)
            raise
        except (TimeoutError, asyncio.TimeoutError):
            if not claim_ack_future.done():
                claim_ack_future.set_exception(PreparationFailedError)
            if prep is not None and claim_acquired and claim_token is not None:
                await self._run_in_thread(
                    self._preparation_repository.mark_preparation_failed_cas,
                    preparation_id=prep.id,
                    request_id=request_id,
                    claim_token=claim_token,
                    error_category="timeout",
                )
                await self._notify_terminal(room_id, prep.id)
        except Exception as exc:
            if not claim_ack_future.done():
                if isinstance(
                    exc,
                    (
                        RoomNotFoundError,
                        RoomClosedError,
                        RoomOwnerRequiredError,
                        InvalidRoomDataError,
                        PreparationConflictError,
                    ),
                ):
                    claim_ack_future.set_exception(exc)
                else:
                    claim_ack_future.set_exception(PreparationFailedError)
            logger.warning("Unexpected failure in background preparation task")
            if prep is not None and claim_acquired and claim_token is not None:
                await self._run_in_thread(
                    self._preparation_repository.mark_preparation_failed_cas,
                    preparation_id=prep.id,
                    request_id=request_id,
                    claim_token=claim_token,
                    error_category="internal_error",
                )
                await self._notify_terminal(room_id, prep.id)

    async def _notify_terminal(self, room_id: UUID, preparation_id: UUID) -> None:
        """Broadcast terminal state (READY or FAILED) to room sockets even if caller disconnected."""
        try:
            final_prep = await self._run_in_thread(self._preparation_repository.get_by_id, preparation_id)
            if (
                final_prep is not None
                and final_prep.status.value
                in {"READY", "FAILED", "CONSUMED", "SUPERSEDED"}
                and self._on_terminal is not None
            ):
                await self._on_terminal(room_id, final_prep)
        except Exception:
            logger.warning("Terminal preparation broadcast failed")

    async def _authoritative_outcome(self, room_id: UUID, preparation_id: UUID) -> QuizPreparation:
        """A lost CAS must never masquerade as a successful generation."""
        room = await self._run_in_thread(self._room_repository.get_by_id, room_id)
        if room is None:
            raise RoomNotFoundError
        if room.closed_at is not None:
            raise RoomClosedError
        current = await self._run_in_thread(self._preparation_repository.get_by_id, preparation_id)
        if current is None:
            raise PreparationFailedError
        if current.status == "GENERATING":
            raise PreparationConflictError
        if current.status == "FAILED" and current.error_category == "ai_generation_unavailable":
            raise AiGenerationUnavailableError
        return current
