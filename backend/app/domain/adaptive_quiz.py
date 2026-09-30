"""Adaptive GCSE quiz domain catalogue, types, rubrics, and validators."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, Overflow as DecimalOverflow, localcontext
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping
from uuid import UUID

MIN_MARK_BUDGET = 5
MAX_MARK_BUDGET = 40
DEFAULT_MARK_BUDGET = 20

MIN_QUESTION_MARKS = 1
MAX_QUESTION_MARKS = 6

LEGACY_DURATION_SECONDS = 20
LEGACY_REVEAL_SECONDS = 3
LEGACY_TOTAL_MARKS = 5

MAX_WRITTEN_ANSWER_LENGTH = 1000

EDUCATION_LEVEL_GCSE = "GCSE"


class QuizMode(str, Enum):
    LEGACY_PHYSICS = "LEGACY_PHYSICS"
    ADAPTIVE = "ADAPTIVE"


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    NUMERICAL = "NUMERICAL"
    WRITTEN = "WRITTEN"


class PreparationStatus(str, Enum):
    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"
    CONSUMED = "CONSUMED"
    SUPERSEDED = "SUPERSEDED"


class GradingMethod(str, Enum):
    LEGACY_OPTION = "LEGACY_OPTION"
    DETERMINISTIC_OPTION = "DETERMINISTIC_OPTION"
    DETERMINISTIC_NUMERICAL = "DETERMINISTIC_NUMERICAL"
    LUNA_RUBRIC = "LUNA_RUBRIC"


class GradingStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    GRADED = "GRADED"
    RETRYABLE = "RETRYABLE"
    UNAVAILABLE = "UNAVAILABLE"


# Explicit 18-topic catalogue across 6 subjects, lowercase snake_case identifiers.
# Subject -> tuple of 3 topics. User-facing labels are a mobile concern.
TOPIC_CATALOGUE: Mapping[str, tuple[str, ...]] = {
    "physics": ("energy", "electricity", "forces"),
    "mathematics": ("number", "algebra", "geometry"),
    "biology": ("cells", "organisation", "ecology"),
    "chemistry": ("atomic_structure", "bonding", "chemical_reactions"),
    "english_language": (
        "reading_comprehension",
        "language_analysis",
        "writing_techniques",
    ),
    "english_literature": (
        "literary_devices",
        "character_and_theme",
        "poetry_analysis",
    ),
}


def normalize_topic_identifier(value: str) -> str:
    """Normalize subject or topic to canonical lowercase snake_case."""
    return re.sub(r"[\s\-]+", "_", value.strip().lower())


def validate_subject_and_topic(subject: str, topic: str) -> tuple[str, str]:
    """Validate subject and topic against the locked catalogue allowlist."""
    norm_subject = normalize_topic_identifier(subject)
    norm_topic = normalize_topic_identifier(topic)

    allowed_topics = TOPIC_CATALOGUE.get(norm_subject)
    if allowed_topics is None:
        raise ValueError(
            f"Subject '{subject}' is not in the allowed GCSE catalogue."
        )
    if norm_topic not in allowed_topics:
        raise ValueError(
            f"Topic '{topic}' is not valid for subject '{subject}'. Allowed topics: {allowed_topics}"
        )
    return norm_subject, norm_topic


def calculate_question_duration_seconds(max_marks: int) -> int:
    """Adaptive questions receive 30s * max_marks (30 to 180 seconds)."""
    if not (MIN_QUESTION_MARKS <= max_marks <= MAX_QUESTION_MARKS):
        raise ValueError(f"max_marks must be between {MIN_QUESTION_MARKS} and {MAX_QUESTION_MARKS}")
    return 30 * max_marks


def calculate_reveal_duration_seconds(max_marks: int) -> int:
    """Adaptive questions receive 15 + 5 * max_marks seconds (20 to 45 seconds)."""
    if not (MIN_QUESTION_MARKS <= max_marks <= MAX_QUESTION_MARKS):
        raise ValueError(f"max_marks must be between {MIN_QUESTION_MARKS} and {MAX_QUESTION_MARKS}")
    return 15 + 5 * max_marks


# --- Rubric Models ---


@dataclass(frozen=True, slots=True)
class MultipleChoiceOption:
    id: str
    label: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MultipleChoiceOption:
        option_id = data["id"]
        label = data["label"]
        if not isinstance(option_id, str) or not isinstance(label, str):
            raise ValueError("MCQ option id and label must be strings.")
        return cls(id=option_id, label=label)


@dataclass(frozen=True, slots=True)
class WrittenCriterion:
    id: str
    marks: int
    marking_point: str
    accepted_meaning: str
    spelling_sensitive: bool
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "marks": self.marks,
            "marking_point": self.marking_point,
            "accepted_meaning": self.accepted_meaning,
            "spelling_sensitive": self.spelling_sensitive,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WrittenCriterion:
        criterion_id = data["id"]
        marks = data["marks"]
        marking_point = data["marking_point"]
        accepted_meaning = data["accepted_meaning"]
        spelling_sensitive = data["spelling_sensitive"]
        explanation = data["explanation"]
        # Strict primitives only: never coerce malformed booleans/objects
        # with str()/bool()/int().
        if not isinstance(criterion_id, str):
            raise ValueError("Written criterion id must be a string.")
        if type(marks) is not int:
            raise ValueError("Written criterion marks must be an integer.")
        for field_name, field_value in (
            ("marking_point", marking_point),
            ("accepted_meaning", accepted_meaning),
            ("explanation", explanation),
        ):
            if not isinstance(field_value, str):
                raise ValueError(f"Written criterion {field_name} must be a string.")
        if type(spelling_sensitive) is not bool:
            raise ValueError("Written criterion spelling_sensitive must be a boolean.")
        return cls(
            id=criterion_id,
            marks=marks,
            marking_point=marking_point,
            accepted_meaning=accepted_meaning,
            spelling_sensitive=spelling_sensitive,
            explanation=explanation,
        )


@dataclass(frozen=True, slots=True)
class WrittenRubric:
    criteria: tuple[WrittenCriterion, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"criteria": [c.to_dict() for c in self.criteria]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WrittenRubric:
        raw_criteria = data.get("criteria", [])
        if not isinstance(raw_criteria, list):
            raise ValueError("Written rubric criteria must be a list.")
        for entry in raw_criteria:
            if not isinstance(entry, dict):
                raise ValueError("Written rubric criteria entries must be objects.")
        return cls(
            criteria=tuple(WrittenCriterion.from_dict(c) for c in raw_criteria)
        )

    def total_marks(self) -> int:
        return sum(c.marks for c in self.criteria)


class UnitDependency(str, Enum):
    INDEPENDENT = "INDEPENDENT"  # Unit mark awarded even if value mark not awarded
    REQUIRES_VALUE = "REQUIRES_VALUE"  # Unit mark only awarded if value mark awarded


UNSAFE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_ALLOWED_UNITS = 8
MAX_UNIT_LENGTH = 32

_NUMERICAL_UNIT_COMPONENT = r"[A-Za-zµΩω°%]+(?:\^[0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?"
_NUMERICAL_UNIT_COMPONENT_RE = re.compile(_NUMERICAL_UNIT_COMPONENT, re.UNICODE)
_NUMERICAL_UNIT_EXPONENT_RE = re.compile(
    r"(?:\^[0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)$",
    re.UNICODE,
)
_NUMERICAL_UNIT_REGEX = re.compile(
    rf"^{_NUMERICAL_UNIT_COMPONENT}(?:\s*(?:[*/]|\s+)\s*{_NUMERICAL_UNIT_COMPONENT})*$",
    re.UNICODE,
)
_NUMERICAL_STANDALONE_UNITS = frozenset({"×"})


def normalize_numerical_unit(value: str) -> str:
    """Normalize a unit alias without rewriting its expression semantics."""
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def is_supported_numerical_unit(value: str) -> bool:
    """Return whether a unit uses the conservative parser-supported syntax."""
    normalized = normalize_numerical_unit(value)
    if not normalized:
        return False
    if normalized in _NUMERICAL_STANDALONE_UNITS:
        return True
    if _NUMERICAL_UNIT_REGEX.fullmatch(normalized) is None:
        return False

    # Connective words are answer alternatives, not units. Inspect each
    # validated component so the rule applies across whitespace, /, and * and
    # also catches optional caret/superscript exponents.
    # Single-letter "e" is an incomplete exponent marker, not a supported unit alias.
    for component_match in _NUMERICAL_UNIT_COMPONENT_RE.finditer(normalized):
        component = _NUMERICAL_UNIT_EXPONENT_RE.sub("", component_match.group(0))
        if component in {"or", "and", "e"}:
            return False
    return True


def _parse_strict_decimal(value: Any, field_name: str) -> Decimal:
    """Parse a decimal from a string/integer payload without float coercion."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"Numerical rubric {field_name} must be a string or integer.")
    text = value if isinstance(value, str) else str(value)
    if not text.strip():
        raise ValueError(f"Numerical rubric {field_name} must be nonblank.")
    try:
        parsed = Decimal(text.strip())
    except InvalidOperation:
        raise ValueError(f"Numerical rubric {field_name} is not a valid decimal.") from None
    _require_bounded_decimal(parsed, field_name)
    return parsed


