from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from app.domain.quiz import (
    AnswerAcknowledgement,
    AuthoritativeSnapshot,
    LeaderboardEntry,
    ParticipantSnapshot,
    PublicQuestion,
    QuizSession,
    ReadyState,
    RevealedQuestion,
    ViewerSubmission,
)
from app.domain.quiz_review import ReviewQuestionItem, SessionReview
from app.realtime.publisher import session_status_value
from app.schemas.rooms import RoomResponse


class QuestionOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    label: str


class PublicQuestionResponse(BaseModel):
    """Safe question response that has no correct-option field."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: UUID
    prompt: str
    options: list[QuestionOptionResponse]
    question_number: int
    total_questions: int
    closes_at: datetime
    question_type: str = "MULTIPLE_CHOICE"
    max_marks: int = 1
    original_extract: str | None = None

    @classmethod
    def from_domain(cls, question: PublicQuestion) -> "PublicQuestionResponse":
        return cls(
            id=question.id,
            prompt=question.prompt,
            options=[
                QuestionOptionResponse(id=option.id, label=option.label)
                for option in question.options
            ],
            question_number=question.question_number,
            total_questions=question.total_questions,
            closes_at=question.closes_at,
            question_type=question.question_type,
            max_marks=question.max_marks,
            original_extract=question.original_extract,
        )


class RevealedQuestionResponse(PublicQuestionResponse):
    """Question response permitted after reveal begins."""

    correct_option_id: str | None = None
    worked_explanation: str = ""

    @classmethod
    def from_domain(
        cls,
        question: RevealedQuestion,
    ) -> "RevealedQuestionResponse":
        return cls(
            id=question.id,
            prompt=question.prompt,
            options=[
                QuestionOptionResponse(id=option.id, label=option.label)
                for option in question.options
            ],
            question_number=question.question_number,
            total_questions=question.total_questions,
            closes_at=question.closes_at,
            correct_option_id=question.correct_option_id,
            question_type=question.question_type,
            max_marks=question.max_marks,
            worked_explanation=question.worked_explanation,
            original_extract=question.original_extract,
        )


class ParticipantSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    user_id: UUID
    display_name: str
    ready: bool

    @classmethod
    def from_domain(cls, participant: ParticipantSnapshot) -> "ParticipantSnapshotResponse":
        return cls(
            user_id=participant.user_id,
            display_name=participant.display_name,
            ready=participant.ready,
        )


class QuizSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: UUID
    room_id: UUID
    question_bank_key: str
    status: Literal["QUESTION_OPEN", "QUESTION_GRADING", "QUESTION_REVEAL", "FINISHED"]
    current_question_position: int
    state_version: int
    reveal_ends_at: datetime | None
    started_at: datetime
    finished_at: datetime | None
    quiz_mode: str = "LEGACY_PHYSICS"
    total_available_marks: int = 5
    education_level: str | None = None
    quiz_subject: str | None = None
    quiz_topic: str | None = None
    preparation_id: UUID | None = None

    @classmethod
    def from_domain(cls, session: QuizSession) -> "QuizSessionResponse":
        return cls(
            id=session.id,
            room_id=session.room_id,
            question_bank_key=session.question_bank_key,
            status=session_status_value(session.status),
            current_question_position=session.current_question_position,
            state_version=session.state_version,
            reveal_ends_at=session.reveal_ends_at,
            started_at=session.started_at,
            finished_at=session.finished_at,
            quiz_mode=session.quiz_mode,
            total_available_marks=session.total_available_marks,
            education_level=session.education_level,
            quiz_subject=session.quiz_subject,
            quiz_topic=session.quiz_topic,
            preparation_id=session.preparation_id,
        )


class ViewerSubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_question_id: UUID
    selected_option_id: str | None = None
    answer_text: str | None = None
    is_correct: bool | None = None
    points: int | None = None
    earned_marks: int | None = None
    max_marks: int | None = None
    grading_status: str = "GRADED"
    feedback: dict[str, Any] = Field(default_factory=dict)
    awarded_criterion_ids: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, submission: ViewerSubmission) -> "ViewerSubmissionResponse":
        return cls(
            session_question_id=submission.session_question_id,
            selected_option_id=submission.selected_option_id,
            answer_text=submission.answer_text,
            is_correct=submission.is_correct,
            points=submission.points,
            earned_marks=submission.earned_marks,
            max_marks=submission.max_marks,
            grading_status=submission.grading_status,
            feedback=submission.feedback,
            awarded_criterion_ids=list(submission.awarded_criterion_ids),
        )


class LeaderboardEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    user_id: UUID
    display_name_snapshot: str
    total_points: int
    correct_answers: int
    rank: int
    earned_marks: int = 0
    total_available_marks: int = 5


class SessionStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    server_time: datetime
    room: RoomResponse
    viewer_role: Literal["host", "member"]
    participants: list[ParticipantSnapshotResponse]
    viewer_ready: bool
    session: QuizSessionResponse | None
    viewer_participated: bool
    state_version: int
    current_question_number: int | None
    total_question_count: int
    question: PublicQuestionResponse | RevealedQuestionResponse | None
    closes_at: datetime | None
    reveal_ends_at: datetime | None
    viewer_submission: ViewerSubmissionResponse | None
    leaderboard: list[LeaderboardEntryResponse]
    finished_at: datetime | None
    active_preparation_status: str | None = None
    active_preparation_version: int | None = None
    active_preparation_error_category: str | None = None
    grading_retry_needed: bool = False

    @classmethod
    def from_domain(
        cls,
        snapshot: AuthoritativeSnapshot,
    ) -> "SessionStateResponse":
        question: PublicQuestionResponse | RevealedQuestionResponse | None
        if isinstance(snapshot.question, RevealedQuestion):
            question = RevealedQuestionResponse.from_domain(snapshot.question)
        elif isinstance(snapshot.question, PublicQuestion):
            question = PublicQuestionResponse.from_domain(snapshot.question)
        else:
            question = None
        return cls(
            server_time=snapshot.server_time,
            room=RoomResponse.from_domain(
                snapshot.room,
                member_count=len(snapshot.participants),
            ),
            viewer_role=snapshot.viewer_role.value,
            participants=[
                ParticipantSnapshotResponse.from_domain(participant)
                for participant in snapshot.participants
            ],
            viewer_ready=snapshot.viewer_ready,
            session=(
                None
                if snapshot.session is None
                else QuizSessionResponse.from_domain(snapshot.session)
            ),
            viewer_participated=snapshot.viewer_participated,
            state_version=snapshot.state_version,
            current_question_number=snapshot.current_question_number,
            total_question_count=snapshot.total_question_count,
            question=question,
            closes_at=snapshot.closes_at,
            reveal_ends_at=snapshot.reveal_ends_at,
            viewer_submission=(
                None
                if snapshot.viewer_submission is None
                else ViewerSubmissionResponse.from_domain(snapshot.viewer_submission)
            ),
            leaderboard=[
                LeaderboardEntryResponse(
                    user_id=entry.user_id,
                    display_name_snapshot=entry.display_name_snapshot,
                    total_points=entry.total_points,
                    correct_answers=entry.correct_answers,
                    rank=entry.rank,
                    earned_marks=entry.earned_marks,
                    total_available_marks=entry.total_available_marks,
                )
                for entry in snapshot.leaderboard
            ],
            finished_at=snapshot.finished_at,
            active_preparation_status=snapshot.active_preparation_status,
            active_preparation_version=snapshot.active_preparation_version,
            active_preparation_error_category=snapshot.active_preparation_error_category,
            grading_retry_needed=snapshot.grading_retry_needed,
        )


class ReadyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ready: bool


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    room_id: UUID
    user_id: UUID
    ready: bool
    ready_at: datetime | None

    @classmethod
    def from_domain(cls, state: ReadyState) -> "ReadyResponse":
        return cls(
            room_id=state.room_id,
            user_id=state.user_id,
            ready=state.ready,
            ready_at=state.ready_at,
        )


class SubmitAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_question_id: UUID
    selected_option_id: StrictStr | None = Field(default=None, max_length=64)
    type: Literal["choice", "text"] | None = None
    option_id: StrictStr | None = Field(default=None, max_length=64)
    text: StrictStr | None = None

    @model_validator(mode="after")
    def validate_submission_shape(self) -> "SubmitAnswerRequest":
        # Legacy compatibility: a type-less `selected_option_id` is the v1
        # choice shape. Typed choice/text payloads must not carry
        # cross-fields; text is stripped nonblank 1..1000 by validation.
        if self.type is None:
            if self.selected_option_id is None or not self.selected_option_id.strip():
                raise ValueError("Must provide either a choice option or text answer.")
            if self.option_id is not None or self.text is not None:
                raise ValueError("Untyped answers carry only selected_option_id.")
            return self
        if self.selected_option_id is not None:
            raise ValueError("Typed answers must not carry selected_option_id.")
        if self.type == "choice":
            if self.option_id is None or not self.option_id.strip():
                raise ValueError("Choice answers require a nonblank option_id.")
            if self.text is not None:
                raise ValueError("Provide either a choice option or text answer, not both.")
            self.selected_option_id = self.option_id.strip()
        else:
            if self.option_id is not None:
                raise ValueError("Provide either a choice option or text answer, not both.")
            if self.text is None or not self.text.strip():
                raise ValueError("Text answers require nonblank text.")
            if len(self.text.strip()) > 1000:
                raise ValueError("Text answers exceed 1000 characters.")
            self.text = self.text.strip()

        return self


class AnswerAcknowledgementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    submission_id: UUID
    session_id: UUID
    session_question_id: UUID
    selected_option_id: str | None = None
    answer_text: str | None = None
    grading_status: str = "GRADED"

    @classmethod
    def from_domain(
        cls,
        acknowledgement: AnswerAcknowledgement,
    ) -> "AnswerAcknowledgementResponse":
        return cls(
            submission_id=acknowledgement.submission_id,
            session_id=acknowledgement.session_id,
            session_question_id=acknowledgement.session_question_id,
            selected_option_id=acknowledgement.selected_option_id,
            answer_text=acknowledgement.answer_text,
            grading_status=acknowledgement.grading_status,
        )


# --- Durable Private Review Schemas ---


class ReviewQuestionItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_question_id: UUID
    position: int
    question_type: str
    prompt: str
    max_marks: int
    options: list[QuestionOptionResponse]
    correct_option_id: str | None
    worked_explanation: str
    original_extract: str | None
    selected_option_id: str | None
    answer_text: str | None
    earned_marks: int
    feedback: dict[str, Any]
    awarded_criterion_ids: list[str]

    @classmethod
    def from_domain(cls, item: ReviewQuestionItem) -> "ReviewQuestionItemResponse":
        return cls(
            session_question_id=item.session_question_id,
            position=item.position,
            question_type=item.question_type,
            prompt=item.prompt,
            max_marks=item.max_marks,
            options=[
                QuestionOptionResponse(id=opt.id, label=opt.label)
                for opt in item.options
            ],
            correct_option_id=item.correct_option_id,
            worked_explanation=item.worked_explanation,
            original_extract=item.original_extract,
            selected_option_id=item.selected_option_id,
            answer_text=item.answer_text,
            earned_marks=item.earned_marks,
            feedback=item.feedback,
            awarded_criterion_ids=list(item.awarded_criterion_ids),
        )


class SessionReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: UUID
    room_id: UUID
    viewer_user_id: UUID
    total_earned_marks: int
    total_available_marks: int
    questions: list[ReviewQuestionItemResponse]

    @classmethod
    def from_domain(cls, review: SessionReview) -> "SessionReviewResponse":
        return cls(
            session_id=review.session_id,
            room_id=review.room_id,
            viewer_user_id=review.viewer_user_id,
            total_earned_marks=review.total_earned_marks,
            total_available_marks=review.total_available_marks,
            questions=[
                ReviewQuestionItemResponse.from_domain(q)
                for q in review.questions
            ],
        )
