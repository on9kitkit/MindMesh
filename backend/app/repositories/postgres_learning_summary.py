"""On-demand bounded SQL aggregation source for viewer-owned learning data."""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.domain.adaptive_quiz import TOPIC_CATALOGUE
from app.domain.learning_summary import (
    MAX_QUESTION_ROWS,
    SESSION_QUERY_LIMIT,
    SESSION_WINDOW_LIMIT,
    EligibleLearningSession,
    LearningQuestionRecord,
    LearningSummaryResult,
    summarize_learning_data,
)

SessionFactory = Callable[[], Session]


def _learning_summary_statement(viewer_id: UUID):
    catalogue_match = or_(
        *(
            and_(
                QuizSessionModel.quiz_subject == subject,
                QuizSessionModel.quiz_topic.in_(topics),
            )
            for subject, topics in TOPIC_CATALOGUE.items()
        )
    )
    eligible_sessions = (
        select(
            QuizSessionModel.id.label("session_id"),
            QuizSessionModel.quiz_subject.label("subject"),
            QuizSessionModel.quiz_topic.label("topic"),
            QuizSessionModel.finished_at.label("finished_at"),
            SessionParticipantModel.id.label("participant_id"),
        )
        .select_from(QuizSessionModel)
        .join(RoomModel, RoomModel.id == QuizSessionModel.room_id)
        .join(
            SessionParticipantModel,
            and_(
                SessionParticipantModel.session_id == QuizSessionModel.id,
                SessionParticipantModel.user_id == viewer_id,
            ),
        )
        .where(
            RoomModel.quiz_mode == "ADAPTIVE",
            RoomModel.education_level == "GCSE",
            QuizSessionModel.quiz_mode == "ADAPTIVE",
            QuizSessionModel.education_level == "GCSE",
            QuizSessionModel.quiz_subject == RoomModel.quiz_subject,
            QuizSessionModel.quiz_topic == RoomModel.quiz_topic,
            QuizSessionModel.status == "FINISHED",
            QuizSessionModel.finished_at.is_not(None),
            SessionParticipantModel.user_id == viewer_id,
            catalogue_match,
        )
        # Session-participant rows are the viewer's retained-history authority;
        # room closure and later membership departure do not remove them.
        .order_by(QuizSessionModel.finished_at.desc(), QuizSessionModel.id.desc())
        .limit(SESSION_QUERY_LIMIT)
        .cte("eligible_learning_sessions")
    )
    ranked_sessions = (
        select(
            eligible_sessions.c.session_id,
            eligible_sessions.c.subject,
            eligible_sessions.c.topic,
            eligible_sessions.c.finished_at,
            eligible_sessions.c.participant_id,
            func.row_number()
            .over(
                order_by=(
                    eligible_sessions.c.finished_at.desc(),
                    eligible_sessions.c.session_id.desc(),
                )
            )
            .label("session_rank"),
        )
        .cte("ranked_learning_sessions")
    )
    question_join = and_(
        SessionQuestionModel.session_id == ranked_sessions.c.session_id,
        ranked_sessions.c.session_rank <= SESSION_WINDOW_LIMIT,
    )
    submission_join = and_(
        AnswerSubmissionModel.session_id == ranked_sessions.c.session_id,
        AnswerSubmissionModel.session_question_id == SessionQuestionModel.id,
        AnswerSubmissionModel.participant_id == ranked_sessions.c.participant_id,
    )

    # Each verified adaptive session is at most 40 marks and each question is
    # at least one mark, so the selected 100 sessions expose at most 4,000
    # question rows. The 101st session is included only as a null-question
    # sentinel for the truncation flag.
    return (
        select(
            ranked_sessions.c.session_rank,
            ranked_sessions.c.session_id,
            ranked_sessions.c.subject,
            ranked_sessions.c.topic,
            SessionQuestionModel.id.label("question_id"),
            SessionQuestionModel.max_marks,
            SessionQuestionModel.content_fingerprint,
            AnswerSubmissionModel.id.label("submission_id"),
            AnswerSubmissionModel.grading_status,
            AnswerSubmissionModel.earned_marks,
        )
        .select_from(
            ranked_sessions.outerjoin(SessionQuestionModel, question_join).outerjoin(
                AnswerSubmissionModel,
                submission_join,
            )
        )
        .where(ranked_sessions.c.session_rank <= SESSION_QUERY_LIMIT)
        .order_by(ranked_sessions.c.session_rank, SessionQuestionModel.position)
    )


class PostgresLearningSummaryRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def get_learning_summary(self, viewer_id: UUID) -> LearningSummaryResult:
        eligible_sessions: list[EligibleLearningSession] = []
        questions: list[LearningQuestionRecord] = []
        truncated = False
        session_ids: set[UUID] = set()

        with self._session_factory() as session:
            rows = session.execute(
                _learning_summary_statement(viewer_id)
            ).mappings()
            for row in rows:
                rank = row["session_rank"]
                session_id = row["session_id"]
                if rank == SESSION_QUERY_LIMIT:
                    truncated = True
                    continue
                if rank < 1 or rank > SESSION_WINDOW_LIMIT:
                    raise RuntimeError("Learning summary query rank is invalid.")
                if session_id not in session_ids:
                    session_ids.add(session_id)
                    eligible_sessions.append(
                        EligibleLearningSession(
                            session_id=session_id,
                            subject=row["subject"],
                            topic=row["topic"],
                        )
                    )
                question_id = row["question_id"]
                if question_id is None:
                    continue
                questions.append(
                    LearningQuestionRecord(
                        session_id=session_id,
                        max_marks=row["max_marks"],
                        content_fingerprint=row["content_fingerprint"],
                        has_submission=row["submission_id"] is not None,
                        grading_status=row["grading_status"],
                        earned_marks=row["earned_marks"],
                    )
                )

        if len(questions) > MAX_QUESTION_ROWS:
            raise RuntimeError("Learning summary query exceeded its row bound.")
        return summarize_learning_data(
            tuple(eligible_sessions),
            tuple(questions),
            truncated=truncated,
        )
