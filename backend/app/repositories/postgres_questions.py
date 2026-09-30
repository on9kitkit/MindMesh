from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.question import QuestionModel
from app.domain.question import Question, QuestionOption


class PostgresQuestionRepository:
    """PostgreSQL read repository for canonical question banks."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_active_by_bank(self, bank_key: str) -> tuple[Question, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(QuestionModel)
                .where(
                    QuestionModel.bank_key == bank_key,
                    QuestionModel.is_active.is_(True),
                )
                .order_by(QuestionModel.position, QuestionModel.id)
            ).all()
            return tuple(_to_domain(model) for model in models)

    def get_by_id(self, question_id: UUID) -> Question | None:
        with self._session_factory() as session:
            model = session.get(QuestionModel, question_id)
            return None if model is None else _to_domain(model)

    def get_by_bank_and_stable_key(
        self,
        bank_key: str,
        stable_key: str,
    ) -> Question | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(QuestionModel).where(
                    QuestionModel.bank_key == bank_key,
                    QuestionModel.stable_key == stable_key,
                )
            )
            return None if model is None else _to_domain(model)


def _to_domain(model: QuestionModel) -> Question:
    return Question(
        id=model.id,
        bank_key=model.bank_key,
        stable_key=model.stable_key,
        position=model.position,
        prompt=model.prompt,
        options=tuple(
            QuestionOption(id=option["id"], label=option["label"])
            for option in model.options
        ),
        correct_option_id=model.correct_option_id,
        duration_seconds=model.duration_seconds,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
