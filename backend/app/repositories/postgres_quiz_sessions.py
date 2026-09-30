"""PostgreSQL repository for durable authoritative quiz sessions and grading."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.generated_quiz_question import GeneratedQuizQuestionModel
from app.db.models.membership import RoomMembershipModel
from app.db.models.question import QuestionModel
from app.db.models.quiz_preparation import QuizPreparationModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.db.models.user import UserModel
from app.domain.adaptive_quiz import (
    MAX_WRITTEN_ANSWER_LENGTH,
    MultipleChoiceOption,
    NumericalRubric,
    QuestionType,
    calculate_question_duration_seconds,
    calculate_reveal_duration_seconds,
    grade_multiple_choice,
    grade_numerical,
)
from app.generator.protocol import GeneratedQuestionData, GeneratorValidationError
from app.generator.validation import validate_generated_quiz_set
from app.generator.verification.protocol import (
    VERIFICATION_REVISION,
    compute_verified_content_digest,
)
from app.learning_companions.room_receipts import (
    enroll_room_participants,
    insert_room_completion_receipts,
)
from app.domain.constants import (
    CORRECT_POINTS,
    INCORRECT_POINTS,
    PHYSICS_SPRINT_BANK_KEY,
    QUESTION_DURATION_SECONDS,
    REVEAL_DURATION_SECONDS,
)
from app.domain.errors import (
    AccountDeletedError,
    AnswerAlreadySubmittedError,
    AnswerTooLateError,
    InsufficientParticipantsError,
    InvalidAnswerTextError,
    InvalidOptionError,
    InvalidSessionTransitionError,
    NotRoomMemberError,
    NotSessionParticipantError,
    ParticipantsNotReadyError,
    QuestionBankUnavailableError,
    QuestionNotOpenError,
    QuizNotReadyError,
    RoomClosedError,
    RoomNotFoundError,
    RoomOwnerRequiredError,
    SessionAlreadyActiveError,
    SessionNotActiveError,
    SessionStartConflictError,
    StaleSessionQuestionError,
)
from app.domain.question import QuestionDefinition, QuestionOption
from app.domain.quiz import (
    AnswerSubmission,
    AuthoritativeSnapshot,
    LeaderboardEntry,
    ParticipantSnapshot,
    PublicQuestion,
    QuizSession,
    QuizSessionStatus,
    ReadyState,
    RevealedQuestion,
    SessionParticipant,
    SessionQuestion,
    ViewerRole,
    ViewerSubmission,
    score_answer,
)
from app.domain.quiz_review import ReviewQuestionItem, SessionReview
from app.domain.room import Room
from app.repositories.quiz_sessions import ClaimedSubmission, QuizSessionRepository

_ACTIVE_SESSION_STATUSES = (
    QuizSessionStatus.QUESTION_OPEN.value,
    QuizSessionStatus.QUESTION_GRADING.value,
    QuizSessionStatus.QUESTION_REVEAL.value,
)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _database_clock(session: Session) -> datetime:
    value = session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        return datetime.now(timezone.utc)
    return _to_utc(value)


class PostgresQuizSessionRepository:
    """PostgreSQL repository for durable authoritative quiz sessions and grading."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_active_by_room(self, room_id: UUID) -> QuizSession | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(QuizSessionModel)
                .where(
                    QuizSessionModel.room_id == room_id,
                    QuizSessionModel.status.in_(_ACTIVE_SESSION_STATUSES),
                )
                .order_by(QuizSessionModel.started_at.desc())
            )
            return None if model is None else _to_session(model)

    def get_by_id(self, session_id: UUID) -> QuizSession | None:
        with self._session_factory() as session:
            model = session.get(QuizSessionModel, session_id)
            return None if model is None else _to_session(model)

    def list_active(self) -> tuple[QuizSession, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(QuizSessionModel)
                .where(QuizSessionModel.status.in_(_ACTIVE_SESSION_STATUSES))
                .order_by(QuizSessionModel.started_at, QuizSessionModel.id)
            ).all()
            return tuple(_to_session(model) for model in models)

    def get_deadline(self, session_id: UUID) -> datetime | None:
        with self._session_factory() as session:
            model = session.get(QuizSessionModel, session_id)
            if model is None or model.status == QuizSessionStatus.FINISHED.value:
                return None
            if model.status == QuizSessionStatus.QUESTION_GRADING.value:
                # QUESTION_GRADING has no client deadline
                return None
            if model.status == QuizSessionStatus.QUESTION_REVEAL.value:
                if model.reveal_ends_at is None:
                    raise InvalidSessionTransitionError
                return _to_utc(model.reveal_ends_at)
            if model.status != QuizSessionStatus.QUESTION_OPEN.value:
                raise InvalidSessionTransitionError
            question = session.scalar(
                select(SessionQuestionModel).where(
                    SessionQuestionModel.session_id == session_id,
                    SessionQuestionModel.position == model.current_question_position,
                )
            )
            if question is None or question.closes_at is None:
                raise InvalidSessionTransitionError
            return _to_utc(question.closes_at)

    def list_questions(self, session_id: UUID) -> tuple[SessionQuestion, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(SessionQuestionModel)
                .where(SessionQuestionModel.session_id == session_id)
                .order_by(SessionQuestionModel.position)
            ).all()
            return tuple(_to_session_question(model) for model in models)

    def list_participants(self, session_id: UUID) -> tuple[SessionParticipant, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(SessionParticipantModel)
                .where(SessionParticipantModel.session_id == session_id)
                .order_by(SessionParticipantModel.created_at, SessionParticipantModel.id)
            ).all()
            return tuple(_to_participant(model) for model in models)

    def list_submissions(self, session_id: UUID) -> tuple[AnswerSubmission, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(AnswerSubmissionModel)
                .where(AnswerSubmissionModel.session_id == session_id)
                .order_by(AnswerSubmissionModel.submitted_at, AnswerSubmissionModel.id)
            ).all()
            return tuple(_to_submission(model) for model in models)

    def derive_leaderboard(
        self,
        session_id: UUID,
        *,
        revealed_only: bool = False,
    ) -> tuple[LeaderboardEntry, ...]:
        with self._session_factory() as session:
            session_model = session.get(QuizSessionModel, session_id)
            is_adaptive = session_model is not None and session_model.quiz_mode == "ADAPTIVE"
            avail_marks = session_model.total_available_marks if session_model else 5
            return _derive_leaderboard(
                session,
                session_id,
                revealed_only=revealed_only,
                is_adaptive=is_adaptive,
                total_available_marks=avail_marks,
            )

    def set_ready(self, room_id: UUID, user_id: UUID, ready: bool) -> ReadyState:
        with self._session_factory() as session:
            with session.begin():
                room = _lock_room(session, room_id)
                if room is None:
                    raise RoomNotFoundError
                if room.closed_at is not None:
                    raise RoomClosedError
                if _find_active_session(session, room_id) is not None:
                    raise SessionAlreadyActiveError

                membership = session.scalar(
                    select(RoomMembershipModel)
                    .where(
                        RoomMembershipModel.room_id == room_id,
                        RoomMembershipModel.user_id == user_id,
                        RoomMembershipModel.left_at.is_(None),
                    )
                    .with_for_update()
                )
                if membership is None:
                    raise NotRoomMemberError

                now = _database_clock(session)
                if ready:
                    if membership.ready_at is None:
                        membership.ready_at = now
                else:
                    membership.ready_at = None
                session.flush()
                return ReadyState(
                    room_id=room_id,
                    user_id=user_id,
                    ready=ready,
                    ready_at=_to_utc(membership.ready_at) if membership.ready_at else None,
                )

    def start_session(self, room_id: UUID, requesting_user_id: UUID) -> QuizSession:
        with self._session_factory() as session:
            with session.begin():
                room = _lock_room(session, room_id)
                if room is None:
                    raise RoomNotFoundError
                if room.closed_at is not None:
                    raise RoomClosedError
                if room.owner_id != requesting_user_id:
                    raise RoomOwnerRequiredError
                if _find_active_session(session, room_id) is not None:
                    raise SessionAlreadyActiveError

                memberships = list(
                    session.scalars(
                        select(RoomMembershipModel)
                        .where(
                            RoomMembershipModel.room_id == room_id,
                            RoomMembershipModel.left_at.is_(None),
                        )
                        .order_by(RoomMembershipModel.joined_at, RoomMembershipModel.id)
                        .with_for_update()
                    ).all()
                )
                if len(memberships) < 2:
                    raise InsufficientParticipantsError
                owner_membership = next(
                    (m for m in memberships if m.user_id == room.owner_id),
                    None,
                )
                if owner_membership is None:
                    raise NotRoomMemberError
                if any(
                    m.user_id != room.owner_id and m.ready_at is None
                    for m in memberships
                ):
                    raise ParticipantsNotReadyError

                user_models = {
                    m.user_id: _lock_user_for_session_start(session, m.user_id)
                    for m in memberships
                }
                if any(user is None for user in user_models.values()):
                    raise NotRoomMemberError
                if any(u is not None and u.deleted_at is not None for u in user_models.values()):
                    raise AccountDeletedError

                now = _database_clock(session)

                # Check quiz mode
                if room.quiz_mode == "ADAPTIVE":
                    prep = session.scalar(
                        select(QuizPreparationModel)
                        .where(
                            QuizPreparationModel.room_id == room_id,
                            QuizPreparationModel.status == "READY",
                        )
                        .with_for_update()
                    )
                    if prep is None:
                        raise QuizNotReadyError

                    # Content verification gate recheck under lock:
                    # READY preparation must carry approved revision and matching content digest
                    if (
                        prep.verification_revision != VERIFICATION_REVISION
                        or prep.verified_content_digest is None
                    ):
                        raise QuizNotReadyError

                    prep_questions = list(
                        session.scalars(
                            select(GeneratedQuizQuestionModel)
                            .where(GeneratedQuizQuestionModel.preparation_id == prep.id)
                            .order_by(GeneratedQuizQuestionModel.position)
                        ).all()
                    )
                    if not prep_questions:
                        raise QuizNotReadyError

                    try:
                        domain_questions = tuple(
                            GeneratedQuestionData(
                                position=q.position,
                                question_type=QuestionType(q.question_type),
                                prompt=q.prompt,
                                max_marks=q.max_marks,
                                duration_seconds=q.duration_seconds,
                                options=tuple(
                                    MultipleChoiceOption(id=opt["id"], label=opt["label"])
                                    for opt in (q.options or [])
                                ),
                                correct_option_id=q.correct_option_id,
                                grading_rubric=dict(q.grading_rubric or {}),
                                worked_explanation=q.worked_explanation,
                                original_extract=q.original_extract,
                                content_fingerprint=q.content_fingerprint,
                            )
                            for q in prep_questions
                        )
                        validated_questions = validate_generated_quiz_set(
                            domain_questions,
                            target_total_marks=room.target_total_marks,
                        )
                    except (GeneratorValidationError, TypeError, ValueError, KeyError):
                        raise QuizNotReadyError from None
                    computed_digest = compute_verified_content_digest(
                        validated_questions,
                        prep.verification_revision,
                    )
                    if computed_digest != prep.verified_content_digest:
                        raise QuizNotReadyError
                    # Mark preparation consumed
                    prep.status = "CONSUMED"
                    prep.consumed_at = now
                    prep.updated_at = now
                    prep.state_version += 1

                    total_marks = sum(q.max_marks for q in prep_questions)
                    session_model = QuizSessionModel(
                        id=uuid4(),
                        room_id=room_id,
                        preparation_id=prep.id,
                        question_bank_key=f"adaptive:{prep.id}",
                        quiz_mode="ADAPTIVE",
                        education_level=room.education_level,
                        quiz_subject=room.quiz_subject,
                        quiz_topic=room.quiz_topic,
                        total_available_marks=total_marks,
                        status=QuizSessionStatus.QUESTION_OPEN.value,
                        current_question_position=0,
                        state_version=1,
                        started_at=now,
                    )
                    session.add(session_model)
                    session.flush()

                    for membership in memberships:
                        user = user_models[membership.user_id]
                        if user is None:
                            raise NotRoomMemberError
                        session.add(
                            SessionParticipantModel(
                                id=uuid4(),
                                session_id=session_model.id,
                                user_id=membership.user_id,
                                room_membership_id=membership.id,
                                display_name_snapshot=user.display_name,
                                created_at=now,
                            )
                        )

                    for position, gq in enumerate(prep_questions):
                        opened_at = now if position == 0 else None
                        closes_at = (now + timedelta(seconds=gq.duration_seconds)) if position == 0 else None
                        session.add(
                            SessionQuestionModel(
                                id=uuid4(),
                                session_id=session_model.id,
                                source_question_id=None,
                                generated_question_id=gq.id,
                                position=position,
                                question_type=gq.question_type,
                                max_marks=gq.max_marks,
                                prompt_snapshot=gq.prompt,
                                options_snapshot=gq.options,
                                correct_option_id=gq.correct_option_id,
                                grading_rubric_snapshot=gq.grading_rubric,
                                worked_explanation_snapshot=gq.worked_explanation,
                                original_extract=gq.original_extract,
                                content_fingerprint=gq.content_fingerprint,
                                duration_seconds=gq.duration_seconds,
                                opened_at=opened_at,
                                closes_at=closes_at,
                            )
                        )

                else:
                    # Legacy Physics Sprint
                    question_models = _load_canonical_question_models(session)
                    session_model = QuizSessionModel(
                        id=uuid4(),
                        room_id=room_id,
                        preparation_id=None,
                        question_bank_key=PHYSICS_SPRINT_BANK_KEY,
                        quiz_mode="LEGACY_PHYSICS",
                        education_level=None,
                        quiz_subject=None,
                        quiz_topic=None,
                        total_available_marks=5,
                        status=QuizSessionStatus.QUESTION_OPEN.value,
                        current_question_position=0,
                        state_version=1,
                        started_at=now,
                    )
                    session.add(session_model)
                    session.flush()

                    for membership in memberships:
                        user = user_models[membership.user_id]
                        if user is None:
                            raise NotRoomMemberError
                        session.add(
                            SessionParticipantModel(
                                id=uuid4(),
                                session_id=session_model.id,
                                user_id=membership.user_id,
                                room_membership_id=membership.id,
                                display_name_snapshot=user.display_name,
                                created_at=now,
                            )
                        )

                    for position, question in enumerate(question_models):
                        opened_at = now if position == 0 else None
                        closes_at = (now + timedelta(seconds=question.duration_seconds)) if position == 0 else None
                        session.add(
                            SessionQuestionModel(
                                id=uuid4(),
                                session_id=session_model.id,
                                source_question_id=question.id,
                                generated_question_id=None,
                                position=position,
                                question_type="MULTIPLE_CHOICE",
                                max_marks=1,
                                prompt_snapshot=question.prompt,
                                options_snapshot=_option_dicts(question.options),
                                correct_option_id=question.correct_option_id,
                                grading_rubric_snapshot={},
                                worked_explanation_snapshot="",
                                original_extract=None,
                                content_fingerprint="",
                                duration_seconds=question.duration_seconds,
                                opened_at=opened_at,
                                closes_at=closes_at,
                            )
                        )

                # Only participants with fixed reward settings at this start
                # boundary are eligible; later settings never backfill a room.
                session.flush()
                enroll_room_participants(session, session_id=session_model.id)

                for membership in memberships:
                    membership.ready_at = None
                session.flush()
                return _to_session(session_model)

    def submit_answer(
        self,
        room_id: UUID,
        user_id: UUID,
        session_question_id: UUID,
        selected_option_id: str | None = None,
        answer_text: str | None = None,
    ) -> AnswerSubmission:
        with self._session_factory() as session:
            with session.begin():
                active_session = _find_active_session(session, room_id, for_update=True)
                if active_session is None:
                    raise SessionNotActiveError
                now = _database_clock(session)
                if active_session.status != QuizSessionStatus.QUESTION_OPEN.value:
                    raise QuestionNotOpenError

                current_question = session.scalar(
                    select(SessionQuestionModel).where(
                        SessionQuestionModel.session_id == active_session.id,
                        SessionQuestionModel.position == active_session.current_question_position,
                    )
                )
                if current_question is None:
                    raise InvalidSessionTransitionError
                if current_question.id != session_question_id:
                    raise StaleSessionQuestionError

                participant = session.scalar(
                    select(SessionParticipantModel).where(
                        SessionParticipantModel.session_id == active_session.id,
                        SessionParticipantModel.user_id == user_id,
                    )
                )
                if participant is None:
                    raise NotSessionParticipantError

                existing = session.scalar(
                    select(AnswerSubmissionModel)
                    .where(
                        AnswerSubmissionModel.session_question_id == session_question_id,
                        AnswerSubmissionModel.participant_id == participant.id,
                    )
                    .with_for_update()
                )

                q_type = current_question.question_type

                if q_type == "MULTIPLE_CHOICE":
                    if selected_option_id is None or answer_text is not None:
                        raise InvalidOptionError
                    option_ids = {opt["id"] for opt in current_question.options_snapshot}
                    if selected_option_id not in option_ids:
                        raise InvalidOptionError

                    if existing is not None:
                        if existing.selected_option_id == selected_option_id:
                            return _to_submission(existing)
                        raise AnswerAlreadySubmittedError

                    if current_question.closes_at is None or now >= current_question.closes_at:
                        raise AnswerTooLateError
                    if current_question.opened_at is None:
                        raise InvalidSessionTransitionError

                    is_correct, points = score_answer(
                        selected_option_id,
                        current_question.correct_option_id or "",
                    )
                    earned_marks = 1 if is_correct else 0
                    grading_method = (
                        "LEGACY_OPTION"
                        if active_session.quiz_mode == "LEGACY_PHYSICS"
                        else "DETERMINISTIC_OPTION"
                    )
                    response_time_ms = max(
                        0,
                        int((now - current_question.opened_at).total_seconds() * 1000),
                    )
                    answer = AnswerSubmissionModel(
                        id=uuid4(),
                        session_id=active_session.id,
                        session_question_id=session_question_id,
                        participant_id=participant.id,
                        selected_option_id=selected_option_id,
                        answer_text=None,
                        submitted_at=now,
                        response_time_ms=response_time_ms,
                        is_correct=is_correct,
                        points=points,
                        earned_marks=earned_marks,
                        grading_method=grading_method,
                        grading_status="GRADED",
                        graded_at=now,
                    )
                    session.add(answer)
                    session.flush()
                    return _to_submission(answer)

                elif q_type == "NUMERICAL":
                    if answer_text is None or selected_option_id is not None:
                        raise InvalidOptionError
                    # Reject, never truncate, overlength/blank responses.
                    clean_text = answer_text.strip()
                    if not clean_text or len(clean_text) > MAX_WRITTEN_ANSWER_LENGTH:
                        raise InvalidAnswerTextError

                    if existing is not None:
                        if existing.answer_text == clean_text:
                            return _to_submission(existing)
                        raise AnswerAlreadySubmittedError

                    if current_question.closes_at is None or now >= current_question.closes_at:
                        raise AnswerTooLateError
                    if current_question.opened_at is None:
                        raise InvalidSessionTransitionError

                    rubric = NumericalRubric.from_dict(current_question.grading_rubric_snapshot)
                    earned_marks, is_correct, feedback = grade_numerical(clean_text, rubric)
                    points = 100 if is_correct else 0
                    response_time_ms = max(
                        0,
                        int((now - current_question.opened_at).total_seconds() * 1000),
                    )
                    answer = AnswerSubmissionModel(
                        id=uuid4(),
                        session_id=active_session.id,
                        session_question_id=session_question_id,
                        participant_id=participant.id,
                        selected_option_id=None,
                        answer_text=clean_text,
                        submitted_at=now,
                        response_time_ms=response_time_ms,
                        is_correct=is_correct,
                        points=points,
                        earned_marks=earned_marks,
                        grading_method="DETERMINISTIC_NUMERICAL",
                        grading_status="GRADED",
                        feedback=feedback,
                        graded_at=now,
                    )
                    session.add(answer)
                    session.flush()
                    return _to_submission(answer)

                elif q_type == "WRITTEN":
                    if answer_text is None or selected_option_id is not None:
                        raise InvalidOptionError
                    # Reject, never truncate, overlength/blank responses.
                    clean_text = answer_text.strip()
                    if not clean_text or len(clean_text) > MAX_WRITTEN_ANSWER_LENGTH:
                        raise InvalidAnswerTextError

                    if existing is not None:
                        if existing.answer_text == clean_text:
                            return _to_submission(existing)
                        raise AnswerAlreadySubmittedError

                    if current_question.closes_at is None or now >= current_question.closes_at:
                        raise AnswerTooLateError
                    if current_question.opened_at is None:
                        raise InvalidSessionTransitionError

                    response_time_ms = max(
                        0,
                        int((now - current_question.opened_at).total_seconds() * 1000),
                    )
                    # Written answers commit as PENDING
                    answer = AnswerSubmissionModel(
                        id=uuid4(),
                        session_id=active_session.id,
                        session_question_id=session_question_id,
                        participant_id=participant.id,
                        selected_option_id=None,
                        answer_text=clean_text,
                        submitted_at=now,
                        response_time_ms=response_time_ms,
                        is_correct=None,
                        points=None,
                        earned_marks=None,
                        grading_method="LUNA_RUBRIC",
                        grading_status="PENDING",
                        attempt_cycle=1,
                        attempt_count=0,
                        graded_at=None,
                    )
                    session.add(answer)
                    session.flush()
                    return _to_submission(answer)

                raise InvalidSessionTransitionError

    def reconcile_session(self, session_id: UUID) -> QuizSession:
        with self._session_factory() as session:
            with session.begin():
                session_model = session.scalar(
                    select(QuizSessionModel)
                    .where(QuizSessionModel.id == session_id)
                    .with_for_update()
                )
                if session_model is None:
                    raise SessionNotActiveError
                if session_model.status == QuizSessionStatus.FINISHED.value:
                    return _to_session(session_model)
                return _reconcile_locked(session, session_model)

    def reconcile_active_for_room(self, room_id: UUID) -> QuizSession | None:
        with self._session_factory() as session:
            with session.begin():
                room = _lock_room(session, room_id)
                if room is None:
                    raise RoomNotFoundError
                if room.closed_at is not None:
                    raise RoomClosedError
                session_model = _find_active_session(session, room_id, for_update=True)
                if session_model is None:
                    return None
                return _reconcile_locked(session, session_model)

    def load_snapshot(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> AuthoritativeSnapshot:
        with self._session_factory() as session:
            room_model = session.get(RoomModel, room_id)
            if room_model is None:
                raise RoomNotFoundError
            if room_model.closed_at is not None:
                raise RoomClosedError

            viewer_membership = session.scalar(
                select(RoomMembershipModel).where(
                    RoomMembershipModel.room_id == room_id,
                    RoomMembershipModel.user_id == user_id,
                    RoomMembershipModel.left_at.is_(None),
                )
            )
            if viewer_membership is None:
                raise NotRoomMemberError
            server_time = _database_clock(session)
            session_model = session.scalar(
                select(QuizSessionModel)
                .where(QuizSessionModel.room_id == room_id)
                .order_by(QuizSessionModel.started_at.desc(), QuizSessionModel.id.desc())
            )
            active_memberships = list(
                session.scalars(
                    select(RoomMembershipModel)
                    .where(
                        RoomMembershipModel.room_id == room_id,
                        RoomMembershipModel.left_at.is_(None),
                    )
                    .order_by(RoomMembershipModel.joined_at, RoomMembershipModel.id)
                ).all()
            )
            user_models = {
                m.user_id: session.get(UserModel, m.user_id) for m in active_memberships
            }
            if any(u is None for u in user_models.values()):
                raise NotRoomMemberError

            participants = tuple(
                ParticipantSnapshot(
                    user_id=m.user_id,
                    display_name=user_models[m.user_id].display_name,
                    ready=m.ready_at is not None,
                )
                for m in active_memberships
            )

            # Latest preparation regardless of status: GENERATING and READY
            # drive the lobby, while FAILED stays observable with its safe
            # error category instead of disappearing. Terminal CONSUMED and
            # SUPERSEDED rows remain visible as the latest request outcome.
            # The monotonic state_version lets clients ignore stale frames.
            active_prep = session.scalar(
                select(QuizPreparationModel).where(
                    QuizPreparationModel.room_id == room_id,
                ).order_by(
                    QuizPreparationModel.created_at.desc(),
                    QuizPreparationModel.id.desc(),
                ).limit(1)
            )

            total_questions = _safe_question_count(session)
            if room_model.quiz_mode == "ADAPTIVE":
                # Adaptive lobbies must not carry fabricated legacy bank
                # metadata: 0 before a usable prepared set exists, else the
                # actual generated question count of the latest READY or
                # CONSUMED preparation.
                total_questions = _adaptive_lobby_question_count(session, room_id)

            if session_model is None:
                return _room_only_snapshot(
                    server_time=server_time,
                    room_model=room_model,
                    user_id=user_id,
                    participants=participants,
                    viewer_membership=viewer_membership,
                    total_question_count=total_questions,
                    active_prep=active_prep,
                )

            session_questions = list(
                session.scalars(
                    select(SessionQuestionModel)
                    .where(SessionQuestionModel.session_id == session_model.id)
                    .order_by(SessionQuestionModel.position)
                ).all()
            )
            participant_models = list(
                session.scalars(
                    select(SessionParticipantModel)
                    .where(SessionParticipantModel.session_id == session_model.id)
                    .order_by(SessionParticipantModel.created_at, SessionParticipantModel.id)
                ).all()
            )
            viewer_participant = next(
                (p for p in participant_models if p.user_id == user_id),
                None,
            )
            if viewer_participant is None:
                if session_model.status != QuizSessionStatus.FINISHED.value:
                    raise NotSessionParticipantError
                return _room_only_snapshot(
                    server_time=server_time,
                    room_model=room_model,
                    user_id=user_id,
                    participants=participants,
                    viewer_membership=viewer_membership,
                    total_question_count=total_questions,
                    active_prep=active_prep,
                )

            current_question = next(
                (q for q in session_questions if q.position == session_model.current_question_position),
                None,
            )
            if current_question is None:
                raise InvalidSessionTransitionError

            revealed = (
                session_model.status in (QuizSessionStatus.QUESTION_REVEAL.value, QuizSessionStatus.FINISHED.value)
                or current_question.revealed_at is not None
            )

            question = _to_visible_question(
                current_question,
                total_questions=len(session_questions),
                revealed=revealed,
            )

            viewer_submission = None
            answer = session.scalar(
                select(AnswerSubmissionModel).where(
                    AnswerSubmissionModel.session_question_id == current_question.id,
                    AnswerSubmissionModel.participant_id == viewer_participant.id,
                )
            )
            if answer is not None:
                viewer_submission = ViewerSubmission(
                    session_question_id=answer.session_question_id,
                    selected_option_id=answer.selected_option_id,
                    answer_text=answer.answer_text,
                    is_correct=answer.is_correct if revealed else None,
                    points=answer.points if revealed else None,
                    earned_marks=answer.earned_marks if revealed else None,
                    max_marks=current_question.max_marks,
                    grading_status=answer.grading_status,
                    feedback=dict(answer.feedback) if revealed else {},
                    awarded_criterion_ids=tuple(answer.awarded_criterion_ids or []) if revealed else (),
                )

            is_adaptive = session_model.quiz_mode == "ADAPTIVE"
            leaderboard = _derive_leaderboard(
                session,
                session_model.id,
                revealed_only=(session_model.status != QuizSessionStatus.FINISHED.value),
                is_adaptive=is_adaptive,
                total_available_marks=session_model.total_available_marks,
            )

            # Aggregate retry signal: an UNAVAILABLE accepted answer on the
            # current question means the host must explicitly retry grading.
            # Boolean/aggregate only; no answer or feedback content leaks.
            grading_retry_needed = False
            if session_model.status == QuizSessionStatus.QUESTION_GRADING.value:
                grading_retry_needed = session.scalar(
                    select(func.count(AnswerSubmissionModel.id)).where(
                        AnswerSubmissionModel.session_question_id == current_question.id,
                        AnswerSubmissionModel.grading_status == "UNAVAILABLE",
                    )
                ) not in (None, 0)

            return AuthoritativeSnapshot(
                server_time=server_time,
                room=_to_room(room_model),
                viewer_role=_viewer_role(room_model, user_id),
                participants=participants,
                viewer_ready=viewer_membership.ready_at is not None,
                session=_to_session(session_model),
                viewer_participated=True,
                state_version=session_model.state_version,
                current_question_number=current_question.position + 1,
                total_question_count=len(session_questions),
                question=question,
                closes_at=_to_utc(current_question.closes_at) if current_question.closes_at else None,
                reveal_ends_at=_to_utc(session_model.reveal_ends_at) if session_model.reveal_ends_at else None,
                viewer_submission=viewer_submission,
                leaderboard=leaderboard,
                finished_at=_to_utc(session_model.finished_at) if session_model.finished_at else None,
                active_preparation_status=active_prep.status if active_prep else None,
                active_preparation_version=active_prep.state_version if active_prep else None,
                active_preparation_error_category=active_prep.error_category if active_prep else None,
                grading_retry_needed=grading_retry_needed,
            )

    def get_session_review(
        self,
        room_id: UUID,
        session_id: UUID,
        user_id: UUID,
    ) -> SessionReview:
        with self._session_factory() as session:
            room_model = session.get(RoomModel, room_id)
            if room_model is None:
                raise RoomNotFoundError
            if room_model.closed_at is not None:
                raise RoomClosedError
            viewer_membership = session.scalar(
                select(RoomMembershipModel).where(
                    RoomMembershipModel.room_id == room_id,
                    RoomMembershipModel.user_id == user_id,
                    RoomMembershipModel.left_at.is_(None),
                )
            )
            if viewer_membership is None:
                raise NotRoomMemberError
            session_model = session.get(QuizSessionModel, session_id)
            if session_model is None or session_model.room_id != room_id:
                raise SessionNotActiveError
            if session_model.status != QuizSessionStatus.FINISHED.value:
                raise InvalidSessionTransitionError

            participant = session.scalar(
                select(SessionParticipantModel).where(
                    SessionParticipantModel.session_id == session_id,
                    SessionParticipantModel.user_id == user_id,
                )
            )
            if participant is None:
                raise NotSessionParticipantError

            questions = list(
                session.scalars(
                    select(SessionQuestionModel)
                    .where(SessionQuestionModel.session_id == session_id)
                    .order_by(SessionQuestionModel.position)
                ).all()
            )

            submissions = {
                sub.session_question_id: sub
                for sub in session.scalars(
                    select(AnswerSubmissionModel).where(
                        AnswerSubmissionModel.session_id == session_id,
                        AnswerSubmissionModel.participant_id == participant.id,
                    )
                ).all()
            }

            review_items: list[ReviewQuestionItem] = []
            total_earned = 0

            for q in questions:
                sub = submissions.get(q.id)
                earned = sub.earned_marks if (sub and sub.earned_marks is not None) else 0
                total_earned += earned

                review_items.append(
                    ReviewQuestionItem(
                        session_question_id=q.id,
                        position=q.position,
                        question_type=q.question_type,
                        prompt=q.prompt_snapshot,
                        max_marks=q.max_marks,
                        options=tuple(
                            QuestionOption(id=opt["id"], label=opt["label"])
                            for opt in q.options_snapshot
                        ),
                        correct_option_id=q.correct_option_id,
                        worked_explanation=q.worked_explanation_snapshot,
                        original_extract=q.original_extract,
                        selected_option_id=sub.selected_option_id if sub else None,
                        answer_text=sub.answer_text if sub else None,
                        earned_marks=earned,
                        feedback=dict(sub.feedback) if sub else {},
                        awarded_criterion_ids=tuple(sub.awarded_criterion_ids or []) if sub else (),
                    )
                )

            return SessionReview(
                session_id=session_id,
                room_id=room_id,
                viewer_user_id=user_id,
                total_earned_marks=total_earned,
                total_available_marks=session_model.total_available_marks,
                questions=tuple(review_items),
            )

    def _grading_candidates(self, *, expired: bool, limit: int) -> tuple[UUID, ...]:
        if limit < 1:
            return ()
        with self._session_factory() as session:
            eligibility = (
                and_(AnswerSubmissionModel.grading_status == "IN_PROGRESS",
                     AnswerSubmissionModel.lease_expires_at <= func.clock_timestamp())
                if expired else
                and_(AnswerSubmissionModel.grading_status.in_(["PENDING", "RETRYABLE"]),
                     AnswerSubmissionModel.attempt_count < 2,
                     (AnswerSubmissionModel.next_attempt_at.is_(None)) |
                     (AnswerSubmissionModel.next_attempt_at <= func.clock_timestamp()))
            )
            return tuple(session.scalars(
                select(AnswerSubmissionModel.id)
                .join(QuizSessionModel, QuizSessionModel.id == AnswerSubmissionModel.session_id)
                .join(SessionQuestionModel, SessionQuestionModel.id == AnswerSubmissionModel.session_question_id)
                .where(eligibility, AnswerSubmissionModel.grading_method == "LUNA_RUBRIC",
                       QuizSessionModel.status.in_(["QUESTION_OPEN", "QUESTION_GRADING"]),
                       SessionQuestionModel.position == QuizSessionModel.current_question_position)
                .order_by(AnswerSubmissionModel.submitted_at, AnswerSubmissionModel.id)
                .limit(min(limit, 100))
            ).all())

    def claim_due_written_submissions(
        self, limit: int = 10, lease_seconds: int = 30,
    ) -> tuple[ClaimedSubmission, ...]:
        claimed: list[ClaimedSubmission] = []
        for submission_id in self._grading_candidates(expired=False, limit=limit):
            with self._session_factory() as session, session.begin():
                locked = _lock_current_written_submission(session, submission_id, skip_locked=True)
                if locked is None:
                    continue
                owning_session, sub, question = locked
                now = _database_clock(session)
                if (sub.grading_status not in ("PENDING", "RETRYABLE")
                    or sub.attempt_count >= 2
                    or (sub.next_attempt_at is not None and sub.next_attempt_at > now)):
                    continue
                token = uuid4()
                sub.grading_status = "IN_PROGRESS"
                sub.claim_token = token
                sub.lease_expires_at = now + timedelta(seconds=lease_seconds)
                sub.attempt_count += 1
                _bump_session_version(owning_session)
                claimed.append(ClaimedSubmission(
                    submission_id=sub.id, session_id=sub.session_id,
                    session_question_id=sub.session_question_id, participant_id=sub.participant_id,
                    claim_token=token, attempt_count=sub.attempt_count, attempt_cycle=sub.attempt_cycle,
                    answer_text=sub.answer_text or "", question_prompt=question.prompt_snapshot,
                    original_extract=question.original_extract, max_marks=question.max_marks,
                    grading_rubric=dict(question.grading_rubric_snapshot),
                    session_state_version=owning_session.state_version,
                ))
                session.flush()
        return tuple(claimed)

    def reset_expired_grading_claims(self, limit: int = 100) -> tuple[UUID, ...]:
        """Recover a bounded ordered batch, skipping locked parents and answers.

        Each mutation owns the session before its answer and rechecks the
        current question and lease after locking. Two attempts exhaust a cycle.
        """
        affected: set[UUID] = set()
        for submission_id in self._grading_candidates(expired=True, limit=limit):
            with self._session_factory() as session, session.begin():
                locked = _lock_current_written_submission(session, submission_id, skip_locked=True)
                if locked is None:
                    continue
                owning_session, sub, _ = locked
                now = _database_clock(session)
                if (sub.grading_status != "IN_PROGRESS" or sub.lease_expires_at is None
                    or sub.lease_expires_at > now):
                    continue
                sub.grading_status = "UNAVAILABLE" if sub.attempt_count >= 2 else "PENDING"
                sub.next_attempt_at = None if sub.attempt_count >= 2 else now
                sub.claim_token = None
                sub.lease_expires_at = None
                sub.awarded_criterion_ids = []
                sub.feedback = {}
                affected.add(sub.session_id)
                _bump_session_version(owning_session)
                session.flush()
        return tuple(sorted(affected, key=str))

    def store_written_grading_result_cas(
        self,
        submission_id: UUID,
        claim_token: UUID,
        earned_marks: int,
        is_correct: bool,
        points: int,
        awarded_criterion_ids: Sequence[str],
        feedback: dict[str, Any],
    ) -> bool:
        with self._session_factory() as session:
            with session.begin():
                locked = _lock_current_written_submission(session, submission_id)
                if locked is None:
                    return False
                quiz_sess, sub, _ = locked

                now = _database_clock(session)
                if (
                    sub.claim_token != claim_token
                    or sub.grading_status != "IN_PROGRESS"
                    or sub.lease_expires_at is None
                    or sub.lease_expires_at <= now
                ):
                    # Stale token, superseded claim, or expired lease: a late
                    # provider result must never resurrect or overwrite state.
                    return False

                sub.grading_status = "GRADED"
                sub.earned_marks = earned_marks
                sub.is_correct = is_correct
                sub.points = points
                sub.awarded_criterion_ids = list(awarded_criterion_ids)
                sub.feedback = feedback
                sub.graded_at = now
                sub.claim_token = None
                sub.lease_expires_at = None
                sub.last_error_category = None
                _bump_session_version(quiz_sess)
                session.flush()
                return True

    def mark_written_grading_retryable_or_unavailable(
        self,
        submission_id: UUID,
        claim_token: UUID,
        error_category: str,
        backoff_seconds: int = 5,
    ) -> bool:
        with self._session_factory() as session:
            with session.begin():
                locked = _lock_current_written_submission(session, submission_id)
                if locked is None:
                    return False
                quiz_sess, sub, _ = locked

                now = _database_clock(session)
                if (
                    sub.claim_token != claim_token
                    or sub.grading_status != "IN_PROGRESS"
                    or sub.lease_expires_at is None
                    or sub.lease_expires_at <= now
                ):
                    return False

                if sub.attempt_count < 2:
                    sub.grading_status = "RETRYABLE"
                    sub.next_attempt_at = now + timedelta(seconds=backoff_seconds)
                else:
                    sub.grading_status = "UNAVAILABLE"
                    sub.next_attempt_at = None

                sub.claim_token = None
                sub.lease_expires_at = None
                sub.last_error_category = error_category
                # Non-GRADED rows carry no awarded IDs or feedback.
                sub.awarded_criterion_ids = []
                sub.feedback = {}
                _bump_session_version(quiz_sess)
                session.flush()
                return True

    def retry_grading_for_room(
        self,
        room_id: UUID,
        requesting_user_id: UUID,
    ) -> int:
        with self._session_factory() as session:
            with session.begin():
                room = _lock_room(session, room_id)
                if room is None:
                    raise RoomNotFoundError
                if room.closed_at is not None:
                    raise RoomClosedError
                if room.owner_id != requesting_user_id:
                    raise RoomOwnerRequiredError

                active_session = _find_active_session(session, room_id, for_update=True)
                if active_session is None or active_session.status != QuizSessionStatus.QUESTION_GRADING.value:
                    return 0

                unavail_subs = list(
                    session.scalars(
                        select(AnswerSubmissionModel)
                        .join(
                            SessionQuestionModel,
                            SessionQuestionModel.id == AnswerSubmissionModel.session_question_id,
                        )
                        .where(
                            AnswerSubmissionModel.session_id == active_session.id,
                            SessionQuestionModel.position == active_session.current_question_position,
                            AnswerSubmissionModel.grading_status == "UNAVAILABLE",
                        )
                        .order_by(AnswerSubmissionModel.id)
                        .limit(100)
                        .with_for_update(of=AnswerSubmissionModel, skip_locked=True)
                    ).all()
                )

                now = _database_clock(session)
                for sub in unavail_subs:
                    sub.grading_status = "PENDING"
                    sub.attempt_cycle += 1
                    sub.attempt_count = 0
                    sub.next_attempt_at = now
                    sub.claim_token = None
                    sub.lease_expires_at = None
                    sub.last_error_category = None

                if unavail_subs:
                    # Advance the session version so every participant's
                    # snapshot observes the new grading cycle.
                    active_session.state_version += 1
                session.flush()
                return len(unavail_subs)


def _bump_session_version(locked_session: QuizSessionModel) -> None:
    """Caller must hold the session row lock before any answer mutation."""
    locked_session.state_version += 1


def _lock_current_written_submission(
    session: Session, submission_id: UUID, *, skip_locked: bool = False,
) -> tuple[QuizSessionModel, AnswerSubmissionModel, SessionQuestionModel] | None:
    # Only an ID hint is read before acquiring the parent lock. No answer
    # lock is retained while waiting for a submit/reconcile/retry transaction.
    session_id = session.scalar(select(AnswerSubmissionModel.session_id).where(
        AnswerSubmissionModel.id == submission_id
    ))
    if session_id is None:
        return None
    quiz = session.scalar(select(QuizSessionModel).where(QuizSessionModel.id == session_id)
                          .with_for_update(skip_locked=skip_locked))
    if quiz is None or quiz.status not in ("QUESTION_OPEN", "QUESTION_GRADING"):
        return None
    sub = session.scalar(select(AnswerSubmissionModel).where(
        AnswerSubmissionModel.id == submission_id, AnswerSubmissionModel.session_id == quiz.id,
    ).with_for_update(skip_locked=skip_locked))
    if sub is None or sub.grading_method != "LUNA_RUBRIC":
        return None
    question = session.get(SessionQuestionModel, sub.session_question_id)
    room = session.get(RoomModel, quiz.room_id)
    if (question is None or question.session_id != quiz.id
        or question.position != quiz.current_question_position or question.question_type != "WRITTEN"
        or room is None or room.closed_at is not None):
        return None
    return quiz, sub, question


def _reconcile_locked(
    session: Session,
    session_model: QuizSessionModel,
) -> QuizSession:
    if session_model.status == QuizSessionStatus.FINISHED.value:
        return _to_session(session_model)
    if session_model.status not in _ACTIVE_SESSION_STATUSES:
        raise InvalidSessionTransitionError

    now = _database_clock(session)
    current_question = session.scalar(
        select(SessionQuestionModel).where(
            SessionQuestionModel.session_id == session_model.id,
            SessionQuestionModel.position == session_model.current_question_position,
        )
    )
    if current_question is None:
        raise InvalidSessionTransitionError

    is_adaptive = session_model.quiz_mode == "ADAPTIVE"
    reveal_seconds = (
        calculate_reveal_duration_seconds(current_question.max_marks)
        if is_adaptive
        else REVEAL_DURATION_SECONDS
    )

    if session_model.status == QuizSessionStatus.QUESTION_OPEN.value:
        if current_question.closes_at is None:
            raise InvalidSessionTransitionError
        if now < current_question.closes_at:
            return _to_session(session_model)

        # Check for any accepted answers still pending grading
        pending_grades_exist = session.scalar(
            select(func.count(AnswerSubmissionModel.id)).where(
                AnswerSubmissionModel.session_question_id == current_question.id,
                AnswerSubmissionModel.grading_status != "GRADED",
            )
        )
        if pending_grades_exist and pending_grades_exist > 0:
            # Transition to QUESTION_GRADING
            session_model.status = QuizSessionStatus.QUESTION_GRADING.value
            session_model.reveal_ends_at = None
            session_model.state_version += 1
            session.flush()
            return _to_session(session_model)

        # All graded or no submissions -> enter QUESTION_REVEAL
        current_question.revealed_at = now
        session_model.status = QuizSessionStatus.QUESTION_REVEAL.value
        session_model.reveal_ends_at = now + timedelta(seconds=reveal_seconds)
        session_model.state_version += 1
        session.flush()
        return _to_session(session_model)

    if session_model.status == QuizSessionStatus.QUESTION_GRADING.value:
        # Check if all submissions are now GRADED
        pending_grades_exist = session.scalar(
            select(func.count(AnswerSubmissionModel.id)).where(
                AnswerSubmissionModel.session_question_id == current_question.id,
                AnswerSubmissionModel.grading_status != "GRADED",
            )
        )
        if pending_grades_exist and pending_grades_exist > 0:
            # Still waiting on grades
            return _to_session(session_model)

        # All final -> transition to reveal
        current_question.revealed_at = now
        session_model.status = QuizSessionStatus.QUESTION_REVEAL.value
        session_model.reveal_ends_at = now + timedelta(seconds=reveal_seconds)
        session_model.state_version += 1
        session.flush()
        return _to_session(session_model)

    if session_model.status != QuizSessionStatus.QUESTION_REVEAL.value:
        raise InvalidSessionTransitionError
    if session_model.reveal_ends_at is None:
        raise InvalidSessionTransitionError
    if now < session_model.reveal_ends_at:
        return _to_session(session_model)

    next_question = session.scalar(
        select(SessionQuestionModel).where(
            SessionQuestionModel.session_id == session_model.id,
            SessionQuestionModel.position == session_model.current_question_position + 1,
        )
    )
    if next_question is None:
        session_model.status = QuizSessionStatus.FINISHED.value
        session_model.finished_at = now
        session_model.reveal_ends_at = None
        session_model.state_version += 1
        insert_room_completion_receipts(
            session,
            session_id=session_model.id,
            completed_at=now,
            completion_state_version=session_model.state_version,
        )
    else:
        session_model.current_question_position += 1
        session_model.status = QuizSessionStatus.QUESTION_OPEN.value
        session_model.reveal_ends_at = None
        next_question.opened_at = now
        next_question.closes_at = now + timedelta(seconds=next_question.duration_seconds)
        session_model.state_version += 1

    session.flush()
    return _to_session(session_model)


def _derive_leaderboard(
    session: Session,
    session_id: UUID,
    *,
    revealed_only: bool,
    is_adaptive: bool = False,
    total_available_marks: int = 5,
) -> tuple[LeaderboardEntry, ...]:
    visible = SessionQuestionModel.revealed_at.is_not(None) if revealed_only else True
    points_total = func.coalesce(
        func.sum(case((visible, AnswerSubmissionModel.points), else_=0)),
        0,
    )
    marks_total = func.coalesce(
        func.sum(case((visible, AnswerSubmissionModel.earned_marks), else_=0)),
        0,
    )
    correct_condition = and_(visible, AnswerSubmissionModel.is_correct.is_(True))
    correct_count = func.coalesce(
        func.sum(case((correct_condition, 1), else_=0)),
        0,
    )
    response_time_total = func.coalesce(
        func.sum(
            case((correct_condition, AnswerSubmissionModel.response_time_ms), else_=0)
        ),
        0,
    )
    statement = (
        select(
            SessionParticipantModel.id,
            SessionParticipantModel.user_id,
            SessionParticipantModel.display_name_snapshot,
            points_total.label("points"),
            marks_total.label("earned_marks"),
            correct_count.label("correct_count"),
            response_time_total.label("response_time_ms"),
        )
        .outerjoin(
            AnswerSubmissionModel,
            (AnswerSubmissionModel.session_id == SessionParticipantModel.session_id)
            & (AnswerSubmissionModel.participant_id == SessionParticipantModel.id),
        )
        .outerjoin(
            SessionQuestionModel,
            (SessionQuestionModel.session_id == SessionParticipantModel.session_id)
            & (SessionQuestionModel.id == AnswerSubmissionModel.session_question_id),
        )
        .where(SessionParticipantModel.session_id == session_id)
        .group_by(
            SessionParticipantModel.id,
            SessionParticipantModel.user_id,
            SessionParticipantModel.display_name_snapshot,
        )
    )
    rows = session.execute(statement).all()

    if is_adaptive:
        # Sort by raw earned marks only
        sorted_rows = sorted(
            rows,
            key=lambda row: (-int(row.earned_marks), str(row.user_id)),
        )
        entries: list[LeaderboardEntry] = []
        current_rank = 1
        for idx, row in enumerate(sorted_rows):
            if idx > 0 and int(row.earned_marks) == int(sorted_rows[idx - 1].earned_marks):
                rank = entries[idx - 1].rank
            else:
                rank = idx + 1
            entries.append(
                LeaderboardEntry(
                    rank=rank,
                    participant_id=row.id,
                    user_id=row.user_id,
                    display_name=row.display_name_snapshot,
                    points=int(row.points),
                    correct_count=int(row.correct_count),
                    total_response_time_ms=int(row.response_time_ms),
                    earned_marks=int(row.earned_marks),
                    total_available_marks=total_available_marks,
                )
            )
        return tuple(entries)
    else:
        # Legacy sorting: points, correct count, response time, user_id
        ranked_rows = sorted(
            rows,
            key=lambda row: (
                -int(row.points),
                -int(row.correct_count),
                int(row.response_time_ms),
                str(row.user_id),
            ),
        )
        return tuple(
            LeaderboardEntry(
                rank=rank,
                participant_id=row.id,
                user_id=row.user_id,
                display_name=row.display_name_snapshot,
                points=int(row.points),
                correct_count=int(row.correct_count),
                total_response_time_ms=int(row.response_time_ms),
                earned_marks=int(row.earned_marks),
                total_available_marks=total_available_marks,
            )
            for rank, row in enumerate(ranked_rows, start=1)
        )


def _to_visible_question(
    model: SessionQuestionModel,
    *,
    total_questions: int,
    revealed: bool,
) -> PublicQuestion | RevealedQuestion:
    if model.closes_at is None:
        raise InvalidSessionTransitionError
    options = _question_options(model.options_snapshot)
    if revealed:
        return RevealedQuestion(
            id=model.id,
            prompt=model.prompt_snapshot,
            options=options,
            question_number=model.position + 1,
            total_questions=total_questions,
            closes_at=_to_utc(model.closes_at),
            correct_option_id=model.correct_option_id,
            question_type=model.question_type,
            max_marks=model.max_marks,
            worked_explanation=model.worked_explanation_snapshot,
            original_extract=model.original_extract,
        )
    return PublicQuestion(
        id=model.id,
        prompt=model.prompt_snapshot,
        options=options,
        question_number=model.position + 1,
        total_questions=total_questions,
        closes_at=_to_utc(model.closes_at),
        question_type=model.question_type,
        max_marks=model.max_marks,
        original_extract=model.original_extract,
    )


def _to_room(model: RoomModel) -> Room:
    return Room(
        id=model.id,
        owner_id=model.owner_id,
        name=model.name,
        join_code=model.join_code,
        maximum_members=model.maximum_members,
        closed_at=_to_utc(model.closed_at) if model.closed_at else None,
        quiz_mode=model.quiz_mode,
        education_level=model.education_level,
        quiz_subject=model.quiz_subject,
        quiz_topic=model.quiz_topic,
        target_total_marks=model.target_total_marks,
    )


def _viewer_role(room: RoomModel, user_id: UUID) -> ViewerRole:
    return ViewerRole.HOST if room.owner_id == user_id else ViewerRole.MEMBER


def _to_session(model: QuizSessionModel) -> QuizSession:
    return QuizSession(
        id=model.id,
        room_id=model.room_id,
        question_bank_key=model.question_bank_key,
        status=QuizSessionStatus(model.status),
        current_question_position=model.current_question_position,
        state_version=model.state_version,
        started_at=_to_utc(model.started_at),
        reveal_ends_at=_to_utc(model.reveal_ends_at) if model.reveal_ends_at else None,
        finished_at=_to_utc(model.finished_at) if model.finished_at else None,
        preparation_id=model.preparation_id,
        quiz_mode=model.quiz_mode,
        education_level=model.education_level,
        quiz_subject=model.quiz_subject,
        quiz_topic=model.quiz_topic,
        total_available_marks=model.total_available_marks,
    )


def _to_participant(model: SessionParticipantModel) -> SessionParticipant:
    return SessionParticipant(
        id=model.id,
        session_id=model.session_id,
        user_id=model.user_id,
        room_membership_id=model.room_membership_id,
        display_name_snapshot=model.display_name_snapshot,
        created_at=_to_utc(model.created_at),
    )


def _to_session_question(model: SessionQuestionModel) -> SessionQuestion:
    return SessionQuestion(
        id=model.id,
        session_id=model.session_id,
        source_question_id=model.source_question_id,
        position=model.position,
        prompt_snapshot=model.prompt_snapshot,
        options_snapshot=tuple(
            QuestionOption(id=opt["id"], label=opt["label"])
            for opt in model.options_snapshot
        ),
        correct_option_id=model.correct_option_id,
        duration_seconds=model.duration_seconds,
        opened_at=_to_utc(model.opened_at) if model.opened_at else None,
        closes_at=_to_utc(model.closes_at) if model.closes_at else None,
        revealed_at=_to_utc(model.revealed_at) if model.revealed_at else None,
        generated_question_id=model.generated_question_id,
        question_type=model.question_type,
        max_marks=model.max_marks,
        grading_rubric_snapshot=dict(model.grading_rubric_snapshot),
        worked_explanation_snapshot=model.worked_explanation_snapshot,
        original_extract=model.original_extract,
        content_fingerprint=model.content_fingerprint,
    )


def _to_submission(model: AnswerSubmissionModel) -> AnswerSubmission:
    return AnswerSubmission(
        id=model.id,
        session_id=model.session_id,
        session_question_id=model.session_question_id,
        participant_id=model.participant_id,
        selected_option_id=model.selected_option_id,
        submitted_at=_to_utc(model.submitted_at),
        response_time_ms=model.response_time_ms,
        is_correct=model.is_correct,
        points=model.points,
        answer_text=model.answer_text,
        earned_marks=model.earned_marks,
        grading_method=model.grading_method,
        grading_status=model.grading_status,
        attempt_cycle=model.attempt_cycle,
        attempt_count=model.attempt_count,
        claim_token=model.claim_token,
        lease_expires_at=_to_utc(model.lease_expires_at) if model.lease_expires_at else None,
        next_attempt_at=_to_utc(model.next_attempt_at) if model.next_attempt_at else None,
        last_error_category=model.last_error_category,
        awarded_criterion_ids=tuple(model.awarded_criterion_ids or []),
        feedback=dict(model.feedback) if model.feedback else {},
        graded_at=_to_utc(model.graded_at) if model.graded_at else None,
    )


def _room_only_snapshot(
    *,
    server_time: datetime,
    room_model: RoomModel,
    user_id: UUID,
    participants: tuple[ParticipantSnapshot, ...],
    viewer_membership: RoomMembershipModel,
    total_question_count: int,
    active_prep: QuizPreparationModel | None = None,
) -> AuthoritativeSnapshot:
    return AuthoritativeSnapshot(
        server_time=server_time,
        room=_to_room(room_model),
        viewer_role=_viewer_role(room_model, user_id),
        participants=participants,
        viewer_ready=viewer_membership.ready_at is not None,
        session=None,
        viewer_participated=False,
        state_version=0,
        current_question_number=None,
        total_question_count=total_question_count,
        question=None,
        closes_at=None,
        reveal_ends_at=None,
        viewer_submission=None,
        leaderboard=(),
        finished_at=None,
        active_preparation_status=active_prep.status if active_prep else None,
        active_preparation_version=active_prep.state_version if active_prep else None,
        active_preparation_error_category=active_prep.error_category if active_prep else None,
    )


def _lock_room(session: Session, room_id: UUID) -> RoomModel | None:
    return session.scalar(
        select(RoomModel).where(RoomModel.id == room_id).with_for_update()
    )


def _lock_user_for_session_start(
    session: Session,
    user_id: UUID,
) -> UserModel | None:
    try:
        return session.scalar(
            select(UserModel).where(UserModel.id == user_id).with_for_update(nowait=True)
        )
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03":
            raise SessionStartConflictError from error
        raise


def _find_active_session(
    session: Session,
    room_id: UUID,
    *,
    for_update: bool = False,
) -> QuizSessionModel | None:
    statement = select(QuizSessionModel).where(
        QuizSessionModel.room_id == room_id,
        QuizSessionModel.status.in_(_ACTIVE_SESSION_STATUSES),
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _load_canonical_question_models(session: Session) -> list[QuestionModel]:
    models = list(
        session.scalars(
            select(QuestionModel)
            .where(
                QuestionModel.bank_key == PHYSICS_SPRINT_BANK_KEY,
                QuestionModel.is_active.is_(True),
            )
            .order_by(QuestionModel.position)
        ).all()
    )
    if len(models) != 5:
        raise QuestionBankUnavailableError
    return models


def _adaptive_lobby_question_count(session: Session, room_id: UUID) -> int:
    """Count the latest usable adaptive prepared set, else 0 for the lobby."""
    latest_usable = session.scalar(
        select(QuizPreparationModel)
        .where(
            QuizPreparationModel.room_id == room_id,
            QuizPreparationModel.status.in_(["READY", "CONSUMED"]),
        )
        .order_by(
            QuizPreparationModel.created_at.desc(),
            QuizPreparationModel.id.desc(),
        )
        .limit(1)
    )
    if latest_usable is None:
        return 0
    return (
        session.scalar(
            select(func.count(GeneratedQuizQuestionModel.id)).where(
                GeneratedQuizQuestionModel.preparation_id == latest_usable.id
            )
        )
        or 0
    )


def _safe_question_count(session: Session) -> int:
    return (
        session.scalar(
            select(func.count(QuestionModel.id)).where(
                QuestionModel.bank_key == PHYSICS_SPRINT_BANK_KEY,
                QuestionModel.is_active.is_(True),
            )
        )
        or 5
    )


def _question_options(
    options_payload: list[dict[str, str]],
) -> tuple[QuestionOption, ...]:
    return tuple(
        QuestionOption(id=str(option["id"]), label=str(option["label"]))
        for option in options_payload
    )


def _option_dicts(options: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return [{"id": opt["id"], "label": opt["label"]} for opt in options]
