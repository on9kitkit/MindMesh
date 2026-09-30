"""Pure qualification tests; transactional PostgreSQL evidence is separate."""

from datetime import datetime, timezone
from uuid import uuid4

from app.learning_companions.room_receipts import (
    RoomAnswerEvidence,
    latest_qualified_answer,
)


def _accepted(hour: int) -> datetime:
    return datetime(2026, 9, 27, hour, tzinfo=timezone.utc)


def test_full_graded_coverage_uses_latest_original_acceptance_not_score() -> None:
    participant = uuid4()
    question_a, question_b = uuid4(), uuid4()
    other = uuid4()
    result = latest_qualified_answer(
        question_ids=frozenset((question_a, question_b)),
        participant_id=participant,
        answers=(
            RoomAnswerEvidence(participant, question_a, _accepted(8), "GRADED"),
            RoomAnswerEvidence(other, question_b, _accepted(20), "GRADED"),
            RoomAnswerEvidence(participant, question_b, _accepted(9), "GRADED"),
        ),
    )
    assert result == _accepted(9)


def test_missing_ungraded_and_empty_evidence_never_qualify() -> None:
    participant = uuid4()
    question_a, question_b = uuid4(), uuid4()
    accepted = RoomAnswerEvidence(participant, question_a, _accepted(8), "GRADED")
    pending = RoomAnswerEvidence(participant, question_b, _accepted(9), "UNAVAILABLE")
    assert latest_qualified_answer(
        question_ids=frozenset(), participant_id=participant, answers=(accepted,)
    ) is None
    assert latest_qualified_answer(
        question_ids=frozenset((question_a, question_b)),
        participant_id=participant,
        answers=(accepted,),
    ) is None
    assert latest_qualified_answer(
        question_ids=frozenset((question_a, question_b)),
        participant_id=participant,
        answers=(accepted, pending),
    ) is None


def test_foreign_or_naive_answers_do_not_fill_coverage() -> None:
    participant, other = uuid4(), uuid4()
    question = uuid4()
    assert latest_qualified_answer(
        question_ids=frozenset((question,)),
        participant_id=participant,
        answers=(RoomAnswerEvidence(other, question, _accepted(8), "GRADED"),),
    ) is None
    assert latest_qualified_answer(
        question_ids=frozenset((question,)),
        participant_id=participant,
        answers=(
            RoomAnswerEvidence(
                participant, question, datetime(2026, 9, 27, 8), "GRADED"
            ),
        ),
    ) is None
