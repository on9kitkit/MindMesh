"""Strict public solo schemas; hidden keys and rubrics never enter progress snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.learning_companions.contracts import LockedSelfCheck
from app.learning_companions.solo_domain import (
    PublicSoloQuestion,
    SoloAnswerState,
    SoloAttemptState,
    SoloReview,
)


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SoloOptionResponse(_StrictResponse):
    id: str
    label: str


class PublicSoloQuestionResponse(_StrictResponse):
    id: UUID
    position: int
    question_type: Literal["MULTIPLE_CHOICE", "NUMERICAL", "WRITTEN"]
    max_marks: int
    prompt: str
    options: list[SoloOptionResponse]
    original_extract: str | None

    @classmethod
    def from_domain(cls, value: PublicSoloQuestion) -> PublicSoloQuestionResponse:
        return cls(
            id=value.id, position=value.position, question_type=value.question_type,
            max_marks=value.max_marks, prompt=value.prompt,
            options=[SoloOptionResponse(id=option.id, label=option.label) for option in value.options],
            original_extract=value.original_extract,
        )


class SoloAnswerResponse(_StrictResponse):
    question_id: UUID
    selected_option_id: str | None
    answer_text: str | None
    accepted_at: datetime
    grading_status: str
    mark_provenance: str
    earned_marks: int | None
    feedback: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, value: SoloAnswerState) -> SoloAnswerResponse:
        return cls(
            question_id=value.question_id,
            selected_option_id=value.selected_option_id,
            answer_text=value.answer_text,
            accepted_at=value.accepted_at,
            grading_status=value.grading_status,
            mark_provenance=value.mark_provenance.value,
            earned_marks=value.earned_marks,
            feedback=value.feedback,
        )


class SoloAttemptResponse(_StrictResponse):
    id: UUID
    request_id: UUID
    status: str
    state_version: int
    subject: str
    topic: str
    total_marks: int
    current_question_position: int
    created_at: datetime
    started_at: datetime | None
    terminal_at: datetime | None
    questions: list[PublicSoloQuestionResponse]
    answers: list[SoloAnswerResponse]

    @classmethod
    def from_domain(cls, value: SoloAttemptState) -> SoloAttemptResponse:
        return cls(
            id=value.id, request_id=value.request_id, status=value.status.value,
            state_version=value.state_version, subject=value.subject, topic=value.topic,
            total_marks=value.total_marks,
            current_question_position=value.current_question_position,
            created_at=value.created_at, started_at=value.started_at,
            terminal_at=value.terminal_at,
            questions=[PublicSoloQuestionResponse.from_domain(q) for q in value.questions],
            answers=[SoloAnswerResponse.from_domain(a) for a in value.answers],
        )


class SelfCheckCriterionResponse(_StrictResponse):
    id: str
    marks: int
    marking_point: str
    explanation: str


class LockedSelfCheckResponse(_StrictResponse):
    question_id: UUID
    locked_answer: str
    intended_answer: str
    max_marks: int
    criteria: list[SelfCheckCriterionResponse]

    @classmethod
    def from_domain(cls, value: LockedSelfCheck) -> LockedSelfCheckResponse:
        return cls(
            question_id=value.question_id, locked_answer=value.locked_answer,
            intended_answer=value.intended_answer, max_marks=value.max_marks,
            criteria=[SelfCheckCriterionResponse(
                id=c.id, marks=c.marks, marking_point=c.marking_point,
                explanation=c.explanation,
            ) for c in value.criteria],
        )


class SoloReviewQuestionResponse(_StrictResponse):
    question: PublicSoloQuestionResponse
    answer: SoloAnswerResponse
    correct_option_id: str | None
    intended_answer: str


class SoloReviewResponse(_StrictResponse):
    attempt: SoloAttemptResponse
    questions: list[SoloReviewQuestionResponse]

    @classmethod
    def from_domain(cls, value: SoloReview) -> SoloReviewResponse:
        return cls(
            attempt=SoloAttemptResponse.from_domain(value.attempt),
            questions=[SoloReviewQuestionResponse(
                question=PublicSoloQuestionResponse.from_domain(item.question),
                answer=SoloAnswerResponse.from_domain(item.answer),
                correct_option_id=item.correct_option_id,
                intended_answer=item.intended_answer,
            ) for item in value.questions],
        )


class RetryMarkingResponse(_StrictResponse):
    queued_answers: int
