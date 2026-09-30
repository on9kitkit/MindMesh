"""Deterministic fake verifiers, solvers, assessors, and canonical test fixtures."""

from __future__ import annotations
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Mapping, Sequence
from app.domain.adaptive_quiz import QuestionType
from app.generator.protocol import GeneratedQuestionData, GenerationRequest
from app.generator.validation import validate_generated_quiz_set, validate_single_question
from app.generator.verification.protocol import (
    VERIFICATION_REVISION,
    BlindQuizSolver,
    BlindSolution,
    BlindSolveQuestionInput,
    BlindSolveRequest,
    BlindSolveResult,
    BlindSolveStatus,
    ConsistencyAssessmentRequest,
    ConsistencyAssessmentResult,
    ConsistencyQuestionInput,
    ConsistencyRejectionReason,
    ConsistencyVerdict,
    QuestionConsistencyVerdict,
    QuizConsistencyAssessor,
    QuizContentVerifier,
    VerificationInvalidError,
    VerificationRejectedError,
    VerifiedQuizSet,
    compute_verified_content_digest,
    validate_deterministic_agreement,
)


class FakeBlindQuizSolver(BlindQuizSolver):
    """Deterministic fake blind solver with programmable solutions and error injection."""

    def __init__(
        self,
        canned_solutions: Mapping[int, BlindSolution] | None = None,
        *,
        fail_with: Exception | None = None,
    ) -> None:
        self._canned = dict(canned_solutions) if canned_solutions else {}
        self._fail_with = fail_with
        self.calls: list[BlindSolveRequest] = []

    async def solve_blind(self, request: BlindSolveRequest) -> BlindSolveResult:
        self.calls.append(request)
        if self._fail_with is not None:
            raise self._fail_with

        solutions: list[BlindSolution] = []
        for q in request.questions:
            if q.position in self._canned:
                solutions.append(self._canned[q.position])
            else:
                # Default clean solutions: solve canonical GCSE questions accurately
                if q.question_type == QuestionType.MULTIPLE_CHOICE:
                    # Solve y = 2x^2 - 1 at x = -3: answer is 17
                    opt_17 = next((o.id for o in q.options if o.label.strip() in ("17", "opt_17")), None)
                    chosen_id = opt_17 or (q.options[0].id if q.options else None)
                    solutions.append(
                        BlindSolution(
                            position=q.position,
                            question_type=q.question_type,
                            solve_status=BlindSolveStatus.SOLVED,
                            selected_option_id=chosen_id,
                            numerical_value=None,
                            numerical_unit=None,
                            key_points=(),
                            reasoning="Solved MCQ independently: 2(-3)^2 - 1 = 17.",
                        )
                    )
                elif q.question_type == QuestionType.NUMERICAL:
                    # Solve 100m in 5s: speed is 20 m/s
                    if "100" in q.prompt and "5" in q.prompt:
                        num_val, num_unit = "20", "m/s"
                    else:
                        num_val, num_unit = "10.0", "m/s"
                    solutions.append(
                        BlindSolution(
                            position=q.position,
                            question_type=q.question_type,
                            solve_status=BlindSolveStatus.SOLVED,
                            selected_option_id=None,
                            numerical_value=num_val,
                            numerical_unit=num_unit,
                            key_points=(),
                            reasoning="Solved numerical calculation independently: 100 / 5 = 20 m/s.",
                        )
                    )
                else:
                    solutions.append(
                        BlindSolution(
                            position=q.position,
                            question_type=q.question_type,
                            solve_status=BlindSolveStatus.SOLVED,
                            selected_option_id=None,
                            numerical_value=None,
                            numerical_unit=None,
                            key_points=("meiosis", "fertilisation"),
                            reasoning="Solved written response independently.",
                        )
                    )
        return BlindSolveResult(solutions=tuple(solutions))


class FakeQuizConsistencyAssessor(QuizConsistencyAssessor):
    """Deterministic fake consistency assessor with programmable verdicts and error injection."""

    def __init__(
        self,
        canned_verdicts: Mapping[int, QuestionConsistencyVerdict] | None = None,
        *,
        default_verdict: ConsistencyVerdict = ConsistencyVerdict.PASS,
        default_reason: ConsistencyRejectionReason = ConsistencyRejectionReason.CONSISTENT,
        fail_with: Exception | None = None,
    ) -> None:
        self._canned = dict(canned_verdicts) if canned_verdicts else {}
        self._default_verdict = default_verdict
        self._default_reason = default_reason
        self._fail_with = fail_with
        self.calls: list[ConsistencyAssessmentRequest] = []

    async def assess_consistency(
        self,
        request: ConsistencyAssessmentRequest,
    ) -> ConsistencyAssessmentResult:
        self.calls.append(request)
        if self._fail_with is not None:
            raise self._fail_with

        verdicts: list[QuestionConsistencyVerdict] = []
        for item in request.assessments:
            if item.position in self._canned:
                verdicts.append(self._canned[item.position])
            else:
                verdicts.append(
                    QuestionConsistencyVerdict(
                        position=item.position,
                        question_type=item.candidate_question.question_type,
                        verdict=self._default_verdict,
                        reason=self._default_reason,
                        explanation=f"Default {self._default_verdict.value} assessment for position {item.position}.",
                    )
                )
        return ConsistencyAssessmentResult(verdicts=tuple(verdicts))


