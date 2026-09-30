"""Verifier protocol, types, exceptions, and digest validation for the content-verification gate."""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence

from app.domain.adaptive_quiz import (
    MAX_DECIMAL_ADJUSTED_EXPONENT,
    MAX_DECIMAL_SIGNIFICANT_DIGITS,
    MAX_MARK_BUDGET,
    MultipleChoiceOption,
    NumericalRubric,
    QuestionType,
    grade_numerical,
    is_supported_numerical_unit,
    normalize_numerical_unit,
)
from app.generator.protocol import (
    GeneratedQuestionData,
    GenerationRequest,
    MODEL_ID_GPT_6_LUNA as GENERATION_MODEL_ID_GPT_6_LUNA,
)

VERIFICATION_REVISION: str = "2026-09-08.1"
BLIND_SOLVE_TIMEOUT_SECONDS: int = 30
CONSISTENCY_ASSESSMENT_TIMEOUT_SECONDS: int = 30
TOTAL_PIPELINE_DEADLINE_SECONDS: int = 165
MAX_VERIFICATION_CALLS: int = 4
MODEL_ID_GPT_6_LUNA: str = GENERATION_MODEL_ID_GPT_6_LUNA
# Preserve the old exported symbol as a compatibility alias; active adapters
# and new callers use MODEL_ID_GPT_6_LUNA.
MODEL_ID_GPT_5_6_LUNA: str = MODEL_ID_GPT_6_LUNA


class VerificationError(Exception):
    """Base exception for all verification gate failures."""

    category: str = "verification_failed"


class VerificationRejectedError(VerificationError):
    """Raised when one or more questions fail deterministic agreement or consistency checks.

    Carries safe, closed reason enums and question positions only; never logs or interpolates
    raw answer text, candidate prompts, keys, rubrics, or provider reasoning.
    """

    category: str = "verification_rejected"

    def __init__(
        self,
        message: str = "Verification rejected one or more questions.",
        *,
        reasons: Sequence[ConsistencyRejectionReason] = (),
        rejected_positions: Sequence[int] = (),
    ) -> None:
        super().__init__(message)
        self.reasons: tuple[ConsistencyRejectionReason, ...] = tuple(reasons)
        self.rejected_positions: tuple[int, ...] = tuple(
            p for p in rejected_positions if type(p) is int
        )


class VerificationInvalidError(VerificationError):
    """Raised when verifier outputs are malformed, incomplete, or structurally invalid."""

    category: str = "verification_invalid"


class VerificationTimeoutError(VerificationError):
    """Raised when any verification provider call or elapsed pipeline exceeds its deadline."""

    category: str = "verification_timeout"


class VerificationUnavailableError(VerificationError):
    """Raised when the AI verification provider is unconfigured, refused, or unavailable."""

    category: str = "verification_unavailable"


class BlindSolveStatus(str, Enum):
    """Closed status choices for independent blind question solving."""

    SOLVED = "SOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNANSWERABLE = "UNANSWERABLE"


class ConsistencyVerdict(str, Enum):
    """Closed decision choices for consistency assessment."""

    PASS = "PASS"
    REJECT = "REJECT"


class ConsistencyRejectionReason(str, Enum):
    """Closed reason taxonomy for question consistency rejection or acceptance."""

    CONSISTENT = "CONSISTENT"
    KEY_MISMATCH = "KEY_MISMATCH"
    NUMERICAL_VALUE_MISMATCH = "NUMERICAL_VALUE_MISMATCH"
    NUMERICAL_UNIT_MISMATCH = "NUMERICAL_UNIT_MISMATCH"
    RUBRIC_MISMATCH = "RUBRIC_MISMATCH"
    EXPLANATION_CONTRADICTION = "EXPLANATION_CONTRADICTION"
    AMBIGUOUS_QUESTION = "AMBIGUOUS_QUESTION"
    UNANSWERABLE = "UNANSWERABLE"
    FAIRNESS_VIOLATION = "FAIRNESS_VIOLATION"
    TOLERANCE_UNJUSTIFIED = "TOLERANCE_UNJUSTIFIED"
    FACT_MISMATCH = "FACT_MISMATCH"
    OTHER_REJECT = "OTHER_REJECT"


