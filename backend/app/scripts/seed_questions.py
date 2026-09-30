from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.data.physics_sprint import PHYSICS_SPRINT_QUESTIONS
from app.db.models.question import QuestionModel
from app.db.session import Database
from app.domain.constants import PHYSICS_SPRINT_BANK_KEY
from app.domain.question import (
    InvalidQuestionDefinitionError,
    QuestionDefinition,
)

EXPECTED_PHYSICS_QUESTION_COUNT = 5


def validate_physics_sprint_questions(
    definitions: Iterable[QuestionDefinition] = PHYSICS_SPRINT_QUESTIONS,
) -> tuple[QuestionDefinition, ...]:
    """Validate the complete seed set before opening a write transaction."""

    questions = tuple(definitions)
    if len(questions) != EXPECTED_PHYSICS_QUESTION_COUNT:
        raise InvalidQuestionDefinitionError(
            "Physics Sprint must contain exactly five questions"
        )
    if any(question.bank_key != PHYSICS_SPRINT_BANK_KEY for question in questions):
        raise InvalidQuestionDefinitionError(
            "Physics Sprint questions must use the canonical bank key"
        )

    stable_keys = [question.stable_key for question in questions]
    positions = [question.position for question in questions]
    if len(stable_keys) != len(set(stable_keys)):
        raise InvalidQuestionDefinitionError("seed stable keys must be unique")
    if len(positions) != len(set(positions)) or set(positions) != set(range(5)):
        raise InvalidQuestionDefinitionError(
            "seed positions must be the deterministic sequence 0 through 4"
        )

    for question in questions:
        question.validate()
        if len(question.options) != 4:
            raise InvalidQuestionDefinitionError(
                "Physics Sprint questions must contain exactly four options"
            )
    return tuple(sorted(questions, key=lambda question: question.position))


def seed_physics_sprint(
    session_factory: sessionmaker[Session],
    definitions: Iterable[QuestionDefinition] = PHYSICS_SPRINT_QUESTIONS,
) -> int:
    """Insert or update the canonical bank atomically and idempotently."""

    questions = validate_physics_sprint_questions(definitions)

    with session_factory() as session:
        with session.begin():
            existing_models = session.scalars(
                select(QuestionModel)
                .where(QuestionModel.bank_key == PHYSICS_SPRINT_BANK_KEY)
                .with_for_update()
            ).all()
            expected_stable_keys = {question.stable_key for question in questions}
            unexpected = {
                model.stable_key
                for model in existing_models
                if model.stable_key not in expected_stable_keys
            }
            if unexpected:
                raise InvalidQuestionDefinitionError(
                    "Physics Sprint contains non-canonical stable keys"
                )

            existing_by_stable_key = {
                model.stable_key: model for model in existing_models
            }
            # Move existing rows out of the unique position range first so a
            # reordered but otherwise valid bank can be repaired atomically.
            for index, model in enumerate(existing_models):
                model.position = 10000 + index
            session.flush()

            for question in questions:
                model = existing_by_stable_key.get(question.stable_key)
                if model is None:
                    model = QuestionModel(
                        id=uuid5(
                            NAMESPACE_URL,
                            f"studyroom:{question.bank_key}:{question.stable_key}",
                        ),
                        bank_key=question.bank_key,
                        stable_key=question.stable_key,
                    )
                    session.add(model)
                model.position = question.position
                model.prompt = question.prompt
                model.options = [
                    {"id": option.id, "label": option.label}
                    for option in question.options
                ]
                model.correct_option_id = question.correct_option_id
                model.duration_seconds = question.duration_seconds
                model.is_active = question.is_active
                model.updated_at = datetime.now(timezone.utc)
            session.flush()

    return len(questions)


def main() -> None:
    database = Database.from_environment()
    try:
        count = seed_physics_sprint(database.session_factory)
    finally:
        database.dispose()
    print(f"Seeded {count} canonical Physics Sprint questions.")


if __name__ == "__main__":
    main()
