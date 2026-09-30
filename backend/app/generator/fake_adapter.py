"""Deterministic fake quiz content generator for testing."""

from __future__ import annotations

from typing import Sequence

from app.domain.adaptive_quiz import (
    MultipleChoiceOption,
    QuestionType,
    UnitDependency,
    calculate_question_duration_seconds,
    compute_content_fingerprint,
)
from app.generator.protocol import (
    GeneratedQuestionData,
    GenerationRequest,
    GeneratorAuthError,
    GeneratorMalformedError,
    GeneratorRateLimitedError,
    GeneratorRefusalError,
    GeneratorTimeoutError,
    GeneratorUnavailableError,
    GeneratorValidationError,
    QuizContentGenerator,
)
from app.generator.validation import validate_generated_quiz_set


_PROMPT_VARIANTS = (
    ("Analyze fundamental properties of", "Calculate resulting magnitude of", "Identify correct principle for"),
    ("Describe practical industrial methods in", "Determine quantitative parameter of", "Select established fact regarding"),
    ("Summarize theoretical observations of", "Compute numerical output for", "Choose verified relationship in"),
    ("Examine experimental evidence surrounding", "Derive standard value for", "Distinguish valid statement about"),
)

class FakeQuizContentGenerator(QuizContentGenerator):
    """Deterministic generator producing valid or simulated erroneous output."""

    def __init__(
        self,
        *,
        is_available: bool = True,
        simulate_timeout: bool = False,
        simulate_refusal: bool = False,
        simulate_rate_limit: bool = False,
        simulate_auth_error: bool = False,
        simulate_malformed: bool = False,
        simulate_repeat_prompt: str | None = None,
        custom_questions: tuple[GeneratedQuestionData, ...] | None = None,
    ) -> None:
        self._is_available = is_available
        self._simulate_timeout = simulate_timeout
        self._simulate_refusal = simulate_refusal
        self._simulate_rate_limit = simulate_rate_limit
        self._simulate_auth_error = simulate_auth_error
        self._simulate_malformed = simulate_malformed
        self._simulate_repeat_prompt = simulate_repeat_prompt
        self._custom_questions = custom_questions
        self.call_count = 0
        self.last_request: GenerationRequest | None = None

    async def generate_quiz_questions(
        self,
        request: GenerationRequest,
    ) -> tuple[GeneratedQuestionData, ...]:
        self.call_count += 1
        self.last_request = request

        if not self._is_available:
            raise GeneratorUnavailableError("AI generation unavailable in test environment.")
        if self._simulate_timeout:
            raise GeneratorTimeoutError("Simulated generation timeout.")
        if self._simulate_refusal:
            raise GeneratorRefusalError("Simulated model refusal.")
        if self._simulate_rate_limit:
            raise GeneratorRateLimitedError("Simulated rate limit.")
        if self._simulate_auth_error:
            raise GeneratorAuthError("Simulated auth failure.")
        if self._simulate_malformed:
            raise GeneratorMalformedError("Simulated malformed JSON output.")

        if self._custom_questions is not None:
            return self._custom_questions

        # Generate a deterministic set summing to target_total_marks.
        # Subject-appropriate mix: English subjects use MULTIPLE_CHOICE and
        # WRITTEN only (never forced NUMERICAL); other subjects rotate all
        # three types. Pattern per position is deterministic for tests.
        target = request.target_total_marks
        subject = request.quiz_subject
        topic = request.quiz_topic
        is_english = subject.strip().lower().startswith("english")

        questions_data: list[dict] = []
        remaining = target
        pos = 0

        # Pattern: alternate MCQ (1 mark), Numerical (2 marks), Written (3-4 marks)
        while remaining > 0:
            if remaining >= 4 and pos % 3 == 2:
                # Written question
                marks = min(remaining, 4)
                prompt_text = (
                    self._simulate_repeat_prompt
                    if (self._simulate_repeat_prompt and pos == 0)
                    else f"{_PROMPT_VARIANTS[self.call_count % len(_PROMPT_VARIANTS)][0]} {topic} item {pos + 1}."
                )
                questions_data.append(
                    {
                        "question_type": "WRITTEN",
                        "prompt": prompt_text,
                        "max_marks": marks,
                        "options": [],
                        "correct_option_id": None,
                        "grading_rubric": {
                            "criteria": [
                                {
                                    "id": f"c_{pos}_1",
                                    "marks": marks // 2 if marks > 1 else 1,
                                    "marking_point": f"States main principle of {topic}",
                                    "accepted_meaning": f"Primary principle of {topic}",
                                    "spelling_sensitive": False,
                                    "explanation": f"Explains the primary principle of {topic}.",
                                },
                                *(
                                    [
                                        {
                                            "id": f"c_{pos}_2",
                                            "marks": marks - (marks // 2),
                                            "marking_point": f"Applies principle to a scenario in {topic}",
                                            "accepted_meaning": f"Application to {topic}",
                                            "spelling_sensitive": False,
                                            "explanation": f"Applies knowledge to {topic}.",
                                        }
                                    ]
                                    if marks > 1
                                    else []
                                ),
                            ],
                            "expected_value": None,
                            "absolute_tolerance": None,
                            "allowed_units": [],
                            "value_marks": 0,
                            "unit_marks": 0,
                            "unit_dependency": "REQUIRES_VALUE",
                        },
                        "worked_explanation": f"Full model answer explaining {topic}.",
                        "original_extract": (
                            f"Sample extract for {topic} analysis."
                            if "english" in subject.lower()
                            else None
                        ),
                    }
                )
                remaining -= marks
            elif remaining >= 2 and pos % 3 == 1 and not is_english:
                # Numerical question (never forced for English subjects)
                marks = 2
                prompt_text = (
                    self._simulate_repeat_prompt
                    if (self._simulate_repeat_prompt and pos == 0)
                    else f"{_PROMPT_VARIANTS[self.call_count % len(_PROMPT_VARIANTS)][1]} {topic} item {pos + 1}."
                )
                questions_data.append(
                    {
                        "question_type": "NUMERICAL",
                        "prompt": prompt_text,
                        "max_marks": 2,
                        "options": [],
                        "correct_option_id": None,
                        "grading_rubric": {
                            "criteria": [],
                            "expected_value": "10.0",
                            "absolute_tolerance": "0.5",
                            "allowed_units": ["j", "n", "m/s", "kg"],
                            "value_marks": 1,
                            "unit_marks": 1,
                            "unit_dependency": "REQUIRES_VALUE",
                        },
                        "worked_explanation": f"Step by step calculation yielding 10.0 for {topic}.",
                        "original_extract": None,
                    }
                )
                remaining -= marks
            else:
                # MCQ question (1 mark)
                marks = 1
                prompt_text = (
                    self._simulate_repeat_prompt
                    if (self._simulate_repeat_prompt and pos == 0)
                    else f"{_PROMPT_VARIANTS[self.call_count % len(_PROMPT_VARIANTS)][2]} {topic} item {pos + 1}."
                )
                questions_data.append(
                    {
                        "question_type": "MULTIPLE_CHOICE",
                        "prompt": prompt_text,
                        "max_marks": 1,
                        "options": [
                            {"id": "opt_a", "label": f"Correct statement for {topic}"},
                            {"id": "opt_b", "label": f"Incorrect distractor 1 for {topic}"},
                            {"id": "opt_c", "label": f"Incorrect distractor 2 for {topic}"},
                            {"id": "opt_d", "label": f"Incorrect distractor 3 for {topic}"},
                        ],
                        "correct_option_id": "opt_a",
                        "grading_rubric": {
                            "criteria": [],
                            "expected_value": None,
                            "absolute_tolerance": None,
                            "allowed_units": [],
                            "value_marks": 0,
                            "unit_marks": 0,
                            "unit_dependency": "REQUIRES_VALUE",
                        },
                        "worked_explanation": f"Option A is correct because of the definition of {topic}.",
                        "original_extract": None,
                    }
                )
                remaining -= marks
            pos += 1

        return validate_generated_quiz_set(
            questions=questions_data,
            target_total_marks=target,
            exclusion_prompts=request.exclusion_prompts,
        )