class FakeQuizContentVerifier(QuizContentVerifier):
    """Full-pipeline fake verifier orchestrating blind solving, pre-checks, and consistency assessment."""

    def __init__(
        self,
        solver: BlindQuizSolver | None = None,
        assessor: QuizConsistencyAssessor | None = None,
        *,
        revision: str = VERIFICATION_REVISION,
    ) -> None:
        self.solver = solver or FakeBlindQuizSolver()
        self.assessor = assessor or FakeQuizConsistencyAssessor()
        self.revision = revision
        self.calls: list[tuple[GeneratedQuestionData, ...]] = []

    async def verify_quiz_content(
        self,
        questions: tuple[GeneratedQuestionData, ...],
        request: GenerationRequest,
        *,
        before_paid_phase: Callable[[], Awaitable[None]] | None = None,
        deadline_at: datetime | None = None,
    ) -> VerifiedQuizSet:
        self.calls.append(questions)
        if not questions:
            raise VerificationInvalidError("Cannot verify empty question set.")

        if before_paid_phase is not None:
            await before_paid_phase()
        # 1. Blind solve phase (excludes keys, rubrics, explanations)
        blind_inputs = tuple(BlindSolveQuestionInput.from_candidate(q) for q in questions)
        solve_request = BlindSolveRequest(
            education_level=request.education_level,
            quiz_subject=request.quiz_subject,
            quiz_topic=request.quiz_topic,
            questions=blind_inputs,
        )
        solve_result = await self.solver.solve_blind(solve_request)

        # Validate blind solver returned exact positions and count
        if len(solve_result.solutions) != len(questions):
            raise VerificationInvalidError("Blind solve solution count does not match question count.")
        solutions_by_pos = {s.position: s for s in solve_result.solutions}
        if len(solutions_by_pos) != len(solve_result.solutions):
            raise VerificationInvalidError("Blind solve returned duplicate question positions.")

        # 2. Deterministic agreement pre-checks (MCQ key agreement and numerical rubric grading)
        rejections: list[ConsistencyRejectionReason] = []
        rejected_positions: list[int] = []
        for q in questions:
            blind_sol = solutions_by_pos.get(q.position)
            if blind_sol is None:
                raise VerificationInvalidError("Blind solve missing solution for question position.")
            passed, reason, _ = validate_deterministic_agreement(q, blind_sol)
            if not passed:
                rejections.append(reason or ConsistencyRejectionReason.OTHER_REJECT)
                rejected_positions.append(q.position)

        if rejections:
            raise VerificationRejectedError(
                "Deterministic agreement failed for one or more questions.",
                reasons=rejections,
                rejected_positions=rejected_positions,
            )

        # 3. Fresh consistency assessment phase
        assessment_inputs = tuple(
            ConsistencyQuestionInput(
                position=q.position,
                candidate_question=q,
                blind_solution=solutions_by_pos[q.position],
            )
            for q in questions
        )
        assessment_request = ConsistencyAssessmentRequest(
            education_level=request.education_level,
            quiz_subject=request.quiz_subject,
            quiz_topic=request.quiz_topic,
            assessments=assessment_inputs,
        )
        assessment_result = await self.assessor.assess_consistency(assessment_request)

        if len(assessment_result.verdicts) != len(questions):
            raise VerificationInvalidError("Consistency verdict count does not match question count.")
        verdicts_by_pos = {v.position: v for v in assessment_result.verdicts}
        for q in questions:
            v = verdicts_by_pos.get(q.position)
            if v is None:
                raise VerificationInvalidError("Consistency assessment missing verdict for question position.")
            if v.verdict != ConsistencyVerdict.PASS:
                rejections.append(v.reason)
                rejected_positions.append(q.position)

        if rejections:
            raise VerificationRejectedError(
                "Consistency assessment rejected one or more questions.",
                reasons=rejections,
                rejected_positions=rejected_positions,
            )

        sorted_verdicts = tuple(verdicts_by_pos[q.position] for q in sorted(questions, key=lambda x: x.position))
        digest = compute_verified_content_digest(questions, self.revision)
        return VerifiedQuizSet(
            candidate_questions=questions,
            verdicts=sorted_verdicts,
            verification_revision=self.revision,
            verified_content_digest=digest,
        )