MAX_DECIMAL_ADJUSTED_EXPONENT = 9999
MAX_DECIMAL_SIGNIFICANT_DIGITS = 50


def _require_bounded_decimal(value: Decimal, field_name: str) -> None:
    """Bound exponent/digits so later arithmetic cannot overflow the context."""
    if not value.is_finite():
        raise ValueError(f"Numerical rubric {field_name} must be finite.")
    if abs(value.adjusted()) > MAX_DECIMAL_ADJUSTED_EXPONENT:
        raise ValueError(f"Numerical rubric {field_name} exponent out of bounds.")
    if len(value.as_tuple().digits) > MAX_DECIMAL_SIGNIFICANT_DIGITS:
        raise ValueError(f"Numerical rubric {field_name} has too many digits.")


@dataclass(frozen=True, slots=True)
class NumericalRubric:
    expected_value: Decimal
    absolute_tolerance: Decimal
    allowed_units: tuple[str, ...]
    value_marks: int
    unit_marks: int
    unit_dependency: UnitDependency = UnitDependency.REQUIRES_VALUE

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_value": str(self.expected_value),
            "absolute_tolerance": str(self.absolute_tolerance),
            "allowed_units": list(self.allowed_units),
            "value_marks": self.value_marks,
            "unit_marks": self.unit_marks,
            "unit_dependency": self.unit_dependency.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NumericalRubric:
        raw_dependency = data.get("unit_dependency")
        if not isinstance(raw_dependency, str):
            raise ValueError("Numerical rubric unit_dependency must be a string.")
        try:
            dependency = UnitDependency(raw_dependency)
        except ValueError:
            # Unknown dependency values are rejected, never silently defaulted.
            raise ValueError(
                f"Unknown numerical rubric unit_dependency: {raw_dependency!r}."
            ) from None

        raw_units = data.get("allowed_units", [])
        if not isinstance(raw_units, list):
            raise ValueError("Numerical rubric allowed_units must be a list.")
        if len(raw_units) > MAX_ALLOWED_UNITS:
            raise ValueError(
                f"Numerical rubric allows at most {MAX_ALLOWED_UNITS} units."
            )
        units: list[str] = []
        for unit in raw_units:
            if not isinstance(unit, str):
                raise ValueError("Numerical rubric units must be strings.")
            clean = normalize_numerical_unit(unit)
            if not clean:
                raise ValueError("Numerical rubric units must be nonblank.")
            if len(clean) > MAX_UNIT_LENGTH:
                raise ValueError(
                    f"Numerical rubric units must be at most {MAX_UNIT_LENGTH} characters."
                )
            if UNSAFE_CONTROL_RE.search(unit):
                raise ValueError("Numerical rubric units must not contain control characters.")
            if clean in units:
                raise ValueError("Numerical rubric units must be unique.")
            units.append(clean)

        expected_value = _parse_strict_decimal(
            data.get("expected_value"), "expected_value"
        )
        absolute_tolerance = _parse_strict_decimal(
            data.get("absolute_tolerance"), "absolute_tolerance"
        )
        if absolute_tolerance < 0:
            raise ValueError("Numerical rubric tolerance must be >= 0.")

        value_marks = data["value_marks"]
        unit_marks = data.get("unit_marks", 0)
        if type(value_marks) is not int or value_marks < 1:
            raise ValueError("Numerical rubric value_marks must be an integer >= 1.")
        if type(unit_marks) is not int or unit_marks < 0:
            raise ValueError("Numerical rubric unit_marks must be an integer >= 0.")
        if unit_marks > 0 and not units:
            raise ValueError(
                "Numerical rubric with unit marks requires nonblank allowed units."
            )
        if unit_marks == 0 and units:
            raise ValueError(
                "Numerical rubric without unit marks must carry no allowed units."
            )

        return cls(
            expected_value=expected_value,
            absolute_tolerance=absolute_tolerance,
            allowed_units=tuple(units),
            value_marks=value_marks,
            unit_marks=unit_marks,
            unit_dependency=dependency,
        )

    def total_marks(self) -> int:
        return self.value_marks + self.unit_marks


