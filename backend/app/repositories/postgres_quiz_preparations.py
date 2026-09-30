"""PostgreSQL implementation of QuizPreparationRepository with CAS and leases."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.generated_quiz_question import GeneratedQuizQuestionModel
from app.db.models.quiz_preparation import QuizPreparationModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.domain.adaptive_quiz import PreparationStatus, QuestionType
from app.domain.errors import (
    InvalidRoomDataError,
    PreparationConflictError,
    RoomClosedError,
    RoomNotFoundError,
    SessionAlreadyActiveError,
)
from app.domain.quiz_preparation import GeneratedQuestion, QuizPreparation
from app.generator.protocol import (
    GENERATION_LEASE_SECONDS,
    GeneratedQuestionData,
    GeneratorValidationError,
    MAX_EXCLUSION_BYTES,
    MAX_EXCLUSION_PROMPTS,
)
from app.generator.validation import validate_generated_quiz_set
from app.generator.verification.protocol import (
    VERIFICATION_REVISION,
    VerifiedQuizSet,
    compute_verified_content_digest,
)
from app.repositories.quiz_preparations import QuizPreparationRepository
_ACTIVE_SESSION_STATUSES = ("QUESTION_OPEN", "QUESTION_GRADING", "QUESTION_REVEAL")


def _interleave_recent_exclusion_prompts(
    recent_preparation_ids: Sequence[UUID],
    prompt_rows: Sequence[tuple[UUID, int, str]],
) -> tuple[str, ...]:
    """Balance same-topic exclusions across the already-selected recent preparations."""
    prompts_by_preparation: dict[UUID, list[tuple[int, str]]] = {
        preparation_id: [] for preparation_id in recent_preparation_ids
    }
    for preparation_id, position, prompt in prompt_rows:
        if preparation_id in prompts_by_preparation:
            prompts_by_preparation[preparation_id].append((position, prompt))

    for prompts in prompts_by_preparation.values():
        prompts.sort(key=lambda item: item[0])

    ordered: list[str] = []
    max_questions = max(
        (len(prompts) for prompts in prompts_by_preparation.values()),
        default=0,
    )
    for question_index in range(max_questions):
        for preparation_id in recent_preparation_ids:
            prompts = prompts_by_preparation[preparation_id]
            if question_index < len(prompts):
                ordered.append(prompts[question_index][1])
    return tuple(ordered)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _database_clock(session: Session) -> datetime:
    val = session.scalar(select(func.clock_timestamp()))
    if not isinstance(val, datetime):
        raise RuntimeError("Database clock unavailable")
    return _to_utc(val)


def _map_question_model_to_domain(model: GeneratedQuizQuestionModel) -> GeneratedQuestion:
    return GeneratedQuestion(
        id=model.id,
        preparation_id=model.preparation_id,
        position=model.position,
        question_type=QuestionType(model.question_type),
        prompt=model.prompt,
        max_marks=model.max_marks,
        duration_seconds=model.duration_seconds,
        options=tuple(model.options),
        correct_option_id=model.correct_option_id,
        grading_rubric=dict(model.grading_rubric),
        worked_explanation=model.worked_explanation,
        original_extract=model.original_extract,
        content_fingerprint=model.content_fingerprint,
        created_at=_to_utc(model.created_at),
    )


def _lock_preparation(
    session: Session, preparation_id: UUID, *, skip_locked: bool = False,
) -> QuizPreparationModel | None:
    # The first lookup supplies only a parent ID, never authoritative state.
    room_id = session.scalar(select(QuizPreparationModel.room_id).where(
        QuizPreparationModel.id == preparation_id
    ))
    if room_id is None:
        return None
    room = session.scalar(select(RoomModel).where(RoomModel.id == room_id)
                          .with_for_update(skip_locked=skip_locked))
    if room is None or room.closed_at is not None or room.quiz_mode != "ADAPTIVE":
        return None
    prep = session.scalar(select(QuizPreparationModel).where(
        QuizPreparationModel.id == preparation_id,
        QuizPreparationModel.room_id == room.id,
    ).with_for_update(skip_locked=skip_locked))
    if prep is None or session.scalar(select(QuizSessionModel.id).where(
        QuizSessionModel.room_id == room.id,
        QuizSessionModel.status.in_(_ACTIVE_SESSION_STATUSES),
    ).limit(1)) is not None:
        return None
    return prep


def _map_preparation_model_to_domain(
    model: QuizPreparationModel,
    questions: Sequence[GeneratedQuizQuestionModel] = (),
) -> QuizPreparation:
    return QuizPreparation(
        id=model.id,
        room_id=model.room_id,
        request_id=model.request_id,
        status=PreparationStatus(model.status),
        state_version=model.state_version,
        generation_attempt=model.generation_attempt,
        claim_token=model.claim_token,
        lease_expires_at=_to_utc(model.lease_expires_at) if model.lease_expires_at else None,
        model_id=model.model_id,
        error_category=model.error_category,
        created_at=_to_utc(model.created_at),
        updated_at=_to_utc(model.updated_at),
        ready_at=_to_utc(model.ready_at) if model.ready_at else None,
        consumed_at=_to_utc(model.consumed_at) if model.consumed_at else None,
        verification_revision=model.verification_revision,
        verified_content_digest=model.verified_content_digest,
        questions=tuple(_map_question_model_to_domain(q) for q in questions),
    )


class PostgresQuizPreparationRepository(QuizPreparationRepository):
    """Manage durable quiz preparations and generated question definitions in PostgreSQL."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_by_id(self, preparation_id: UUID) -> QuizPreparation | None:
        with self._session_factory() as session:
            prep = session.scalar(
                select(QuizPreparationModel).where(QuizPreparationModel.id == preparation_id)
            )
            if prep is None:
                return None
            questions = session.scalars(
                select(GeneratedQuizQuestionModel)
                .where(GeneratedQuizQuestionModel.preparation_id == preparation_id)
                .order_by(GeneratedQuizQuestionModel.position)
            ).all()
            return _map_preparation_model_to_domain(prep, questions)

    def get_by_room_and_request_id(
        self,
        room_id: UUID,
        request_id: UUID,
    ) -> QuizPreparation | None:
        with self._session_factory() as session:
            prep = session.scalar(
                select(QuizPreparationModel).where(
                    QuizPreparationModel.room_id == room_id,
                    QuizPreparationModel.request_id == request_id,
                )
            )
            if prep is None:
                return None
            questions = session.scalars(
                select(GeneratedQuizQuestionModel)
                .where(GeneratedQuizQuestionModel.preparation_id == prep.id)
                .order_by(GeneratedQuizQuestionModel.position)
            ).all()
            return _map_preparation_model_to_domain(prep, questions)

    def get_active_for_room(self, room_id: UUID) -> QuizPreparation | None:
        with self._session_factory() as session:
            prep = session.scalar(
                select(QuizPreparationModel).where(
                    QuizPreparationModel.room_id == room_id,
                    QuizPreparationModel.status.in_(["GENERATING", "READY"]),
                )
            )
            if prep is None:
                return None
            questions = session.scalars(
                select(GeneratedQuizQuestionModel)
                .where(GeneratedQuizQuestionModel.preparation_id == prep.id)
                .order_by(GeneratedQuizQuestionModel.position)
            ).all()
            return _map_preparation_model_to_domain(prep, questions)

    def claim_or_create_preparation(
        self,
        room_id: UUID,
        request_id: UUID,
        model_id: str,
        lease_seconds: int = GENERATION_LEASE_SECONDS,
    ) -> tuple[QuizPreparation, bool]:
        with self._session_factory() as session:
            with session.begin():
                room = session.scalar(
                    select(RoomModel)
                    .where(RoomModel.id == room_id)
                    .with_for_update()
                )
                if room is None:
                    raise RoomNotFoundError
                if room.closed_at is not None:
                    raise RoomClosedError
                if room.quiz_mode != "ADAPTIVE":
                    raise InvalidRoomDataError(
                        "Quiz preparation requires an adaptive room."
                    )

                # Active session check
                active_session = session.scalar(
                    select(QuizSessionModel).where(
                        QuizSessionModel.room_id == room_id,
                        QuizSessionModel.status.in_(_ACTIVE_SESSION_STATUSES),
                    )
                )
                if active_session is not None:
                    raise SessionAlreadyActiveError

                # Check for existing preparation with this request_id
                existing = session.scalar(
                    select(QuizPreparationModel)
                    .where(
                        QuizPreparationModel.room_id == room_id,
                        QuizPreparationModel.request_id == request_id,
                    )
                    .with_for_update()
                )

                now = _database_clock(session)
                lease_deadline = now + timedelta(seconds=lease_seconds)
                if existing is not None:
                    if existing.status == "READY":
                        questions = session.scalars(
                            select(GeneratedQuizQuestionModel)
                            .where(GeneratedQuizQuestionModel.preparation_id == existing.id)
                            .order_by(GeneratedQuizQuestionModel.position)
                        ).all()
                        return _map_preparation_model_to_domain(existing, questions), False

                    if existing.status in ("FAILED", "CONSUMED", "SUPERSEDED"):
                        # Terminal state for this request ID: return the
                        # durable outcome and never launch another paid call.
                        questions = session.scalars(
                            select(GeneratedQuizQuestionModel)
                            .where(GeneratedQuizQuestionModel.preparation_id == existing.id)
                            .order_by(GeneratedQuizQuestionModel.position)
                        ).all()
                        return _map_preparation_model_to_domain(existing, questions), False

                    if (
                        existing.status == "GENERATING"
                        and existing.lease_expires_at is not None
                        and existing.lease_expires_at > now
                    ):
                        # Live claim owned by another worker (possibly this
                        # process on a concurrent retry): observe only. The
                        # token is never handed out for a second paid call.
                        return _map_preparation_model_to_domain(existing), False

                    # Reclaim only an expired GENERATING preparation.
                    new_token = uuid4()
                    existing.status = "GENERATING"
                    existing.generation_attempt += 1
                    existing.claim_token = new_token
                    existing.lease_expires_at = lease_deadline
                    existing.updated_at = now
                    existing.error_category = None
                    existing.state_version += 1
                    session.flush()
                    return _map_preparation_model_to_domain(existing), True

                # Check if another preparation is active in this room
                other_active = session.scalar(
                    select(QuizPreparationModel)
                    .where(
                        QuizPreparationModel.room_id == room_id,
                        QuizPreparationModel.status.in_(["GENERATING", "READY"]),
                    )
                    .with_for_update()
                )
                now = _database_clock(session)
                lease_deadline = now + timedelta(seconds=lease_seconds)
                if other_active is not None:
                    if other_active.status == "READY" or (
                        other_active.lease_expires_at is not None
                        and other_active.lease_expires_at > now
                    ):
                        raise PreparationConflictError
                    # If other is expired GENERATING, mark SUPERSEDED
                    other_active.status = "SUPERSEDED"
                    other_active.claim_token = None
                    other_active.lease_expires_at = None
                    other_active.updated_at = now
                    other_active.state_version += 1
                    session.flush()

                # Create new preparation row. state_version is monotonic
                # room-wide across rows so clients comparing versions never
                # treat a fresh rematch GENERATING as stale next to an older
                # READY/CONSUMED row: the new row starts above every prior
                # version and every transition still increments.
                max_version = session.scalar(
                    select(func.max(QuizPreparationModel.state_version)).where(
                        QuizPreparationModel.room_id == room_id
                    )
                )
                new_token = uuid4()
                prep = QuizPreparationModel(
                    id=uuid4(),
                    room_id=room_id,
                    request_id=request_id,
                    status="GENERATING",
                    state_version=(max_version or 0) + 1,
                    generation_attempt=1,
                    claim_token=new_token,
                    lease_expires_at=lease_deadline,
                    model_id=model_id,
                    error_category=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(prep)
                session.flush()
                return _map_preparation_model_to_domain(prep), True

    def store_generated_questions_cas(
        self,
        preparation_id: UUID,
        request_id: UUID,
        claim_token: UUID,
        attempt: int,
        verified_quiz_set: VerifiedQuizSet,
        operation_deadline: datetime,
    ) -> bool:
        # 1. Pre-transaction validation of proof:
        # Require typed VerifiedQuizSet, current revision, and verify content digest
        if type(verified_quiz_set) is not VerifiedQuizSet:
            raise ValueError("store_generated_questions_cas requires a typed VerifiedQuizSet.")
        if verified_quiz_set.verification_revision != VERIFICATION_REVISION:
            raise ValueError("store_generated_questions_cas requires current verification revision.")

        questions = verified_quiz_set.candidate_questions
        if not questions:
            raise ValueError("VerifiedQuizSet contains no questions.")

        computed_digest = compute_verified_content_digest(questions, VERIFICATION_REVISION)
        if verified_quiz_set.verified_content_digest != computed_digest:
            raise ValueError("VerifiedQuizSet content digest does not match candidate questions.")

        with self._session_factory() as session:
            with session.begin():
                prep = _lock_preparation(session, preparation_id)
                if prep is None:
                    return False

                room = session.scalar(
                    select(RoomModel)
                    .where(RoomModel.id == prep.room_id)
                    .with_for_update()
                )
                if room is None or room.target_total_marks is None:
                    return False

                now = _database_clock(session)
                # Authoritative post-lock deadline and ownership checks run
                # before any local validation or insert work. A late or
                # superseded provider result is a no-op, even if its payload
                # is malformed.
                if now >= operation_deadline:
                    return False
                if (
                    prep.status != "GENERATING"
                    or prep.request_id != request_id
                    or prep.claim_token != claim_token
                    or prep.generation_attempt != attempt
                    or prep.lease_expires_at is None
                    or prep.lease_expires_at <= now
                ):
                    return False

                # The typed proof is necessary but not sufficient: re-run the
                # complete local validator at the persistence trust boundary
                # so alternate verifiers/adapters cannot create READY content
                # with a malformed rubric, marks, duration, or duplicate.
                try:
                    validated_questions = validate_generated_quiz_set(
                        questions,
                        target_total_marks=room.target_total_marks,
                    )
                except GeneratorValidationError:
                    raise ValueError("Verified quiz content failed local validation.") from None
                validated_digest = compute_verified_content_digest(
                    validated_questions,
                    VERIFICATION_REVISION,
                )
                if validated_digest != verified_quiz_set.verified_content_digest:
                    raise ValueError("Verified quiz content changed during local validation.")

                # Insert question models
                for q in validated_questions:
                    session.add(
                        GeneratedQuizQuestionModel(
                            id=uuid4(),
                            preparation_id=preparation_id,
                            position=q.position,
                            question_type=q.question_type.value,
                            prompt=q.prompt,
                            max_marks=q.max_marks,
                            duration_seconds=q.duration_seconds,
                            options=[opt.to_dict() for opt in q.options],
                            correct_option_id=q.correct_option_id,
                            grading_rubric=q.grading_rubric,
                            worked_explanation=q.worked_explanation,
                            original_extract=q.original_extract,
                            content_fingerprint=q.content_fingerprint,
                            created_at=now,
                        )
                    )

                prep.status = "READY"
                prep.verification_revision = verified_quiz_set.verification_revision
                prep.verified_content_digest = verified_quiz_set.verified_content_digest
                prep.ready_at = now
                prep.updated_at = now
                prep.claim_token = None
                prep.lease_expires_at = None
                prep.error_category = None
                prep.state_version += 1
                session.flush()
                return True

    def mark_preparation_failed_cas(
        self,
        preparation_id: UUID,
        request_id: UUID,
        claim_token: UUID,
        error_category: str,
    ) -> bool:
        with self._session_factory() as session:
            with session.begin():
                prep = _lock_preparation(session, preparation_id)
                if prep is None:
                    return False

                now = _database_clock(session)
                if (
                    prep.request_id != request_id
                    or prep.claim_token != claim_token
                    or prep.status != "GENERATING"
                    or prep.lease_expires_at is None
                    or prep.lease_expires_at <= now
                ):
                    return False

                prep.status = "FAILED"
                prep.error_category = error_category
                prep.claim_token = None
                prep.lease_expires_at = None
                prep.updated_at = now
                prep.state_version += 1
                session.flush()
                return True

    def renew_preparation_lease_cas(
        self,
        preparation_id: UUID,
        request_id: UUID,
        claim_token: UUID,
        lease_seconds: int = GENERATION_LEASE_SECONDS,
    ) -> bool:
        """Extend a live lease so the one permitted content retry stays covered."""
        if lease_seconds <= 0:
            return False
        with self._session_factory() as session:
            with session.begin():
                prep = _lock_preparation(session, preparation_id)
                if prep is None:
                    return False
                now = _database_clock(session)
                if (
                    prep.request_id != request_id
                    or prep.claim_token != claim_token
                    or prep.status != "GENERATING"
                    or prep.lease_expires_at is None
                    or prep.lease_expires_at <= now
                ):
                    return False
                prep.lease_expires_at = now + timedelta(seconds=lease_seconds)
                prep.updated_at = now
                prep.state_version += 1
                session.flush()
                return True

    def fail_expired_generating_preparations(
        self,
        limit: int = 20,
    ) -> tuple[QuizPreparation, ...]:
        """Recover crashed generation: expired GENERATING leases become FAILED.

        The safe retryable category lets a fresh client request UUID retry;
        no provider call is launched and no unbounded retry is scheduled.
        Live leases are untouched.
        """
        if limit < 1:
            return ()
        with self._session_factory() as session:
            candidates = session.scalars(select(QuizPreparationModel.id).where(
                QuizPreparationModel.status == "GENERATING",
                QuizPreparationModel.lease_expires_at <= func.clock_timestamp(),
            ).order_by(QuizPreparationModel.lease_expires_at, QuizPreparationModel.id)
              .limit(min(limit, 100))).all()
        recovered: list[QuizPreparation] = []
        # One parent/child pair per transaction: never retain one room while
        # acquiring another, and never wait for contended recovery work.
        for preparation_id in candidates:
            with self._session_factory() as session, session.begin():
                prep = _lock_preparation(session, preparation_id, skip_locked=True)
                now = _database_clock(session)
                if (prep is not None and prep.status == "GENERATING"
                    and prep.lease_expires_at is not None and prep.lease_expires_at <= now):
                    prep.status = "FAILED"
                    prep.error_category = "generation_lease_expired"
                    prep.claim_token = None
                    prep.lease_expires_at = None
                    prep.updated_at = now
                    prep.state_version += 1
                    recovered.append(_map_preparation_model_to_domain(prep))
                    session.flush()
        return tuple(recovered)

    def get_recent_exclusion_prompts(
        self,
        host_id: UUID,
        quiz_subject: str,
        quiz_topic: str,
        exclude_preparation_id: UUID | None = None,
    ) -> tuple[str, ...]:
        with self._session_factory() as session:
            # Find up to 3 most recent READY/CONSUMED preparations for this host/subject/topic
            conditions = [
                RoomModel.owner_id == host_id,
                RoomModel.quiz_subject == quiz_subject,
                RoomModel.quiz_topic == quiz_topic,
                QuizPreparationModel.status.in_(["READY", "CONSUMED"]),
            ]
            if exclude_preparation_id is not None:
                conditions.append(QuizPreparationModel.id != exclude_preparation_id)

            recent_prep_ids = session.scalars(
                select(QuizPreparationModel.id)
                .join(RoomModel, RoomModel.id == QuizPreparationModel.room_id)
                .where(*conditions)
                .order_by(QuizPreparationModel.created_at.desc())
                .limit(3)
            ).all()

            if not recent_prep_ids:
                return ()

            # Fetch only prompts from the three preparations already selected
            # for this same host, subject, and topic. Round-robin ordering below
            # prevents one longer preparation from consuming the whole bound.
            prompt_rows = session.execute(
                select(
                    GeneratedQuizQuestionModel.preparation_id,
                    GeneratedQuizQuestionModel.position,
                    GeneratedQuizQuestionModel.prompt,
                )
                .where(GeneratedQuizQuestionModel.preparation_id.in_(recent_prep_ids))
                .order_by(
                    GeneratedQuizQuestionModel.preparation_id,
                    GeneratedQuizQuestionModel.position,
                )
            ).all()
            prompts = _interleave_recent_exclusion_prompts(
                recent_prep_ids,
                tuple((row[0], row[1], row[2]) for row in prompt_rows),
            )

            bounded_prompts: list[str] = []
            total_bytes = 0
            for p in prompts:
                if len(bounded_prompts) >= MAX_EXCLUSION_PROMPTS:
                    break
                p_bytes = len(p.encode("utf-8"))
                if total_bytes + p_bytes > MAX_EXCLUSION_BYTES:
                    break
                total_bytes += p_bytes
                bounded_prompts.append(p)

            return tuple(bounded_prompts)
