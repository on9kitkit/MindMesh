"""Unit tests for adaptive quiz domain catalogue, rubrics, timing, and grading."""

from decimal import Decimal
import pytest

from app.domain.adaptive_quiz import (
    DEFAULT_MARK_BUDGET,
    MAX_MARK_BUDGET,
    MAX_QUESTION_MARKS,
    MIN_MARK_BUDGET,
    MIN_QUESTION_MARKS,
    TOPIC_CATALOGUE,
    NumericalRubric,
    QuestionType,
    UnitDependency,
    WrittenCriterion,
    WrittenRubric,
    calculate_question_duration_seconds,
    calculate_reveal_duration_seconds,
    compute_content_fingerprint,
    grade_multiple_choice,
    grade_numerical,
    is_supported_numerical_unit,
    normalize_numerical_unit,
    normalize_topic_identifier,
    parse_numerical_answer,
    validate_subject_and_topic,
)


def test_topic_catalogue_contains_exact_eighteen_topics():
    assert len(TOPIC_CATALOGUE) == 6
    total_topics = sum(len(topics) for topics in TOPIC_CATALOGUE.values())
    assert total_topics == 18

    assert TOPIC_CATALOGUE["physics"] == ("energy", "electricity", "forces")
    assert TOPIC_CATALOGUE["mathematics"] == ("number", "algebra", "geometry")
    assert TOPIC_CATALOGUE["biology"] == ("cells", "organisation", "ecology")
    assert TOPIC_CATALOGUE["chemistry"] == (
        "atomic_structure",
        "bonding",
        "chemical_reactions",
    )
    assert TOPIC_CATALOGUE["english_language"] == (
        "reading_comprehension",
        "language_analysis",
        "writing_techniques",
    )
    assert TOPIC_CATALOGUE["english_literature"] == (
        "literary_devices",
        "character_and_theme",
        "poetry_analysis",
    )


def test_topic_identifiers_are_lowercase_snake_case():
    import re

    pattern = re.compile(r"^[a-z]+(?:_[a-z]+)*$")
    for subject, topics in TOPIC_CATALOGUE.items():
        assert pattern.match(subject), f"Subject identifier not snake_case: {subject!r}"
        for topic in topics:
            assert pattern.match(topic), f"Topic identifier not snake_case: {topic!r}"


def test_validate_subject_and_topic_success():
    subject, topic = validate_subject_and_topic("Physics", "Energy")
    assert subject == "physics"
    assert topic == "energy"

    subject, topic = validate_subject_and_topic("  English Literature  ", " POETRY analysis ")
    assert subject == "english_literature"
    assert topic == "poetry_analysis"

    # Hyphen/space variants normalize to the same canonical identifiers.
    assert validate_subject_and_topic("english-language", "reading-comprehension") == (
        "english_language",
        "reading_comprehension",
    )
    assert validate_subject_and_topic("Chemistry", "Atomic Structure") == (
        "chemistry",
        "atomic_structure",
    )


def test_validate_subject_and_topic_rejects_unknown_subject():
    with pytest.raises(ValueError, match="not in the allowed GCSE catalogue"):
        validate_subject_and_topic("History", "World War 1")


def test_validate_subject_and_topic_rejects_topic_mismatch():
    with pytest.raises(ValueError, match="not valid for subject"):
        validate_subject_and_topic("Physics", "number")


def test_calculate_question_duration_seconds():
    # 30s * marks: 1->30s, 6->180s
    assert calculate_question_duration_seconds(1) == 30
    assert calculate_question_duration_seconds(2) == 60
    assert calculate_question_duration_seconds(3) == 90
    assert calculate_question_duration_seconds(4) == 120
    assert calculate_question_duration_seconds(5) == 150
    assert calculate_question_duration_seconds(6) == 180

    with pytest.raises(ValueError):
        calculate_question_duration_seconds(0)
    with pytest.raises(ValueError):
        calculate_question_duration_seconds(7)


def test_calculate_reveal_duration_seconds():
    # 15 + 5 * marks: 1->20s, 6->45s
    assert calculate_reveal_duration_seconds(1) == 20
    assert calculate_reveal_duration_seconds(2) == 25
    assert calculate_reveal_duration_seconds(3) == 30
    assert calculate_reveal_duration_seconds(4) == 35
    assert calculate_reveal_duration_seconds(5) == 40
    assert calculate_reveal_duration_seconds(6) == 45

    with pytest.raises(ValueError):
        calculate_reveal_duration_seconds(0)
    with pytest.raises(ValueError):
        calculate_reveal_duration_seconds(7)


def test_grade_multiple_choice():
    earned, is_correct = grade_multiple_choice("opt_a", "opt_a")
    assert earned == 1
    assert is_correct is True

    earned, is_correct = grade_multiple_choice("opt_b", "opt_a")
    assert earned == 0
    assert is_correct is False


