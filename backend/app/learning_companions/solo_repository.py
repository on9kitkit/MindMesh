"""PostgreSQL authority for owner-scoped, self-paced solo attempts.

All completion receipts are inserted in the same transaction as FINISHED.
The receipt has no user/source FK, so an attempt lock never takes a user FK
lock after account deletion has taken the user lock. See foundation contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.membership import RoomMembershipModel
from app.db.models.room import RoomModel
from app.db.models.user import UserModel
from app.domain.adaptive_quiz import (
    MultipleChoiceOption,
    NumericalRubric,
    QuestionType,
    WrittenRubric,
    calculate_question_duration_seconds,
    grade_multiple_choice,
    grade_numerical,
)
from app.generator.protocol import GeneratedQuestionData, GeneratorValidationError
from app.generator.validation import validate_generated_quiz_set
from app.generator.verification.protocol import (
    VERIFICATION_REVISION,
    VerifiedQuizSet,
    compute_verified_content_digest,
)
from app.learning_companions.contracts import (
    CompletionEvidence,
    CompletionSource,
    LockedSelfCheck,
    MarkProvenance,
    REWARD_RULE_VERSION,
    SelfCheckCriterion,
    SoloAttemptStatus,
    SoloCreateRequest,
    resolve_self_check,
)
from app.learning_companions.models import (
    CompletionReceiptModel,
    LearningSettingsModel,
    SoloAnswerModel,
    SoloAttemptModel,
    SoloPreparationModel,
    SoloQuestionModel,
    SoloSelfCheckModel,
)
from app.learning_companions.solo_domain import (
    ACTIVE_ATTEMPT,
    ACTIVE_ROOM,
    CONFLICT,
    MARKING_PENDING,
    NOT_FOUND,
    NOT_READY,
    ZONE_REQUIRED,
    ClaimedSoloGrade,
    PreparationClaim,
    PublicSoloQuestion,
    SoloAnswerState,
    SoloAttemptState,
    SoloOption,
    SoloReview,
    SoloReviewQuestion,
)


_ACTIVE = ("PREPARING", "READY", "IN_PROGRESS", "AWAITING_MARKING")
_TERMINAL = ("FINISHED", "ABANDONED", "FAILED")


def _clock(session: Session) -> datetime:
    return session.scalar(select(func.clock_timestamp()))


def _attempt(session: Session, owner_id: UUID, attempt_id: UUID, *, lock: bool = False) -> SoloAttemptModel:
    statement = select(SoloAttemptModel).where(
        SoloAttemptModel.id == attempt_id,
        SoloAttemptModel.owner_id == owner_id,
    )
    if lock:
        statement = statement.with_for_update()
    attempt = session.scalar(statement)
    if attempt is None:
        raise NOT_FOUND
    return attempt


def _has_active_room(session: Session, owner_id: UUID) -> bool:
    return session.scalar(
        select(RoomMembershipModel.id)
        .join(RoomModel, RoomModel.id == RoomMembershipModel.room_id)
        .where(
            RoomMembershipModel.user_id == owner_id,
            RoomMembershipModel.left_at.is_(None),
            RoomModel.closed_at.is_(None),
        )
        .limit(1)
    ) is not None


def _public_question(question: SoloQuestionModel) -> PublicSoloQuestion:
    return PublicSoloQuestion(
        id=question.id,
        position=question.position,
        question_type=question.question_type,
        max_marks=question.max_marks,
        prompt=question.prompt_snapshot,
        options=tuple(SoloOption(id=option["id"], label=option["label"]) for option in question.options_snapshot),
        original_extract=question.original_extract,
    )


def _answer_state(answer: SoloAnswerModel) -> SoloAnswerState:
    return SoloAnswerState(
        question_id=answer.question_id,
        selected_option_id=answer.selected_option_id,
        answer_text=answer.answer_text,
        accepted_at=answer.accepted_at,
        grading_status=answer.grading_status,
        mark_provenance=MarkProvenance(answer.mark_provenance),
        earned_marks=answer.earned_marks,
        feedback=dict(answer.feedback),
    )


def _state(session: Session, attempt: SoloAttemptModel) -> SoloAttemptState:
    visible = attempt.status in ("IN_PROGRESS", "AWAITING_MARKING", "FINISHED")
    questions = tuple(session.scalars(
        select(SoloQuestionModel).where(SoloQuestionModel.attempt_id == attempt.id)
        .order_by(SoloQuestionModel.position)
    )) if visible else ()
    answers = tuple(session.scalars(
        select(SoloAnswerModel).where(SoloAnswerModel.attempt_id == attempt.id)
        .order_by(SoloAnswerModel.accepted_at, SoloAnswerModel.id)
    )) if visible else ()
    return SoloAttemptState(
        id=attempt.id,
        request_id=attempt.request_id,
        status=SoloAttemptStatus(attempt.status),
        state_version=attempt.state_version,
        subject=attempt.subject,
        topic=attempt.topic,
        total_marks=attempt.total_marks,
        current_question_position=attempt.current_question_position,
        created_at=attempt.created_at,
        started_at=attempt.started_at,
        terminal_at=attempt.terminal_at,
        questions=tuple(_public_question(question) for question in questions),
        answers=tuple(_answer_state(answer) for answer in answers),
    )


def _locked_self_check(question: SoloQuestionModel, answer: SoloAnswerModel) -> LockedSelfCheck:
    if question.question_type != QuestionType.WRITTEN.value or not 1 <= question.max_marks <= 4:
        raise CONFLICT
    rubric = WrittenRubric.from_dict(question.grading_rubric_snapshot)
    return LockedSelfCheck(
        question_id=question.id,
        locked_answer=answer.answer_text or "",
        intended_answer=question.worked_explanation_snapshot,
        max_marks=question.max_marks,
        criteria=tuple(
            SelfCheckCriterion(
                id=criterion.id,
                marks=criterion.marks,
                marking_point=criterion.marking_point,
                explanation=criterion.explanation,
            )
            for criterion in rubric.criteria
        ),
    )


def _reconcile_completion(session: Session, attempt: SoloAttemptModel, now: datetime) -> None:
    """Under attempt lock, finalize once and persist trusted coverage proof."""
    if attempt.status in _TERMINAL:
        return
    questions = tuple(session.scalars(
        select(SoloQuestionModel).where(SoloQuestionModel.attempt_id == attempt.id)
        .order_by(SoloQuestionModel.position)
    ))
    if not questions or attempt.current_question_position < len(questions):
        return
    answers = tuple(session.scalars(
        select(SoloAnswerModel).where(SoloAnswerModel.attempt_id == attempt.id)
    ))
    canonical_ids = {question.id for question in questions}
    accepted_ids = {answer.question_id for answer in answers}
    if len(canonical_ids) != len(questions) or accepted_ids != canonical_ids:
        return
    if any(answer.grading_status != "GRADED" for answer in answers):
        if attempt.status != "AWAITING_MARKING":
            attempt.status = "AWAITING_MARKING"
            attempt.state_version += 1
        return
    required_self_checks = {answer.id for answer in answers if answer.mark_provenance == "SELF_ASSESSED"}
    if required_self_checks:
        finalized_self_checks = set(session.scalars(select(SoloSelfCheckModel.answer_id).where(
            SoloSelfCheckModel.answer_id.in_(required_self_checks)
        )))
        if finalized_self_checks != required_self_checks:
            return
    evidence = CompletionEvidence(
        user_id=attempt.owner_id,
        source_kind=CompletionSource.SOLO,
        source_id=attempt.id,
        terminal_state="FINISHED",
        canonical_question_count=len(questions),
        distinct_accepted_answer_count=len(accepted_ids),
        latest_original_accepted_at_utc=max(answer.accepted_at for answer in answers),
        home_timezone_snapshot=attempt.home_timezone_snapshot,
        home_zone_version=attempt.home_zone_version,
        completed_at_utc=now,
        completion_state_version=attempt.state_version + 1,
        reward_rule_version=attempt.reward_rule_version,
    )
    attempt.status = "FINISHED"
    attempt.terminal_at = now
    attempt.state_version += 1
    session.add(CompletionReceiptModel(
        id=uuid4(),
        user_id=evidence.user_id,
        source_kind=evidence.source_kind.value,
        source_id=evidence.source_id,
        terminal_state=evidence.terminal_state,
        canonical_question_count=evidence.canonical_question_count,
        accepted_answer_count=evidence.distinct_accepted_answer_count,
        latest_accepted_at=evidence.latest_original_accepted_at_utc,
        home_timezone_snapshot=evidence.home_timezone_snapshot,
        home_zone_version=evidence.home_zone_version,
        study_date=evidence.study_date,
        completed_at=evidence.completed_at_utc,
        completion_state_version=evidence.completion_state_version,
        reward_rule_version=evidence.reward_rule_version,
        status="pending",
        created_at=now,
    ))


class PostgresSoloRepository:
    """Transactional repository; all public lookups scope the authenticated owner."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def claim_or_create(
        self, owner_id: UUID, request: SoloCreateRequest, *, model_id: str, lease_seconds: int
    ) -> PreparationClaim:
        with self._session_factory() as session, session.begin():
            # User-first lock is shared with account deletion; source updates
            # later never acquire a user FK lock via the answer-free receipt.
            user = session.scalar(select(UserModel).where(UserModel.id == owner_id).with_for_update())
            if user is None or user.deleted_at is not None or user.suspended_at is not None:
                raise NOT_FOUND
            settings = session.get(LearningSettingsModel, owner_id)
            if settings is None:
                raise ZONE_REQUIRED
            now = _clock(session)
            existing = session.scalar(select(SoloAttemptModel).where(
                SoloAttemptModel.owner_id == owner_id,
                SoloAttemptModel.request_id == request.request_id,
            ).with_for_update())
            if existing is not None:
                if (existing.subject, existing.topic, existing.total_marks) != (
                    request.subject, request.topic, request.total_marks
                ):
                    raise CONFLICT
                prep = session.scalar(select(SoloPreparationModel).where(
                    SoloPreparationModel.attempt_id == existing.id
                ).with_for_update())
                if prep is None:
                    raise CONFLICT
                claim = False
                if (
                    existing.status == "PREPARING"
                    and prep.status == "GENERATING"
                    and (prep.lease_expires_at is None or prep.lease_expires_at <= now)
                ):
                    prep.claim_token = uuid4()
                    prep.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    prep.generation_attempt += 1
                    prep.state_version += 1
                    prep.updated_at = now
                    claim = True
                return PreparationClaim(
                    _state(session, existing), prep.id, prep.claim_token,
                    prep.generation_attempt, prep.lease_expires_at, claim,
                )
            if _has_active_room(session, owner_id):
                raise ACTIVE_ROOM
            other = session.scalar(select(SoloAttemptModel.id).where(
                SoloAttemptModel.owner_id == owner_id, SoloAttemptModel.status.in_(_ACTIVE)
            ).limit(1))
            if other is not None:
                raise ACTIVE_ATTEMPT
            attempt = SoloAttemptModel(
                id=uuid4(), owner_id=owner_id, request_id=request.request_id,
                status="PREPARING", state_version=1, education_level="GCSE",
                subject=request.subject, topic=request.topic, total_marks=request.total_marks,
                current_question_position=0,
                home_timezone_snapshot=settings.home_timezone,
                home_zone_version=settings.home_zone_version,
                reward_rule_version=REWARD_RULE_VERSION,
                created_at=now,
            )
            token = uuid4()
            prep = SoloPreparationModel(
                id=uuid4(), attempt_id=attempt.id, status="GENERATING",
                state_version=1, generation_attempt=1, claim_token=token,
                lease_expires_at=now + timedelta(seconds=lease_seconds), model_id=model_id,
                created_at=now, updated_at=now,
            )
            session.add(attempt)
            session.add(prep)
            session.flush()
            return PreparationClaim(_state(session, attempt), prep.id, token, 1, prep.lease_expires_at, True)

    def get_by_request(self, owner_id: UUID, request_id: UUID) -> SoloAttemptState | None:
        with self._session_factory() as session:
            attempt = session.scalar(select(SoloAttemptModel).where(
                SoloAttemptModel.owner_id == owner_id, SoloAttemptModel.request_id == request_id
            ))
            return _state(session, attempt) if attempt is not None else None

    def get_active(self, owner_id: UUID) -> SoloAttemptState | None:
        with self._session_factory() as session:
            attempt = session.scalar(select(SoloAttemptModel).where(
                SoloAttemptModel.owner_id == owner_id, SoloAttemptModel.status.in_(_ACTIVE)
            ).order_by(SoloAttemptModel.created_at.desc()).limit(1))
            return _state(session, attempt) if attempt is not None else None

    def get_state(self, owner_id: UUID, attempt_id: UUID) -> SoloAttemptState:
        with self._session_factory() as session:
            return _state(session, _attempt(session, owner_id, attempt_id))

    def get_recent_exclusion_prompts(self, owner_id: UUID, subject: str, topic: str) -> tuple[str, ...]:
        with self._session_factory() as session:
            recent_ids = tuple(session.scalars(select(SoloAttemptModel.id).where(
                SoloAttemptModel.owner_id == owner_id,
                SoloAttemptModel.subject == subject, SoloAttemptModel.topic == topic,
                SoloAttemptModel.status == "FINISHED",
            ).order_by(SoloAttemptModel.terminal_at.desc()).limit(3)))
            if not recent_ids:
                return ()
            return tuple(session.scalars(select(SoloQuestionModel.prompt_snapshot).where(
                SoloQuestionModel.attempt_id.in_(recent_ids)
            ).order_by(SoloQuestionModel.created_at.desc(), SoloQuestionModel.position).limit(50)))

    def renew_preparation_lease(
        self, owner_id: UUID, attempt_id: UUID, preparation_id: UUID,
        claim_token: UUID, *, lease_seconds: int,
    ) -> bool:
        with self._session_factory() as session, session.begin():
            attempt = session.scalar(select(SoloAttemptModel).where(
                SoloAttemptModel.id == attempt_id, SoloAttemptModel.owner_id == owner_id,
            ).with_for_update())
            if attempt is None:
                return False
            prep = session.scalar(select(SoloPreparationModel).where(
                SoloPreparationModel.id == preparation_id,
                SoloPreparationModel.attempt_id == attempt_id,
            ).with_for_update())
            now = _clock(session)
            if (attempt.status != "PREPARING" or prep is None or prep.status != "GENERATING"
                or prep.claim_token != claim_token or prep.lease_expires_at is None
                or prep.lease_expires_at <= now):
                return False
            prep.lease_expires_at = now + timedelta(seconds=lease_seconds)
            prep.updated_at = now
            prep.state_version += 1
            return True

    def store_verified_set_cas(
        self, owner_id: UUID, attempt_id: UUID, preparation_id: UUID,
        claim_token: UUID, generation_attempt: int,
        verified_set: VerifiedQuizSet, operation_deadline: datetime,
    ) -> bool:
        if type(verified_set) is not VerifiedQuizSet or verified_set.verification_revision != VERIFICATION_REVISION:
            raise ValueError("Current typed verification proof is required.")
        questions = verified_set.candidate_questions
        if compute_verified_content_digest(questions, VERIFICATION_REVISION) != verified_set.verified_content_digest:
            raise ValueError("Verified content digest mismatch.")
        with self._session_factory() as session, session.begin():
            attempt = session.scalar(select(SoloAttemptModel).where(
                SoloAttemptModel.id == attempt_id, SoloAttemptModel.owner_id == owner_id,
            ).with_for_update())
            if attempt is None:
                return False
            prep = session.scalar(select(SoloPreparationModel).where(
                SoloPreparationModel.id == preparation_id,
                SoloPreparationModel.attempt_id == attempt_id,
            ).with_for_update())
            now = _clock(session)
            if (prep is None or attempt.status != "PREPARING" or prep.status != "GENERATING"
                or prep.claim_token != claim_token or prep.generation_attempt != generation_attempt
                or prep.lease_expires_at is None or prep.lease_expires_at <= now
                or now >= operation_deadline):
                return False
            try:
                validated = validate_generated_quiz_set(questions, target_total_marks=attempt.total_marks)
            except GeneratorValidationError:
                raise ValueError("Verified content failed local validation.") from None
            if compute_verified_content_digest(validated, VERIFICATION_REVISION) != verified_set.verified_content_digest:
                raise ValueError("Verified content changed during local validation.")
            for question in validated:
                session.add(SoloQuestionModel(
                    id=uuid4(), attempt_id=attempt_id, position=question.position,
                    question_type=question.question_type.value, max_marks=question.max_marks,
                    prompt_snapshot=question.prompt,
                    options_snapshot=[option.to_dict() for option in question.options],
                    correct_option_id=question.correct_option_id,
                    grading_rubric_snapshot=question.grading_rubric,
                    worked_explanation_snapshot=question.worked_explanation,
                    original_extract=question.original_extract,
                    content_fingerprint=question.content_fingerprint, created_at=now,
                ))
            prep.status = "READY"
            prep.claim_token = None
            prep.lease_expires_at = None
            prep.verification_revision = verified_set.verification_revision
            prep.verified_content_digest = verified_set.verified_content_digest
            prep.ready_at = now
            prep.updated_at = now
            prep.state_version += 1
            attempt.status = "READY"
            attempt.state_version += 1
            session.flush()
            return True

    def fail_preparation_cas(
        self, owner_id: UUID, attempt_id: UUID, preparation_id: UUID,
        claim_token: UUID, error_category: str,
    ) -> bool:
        with self._session_factory() as session, session.begin():
            attempt = session.scalar(select(SoloAttemptModel).where(
                SoloAttemptModel.id == attempt_id, SoloAttemptModel.owner_id == owner_id,
            ).with_for_update())
            if attempt is None:
                return False
            prep = session.scalar(select(SoloPreparationModel).where(
                SoloPreparationModel.id == preparation_id,
                SoloPreparationModel.attempt_id == attempt_id,
            ).with_for_update())
            if prep is None or prep.status != "GENERATING" or prep.claim_token != claim_token:
                return False
            now = _clock(session)
            prep.status = "FAILED"
            prep.claim_token = None
            prep.lease_expires_at = None
            prep.error_category = error_category
            prep.updated_at = now
            prep.state_version += 1
            if attempt.status == "PREPARING":
                attempt.status = "FAILED"
                attempt.terminal_at = now
                attempt.state_version += 1
            return True

    def fail_expired_preparations(self, *, limit: int = 20) -> int:
        """Release active slots after process loss without starting paid work."""
        with self._session_factory() as session:
            candidate_ids = tuple(session.scalars(select(SoloPreparationModel.attempt_id).where(
                SoloPreparationModel.status == "GENERATING",
            ).order_by(SoloPreparationModel.created_at).limit(min(limit, 100))))
        changed = 0
        for attempt_id in candidate_ids:
            with self._session_factory() as session, session.begin():
                attempt = session.scalar(select(SoloAttemptModel).where(
                    SoloAttemptModel.id == attempt_id
                ).with_for_update(skip_locked=True))
                if attempt is None or attempt.status != "PREPARING":
                    continue
                prep = session.scalar(select(SoloPreparationModel).where(
                    SoloPreparationModel.attempt_id == attempt_id
                ).with_for_update(skip_locked=True))
                now = _clock(session)
                if (prep is None or prep.status != "GENERATING"
                    or prep.lease_expires_at is None or prep.lease_expires_at > now):
                    continue
                prep.status = "FAILED"
                prep.claim_token = None
                prep.lease_expires_at = None
                prep.error_category = "generation_lease_expired"
                prep.updated_at = now
                prep.state_version += 1
                attempt.status = "FAILED"
                attempt.terminal_at = now
                attempt.state_version += 1
                changed += 1
        return changed

    def start(self, owner_id: UUID, attempt_id: UUID) -> SoloAttemptState:
        with self._session_factory() as session, session.begin():
            attempt = _attempt(session, owner_id, attempt_id, lock=True)
            if attempt.status in ("IN_PROGRESS", "AWAITING_MARKING", "FINISHED"):
                return _state(session, attempt)
            if attempt.status != "READY":
                raise NOT_READY
            if _has_active_room(session, owner_id):
                raise ACTIVE_ROOM
            prep = session.scalar(select(SoloPreparationModel).where(
                SoloPreparationModel.attempt_id == attempt_id
            ).with_for_update())
            if (prep is None or prep.status != "READY"
                or prep.verification_revision != VERIFICATION_REVISION
                or not prep.verified_content_digest):
                raise NOT_READY
            question_rows = tuple(session.scalars(select(SoloQuestionModel).where(
                SoloQuestionModel.attempt_id == attempt_id
            ).order_by(SoloQuestionModel.position)))
            if not question_rows:
                raise NOT_READY
            generated = tuple(GeneratedQuestionData(
                position=question.position,
                question_type=QuestionType(question.question_type),
                prompt=question.prompt_snapshot,
                max_marks=question.max_marks,
                duration_seconds=calculate_question_duration_seconds(question.max_marks),
                options=tuple(MultipleChoiceOption.from_dict(option) for option in question.options_snapshot),
                correct_option_id=question.correct_option_id,
                grading_rubric=question.grading_rubric_snapshot,
                worked_explanation=question.worked_explanation_snapshot,
                original_extract=question.original_extract,
                content_fingerprint=question.content_fingerprint,
            ) for question in question_rows)
            try:
                validated = validate_generated_quiz_set(generated, target_total_marks=attempt.total_marks)
            except GeneratorValidationError:
                raise NOT_READY from None
            if compute_verified_content_digest(validated, VERIFICATION_REVISION) != prep.verified_content_digest:
                raise NOT_READY
            now = _clock(session)
            prep.status = "CONSUMED"
            prep.consumed_at = now
            prep.updated_at = now
            prep.state_version += 1
            attempt.status = "IN_PROGRESS"
            attempt.started_at = now
            attempt.state_version += 1
            session.flush()
            return _state(session, attempt)

    def submit_answer(
        self, owner_id: UUID, attempt_id: UUID, question_id: UUID,
        selected_option_id: str | None, answer_text: str | None,
    ) -> SoloAnswerState:
        with self._session_factory() as session, session.begin():
            attempt = _attempt(session, owner_id, attempt_id, lock=True)
            question = session.scalar(select(SoloQuestionModel).where(
                SoloQuestionModel.id == question_id, SoloQuestionModel.attempt_id == attempt_id
            ))
            if question is None:
                raise NOT_FOUND
            existing = session.scalar(select(SoloAnswerModel).where(
                SoloAnswerModel.attempt_id == attempt_id,
                SoloAnswerModel.question_id == question_id,
            ))
            if existing is not None:
                if (existing.selected_option_id, existing.answer_text) == (selected_option_id, answer_text):
                    return _answer_state(existing)
                raise CONFLICT
            if attempt.status != "IN_PROGRESS" or question.position != attempt.current_question_position:
                raise CONFLICT
            if question.question_type == QuestionType.MULTIPLE_CHOICE.value:
                if answer_text is not None or selected_option_id not in {
                    option["id"] for option in question.options_snapshot
                }:
                    raise CONFLICT
                marks, _ = grade_multiple_choice(selected_option_id, question.correct_option_id or "", 1)
                status = "GRADED"
                method = MarkProvenance.DETERMINISTIC_OPTION
                feedback: dict[str, Any] = {}
            elif question.question_type == QuestionType.NUMERICAL.value:
                if selected_option_id is not None or answer_text is None:
                    raise CONFLICT
                rubric = NumericalRubric.from_dict(question.grading_rubric_snapshot)
                marks, _, feedback = grade_numerical(answer_text, rubric)
                status = "GRADED"
                method = MarkProvenance.DETERMINISTIC_NUMERICAL
            else:
                if selected_option_id is not None or answer_text is None:
                    raise CONFLICT
                if question.max_marks <= 4:
                    status = "SELF_CHECK_PENDING"
                    method = MarkProvenance.SELF_ASSESSED
                else:
                    status = "PENDING"
                    method = MarkProvenance.AI_RUBRIC
                marks = None
                feedback = {}
            now = _clock(session)
            answer = SoloAnswerModel(
                id=uuid4(), attempt_id=attempt_id, question_id=question_id,
                selected_option_id=selected_option_id, answer_text=answer_text,
                accepted_at=now, grading_status=status, mark_provenance=method.value,
                earned_marks=marks, graded_at=now if marks is not None else None,
                attempt_cycle=1, attempt_count=0,
                awarded_criterion_ids=[], feedback=feedback,
            )
            session.add(answer)
            session.flush()
            if status != "SELF_CHECK_PENDING":
                attempt.current_question_position += 1
            attempt.state_version += 1
            _reconcile_completion(session, attempt, now)
            session.flush()
            return _answer_state(answer)

    def get_self_check(self, owner_id: UUID, attempt_id: UUID, question_id: UUID) -> LockedSelfCheck:
        with self._session_factory() as session:
            attempt = _attempt(session, owner_id, attempt_id)
            if attempt.status not in ("IN_PROGRESS", "AWAITING_MARKING", "FINISHED"):
                raise CONFLICT
            question = session.scalar(select(SoloQuestionModel).where(
                SoloQuestionModel.id == question_id, SoloQuestionModel.attempt_id == attempt_id
            ))
            answer = session.scalar(select(SoloAnswerModel).where(
                SoloAnswerModel.attempt_id == attempt_id, SoloAnswerModel.question_id == question_id
            ))
            if question is None or answer is None or answer.mark_provenance != "SELF_ASSESSED":
                raise NOT_FOUND
            return _locked_self_check(question, answer)

    def finalize_self_check(
        self, owner_id: UUID, attempt_id: UUID, question_id: UUID,
        selected_criterion_ids: tuple[str, ...],
    ) -> SoloAnswerState:
        with self._session_factory() as session, session.begin():
            attempt = _attempt(session, owner_id, attempt_id, lock=True)
            question = session.scalar(select(SoloQuestionModel).where(
                SoloQuestionModel.id == question_id, SoloQuestionModel.attempt_id == attempt_id
            ))
            answer = session.scalar(select(SoloAnswerModel).where(
                SoloAnswerModel.attempt_id == attempt_id, SoloAnswerModel.question_id == question_id
            ).with_for_update())
            if question is None or answer is None or answer.mark_provenance != "SELF_ASSESSED":
                raise NOT_FOUND
            try:
                result = resolve_self_check(_locked_self_check(question, answer), selected_criterion_ids)
            except ValueError:
                raise CONFLICT from None
            prior = session.get(SoloSelfCheckModel, answer.id)
            if prior is not None:
                if tuple(sorted(prior.selected_criterion_ids)) != result.selected_criterion_ids:
                    raise CONFLICT
                return _answer_state(answer)
            if attempt.status != "IN_PROGRESS" or answer.grading_status != "SELF_CHECK_PENDING":
                raise CONFLICT
            now = _clock(session)
            session.add(SoloSelfCheckModel(
                answer_id=answer.id, selected_criterion_ids=list(result.selected_criterion_ids),
                earned_marks=result.earned_marks, finalized_at=now,
            ))
            answer.grading_status = "GRADED"
            answer.earned_marks = result.earned_marks
            answer.graded_at = now
            answer.awarded_criterion_ids = list(result.selected_criterion_ids)
            answer.feedback = {"self_assessed": True}
            if attempt.current_question_position != question.position:
                raise CONFLICT
            attempt.current_question_position += 1
            attempt.state_version += 1
            session.flush()
            _reconcile_completion(session, attempt, now)
            session.flush()
            return _answer_state(answer)

    def abandon(self, owner_id: UUID, attempt_id: UUID) -> SoloAttemptState:
        with self._session_factory() as session, session.begin():
            attempt = _attempt(session, owner_id, attempt_id, lock=True)
            if attempt.status == "ABANDONED":
                return _state(session, attempt)
            if attempt.status in ("FINISHED", "FAILED"):
                raise CONFLICT
            now = _clock(session)
            prep = session.scalar(select(SoloPreparationModel).where(
                SoloPreparationModel.attempt_id == attempt_id
            ).with_for_update())
            if prep is not None and prep.status == "GENERATING":
                prep.status = "FAILED"
                prep.claim_token = None
                prep.lease_expires_at = None
                prep.error_category = "abandoned"
                prep.updated_at = now
                prep.state_version += 1
            attempt.status = "ABANDONED"
            attempt.terminal_at = now
            attempt.state_version += 1
            session.flush()
            return _state(session, attempt)

    def get_review(self, owner_id: UUID, attempt_id: UUID) -> SoloReview:
        with self._session_factory() as session:
            attempt = _attempt(session, owner_id, attempt_id)
            if attempt.status != "FINISHED":
                raise MARKING_PENDING
            state = _state(session, attempt)
            questions = tuple(session.scalars(select(SoloQuestionModel).where(
                SoloQuestionModel.attempt_id == attempt_id
            ).order_by(SoloQuestionModel.position)))
            answer_by_question = {
                answer.question_id: answer for answer in session.scalars(select(SoloAnswerModel).where(
                    SoloAnswerModel.attempt_id == attempt_id
                ))
            }
            return SoloReview(state, tuple(SoloReviewQuestion(
                question=_public_question(question),
                answer=_answer_state(answer_by_question[question.id]),
                correct_option_id=question.correct_option_id,
                intended_answer=question.worked_explanation_snapshot,
            ) for question in questions))

    def claim_due_ai(self, *, limit: int = 4, lease_seconds: int = 30) -> tuple[ClaimedSoloGrade, ...]:
        with self._session_factory() as session:
            candidate_ids = tuple(session.scalars(select(SoloAnswerModel.id).where(
                SoloAnswerModel.mark_provenance == "AI_RUBRIC",
                SoloAnswerModel.grading_status.in_(("PENDING", "RETRYABLE")),
            ).order_by(SoloAnswerModel.accepted_at).limit(min(limit * 4, 100))))
        claimed: list[ClaimedSoloGrade] = []
        for answer_id in candidate_ids:
            if len(claimed) >= limit:
                break
            with self._session_factory() as session, session.begin():
                identity = session.get(SoloAnswerModel, answer_id)
                if identity is None:
                    continue
                attempt = session.scalar(select(SoloAttemptModel).where(
                    SoloAttemptModel.id == identity.attempt_id
                ).with_for_update(skip_locked=True))
                if attempt is None or attempt.status not in ("IN_PROGRESS", "AWAITING_MARKING"):
                    continue
                answer = session.scalar(select(SoloAnswerModel).where(
                    SoloAnswerModel.id == answer_id
                ).with_for_update(skip_locked=True))
                now = _clock(session)
                if (answer is None or answer.grading_status not in ("PENDING", "RETRYABLE")
                    or answer.attempt_count >= 2 or (answer.next_attempt_at is not None and answer.next_attempt_at > now)):
                    continue
                question = session.scalar(select(SoloQuestionModel).where(
                    SoloQuestionModel.id == answer.question_id,
                    SoloQuestionModel.attempt_id == attempt.id,
                ))
                if question is None or question.question_type != "WRITTEN" or question.max_marks < 5:
                    continue
                token = uuid4()
                answer.grading_status = "IN_PROGRESS"
                answer.claim_token = token
                answer.lease_expires_at = now + timedelta(seconds=lease_seconds)
                answer.attempt_count += 1
                attempt.state_version += 1
                claimed.append(ClaimedSoloGrade(
                    attempt_id=attempt.id, answer_id=answer.id,
                    question_id=question.id, claim_token=token,
                    attempt_count=answer.attempt_count, attempt_cycle=answer.attempt_cycle,
                    answer_text=answer.answer_text or "",
                    prompt=question.prompt_snapshot, original_extract=question.original_extract,
                    max_marks=question.max_marks,
                    grading_rubric=dict(question.grading_rubric_snapshot),
                ))
        return tuple(claimed)

    def finish_ai_cas(
        self, claim: ClaimedSoloGrade, *, earned_marks: int,
        awarded_criterion_ids: Sequence[str], feedback: dict[str, Any],
    ) -> bool:
        with self._session_factory() as session, session.begin():
            attempt = session.scalar(select(SoloAttemptModel).where(
                SoloAttemptModel.id == claim.attempt_id
            ).with_for_update())
            if attempt is None or attempt.status not in ("IN_PROGRESS", "AWAITING_MARKING"):
                return False
            answer = session.scalar(select(SoloAnswerModel).where(
                SoloAnswerModel.id == claim.answer_id,
                SoloAnswerModel.attempt_id == claim.attempt_id,
            ).with_for_update())
            now = _clock(session)
            if (answer is None or answer.claim_token != claim.claim_token
                or answer.grading_status != "IN_PROGRESS"
                or answer.lease_expires_at is None or answer.lease_expires_at <= now
                or answer.attempt_cycle != claim.attempt_cycle
                or answer.attempt_count != claim.attempt_count):
                return False
            if not 0 <= earned_marks <= claim.max_marks:
                raise ValueError("AI marks out of range.")
            question = session.scalar(select(SoloQuestionModel).where(
                SoloQuestionModel.id == answer.question_id,
                SoloQuestionModel.attempt_id == attempt.id,
            ))
            if (question is None or question.question_type != "WRITTEN"
                or question.max_marks != claim.max_marks or not 5 <= question.max_marks <= 6
                or answer.mark_provenance != "AI_RUBRIC"):
                raise ValueError("AI answer/question authority mismatch.")
            rubric = WrittenRubric.from_dict(question.grading_rubric_snapshot)
            weights = {criterion.id: criterion.marks for criterion in rubric.criteria}
            if (len(weights) != len(rubric.criteria) or rubric.total_marks() != question.max_marks
                or len(awarded_criterion_ids) != len(set(awarded_criterion_ids))
                or any(criterion_id not in weights for criterion_id in awarded_criterion_ids)
                or sum(weights[criterion_id] for criterion_id in awarded_criterion_ids) != earned_marks):
                raise ValueError("AI grade does not match the saved rubric.")
            answer.grading_status = "GRADED"
            answer.earned_marks = earned_marks
            answer.graded_at = now
            answer.awarded_criterion_ids = list(awarded_criterion_ids)
            answer.feedback = feedback
            answer.claim_token = None
            answer.lease_expires_at = None
            answer.next_attempt_at = None
            answer.last_error_category = None
            attempt.state_version += 1
            session.flush()
            _reconcile_completion(session, attempt, now)
            return True

    def fail_ai_cas(self, claim: ClaimedSoloGrade, error_category: str, *, backoff_seconds: int = 5) -> bool:
        with self._session_factory() as session, session.begin():
            attempt = session.scalar(select(SoloAttemptModel).where(
                SoloAttemptModel.id == claim.attempt_id
            ).with_for_update())
            if attempt is None or attempt.status not in ("IN_PROGRESS", "AWAITING_MARKING"):
                return False
            answer = session.scalar(select(SoloAnswerModel).where(
                SoloAnswerModel.id == claim.answer_id,
                SoloAnswerModel.attempt_id == claim.attempt_id,
            ).with_for_update())
            now = _clock(session)
            if (answer is None or answer.claim_token != claim.claim_token
                or answer.grading_status != "IN_PROGRESS"
                or answer.lease_expires_at is None or answer.lease_expires_at <= now
                or answer.attempt_cycle != claim.attempt_cycle
                or answer.attempt_count != claim.attempt_count):
                return False
            if answer.attempt_count < 2:
                answer.grading_status = "RETRYABLE"
                answer.next_attempt_at = now + timedelta(seconds=backoff_seconds)
            else:
                answer.grading_status = "UNAVAILABLE"
                answer.next_attempt_at = None
            answer.claim_token = None
            answer.lease_expires_at = None
            answer.last_error_category = error_category
            answer.awarded_criterion_ids = []
            answer.feedback = {}
            attempt.state_version += 1
            return True

    def reset_expired_ai(self, *, limit: int = 100) -> int:
        with self._session_factory() as session:
            candidate_ids = tuple(session.scalars(select(SoloAnswerModel.id).where(
                SoloAnswerModel.mark_provenance == "AI_RUBRIC",
                SoloAnswerModel.grading_status == "IN_PROGRESS",
            ).order_by(SoloAnswerModel.accepted_at).limit(min(limit, 100))))
        changed = 0
        for answer_id in candidate_ids:
            with self._session_factory() as session, session.begin():
                identity = session.get(SoloAnswerModel, answer_id)
                if identity is None:
                    continue
                attempt = session.scalar(select(SoloAttemptModel).where(
                    SoloAttemptModel.id == identity.attempt_id
                ).with_for_update(skip_locked=True))
                if attempt is None or attempt.status not in ("IN_PROGRESS", "AWAITING_MARKING"):
                    continue
                answer = session.scalar(select(SoloAnswerModel).where(
                    SoloAnswerModel.id == answer_id
                ).with_for_update(skip_locked=True))
                now = _clock(session)
                if (answer is None or answer.grading_status != "IN_PROGRESS"
                    or answer.lease_expires_at is None or answer.lease_expires_at > now):
                    continue
                answer.grading_status = "UNAVAILABLE" if answer.attempt_count >= 2 else "PENDING"
                answer.next_attempt_at = None if answer.attempt_count >= 2 else now
                answer.claim_token = None
                answer.lease_expires_at = None
                answer.awarded_criterion_ids = []
                answer.feedback = {}
                attempt.state_version += 1
                changed += 1
        return changed

    def retry_ai(self, owner_id: UUID, attempt_id: UUID) -> int:
        with self._session_factory() as session, session.begin():
            attempt = _attempt(session, owner_id, attempt_id, lock=True)
            if attempt.status not in ("IN_PROGRESS", "AWAITING_MARKING"):
                raise CONFLICT
            answers = tuple(session.scalars(select(SoloAnswerModel).where(
                SoloAnswerModel.attempt_id == attempt_id,
                SoloAnswerModel.mark_provenance == "AI_RUBRIC",
                SoloAnswerModel.grading_status == "UNAVAILABLE",
            ).with_for_update()))
            now = _clock(session)
            for answer in answers:
                answer.grading_status = "PENDING"
                answer.attempt_cycle += 1
                answer.attempt_count = 0
                answer.next_attempt_at = now
                answer.last_error_category = None
            if answers:
                attempt.state_version += 1
            return len(answers)

    def purge_terminal_content(self, cutoff_utc: datetime, *, limit: int = 100) -> int:
        """Delete only terminal educational content after its 30-day cutoff.

        The caller computes `cutoff_utc = now_utc - timedelta(days=30)` from
        the approved policy. AWAITING_MARKING has no inactivity expiry. The
        answer-free completion receipt is independent and must survive this
        source purge until reward posting/account deletion rules handle it.
        """
        if cutoff_utc.tzinfo is None:
            raise ValueError("Terminal-content cutoff must be timezone-aware.")
        if not 1 <= limit <= 100:
            raise ValueError("Terminal-content purge limit must be 1..100.")
        with self._session_factory() as session, session.begin():
            ids = tuple(session.scalars(select(SoloAttemptModel.id).where(
                SoloAttemptModel.status.in_(_TERMINAL),
                SoloAttemptModel.terminal_at.is_not(None),
                SoloAttemptModel.terminal_at <= cutoff_utc,
            ).order_by(SoloAttemptModel.terminal_at, SoloAttemptModel.id).limit(limit)))
            if not ids:
                return 0
            deleted = tuple(session.scalars(delete(SoloAttemptModel).where(
                SoloAttemptModel.id.in_(ids),
                SoloAttemptModel.status.in_(_TERMINAL),
                SoloAttemptModel.terminal_at <= cutoff_utc,
            ).returning(SoloAttemptModel.id)))
            return len(deleted)
