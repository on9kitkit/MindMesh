from dataclasses import replace

import pytest

from app.data.physics_sprint import PHYSICS_SPRINT_QUESTIONS
from app.domain.question import InvalidQuestionDefinitionError, QuestionOption
from app.scripts.seed_questions import validate_physics_sprint_questions


def test_physics_seed_order_is_deterministic() -> None:
    questions = validate_physics_sprint_questions()

    assert [question.position for question in questions] == [0, 1, 2, 3, 4]
    assert [question.stable_key for question in questions] == [
        "physics-1",
        "physics-2",
        "physics-3",
        "physics-4",
        "physics-5",
    ]
    assert all(len(question.options) == 4 for question in questions)


def test_duplicate_option_ids_are_rejected_before_seed() -> None:
    question = PHYSICS_SPRINT_QUESTIONS[0]
    duplicate_options = (
        QuestionOption(id="newton", label="Newton"),
        QuestionOption(id="newton", label="Also Newton"),
        question.options[2],
        question.options[3],
    )

    with pytest.raises(InvalidQuestionDefinitionError, match="unique"):
        validate_physics_sprint_questions(
            (replace(question, options=duplicate_options),)
            + PHYSICS_SPRINT_QUESTIONS[1:]
        )


def test_missing_correct_option_is_rejected_before_seed() -> None:
    question = PHYSICS_SPRINT_QUESTIONS[0]

    with pytest.raises(InvalidQuestionDefinitionError, match="correct_option_id"):
        validate_physics_sprint_questions(
            (replace(question, correct_option_id="missing"),)
            + PHYSICS_SPRINT_QUESTIONS[1:]
        )