@dataclass(frozen=True, slots=True)
class BlindSolveQuestionInput:
    """Question content supplied to the blind solver, strictly omitting alleged keys and rubrics."""

    position: int
    question_type: QuestionType
    prompt: str
    max_marks: int
    options: tuple[MultipleChoiceOption, ...]
    original_extract: str | None

    @classmethod
    def from_candidate(cls, candidate: GeneratedQuestionData) -> BlindSolveQuestionInput:
        """Create a key-blind input from candidate question data."""
        return cls(
            position=candidate.position,
            question_type=candidate.question_type,
            prompt=candidate.prompt,
            max_marks=candidate.max_marks,
            options=candidate.options if candidate.question_type == QuestionType.MULTIPLE_CHOICE else (),
            original_extract=candidate.original_extract,
        )


@dataclass(frozen=True, slots=True)
class BlindSolveRequest:
    """Request envelope passed to the blind solver."""

    education_level: str
    quiz_subject: str
    quiz_topic: str
    questions: tuple[BlindSolveQuestionInput, ...]


@dataclass(frozen=True, slots=True)
class BlindSolution:
    """Independent answer and working generated without knowledge of candidate keys or rubrics.

    The reasoning field holds a brief answer justification, not a request for hidden chain-of-thought.
    """

    position: int
    question_type: QuestionType
    solve_status: BlindSolveStatus
    selected_option_id: str | None
    numerical_value: str | None
    numerical_unit: str | None
    key_points: tuple[str, ...]
    reasoning: str


@dataclass(frozen=True, slots=True)
class BlindSolveResult:
    """Envelope of blind solutions for all questions in a candidate quiz set."""

    solutions: tuple[BlindSolution, ...]


@dataclass(frozen=True, slots=True)
class ConsistencyQuestionInput:
    """Comparison unit provided to the consistency assessor."""

    position: int
    candidate_question: GeneratedQuestionData
    blind_solution: BlindSolution


@dataclass(frozen=True, slots=True)
class ConsistencyAssessmentRequest:
    """Request envelope passed to the consistency assessor."""

    education_level: str
    quiz_subject: str
    quiz_topic: str
    assessments: tuple[ConsistencyQuestionInput, ...]


@dataclass(frozen=True, slots=True)
class QuestionConsistencyVerdict:
    """Per-question verdict from consistency assessment."""

    position: int
    question_type: QuestionType
    verdict: ConsistencyVerdict
    reason: ConsistencyRejectionReason
    explanation: str


@dataclass(frozen=True, slots=True)
class ConsistencyAssessmentResult:
    """Envelope of consistency verdicts for all questions in a candidate quiz set."""

    verdicts: tuple[QuestionConsistencyVerdict, ...]