# --- Canonical domain test fixtures consuming actual locally validated generated sets ---


def make_motivating_contradiction_mcq(position: int = 0) -> GeneratedQuestionData:
    """Motivating defect from technical plan addendum validated through validate_single_question:

    Prompt: "Evaluate y = 2x^2 - 1 at x = -3."
    Candidate correct_option_id is set to "opt_19", but candidate worked_explanation
    and mathematical reality show 2(-3)^2 - 1 = 2(9) - 1 = 17.
    """
    raw = {
        "question_type": "MULTIPLE_CHOICE",
        "prompt": "Evaluate y = 2x^2 - 1 at x = -3.",
        "max_marks": 1,
        "options": [
            {"id": "opt_11", "label": "11"},
            {"id": "opt_17", "label": "17"},
            {"id": "opt_19", "label": "19"},
            {"id": "opt_35", "label": "35"},
        ],
        "correct_option_id": "opt_19",  # Contradictory key
        "grading_rubric": {
            "criteria": [],
            "expected_value": None,
            "absolute_tolerance": None,
            "allowed_units": [],
            "value_marks": 0,
            "unit_marks": 0,
            "unit_dependency": "REQUIRES_VALUE",
        },
        "worked_explanation": "Substitute x = -3: y = 2(-3)^2 - 1 = 2(9) - 1 = 18 - 1 = 17.",
        "original_extract": None,
    }
    return validate_single_question(raw, position=position)


def make_consistent_mcq(position: int = 0) -> GeneratedQuestionData:
    """Consistent MCQ where correct_option_id correctly identifies option 17."""
    raw = {
        "question_type": "MULTIPLE_CHOICE",
        "prompt": "Evaluate y = 2x^2 - 1 at x = -3.",
        "max_marks": 1,
        "options": [
            {"id": "opt_11", "label": "11"},
            {"id": "opt_17", "label": "17"},
            {"id": "opt_19", "label": "19"},
            {"id": "opt_35", "label": "35"},
        ],
        "correct_option_id": "opt_17",
        "grading_rubric": {
            "criteria": [],
            "expected_value": None,
            "absolute_tolerance": None,
            "allowed_units": [],
            "value_marks": 0,
            "unit_marks": 0,
            "unit_dependency": "REQUIRES_VALUE",
        },
        "worked_explanation": "Substitute x = -3: y = 2(-3)^2 - 1 = 2(9) - 1 = 18 - 1 = 17. Therefore option 17 is correct.",
        "original_extract": None,
    }
    return validate_single_question(raw, position=position)


def make_consistent_numerical(position: int = 1) -> GeneratedQuestionData:
    """Consistent numerical question assessing calculation and units."""
    raw = {
        "question_type": "NUMERICAL",
        "prompt": "A car travels 100 metres in 5 seconds at constant speed. Calculate its speed.",
        "max_marks": 2,
        "options": [],
        "correct_option_id": None,
        "grading_rubric": {
            "criteria": [],
            "expected_value": "20",
            "absolute_tolerance": "0",
            "allowed_units": ["m/s"],
            "value_marks": 1,
            "unit_marks": 1,
            "unit_dependency": "REQUIRES_VALUE",
        },
        "worked_explanation": "Speed = distance / time = 100 m / 5 s = 20 m/s.",
        "original_extract": None,
    }
    return validate_single_question(raw, position=position)


def make_mismatch_numerical(position: int = 1) -> GeneratedQuestionData:
    """Numerical question with calculation mismatch."""
    raw = {
        "question_type": "NUMERICAL",
        "prompt": "A car travels 100 metres in 5 seconds at constant speed. Calculate its speed.",
        "max_marks": 2,
        "options": [],
        "correct_option_id": None,
        "grading_rubric": {
            "criteria": [],
            "expected_value": "25",  # Contradictory value (100 / 5 is 20, not 25)
            "absolute_tolerance": "0",
            "allowed_units": ["m/s"],
            "value_marks": 1,
            "unit_marks": 1,
            "unit_dependency": "REQUIRES_VALUE",
        },
        "worked_explanation": "Speed = distance / time = 100 m / 5 s = 25 m/s.",
        "original_extract": None,
    }
    return validate_single_question(raw, position=position)