def compute_content_fingerprint(
    prompt: str,
    question_type: QuestionType,
    max_marks: int,
    options: tuple[MultipleChoiceOption, ...] | None = None,
    correct_option_id: str | None = None,
    extract: str | None = None,
) -> str:
    """Compute normalized SHA-256 fingerprint for question deduplication."""
    norm_prompt = re.sub(r"\s+", " ", prompt.strip().lower())
    norm_extract = re.sub(r"\s+", " ", (extract or "").strip().lower())
    norm_type = question_type.value
    parts = [norm_type, str(max_marks), norm_prompt, norm_extract]
    if options:
        opt_parts = []
        for o in sorted(options, key=lambda x: x.id):
            norm_id = o.id.strip().lower()
            norm_label = re.sub(r"\s+", " ", o.label.strip().lower())
            opt_parts.append(f"{norm_id}:{norm_label}")
        opt_str = ";".join(opt_parts)
        parts.append(opt_str)
    if correct_option_id:
        parts.append(correct_option_id.strip())

    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# --- Deterministic Grading Helpers ---


def grade_multiple_choice(
    selected_option_id: str,
    correct_option_id: str,
    max_marks: int = 1,
) -> tuple[int, bool]:
    """MCQ is 1 mark: exact match awards full marks, otherwise 0."""
    is_correct = (selected_option_id.strip() == correct_option_id.strip())
    earned_marks = max_marks if is_correct else 0
    return earned_marks, is_correct


