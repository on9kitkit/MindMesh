"""Strict closed response schemas for the viewer-only learning summary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.adaptive_quiz import validate_subject_and_topic
from app.domain.learning_summary import LearningSummaryResult

LearningSubjectCode = Literal[
    "physics",
    "mathematics",
    "biology",
    "chemistry",
    "english_language",
    "english_literature",
]
LearningTopicCode = Literal[
    "energy",
    "electricity",
    "forces",
    "number",
    "algebra",
    "geometry",
    "cells",
    "organisation",
    "ecology",
    "atomic_structure",
    "bonding",
    "chemical_reactions",
    "reading_comprehension",
    "language_analysis",
    "writing_techniques",
    "literary_devices",
    "character_and_theme",
    "poetry_analysis",
]
LearningEvidenceStatus = Literal[
    "no_data",
    "insufficient_evidence",
    "observed",
]


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class LearningTopicKeyResponse(_StrictResponse):
    subject: LearningSubjectCode
    topic: LearningTopicCode

    @model_validator(mode="after")
    def validate_catalogue_pair(self) -> "LearningTopicKeyResponse":
        try:
            validate_subject_and_topic(self.subject, self.topic)
        except ValueError as error:
            raise ValueError("Topic does not belong to the subject catalogue.") from error
        return self


class LearningTopicSummaryResponse(LearningTopicKeyResponse):
    evidence_status: LearningEvidenceStatus
    finished_session_count: int = Field(ge=1, le=100)
    presented_question_count: int = Field(ge=0, le=4_000)
    answered_attempt_count: int = Field(ge=0, le=4_000)
    graded_attempt_count: int = Field(ge=0, le=4_000)
    ungraded_attempt_count: int = Field(ge=0, le=4_000)
    unanswered_question_count: int = Field(ge=0, le=4_000)
    distinct_question_count: int = Field(ge=0, le=4_000)
    repeat_attempt_count: int = Field(ge=0, le=4_000)
    earned_marks: int = Field(ge=0, le=24_000)
    possible_marks: int = Field(ge=0, le=24_000)
    accuracy_on_graded_answers_percent: float | None = Field(
        ge=0.0,
        le=100.0,
    )
    full_credit_attempt_count: int = Field(ge=0, le=4_000)
    partial_credit_attempt_count: int = Field(ge=0, le=4_000)
    zero_credit_attempt_count: int = Field(ge=0, le=4_000)

    @model_validator(mode="after")
    def validate_counts_and_evidence(self) -> "LearningTopicSummaryResponse":
        if self.answered_attempt_count != (
            self.graded_attempt_count + self.ungraded_attempt_count
        ):
            raise ValueError("Answered attempts do not partition by grading state.")
        if self.presented_question_count != (
            self.answered_attempt_count + self.unanswered_question_count
        ):
            raise ValueError("Presented questions do not partition by answer state.")
        if self.presented_question_count > 40 * self.finished_session_count:
            raise ValueError("Presented questions exceed the adaptive session bound.")
        if self.graded_attempt_count != (
            self.full_credit_attempt_count
            + self.partial_credit_attempt_count
            + self.zero_credit_attempt_count
        ):
            raise ValueError("Graded attempts do not partition by credit.")
        if self.repeat_attempt_count != (
            self.graded_attempt_count - self.distinct_question_count
        ):
            raise ValueError("Repeat attempts do not match exact fingerprints.")
        if self.earned_marks > self.possible_marks:
            raise ValueError("Earned marks exceed possible marks.")
        if (self.graded_attempt_count == 0) != (self.possible_marks == 0):
            raise ValueError("Graded attempts and possible marks disagree.")
        if self.possible_marks < self.graded_attempt_count or self.possible_marks > (
            6 * self.graded_attempt_count
        ):
            raise ValueError("Possible marks exceed the adaptive question bounds.")
        accuracy = self.accuracy_on_graded_answers_percent
        if self.possible_marks == 0:
            if accuracy is not None:
                raise ValueError("Accuracy must be absent without graded marks.")
        elif (
            accuracy is None
            or abs((accuracy * 10) - round(accuracy * 10)) > 1e-8
            or abs(
                accuracy - (self.earned_marks / self.possible_marks) * 100
            ) > 0.051
        ):
            raise ValueError("Accuracy must match the graded mark ratio to one decimal.")

        if (self.evidence_status == "no_data") != (self.graded_attempt_count == 0):
            raise ValueError("Topic evidence state disagrees with graded attempts.")
        reaches_floor = (
            self.distinct_question_count >= 5 and self.finished_session_count >= 2
        )
        if (self.evidence_status == "observed") != reaches_floor:
            raise ValueError("Topic evidence state disagrees with its display minimum.")
        return self


class LearningSessionWindowResponse(_StrictResponse):
    limit: Literal[100]
    included: int = Field(ge=0, le=100)
    truncated: bool


def _expected_relative_keys(
    topics: tuple[LearningTopicSummaryResponse, ...],
) -> tuple[tuple[LearningTopicKeyResponse, ...], tuple[LearningTopicKeyResponse, ...]]:
    subjects: tuple[LearningSubjectCode, ...] = (
        "physics",
        "mathematics",
        "biology",
        "chemistry",
        "english_language",
        "english_literature",
    )
    strongest: list[LearningTopicKeyResponse] = []
    weakest: list[LearningTopicKeyResponse] = []
    for subject in subjects:
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
            LearningTopicKeyResponse(subject=topic.subject, topic=topic.topic)
            for topic in comparable
            if topic.earned_marks * highest_topic.possible_marks
            == highest_topic.earned_marks * topic.possible_marks
        )
        weakest.extend(
            LearningTopicKeyResponse(subject=topic.subject, topic=topic.topic)
            for topic in comparable
            if topic.earned_marks * lowest_topic.possible_marks
            == lowest_topic.earned_marks * topic.possible_marks
        )
    return tuple(strongest), tuple(weakest)


class LearningSummaryResponse(_StrictResponse):
    status: LearningEvidenceStatus
    session_window: LearningSessionWindowResponse
    topics: tuple[LearningTopicSummaryResponse, ...]
    strongest_topics: tuple[LearningTopicKeyResponse, ...]
    weakest_topics: tuple[LearningTopicKeyResponse, ...]

    @model_validator(mode="after")
    def validate_response_invariants(self) -> "LearningSummaryResponse":
        if len(self.topics) > 18:
            raise ValueError("Topic count exceeds the catalogue.")
        keys = [(topic.subject, topic.topic) for topic in self.topics]
        if len(set(keys)) != len(keys):
            raise ValueError("Topic rows must be unique.")
        if sum(topic.presented_question_count for topic in self.topics) > 4_000:
            raise ValueError("Presented question count exceeds the query bound.")
        if sum(topic.finished_session_count for topic in self.topics) != (
            self.session_window.included
        ):
            raise ValueError("Topic session counts must match the included window.")

        graded_attempt_count = sum(
            topic.graded_attempt_count for topic in self.topics
        )
        has_observed_topic = any(
            topic.evidence_status == "observed" for topic in self.topics
        )
        if (self.status == "no_data") != (graded_attempt_count == 0):
            raise ValueError("Summary evidence state disagrees with graded attempts.")
        if (self.status == "observed") != has_observed_topic:
            raise ValueError("Summary evidence state disagrees with observed topics.")

        expected_strongest, expected_weakest = _expected_relative_keys(self.topics)
        actual_strongest = tuple(
            (topic.subject, topic.topic) for topic in self.strongest_topics
        )
        actual_weakest = tuple(
            (topic.subject, topic.topic) for topic in self.weakest_topics
        )
        if actual_strongest != tuple(
            (topic.subject, topic.topic) for topic in expected_strongest
        ):
            raise ValueError("Strongest topics do not match within-subject results.")
        if actual_weakest != tuple(
            (topic.subject, topic.topic) for topic in expected_weakest
        ):
            raise ValueError("Weakest topics do not match within-subject results.")
        return self

    @classmethod
    def from_result(cls, result: LearningSummaryResult) -> "LearningSummaryResponse":
        return cls(
            status=result.status,
            session_window=LearningSessionWindowResponse(
                limit=100,
                included=result.included_session_count,
                truncated=result.session_window_truncated,
            ),
            topics=tuple(
                LearningTopicSummaryResponse(
                    subject=topic.subject,
                    topic=topic.topic,
                    evidence_status=topic.evidence_status,
                    finished_session_count=topic.finished_session_count,
                    presented_question_count=topic.presented_question_count,
                    answered_attempt_count=topic.answered_attempt_count,
                    graded_attempt_count=topic.graded_attempt_count,
                    ungraded_attempt_count=topic.ungraded_attempt_count,
                    unanswered_question_count=topic.unanswered_question_count,
                    distinct_question_count=topic.distinct_question_count,
                    repeat_attempt_count=topic.repeat_attempt_count,
                    earned_marks=topic.earned_marks,
                    possible_marks=topic.possible_marks,
                    accuracy_on_graded_answers_percent=(
                        topic.accuracy_on_graded_answers_percent
                    ),
                    full_credit_attempt_count=topic.full_credit_attempt_count,
                    partial_credit_attempt_count=topic.partial_credit_attempt_count,
                    zero_credit_attempt_count=topic.zero_credit_attempt_count,
                )
                for topic in result.topics
            ),
            strongest_topics=tuple(
                LearningTopicKeyResponse(subject=topic.subject, topic=topic.topic)
                for topic in result.strongest_topics
            ),
            weakest_topics=tuple(
                LearningTopicKeyResponse(subject=topic.subject, topic=topic.topic)
                for topic in result.weakest_topics
            ),
        )