def make_consistent_written(position: int = 2) -> GeneratedQuestionData:
    """Consistent written question with complete rubric and clear prompt."""
    raw = {
        "question_type": "WRITTEN",
        "prompt": "Explain why an unfertilised human egg contains only 23 chromosomes.",
        "max_marks": 2,
        "options": [],
        "correct_option_id": None,
        "grading_rubric": {
            "criteria": [
                {
                    "id": "c1",
                    "marks": 1,
                    "marking_point": "Produced by meiosis",
                    "accepted_meaning": "meiosis",
                    "spelling_sensitive": False,
                    "explanation": "State that gametes are formed by meiosis which halves chromosome number.",
                },
                {
                    "id": "c2",
                    "marks": 1,
                    "marking_point": "Restores 46 chromosomes at fertilisation",
                    "accepted_meaning": "fertilisation restores diploid number",
                    "spelling_sensitive": False,
                    "explanation": "State that when sperm fuses with egg, the full 46 chromosomes are restored.",
                },
            ],
            "expected_value": None,
            "absolute_tolerance": None,
            "allowed_units": [],
            "value_marks": 0,
            "unit_marks": 0,
            "unit_dependency": "REQUIRES_VALUE",
        },
        "worked_explanation": "Eggs are formed by meiosis which halves the chromosome count to 23, so fertilisation by a sperm restores the normal diploid count of 46 chromosomes.",
        "original_extract": None,
    }
    return validate_single_question(raw, position=position)


def make_sample_consistent_quiz_set() -> tuple[GeneratedQuestionData, ...]:
    """Return an actual locally validated generated question set with 0-based positions (0, 1, 2) summing to 5 marks."""
    raw_questions = [
        {
            "question_type": "MULTIPLE_CHOICE",
            "prompt": "Evaluate y = 2x^2 - 1 at x = -3.",
            "max_marks": 1,
            "options": [
                {"id": "opt_11", "label": "11"},
                {"id": "opt_17", "label": "17"},
                {"id": "opt_19", "label": "19"},
                {"id": "opt_35", "label": "35"},
            ],
            "correct_option_id": "opt_17",
            "grading_rubric": {
                "criteria": [],
                "expected_value": None,
                "absolute_tolerance": None,
                "allowed_units": [],
                "value_marks": 0,
                "unit_marks": 0,
                "unit_dependency": "REQUIRES_VALUE",
            },
            "worked_explanation": "Substitute x = -3: y = 2(-3)^2 - 1 = 2(9) - 1 = 18 - 1 = 17.",
            "original_extract": None,
        },
        {
            "question_type": "NUMERICAL",
            "prompt": "A car travels 100 metres in 5 seconds at constant speed. Calculate its speed.",
            "max_marks": 2,
            "options": [],
            "correct_option_id": None,
            "grading_rubric": {
                "criteria": [],
                "expected_value": "20",
                "absolute_tolerance": "0",
                "allowed_units": ["m/s"],
                "value_marks": 1,
                "unit_marks": 1,
                "unit_dependency": "REQUIRES_VALUE",
            },
            "worked_explanation": "Speed = distance / time = 100 m / 5 s = 20 m/s.",
            "original_extract": None,
        },
        {
            "question_type": "WRITTEN",
            "prompt": "Explain why an unfertilised human egg contains only 23 chromosomes.",
            "max_marks": 2,
            "options": [],
            "correct_option_id": None,
            "grading_rubric": {
                "criteria": [
                    {
                        "id": "c1",
                        "marks": 1,
                        "marking_point": "Produced by meiosis",
                        "accepted_meaning": "meiosis",
                        "spelling_sensitive": False,
                        "explanation": "State that gametes are formed by meiosis which halves chromosome number.",
                    },
                    {
                        "id": "c2",
                        "marks": 1,
                        "marking_point": "Restores 46 chromosomes at fertilisation",
                        "accepted_meaning": "fertilisation restores diploid number",
                        "spelling_sensitive": False,
                        "explanation": "State that when sperm fuses with egg, the full 46 chromosomes are restored.",
                    },
                ],
                "expected_value": None,
                "absolute_tolerance": None,
                "allowed_units": [],
                "value_marks": 0,
                "unit_marks": 0,
                "unit_dependency": "REQUIRES_VALUE",
            },
            "worked_explanation": "Eggs are formed by meiosis which halves the chromosome count to 23, so fertilisation by a sperm restores the normal diploid count of 46 chromosomes.",
            "original_extract": None,
        },
    ]
    return validate_generated_quiz_set(raw_questions, target_total_marks=5)