def validate_deterministic_agreement(
    candidate: GeneratedQuestionData,
    blind: BlindSolution,
) -> tuple[bool, ConsistencyRejectionReason | None, str]:
    """Validate deterministic agreement for MCQ and NUMERICAL before consistency assessment.

    - Enforces exact integer positions (zero-based) and exact QuestionType enums.
    - Requires exact BlindSolveStatus.SOLVED; any other status fails pre-check.
    - For MULTIPLE_CHOICE: validates selected option exists in candidate options and matches candidate key.
      Rejects any numerical cross-fields.
    - For NUMERICAL: parses bounded finite Decimal separately from unit, validates unit string, canonicalizes
      to safe numeric string, and invokes existing unchanged grade_numerical to enforce is_correct and full marks.
      Rejects choice cross-fields.
    - For WRITTEN: validates absence of choice or numerical cross-fields; passes to consistency assessment.
    - Returns fixed safe descriptions without interpolating raw answers, keys, rubrics, or formulas.
    """
    if type(candidate.position) is not int or type(blind.position) is not int:
        return (False, ConsistencyRejectionReason.OTHER_REJECT, "Question position must be an integer.")
    if candidate.position != blind.position:
        return (False, ConsistencyRejectionReason.OTHER_REJECT, "Position mismatch.")

    if type(candidate.question_type) is not QuestionType or type(blind.question_type) is not QuestionType:
        return (False, ConsistencyRejectionReason.OTHER_REJECT, "Invalid question type.")
    if candidate.question_type != blind.question_type:
        return (False, ConsistencyRejectionReason.OTHER_REJECT, "Question type mismatch.")

    if type(blind.solve_status) is not BlindSolveStatus:
        return (False, ConsistencyRejectionReason.OTHER_REJECT, "Invalid solve status type.")
    if blind.solve_status == BlindSolveStatus.AMBIGUOUS:
        return (False, ConsistencyRejectionReason.AMBIGUOUS_QUESTION, "Question is ambiguous.")
    if blind.solve_status == BlindSolveStatus.UNANSWERABLE:
        return (False, ConsistencyRejectionReason.UNANSWERABLE, "Question is unanswerable.")
    if blind.solve_status != BlindSolveStatus.SOLVED:
        return (False, ConsistencyRejectionReason.OTHER_REJECT, "Blind solver did not solve question.")

    if candidate.question_type == QuestionType.MULTIPLE_CHOICE:
        # Cross-field rejection: numerical fields must not be present
        if blind.numerical_value is not None or blind.numerical_unit is not None:
            return (False, ConsistencyRejectionReason.OTHER_REJECT, "Cross-field violation.")
        if not blind.selected_option_id or type(blind.selected_option_id) is not str:
            return (False, ConsistencyRejectionReason.KEY_MISMATCH, "MCQ missing selected option.")
        # Option membership check: selected option must exist in candidate options
        candidate_option_ids = {opt.id for opt in candidate.options}
        if blind.selected_option_id not in candidate_option_ids:
            return (False, ConsistencyRejectionReason.KEY_MISMATCH, "Selected option not in candidate options.")
        if blind.selected_option_id != candidate.correct_option_id:
            return (False, ConsistencyRejectionReason.KEY_MISMATCH, "MCQ key mismatch.")
        return (True, None, "MCQ deterministic key agreement verified.")

    if candidate.question_type == QuestionType.NUMERICAL:
        # Cross-field rejection: option field must not be present
        if blind.selected_option_id is not None:
            return (False, ConsistencyRejectionReason.OTHER_REJECT, "Cross-field violation.")
        if blind.numerical_value is None or type(blind.numerical_value) is not str or not blind.numerical_value.strip():
            return (False, ConsistencyRejectionReason.NUMERICAL_VALUE_MISMATCH, "Numerical solution missing value.")

        # Typed bounded Decimal evaluation separate from unit
        val_str = blind.numerical_value.strip()
        try:
            val = Decimal(val_str)
        except (InvalidOperation, TypeError, ValueError):
            return (False, ConsistencyRejectionReason.NUMERICAL_VALUE_MISMATCH, "Numerical value is not a valid decimal.")

        if not val.is_finite():
            return (False, ConsistencyRejectionReason.NUMERICAL_VALUE_MISMATCH, "Numerical value is not finite.")
        if abs(val.adjusted()) > MAX_DECIMAL_ADJUSTED_EXPONENT or len(val.as_tuple().digits) > MAX_DECIMAL_SIGNIFICANT_DIGITS:
            return (False, ConsistencyRejectionReason.NUMERICAL_VALUE_MISMATCH, "Numerical value exponent or digits out of bounds.")

        # Validate unit string type and grammar before grading
        if blind.numerical_unit is not None:
            if type(blind.numerical_unit) is not str:
                return (False, ConsistencyRejectionReason.NUMERICAL_UNIT_MISMATCH, "Numerical unit must be a string or null.")
            clean_unit = blind.numerical_unit.strip()
            if clean_unit and not is_supported_numerical_unit(clean_unit):
                return (False, ConsistencyRejectionReason.NUMERICAL_UNIT_MISMATCH, "Numerical unit is unsupported.")
            unit_suffix = f" {clean_unit}" if clean_unit else ""
        else:
            unit_suffix = ""

        try:
            rubric = NumericalRubric.from_dict(candidate.grading_rubric)
        except Exception:
            return (False, ConsistencyRejectionReason.RUBRIC_MISMATCH, "Candidate numerical rubric is malformed.")

        # Canonicalize Decimal to safe numeric string and grade using unchanged grade_numerical
        canonical_num_str = format(val, "f") if abs(val.adjusted()) < 20 else str(val)
        answer_repr = f"{canonical_num_str}{unit_suffix}".strip()
        earned, is_correct, feedback = grade_numerical(answer_repr, rubric)
        if not is_correct or earned != candidate.max_marks:
            if not feedback.get("value_awarded", False):
                return (False, ConsistencyRejectionReason.NUMERICAL_VALUE_MISMATCH, "Numerical value mismatch.")
            return (False, ConsistencyRejectionReason.NUMERICAL_UNIT_MISMATCH, "Numerical unit mismatch.")

        return (True, None, "Numerical deterministic agreement passed.")

    if candidate.question_type == QuestionType.WRITTEN:
        # Cross-field rejection
        if blind.selected_option_id is not None or blind.numerical_value is not None or blind.numerical_unit is not None:
            return (False, ConsistencyRejectionReason.OTHER_REJECT, "Cross-field violation.")
        return (True, None, "Written pre-check passed.")

    return (False, ConsistencyRejectionReason.OTHER_REJECT, "Unknown question type.")


