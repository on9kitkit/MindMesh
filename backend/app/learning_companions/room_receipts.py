"""Start-time room reward enrollment and answer-free completion receipts.

These helpers run inside the caller's existing room/session transaction. They
never acquire a user or wallet lock during the FINISHED transition. The
separate reward worker owns user-first posting after this transaction commits.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.learning_companions.contracts import (
    CompletionEvidence,
    CompletionSource,
    REWARD_RULE_VERSION,
)
from app.learning_companions.models import (
    LearningSettingsModel,
    RoomRewardEnrollmentModel,
)
from app.learning_companions.reward_repository import insert_completion_receipt


@dataclass(frozen=True, slots=True)
class RoomAnswerEvidence:
    participant_id: UUID
    question_id: UUID
    accepted_at: datetime
    grading_status: str


def latest_qualified_answer(
    *,
    question_ids: frozenset[UUID],
    participant_id: UUID,
    answers: Iterable[RoomAnswerEvidence],
) -> datetime | None:
    """Return the latest original accepted instant iff all questions were answered.

    A FINISHED session should have only graded answers, but fail closed if the
    supplied evidence contradicts that invariant. Score/correctness is not a
    qualification input.
    """
    if not question_ids:
        return None
    accepted: dict[UUID, datetime] = {}
    for answer in answers:
        if answer.participant_id != participant_id:
            continue
        if answer.question_id not in question_ids or answer.grading_status != "GRADED":
            continue
        if answer.accepted_at.tzinfo is None:
            continue
        accepted[answer.question_id] = answer.accepted_at.astimezone(timezone.utc)
    if frozenset(accepted) != question_ids:
        return None
    return max(accepted.values())


def enroll_room_participants(session: Session, *, session_id: UUID) -> None:
    """Snapshot only already-configured participants at normal room start.

    Missing settings intentionally mean no reward for this room: a later zone
    choice must not retroactively enroll an active or historical session.
    The start transaction has already checked and locked its participant users.
    """
    participants = tuple(
        session.scalars(
            select(SessionParticipantModel).where(
                SessionParticipantModel.session_id == session_id
            )
        ).all()
    )
    if not participants:
        return
    settings = {
        entry.user_id: entry
        for entry in session.scalars(
            select(LearningSettingsModel).where(
                LearningSettingsModel.user_id.in_(
                    tuple(participant.user_id for participant in participants)
                )
            )
        ).all()
    }
    for participant in participants:
        setting = settings.get(participant.user_id)
        if setting is None:
            continue
        session.add(
            RoomRewardEnrollmentModel(
                session_id=session_id,
                participant_id=participant.id,
                user_id=participant.user_id,
                home_timezone_snapshot=setting.home_timezone,
                home_zone_version=setting.home_zone_version,
                reward_rule_version=REWARD_RULE_VERSION,
            )
        )


def insert_room_completion_receipts(
    session: Session,
    *,
    session_id: UUID,
    completed_at: datetime,
    completion_state_version: int,
) -> None:
    """Insert qualifying per-person receipts before FINISHED commits.

    Only IDs, status and acceptance instants are read from answers; their
    contents, scores, peers and room codes never enter the receipt.
    """
    question_ids = frozenset(
        session.scalars(
            select(SessionQuestionModel.id).where(
                SessionQuestionModel.session_id == session_id
            )
        ).all()
    )
    if not question_ids:
        return
    enrollments = tuple(
        session.scalars(
            select(RoomRewardEnrollmentModel).where(
                RoomRewardEnrollmentModel.session_id == session_id
            )
        ).all()
    )
    if not enrollments:
        return
    participants = {
        participant.id: participant.user_id
        for participant in session.scalars(
            select(SessionParticipantModel).where(
                SessionParticipantModel.session_id == session_id
            )
        ).all()
    }
    answers = tuple(
        RoomAnswerEvidence(participant_id, question_id, accepted_at, grading_status)
        for participant_id, question_id, accepted_at, grading_status in session.execute(
            select(
                AnswerSubmissionModel.participant_id,
                AnswerSubmissionModel.session_question_id,
                AnswerSubmissionModel.submitted_at,
                AnswerSubmissionModel.grading_status,
            ).where(AnswerSubmissionModel.session_id == session_id)
        ).all()
    )
    for enrollment in enrollments:
        if participants.get(enrollment.participant_id) != enrollment.user_id:
            continue
        latest_accepted_at = latest_qualified_answer(
            question_ids=question_ids,
            participant_id=enrollment.participant_id,
            answers=answers,
        )
        if latest_accepted_at is None or latest_accepted_at > completed_at:
            continue
        insert_completion_receipt(
            session,
            CompletionEvidence(
                user_id=enrollment.user_id,
                source_kind=CompletionSource.ROOM,
                source_id=session_id,
                terminal_state="FINISHED",
                canonical_question_count=len(question_ids),
                distinct_accepted_answer_count=len(question_ids),
                latest_original_accepted_at_utc=latest_accepted_at,
                home_timezone_snapshot=enrollment.home_timezone_snapshot,
                home_zone_version=enrollment.home_zone_version,
                completed_at_utc=completed_at,
                completion_state_version=completion_state_version,
                reward_rule_version=enrollment.reward_rule_version,
            ),
        )
