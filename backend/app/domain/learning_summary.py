"""Viewer-only descriptive statistics for retained adaptive GCSE sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.domain.adaptive_quiz import TOPIC_CATALOGUE, validate_subject_and_topic

SESSION_WINDOW_LIMIT = 100
SESSION_QUERY_LIMIT = SESSION_WINDOW_LIMIT + 1
MAX_QUESTION_ROWS = 4_000
MIN_DISTINCT_QUESTIONS_FOR_OBSERVED = 5
MIN_SESSIONS_FOR_OBSERVED = 2

EvidenceStatus = Literal["no_data", "insufficient_evidence", "observed"]


class LearningSummaryIntegrityError(ValueError):
    """Raised when persisted adaptive rows violate their scoring invariants."""


@dataclass(frozen=True, slots=True)
class EligibleLearningSession:
    session_id: UUID
    subject: str
    topic: str


@dataclass(frozen=True, slots=True)
class LearningQuestionRecord:
    session_id: UUID
    max_marks: int
    content_fingerprint: str
    has_submission: bool
    grading_status: str | None
    earned_marks: int | None


@dataclass(frozen=True, slots=True)
class LearningTopicKeyResult:
    subject: str
    topic: str


@dataclass(frozen=True, slots=True)
class LearningTopicResult:
    subject: str
    topic: str
    evidence_status: EvidenceStatus
    finished_session_count: int
    presented_question_count: int
    answered_attempt_count: int
    graded_attempt_count: int
    ungraded_attempt_count: int
    unanswered_question_count: int
    distinct_question_count: int
    repeat_attempt_count: int
    earned_marks: int
    possible_marks: int
    accuracy_on_graded_answers_percent: float | None
    full_credit_attempt_count: int
    partial_credit_attempt_count: int
    zero_credit_attempt_count: int


@dataclass(frozen=True, slots=True)
class LearningSummaryResult:
    status: EvidenceStatus
    session_window_limit: int
    included_session_count: int
    session_window_truncated: bool
    topics: tuple[LearningTopicResult, ...]
    strongest_topics: tuple[LearningTopicKeyResult, ...]
    weakest_topics: tuple[LearningTopicKeyResult, ...]


@dataclass(slots=True)
class _TopicCounts:
    session_ids: set[UUID] = field(default_factory=set)
    fingerprints: set[str] = field(default_factory=set)
    presented_question_count: int = 0
    answered_attempt_count: int = 0
    graded_attempt_count: int = 0
    ungraded_attempt_count: int = 0
    unanswered_question_count: int = 0
    earned_marks: int = 0
    possible_marks: int = 0
    full_credit_attempt_count: int = 0
    partial_credit_attempt_count: int = 0
    zero_credit_attempt_count: int = 0


def summarize_learning_data(
    sessions: tuple[EligibleLearningSession, ...],
    questions: tuple[LearningQuestionRecord, ...],
    *,
    truncated: bool,
) -> LearningSummaryResult:
    """Aggregate bounded viewer-owned question rows into closed metric data."""
    if len(sessions) > SESSION_WINDOW_LIMIT:
        raise LearningSummaryIntegrityError("Session window exceeds its limit.")
    if len(questions) > MAX_QUESTION_ROWS:
        raise LearningSummaryIntegrityError("Question window exceeds its limit.")
    if type(truncated) is not bool:
        raise LearningSummaryIntegrityError("Session truncation flag is invalid.")

    sessions_by_id: dict[UUID, EligibleLearningSession] = {}
    counts_by_topic: dict[tuple[str, str], _TopicCounts] = {}
    for eligible_session in sessions:
        key = _validated_topic_key(eligible_session.subject, eligible_session.topic)
        if eligible_session.session_id in sessions_by_id:
            raise LearningSummaryIntegrityError("Eligible session was duplicated.")
        sessions_by_id[eligible_session.session_id] = eligible_session
        counts_by_topic.setdefault(key, _TopicCounts()).session_ids.add(
            eligible_session.session_id
        )

    for question in questions:
        eligible_session = sessions_by_id.get(question.session_id)
        if eligible_session is None:
            raise LearningSummaryIntegrityError("Question is outside the session window.")
        if type(question.max_marks) is not int or question.max_marks < 1:
            raise LearningSummaryIntegrityError("Question mark maximum is invalid.")

        counts = counts_by_topic[
            (eligible_session.subject, eligible_session.topic)
        ]
        counts.presented_question_count += 1
        if not question.has_submission:
            if question.grading_status is not None or question.earned_marks is not None:
                raise LearningSummaryIntegrityError(
                    "Missing submission contains grading data."
                )
            counts.unanswered_question_count += 1
            continue

        counts.answered_attempt_count += 1
        if question.grading_status != "GRADED":
            if question.grading_status not in {
                "PENDING",
                "IN_PROGRESS",
                "RETRYABLE",
                "UNAVAILABLE",
            } or question.earned_marks is not None:
                raise LearningSummaryIntegrityError(
                    "Ungraded submission contains invalid grading data."
                )
            counts.ungraded_attempt_count += 1
            continue

        earned_marks = question.earned_marks
        if (
            type(earned_marks) is not int
            or earned_marks < 0
            or earned_marks > question.max_marks
        ):
            raise LearningSummaryIntegrityError("Awarded marks are invalid.")
        if not question.content_fingerprint:
            raise LearningSummaryIntegrityError(
                "Adaptive question fingerprint is missing."
            )

        counts.graded_attempt_count += 1
        counts.earned_marks += earned_marks
        counts.possible_marks += question.max_marks
        counts.fingerprints.add(question.content_fingerprint)
        if earned_marks == question.max_marks:
            counts.full_credit_attempt_count += 1
        elif earned_marks == 0:
            counts.zero_credit_attempt_count += 1
        else:
            counts.partial_credit_attempt_count += 1

    topic_results = tuple(
        _topic_result(subject, topic, counts_by_topic[(subject, topic)])
        for subject, topics in TOPIC_CATALOGUE.items()
        for topic in topics
        if (subject, topic) in counts_by_topic
    )
    graded_attempt_count = sum(
        topic.graded_attempt_count for topic in topic_results
    )
    if graded_attempt_count == 0:
        overall_status: EvidenceStatus = "no_data"
    elif any(topic.evidence_status == "observed" for topic in topic_results):
        overall_status = "observed"
    else:
        overall_status = "insufficient_evidence"

    strongest, weakest = _relative_topics(topic_results)
    return LearningSummaryResult(
        status=overall_status,
        session_window_limit=SESSION_WINDOW_LIMIT,
        included_session_count=len(sessions),
        session_window_truncated=truncated,
        topics=topic_results,
        strongest_topics=strongest,
        weakest_topics=weakest,
    )


def _validated_topic_key(subject: str, topic: str) -> tuple[str, str]:
    try:
        normalized = validate_subject_and_topic(subject, topic)
    except ValueError as error:
        raise LearningSummaryIntegrityError(
            "Adaptive session topic is outside the catalogue."
        ) from error
    if normalized != (subject, topic):
        raise LearningSummaryIntegrityError(
            "Adaptive session topic is not canonical."
        )
    return normalized


def _topic_result(
    subject: str,
    topic: str,
    counts: _TopicCounts,
) -> LearningTopicResult:
    distinct_question_count = len(counts.fingerprints)
    if counts.graded_attempt_count == 0:
        evidence_status: EvidenceStatus = "no_data"
    elif (
        distinct_question_count >= MIN_DISTINCT_QUESTIONS_FOR_OBSERVED
        and len(counts.session_ids) >= MIN_SESSIONS_FOR_OBSERVED
    ):
        evidence_status = "observed"
    else:
        evidence_status = "insufficient_evidence"

    accuracy = (
        round((counts.earned_marks / counts.possible_marks) * 100, 1)
        if counts.possible_marks
        else None
    )
    return LearningTopicResult(
        subject=subject,
        topic=topic,
        evidence_status=evidence_status,
        finished_session_count=len(counts.session_ids),
        presented_question_count=counts.presented_question_count,
        answered_attempt_count=counts.answered_attempt_count,
        graded_attempt_count=counts.graded_attempt_count,
        ungraded_attempt_count=counts.ungraded_attempt_count,
        unanswered_question_count=counts.unanswered_question_count,
        distinct_question_count=distinct_question_count,
        repeat_attempt_count=counts.graded_attempt_count - distinct_question_count,
        earned_marks=counts.earned_marks,
        possible_marks=counts.possible_marks,
        accuracy_on_graded_answers_percent=accuracy,
        full_credit_attempt_count=counts.full_credit_attempt_count,
        partial_credit_attempt_count=counts.partial_credit_attempt_count,
        zero_credit_attempt_count=counts.zero_credit_attempt_count,
    )


def _relative_topics(
    topics: tuple[LearningTopicResult, ...],
) -> tuple[tuple[LearningTopicKeyResult, ...], tuple[LearningTopicKeyResult, ...]]:
    strongest: list[LearningTopicKeyResult] = []
    weakest: list[LearningTopicKeyResult] = []
    for subject in TOPIC_CATALOGUE:
        comparable = [
            topic
            for topic in topics
            if topic.subject == subject and topic.evidence_status == "observed"
        ]
        if len(comparable) < 2:
            continue
        highest_topic = comparable[0]
        lowest_topic = comparable[0]
        for candidate in comparable[1:]:
            if candidate.earned_marks * highest_topic.possible_marks > (
                highest_topic.earned_marks * candidate.possible_marks
            ):
                highest_topic = candidate
            if candidate.earned_marks * lowest_topic.possible_marks < (
                lowest_topic.earned_marks * candidate.possible_marks
            ):
                lowest_topic = candidate
        strongest.extend(
            LearningTopicKeyResult(subject, topic_name)
            for topic_name in (
                topic.topic
                for topic in comparable
                if topic.earned_marks * highest_topic.possible_marks
                == highest_topic.earned_marks * topic.possible_marks
            )
        )
        weakest.extend(
            LearningTopicKeyResult(subject, topic_name)
            for topic_name in (
                topic.topic
                for topic in comparable
                if topic.earned_marks * lowest_topic.possible_marks
                == lowest_topic.earned_marks * topic.possible_marks
            )
        )
    return tuple(strongest), tuple(weakest)
