"""Offline repository boundary checks; PostgreSQL races remain a release gate."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects.postgresql import dialect

from app.generator.fake_adapter import FakeQuizContentGenerator
from app.generator.protocol import GenerationRequest
from app.generator.verified_runner import generate_verified_quiz
from app.generator.verification.fixtures import FakeQuizContentVerifier
from app.learning_companions.models import SoloAnswerModel, SoloAttemptModel, SoloQuestionModel
from app.learning_companions.solo_domain import SoloError
from app.learning_companions.solo_repository import PostgresSoloRepository, _reconcile_completion


class _RowsSession:
    def __init__(
        self, questions: tuple[SoloQuestionModel, ...], answers: tuple[SoloAnswerModel, ...],
        *, finalized_self_checks: tuple[UUID, ...] | None = None,
    ) -> None:
        checks = finalized_self_checks if finalized_self_checks is not None else tuple(
            answer.id for answer in answers if answer.mark_provenance == "SELF_ASSESSED"
        )
        self._rows = [questions, answers, checks]
        self.added: list[object] = []

    def scalars(self, _statement: object):
        return iter(self._rows.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)


def _attempt() -> SoloAttemptModel:
    return SoloAttemptModel(
        id=uuid4(), owner_id=uuid4(), request_id=uuid4(), status="IN_PROGRESS",
        state_version=5, subject="physics", topic="forces", total_marks=5,
        current_question_position=2, home_timezone_snapshot="Europe/London",
        home_zone_version=1, reward_rule_version=1,
    )


def _rows(attempt: SoloAttemptModel, accepted_at: datetime, *, ai_last: bool = False):
    questions = tuple(SoloQuestionModel(
        id=uuid4(), attempt_id=attempt.id, position=position,
        question_type="WRITTEN", max_marks=5 if ai_last and position == 1 else position + 2,
        prompt_snapshot="prompt", options_snapshot=[], correct_option_id=None,
        grading_rubric_snapshot={"criteria": []}, worked_explanation_snapshot="explanation",
        content_fingerprint=f"fingerprint_{position}",
    ) for position in range(2))
    answers = tuple(SoloAnswerModel(
        id=uuid4(), attempt_id=attempt.id, question_id=question.id,
        answer_text="valid, accepted response", selected_option_id=None,
        accepted_at=accepted_at + timedelta(minutes=position),
        grading_status="GRADED",
        mark_provenance="AI_RUBRIC" if ai_last and position == 1 else "SELF_ASSESSED",
        earned_marks=0, graded_at=accepted_at + timedelta(minutes=position + 1),
        feedback={}, awarded_criterion_ids=[],
    ) for position, question in enumerate(questions))
    return questions, answers


def test_zero_marked_full_coverage_finishes_with_original_study_day_receipt() -> None:
    attempt = _attempt()
    accepted_at = datetime(2026, 3, 29, 23, 30, tzinfo=timezone.utc)
    questions, answers = _rows(attempt, accepted_at)
    session = _RowsSession(questions, answers)
    completed_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
    _reconcile_completion(session, attempt, completed_at)
    assert attempt.status == "FINISHED"
    assert attempt.terminal_at == completed_at
    assert len(session.added) == 1
    receipt = session.added[0]
    assert receipt.user_id == attempt.owner_id
    assert receipt.source_kind == "solo" and receipt.source_id == attempt.id
    assert receipt.canonical_question_count == receipt.accepted_answer_count == 2
    assert receipt.latest_accepted_at == answers[-1].accepted_at
    assert receipt.study_date.isoformat() == "2026-03-30"  # London after DST jump
    assert receipt.completed_at == completed_at
    assert receipt.status == "pending"
    assert not hasattr(receipt, "answer_text")


def test_pending_grade_never_finishes_or_mints_reward_then_keeps_answer_anchor() -> None:
    attempt = _attempt()
    attempt.total_marks = 7
    accepted_at = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    questions, answers = _rows(attempt, accepted_at, ai_last=True)
    answers[-1].grading_status = "UNAVAILABLE"
    answers[-1].earned_marks = None
    answers[-1].graded_at = None
    pending = _RowsSession(questions, answers)
    _reconcile_completion(pending, attempt, datetime(2026, 10, 25, tzinfo=timezone.utc))
    assert attempt.status == "AWAITING_MARKING" and not pending.added
    answers[-1].grading_status = "GRADED"
    answers[-1].earned_marks = 0
    answers[-1].graded_at = datetime(2026, 10, 29, tzinfo=timezone.utc)
    settled = _RowsSession(questions, answers)
    _reconcile_completion(settled, attempt, datetime(2026, 10, 29, tzinfo=timezone.utc))
    assert settled.added[0].study_date.isoformat() == "2026-10-24"


def test_missing_answer_cannot_finish() -> None:
    attempt = _attempt()
    questions, answers = _rows(attempt, datetime(2026, 9, 1, tzinfo=timezone.utc))
    session = _RowsSession(questions, answers[:1])
    _reconcile_completion(session, attempt, datetime(2026, 9, 2, tzinfo=timezone.utc))
    assert attempt.status == "IN_PROGRESS" and not session.added


def test_locked_short_answer_without_finalized_check_cannot_complete_even_at_zero_marks() -> None:
    attempt = _attempt()
    questions, answers = _rows(attempt, datetime(2026, 9, 1, tzinfo=timezone.utc))
    session = _RowsSession(questions, answers, finalized_self_checks=())
    _reconcile_completion(session, attempt, datetime(2026, 9, 2, tzinfo=timezone.utc))
    assert attempt.status == "IN_PROGRESS" and not session.added


class _StatementSession:
    def __init__(self, scalars_results: list[object]) -> None:
        self._results = scalars_results
        self.statements: list[object] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def begin(self):
        return self

    def scalars(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)

    def scalar(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)


def test_terminal_purge_is_bounded_to_terminal_timestamp_and_leaves_receipts_alone() -> None:
    attempt_id = uuid4()
    session = _StatementSession([iter((attempt_id,)), [attempt_id]])
    repository = PostgresSoloRepository(lambda: session)
    cutoff = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert repository.purge_terminal_content(cutoff, limit=1) == 1
    sql = [str(statement.compile(dialect=dialect())) for statement in session.statements]
    assert len(sql) == 2
    assert all("solo_attempts" in statement for statement in sql)
    assert all("terminal_at <=" in statement and "status IN" in statement for statement in sql)
    assert all("learning_completion_receipts" not in statement for statement in sql)
    with pytest.raises(ValueError, match="timezone-aware"):
        repository.purge_terminal_content(cutoff.replace(tzinfo=None))


def test_self_check_lookup_requires_locked_owner_answer_before_rubric_exposure() -> None:
    attempt = _attempt()
    question = SoloQuestionModel(
        id=uuid4(), attempt_id=attempt.id, position=0,
        question_type="WRITTEN", max_marks=3,
        prompt_snapshot="prompt", options_snapshot=[], correct_option_id=None,
        grading_rubric_snapshot={"criteria": [{"id": "hidden"}]},
        worked_explanation_snapshot="secret reference answer", content_fingerprint="fingerprint",
    )
    session = _StatementSession([attempt, question, None])
    repository = PostgresSoloRepository(lambda: session)
    with pytest.raises(SoloError) as error:
        repository.get_self_check(attempt.owner_id, attempt.id, question.id)
    assert error.value.code == "solo_not_found"
    owner_query = str(session.statements[0].compile(dialect=dialect()))
    assert "owner_id" in owner_query


def test_late_preparation_worker_cannot_recreate_deleted_attempt() -> None:
    session = _StatementSession([None, None])
    repository = PostgresSoloRepository(lambda: session)
    owner_id, attempt_id, preparation_id, token = (uuid4() for _ in range(4))
    assert not repository.renew_preparation_lease(
        owner_id, attempt_id, preparation_id, token, lease_seconds=30,
    )
    assert not repository.fail_preparation_cas(
        owner_id, attempt_id, preparation_id, token, "timeout",
    )
    assert len(session.statements) == 2
    assert all("owner_id" in str(statement.compile(dialect=dialect())) for statement in session.statements)


def test_late_verified_generation_cas_cannot_recreate_deleted_attempt() -> None:
    async def verified_set():
        async def renew(_seconds: int) -> bool:
            return True

        return await generate_verified_quiz(
            request=GenerationRequest("GCSE", "physics", "forces", 5),
            generator=FakeQuizContentGenerator(), verifier=FakeQuizContentVerifier(),
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=165),
            deadline_monotonic=asyncio.get_running_loop().time() + 165,
            renew_lease=renew,
        )

    session = _StatementSession([None])
    repository = PostgresSoloRepository(lambda: session)
    assert not repository.store_verified_set_cas(
        uuid4(), uuid4(), uuid4(), uuid4(), 1,
        asyncio.run(verified_set()), datetime.now(timezone.utc) + timedelta(seconds=165),
    )
    assert len(session.statements) == 1
    assert "owner_id" in str(session.statements[0].compile(dialect=dialect()))