_NUMERICAL_REGEX = re.compile(
    r"^\s*(?P<num>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<unit>.*?)\s*$",
    re.UNICODE,
)


def parse_numerical_answer(answer_text: str) -> tuple[Decimal | None, str | None]:
    """Conservatively parse a student's numerical answer into (value, unit)."""
    text = answer_text.strip()
    match = _NUMERICAL_REGEX.match(text)
    if not match:
        return None, None

    num_str = match.group("num")
    unit_str = match.group("unit")
    norm_unit = normalize_numerical_unit(unit_str) if unit_str else None
    # An incomplete exponent must not be reinterpreted as a unit (``2e``,
    # ``2e-``, ``2e+``), and arithmetic/fraction tails such as ``2N/4`` or
    # ``300×2`` must not score the valid numeric prefix. Compound units
    # remain supported (m/s^2, m/s², N/kg) and standalone ``×`` through
    # the conservative lexical grammar below.
    if norm_unit and not is_supported_numerical_unit(norm_unit):
        return None, None

    try:
        val = Decimal(num_str)
    except InvalidOperation:
        return None, None
    try:
        _require_bounded_decimal(val, "answer")
    except ValueError:
        # Huge exponents or digit strings parse but can never be graded
        # safely: treat as unparseable rather than risking Overflow.
        return None, None
    return val, norm_unit


def grade_numerical(
    answer_text: str,
    rubric: NumericalRubric,
) -> tuple[int, bool, dict[str, Any]]:
    """Deterministically grade a numerical answer against its rubric."""
    value, unit = parse_numerical_answer(answer_text)
    if value is None:
        feedback = {
            "value_awarded": False,
            "unit_awarded": False,
            "explanation": "Could not parse a valid number from the answer.",
        }
        return 0, False, feedback

    # Value check: |value - expected| <= tolerance. The arithmetic runs
    # in a bounded local context; InvalidOperation/Overflow degrades to an
    # unparseable zero grade instead of a 500/rollback.
    try:
        with localcontext() as _ctx:
            _ctx.prec = 28
            diff = abs(value - rubric.expected_value)
            value_correct = diff <= rubric.absolute_tolerance
    except (InvalidOperation, DecimalOverflow, ValueError):
        feedback = {
            "value_awarded": False,
            "unit_awarded": False,
            "explanation": "Could not compare the answer value safely.",
        }
        return 0, False, feedback

    # Unit check
    unit_correct = False
    if rubric.unit_marks > 0 and rubric.allowed_units:
        if unit is not None and unit in rubric.allowed_units:
            unit_correct = True
    elif rubric.unit_marks == 0:
        # No unit required
        unit_correct = True

    earned_marks = 0
    if value_correct:
        earned_marks += rubric.value_marks

    if rubric.unit_marks > 0:
        if rubric.unit_dependency == UnitDependency.REQUIRES_VALUE:
            if value_correct and unit_correct:
                earned_marks += rubric.unit_marks
        else:
            if unit_correct:
                earned_marks += rubric.unit_marks

    total_avail = rubric.total_marks()
    is_correct = (earned_marks == total_avail) and (total_avail > 0)
    feedback = {
        "value_awarded": value_correct,
        "unit_awarded": unit_correct,
        "earned_marks": earned_marks,
        "max_marks": total_avail,
    }
    return earned_marks, is_correct, feedback