def compute_verified_content_digest(
    questions: Sequence[GeneratedQuestionData],
    revision: str = VERIFICATION_REVISION,
) -> str:
    """Compute a canonical SHA-256 digest over all scoring-relevant content.

    Uses canonical UTF-8 JSON serialization with sorted keys and no whitespace
    separators, preserving exact prompt, extract, explanation, option IDs/labels/order,
    key, rubric, marks, and duration without lossy stripping or ambiguous delimiters.
    Rejects duplicate positions and non-integer positions.
    """
    positions = [q.position for q in questions]
    if any(type(p) is not int for p in positions):
        raise ValueError("Question positions must be integers.")
    if len(positions) != len(set(positions)):
        raise ValueError("Duplicate question positions in content digest computation.")

    payload = {
        "revision": revision,
        "questions": [
            {
                "position": q.position,
                "question_type": q.question_type.value if isinstance(q.question_type, QuestionType) else str(q.question_type),
                "prompt": q.prompt,
                "max_marks": q.max_marks,
                "duration_seconds": q.duration_seconds,
                "options": [
                    {"id": o.id, "label": o.label}
                    for o in q.options
                ],
                "correct_option_id": q.correct_option_id,
                "grading_rubric": q.grading_rubric,
                "worked_explanation": q.worked_explanation,
                "original_extract": q.original_extract,
            }
            for q in sorted(questions, key=lambda x: x.position)
        ],
    }
    canonical_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def _serialize_candidate_questions_canonical_json(questions: Sequence[GeneratedQuestionData]) -> bytes:
    """Serialize candidate questions into immutable canonical UTF-8 JSON bytes."""
    payload = [
        {
            "position": q.position,
            "question_type": q.question_type.value,
            "prompt": q.prompt,
            "max_marks": q.max_marks,
            "duration_seconds": q.duration_seconds,
            "options": [{"id": o.id, "label": o.label} for o in q.options],
            "correct_option_id": q.correct_option_id,
            "grading_rubric": q.grading_rubric,
            "worked_explanation": q.worked_explanation,
            "original_extract": q.original_extract,
            "content_fingerprint": q.content_fingerprint,
        }
        for q in sorted(questions, key=lambda x: x.position)
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _deserialize_candidate_questions_canonical_json(data: bytes) -> tuple[GeneratedQuestionData, ...]:
    """Deserialize fresh GeneratedQuestionData instances from immutable canonical UTF-8 JSON bytes."""
    raw_list = json.loads(data.decode("utf-8"))
    questions: list[GeneratedQuestionData] = []
    for item in raw_list:
        options = tuple(
            MultipleChoiceOption(id=opt["id"], label=opt["label"])
            for opt in item["options"]
        )
        questions.append(
            GeneratedQuestionData(
                position=item["position"],
                question_type=QuestionType(item["question_type"]),
                prompt=item["prompt"],
                max_marks=item["max_marks"],
                duration_seconds=item["duration_seconds"],
                options=options,
                correct_option_id=item["correct_option_id"],
                grading_rubric=copy.deepcopy(item["grading_rubric"]),
                worked_explanation=item["worked_explanation"],
                original_extract=item["original_extract"],
                content_fingerprint=item["content_fingerprint"],
            )
        )
    return tuple(questions)


@dataclass(frozen=True, slots=True)
class VerifiedQuizSet:
    """Immutable verified quiz set stored as canonical serialized bytes.

    Frozen dataclass storing ONLY canonical serialized candidate bytes privately,
    deserializing defensively on access. Attributes cannot be reassigned (FrozenInstanceError),
    and mutating the returned candidate questions or their rubrics does not affect internal state.
    """

    _canonical_candidate_bytes: bytes
    _verdicts: tuple[QuestionConsistencyVerdict, ...]
    _verification_revision: str
    _verified_content_digest: str

    def __init__(
        self,
        candidate_questions: Sequence[GeneratedQuestionData],
        verdicts: Sequence[QuestionConsistencyVerdict],
        verification_revision: str,
        verified_content_digest: str,
    ) -> None:
        if verification_revision != VERIFICATION_REVISION:
            raise ValueError("VerifiedQuizSet requires current verification revision.")

        q_list = list(candidate_questions)
        v_list = list(verdicts)

        if not (1 <= len(q_list) <= MAX_MARK_BUDGET):
            raise ValueError("Candidate question count out of bounds.")
        if len(q_list) != len(v_list):
            raise ValueError("Candidate question and verdict counts do not match.")

        # Nonempty 0..N-1 contiguous integer positions
        for idx, (q, v) in enumerate(zip(q_list, v_list, strict=True)):
            if type(q.position) is not int or type(v.position) is not int:
                raise ValueError("Question and verdict positions must be integers.")
            if q.position != idx or v.position != idx:
                raise ValueError("Candidate questions and verdicts must have contiguous zero-based positions.")
            if type(q.question_type) is not QuestionType or type(v.question_type) is not QuestionType:
                raise ValueError("Invalid question type.")
            if q.question_type != v.question_type:
                raise ValueError("Question and verdict type mismatch.")
            if type(v.verdict) is not ConsistencyVerdict or v.verdict != ConsistencyVerdict.PASS:
                raise ValueError("Consistency verdict must be PASS.")
            if type(v.reason) is not ConsistencyRejectionReason or v.reason != ConsistencyRejectionReason.CONSISTENT:
                raise ValueError("Consistency reason must be CONSISTENT.")

        # Serialize candidate questions into canonical immutable bytes
        canonical_bytes = _serialize_candidate_questions_canonical_json(q_list)
        computed_digest = compute_verified_content_digest(q_list, verification_revision)
        if verified_content_digest != computed_digest:
            raise ValueError("Content digest mismatch.")

        # Initialize frozen dataclass slots via object.__setattr__
        object.__setattr__(self, "_canonical_candidate_bytes", canonical_bytes)
        object.__setattr__(self, "_verdicts", tuple(v_list))
        object.__setattr__(self, "_verification_revision", verification_revision)
        object.__setattr__(self, "_verified_content_digest", verified_content_digest)

    @property
    def candidate_questions(self) -> tuple[GeneratedQuestionData, ...]:
        """Return fresh deserialized candidate questions from immutable canonical bytes."""
        return _deserialize_candidate_questions_canonical_json(self._canonical_candidate_bytes)

    @property
    def verdicts(self) -> tuple[QuestionConsistencyVerdict, ...]:
        return self._verdicts

    @property
    def verification_revision(self) -> str:
        return self._verification_revision

    @property
    def verified_content_digest(self) -> str:
        return self._verified_content_digest

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VerifiedQuizSet):
            return False
        return (
            self._verification_revision == other._verification_revision
            and self._verified_content_digest == other._verified_content_digest
            and len(self._verdicts) == len(other._verdicts)
        )

    def __repr__(self) -> str:
        return f"VerifiedQuizSet(revision=CURRENT, verified=True, count={len(self._verdicts)})"


class BlindQuizSolver(Protocol):
    """Protocol for independent blind question solving."""

    async def solve_blind(self, request: BlindSolveRequest) -> BlindSolveResult:
        """Solve candidate questions without access to alleged keys, rubrics, or explanations."""
        ...


class QuizConsistencyAssessor(Protocol):
    """Protocol for consistency assessment between candidate questions and blind solutions."""

    async def assess_consistency(
        self,
        request: ConsistencyAssessmentRequest,
    ) -> ConsistencyAssessmentResult:
        """Assess consistency, rubric validity, and fairness for each candidate question."""
        ...


class QuizContentVerifier(Protocol):
    """Composite protocol orchestrating key-blind solving, deterministic checks, and consistency assessment."""

    async def verify_quiz_content(
        self,
        questions: tuple[GeneratedQuestionData, ...],
        request: GenerationRequest,
        *,
        before_paid_phase: Callable[[], Awaitable[None]] | None = None,
        deadline_at: datetime | None = None,
    ) -> VerifiedQuizSet:
        """Verify candidate questions against independent solving and consistency assessment."""
        ...