def test_parse_numerical_answer():
    val, unit = parse_numerical_answer("42")
    assert val == Decimal("42")
    assert unit is None

    val, unit = parse_numerical_answer("  -3.1415 m/s^2  ")
    assert val == Decimal("-3.1415")
    assert unit == "m/s^2"

    val, unit = parse_numerical_answer("1.5e3 J")
    assert val == Decimal("1500")
    assert unit == "j"

    val, unit = parse_numerical_answer("invalid")
    assert val is None
    assert unit is None


def test_grade_numerical_exact_and_tolerance():
    rubric = NumericalRubric(
        expected_value=Decimal("9.81"),
        absolute_tolerance=Decimal("0.05"),
        allowed_units=("m/s^2", "m/s2", "n/kg"),
        value_marks=1,
        unit_marks=1,
        unit_dependency=UnitDependency.REQUIRES_VALUE,
    )

    # Exact with valid unit
    earned, correct, fb = grade_numerical("9.81 m/s^2", rubric)
    assert earned == 2
    assert correct is True
    assert fb["value_awarded"] is True
    assert fb["unit_awarded"] is True

    # Within tolerance with valid unit
    earned, correct, fb = grade_numerical("9.84 N/kg", rubric)
    assert earned == 2
    assert correct is True

    # Outside tolerance with valid unit
    earned, correct, fb = grade_numerical("9.90 m/s^2", rubric)
    assert earned == 0
    assert correct is False
    assert fb["value_awarded"] is False
    # unit was valid, but unit_dependency=REQUIRES_VALUE so 0 marks earned
    assert fb["unit_awarded"] is True

    # Correct value, wrong/missing unit
    earned, correct, fb = grade_numerical("9.81 kg", rubric)
    assert earned == 1
    assert correct is False
    assert fb["value_awarded"] is True
    assert fb["unit_awarded"] is False

    # Unparseable answer
    earned, correct, fb = grade_numerical("not a number", rubric)
    assert earned == 0
    assert correct is False


def test_written_rubric_round_trip():
    criterion = WrittenCriterion(
        id="c1",
        marks=2,
        marking_point="States kinetic energy formula",
        accepted_meaning="0.5 * m * v^2",
        spelling_sensitive=False,
        explanation="The formula for kinetic energy is 1/2 m v^2",
    )
    rubric = WrittenRubric(criteria=(criterion,))
    data = rubric.to_dict()
    restored = WrittenRubric.from_dict(data)
    assert restored.total_marks() == 2
    assert restored.criteria[0].id == "c1"
    assert restored.criteria[0].marks == 2


def test_content_fingerprint_normalization():
    fp1 = compute_content_fingerprint(
        prompt="What is energy?",
        question_type=QuestionType.WRITTEN,
        max_marks=2,
    )
    fp2 = compute_content_fingerprint(
        prompt="  WHAT   IS   ENERGY?  ",
        question_type=QuestionType.WRITTEN,
        max_marks=2,
    )
    assert fp1 == fp2

    # Changing max_marks or prompt changes fingerprint
    fp3 = compute_content_fingerprint(
        prompt="What is energy?",
        question_type=QuestionType.WRITTEN,
        max_marks=3,
    )
    assert fp1 != fp3


@pytest.mark.parametrize(
    "unit,supported",
    [
        ("×", True),
        ("x", True),
        ("times", True),
        ("m/s^2", True),
        ("m/s²", True),
        ("N/kg", True),
        ("kg", True),
        ("m", True),
        ("s", True),
        ("deg", True),
        ("ev", True),
        ("%", True),
        ("Ω", True),
        ("ω", True),
        ("µs", True),
        ("e", False),
        ("E", False),
        ("e^2", False),
        ("e/s", False),
        ("N/e", False),
        ("×2", False),
        ("300×2", False),
        ("or", False),
        ("and", False),
        ("2N/4", False),
        ("m/or", False),
        ("N/and²", False),
    ],
)
def test_is_supported_numerical_unit_positives_and_negatives(unit: str, supported: bool) -> None:
    assert is_supported_numerical_unit(unit) is supported


@pytest.mark.parametrize(
    "unit_alias,expected_norm",
    [
        ("×", "×"),
        ("x", "x"),
        ("times", "times"),
        ("m/s^2", "m/s^2"),
        ("m/s²", "m/s²"),
        ("N/kg", "n/kg"),
        ("kg", "kg"),
        ("Ω", "ω"),
        ("ω", "ω"),
        ("µs", "µs"),
    ],
)
def test_numerical_unit_alias_roundtrip(unit_alias: str, expected_norm: str) -> None:
    # Test with space
    val, norm = parse_numerical_answer(f"300 {unit_alias}")
    assert val == Decimal("300")
    assert norm == expected_norm

    # Test without space
    val, norm = parse_numerical_answer(f"300{unit_alias}")
    assert val == Decimal("300")
    assert norm == expected_norm
