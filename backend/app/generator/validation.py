"""Strict local validation for generated quiz questions and repeat exclusions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence

from app.domain.adaptive_quiz import (
    MAX_MARK_BUDGET,
    MAX_QUESTION_MARKS,
    MIN_MARK_BUDGET,
    MIN_QUESTION_MARKS,
    MultipleChoiceOption,
    NumericalRubric,
    QuestionType,
    UnitDependency,
    WrittenCriterion,
    WrittenRubric,
    UNSAFE_CONTROL_RE,
    calculate_question_duration_seconds,
    compute_content_fingerprint,
    is_supported_numerical_unit,
)
from app.generator.protocol import (
    GeneratedQuestionData,
    GeneratorValidationError,
    MAX_EXCLUSION_BYTES,
    MAX_EXCLUSION_PROMPTS,
)

_UNSUPPORTED_NON_TAG_DISPLAY_MARKUP_RE = re.compile(
    r"\\[A-Za-z]+|\\[()\[\]]|\$\$?[^$\r\n]+\$\$?|"
    r"<!--[\s\S]*?-->|<![A-Za-z][^>]*>|"
    r"^[ \t]*`{3,}|^#{1,6}[ \t]+|"
    r"`+[^`\r\n]+`+|"
    r"\*\*[^*\r\n]+\*\*|__[^_\r\n]+__|"
    r"\[[^\]\r\n]+\]\([^)\r\n]+\)|"
    r"&(?:[A-Za-z][A-Za-z0-9]+|#\d+|#x[0-9A-Fa-f]+);",
    re.IGNORECASE | re.MULTILINE,
)
_HTML_TAG_CANDIDATE_RE = re.compile(
    r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s+[^<>]*)?\s*/?>",
    re.IGNORECASE,
)
_HTML_VOID_TAG_CANDIDATE_RE = re.compile(
    r"</?(?:area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)"
    r"(?=[\s/>])[^<>]*/?>",
    re.IGNORECASE,
)
_HTML_MULTILETTER_TAG_NAMES = (
    "abbr", "address", "article", "aside", "audio", "bdi", "bdo",
    "blockquote", "body", "button", "canvas", "caption", "cite", "code",
    "colgroup", "data", "datalist", "dd", "del", "details", "dfn",
    "dialog", "div", "dl", "dt", "em", "fieldset", "figcaption", "figure",
    "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "head",
    "header", "hgroup", "html", "iframe", "ins", "kbd", "label", "legend",
    "li", "main", "map", "mark", "math", "menu", "meter", "nav", "noscript",
    "object", "ol", "optgroup", "option", "output", "picture", "pre",
    "progress", "rp", "rt", "ruby", "samp", "script", "search", "section",
    "select", "slot", "small", "span", "strong", "style", "sub", "summary",
    "sup", "table", "tbody", "td", "template", "textarea", "tfoot", "th",
    "thead", "time", "title", "tr", "ul", "var", "video",
)
_HTML_MULTILETTER_TAG_CANDIDATE_RE = re.compile(
    rf"</?(?:{'|'.join(_HTML_MULTILETTER_TAG_NAMES)})(?=[\s/>])[^<>]*/?>",
    re.IGNORECASE,
)
_COMPARISON_TERM = r"(?:[+-]?\d+(?:\.\d+)?|\w+)"
_COMPARISON_OPERATOR = r"(?:<=|>=|<|>|≤|≥)"
_MATH_COMPARISON_EXPRESSION_RE = re.compile(
    rf"(?<!\w){_COMPARISON_TERM}(?:\s*{_COMPARISON_OPERATOR}\s*{_COMPARISON_TERM})+"
    rf"(?:\s+(?:and|or)\s+{_COMPARISON_TERM}"
    rf"(?:\s*{_COMPARISON_OPERATOR}\s*{_COMPARISON_TERM})+)*(?!\w)",
    re.IGNORECASE,
)


def _tokenize_prompt(prompt: str) -> set[str]:
    """Tokenize a prompt into lowercased alphanumeric words."""
    return set(re.findall(r"\w+", prompt.lower()))


def _require_safe_text(
    value: Any,
    *,
    field: str,
    position: int,
    min_length: int = 1,
    max_length: int = 2000,
) -> str:
    """Require a string payload that PostgreSQL and UI can safely carry."""
    if not isinstance(value, str):
        raise GeneratorValidationError(
            f"{field} at position {position} must be a string."
        )
    text = value.strip()
    if len(text) < min_length:
        raise GeneratorValidationError(
            f"{field} at position {position} must not be blank."
        )
    if len(text) > max_length:
        raise GeneratorValidationError(
            f"{field} at position {position} exceeds {max_length} characters."
        )
    if UNSAFE_CONTROL_RE.search(value):
        raise GeneratorValidationError(
            f"{field} at position {position} contains unsafe control content."
        )
    return text


def _require_plain_display_text(value: str, *, field: str, position: int) -> str:
    """Reject rich markup that the mobile plain-text question view cannot render."""
    if (
        _UNSUPPORTED_NON_TAG_DISPLAY_MARKUP_RE.search(value)
        or _HTML_VOID_TAG_CANDIDATE_RE.search(value)
        or _HTML_MULTILETTER_TAG_CANDIDATE_RE.search(value)
    ):
        raise GeneratorValidationError(
            f"{field} at position {position} uses unsupported display markup."
        )

    comparison_spans = tuple(
        match.span() for match in _MATH_COMPARISON_EXPRESSION_RE.finditer(value)
    )
    has_unmatched_tag = any(
        not any(
            comparison_start <= tag.start() and tag.end() <= comparison_end
            for comparison_start, comparison_end in comparison_spans
        )
        for tag in _HTML_TAG_CANDIDATE_RE.finditer(value)
    )
    if has_unmatched_tag:
        raise GeneratorValidationError(
            f"{field} at position {position} uses unsupported display markup."
        )
    return value


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def validate_repeat_exclusions(
    prompt: str,
    exclusion_prompts: Sequence[str],
    similarity_threshold: float = 0.8,
) -> None:
    """Validate that prompt does not match or closely resemble recent prompts."""
    norm_prompt = re.sub(r"\s+", " ", prompt.strip().lower())
    prompt_tokens = _tokenize_prompt(norm_prompt)

    # Bound exclusion checks to max 50 prompts
    bounded_exclusions = exclusion_prompts[:MAX_EXCLUSION_PROMPTS]

    total_bytes = 0
    for prior in bounded_exclusions:
        prior_bytes = len(prior.encode("utf-8"))
        if total_bytes + prior_bytes > MAX_EXCLUSION_BYTES:
            break
        total_bytes += prior_bytes

        norm_prior = re.sub(r"\s+", " ", prior.strip().lower())
        if norm_prompt == norm_prior:
            raise GeneratorValidationError(
                f"Generated question prompt is an exact duplicate of a recent question."
            )

        prior_tokens = _tokenize_prompt(norm_prior)
        sim = _jaccard_similarity(prompt_tokens, prior_tokens)
        if sim >= similarity_threshold:
            raise GeneratorValidationError(
                f"Generated question prompt is too similar to a recent question (similarity {sim:.2f})."
            )


def _require_unused_rubric_sentinels(
    rubric_raw: dict[str, Any], *, position: int, kind: str
) -> None:
    """Enforce canonical unused-variant sentinels for closed rubric models.

    The strict provider schema always emits every heterogeneous rubric
    property; unused variants must carry null/empty/zero sentinels so
    malformed cross-variant data cannot persist.
    """
    if rubric_raw.get("expected_value") is not None:
        raise GeneratorValidationError(
            f"{kind} question at position {position} must carry no numerical expected value."
        )
    if rubric_raw.get("absolute_tolerance") is not None:
        raise GeneratorValidationError(
            f"{kind} question at position {position} must carry no numerical tolerance."
        )
    if rubric_raw.get("allowed_units", []) != []:
        raise GeneratorValidationError(
            f"{kind} question at position {position} must carry no allowed units."
        )
    for mark_field in ("value_marks", "unit_marks"):
        mark_value = rubric_raw.get(mark_field, 0)
        if type(mark_value) is not int or mark_value != 0:
            raise GeneratorValidationError(
                f"{kind} question at position {position} must carry zero {mark_field}."
            )
    dependency = rubric_raw.get("unit_dependency")
    if not isinstance(dependency, str):
        raise GeneratorValidationError(
            f"{kind} question at position {position} must carry an explicit unit_dependency."
        )
    try:
        UnitDependency(dependency)
    except ValueError:
        raise GeneratorValidationError(
            f"{kind} question at position {position} has invalid unit_dependency."
        ) from None


def validate_single_question(
    data: Mapping[str, Any] | GeneratedQuestionData,
    position: int,
    exclusion_prompts: Sequence[str] = (),
) -> GeneratedQuestionData:
    """Validate a single generated question dictionary or object against strict invariants."""
    if isinstance(data, GeneratedQuestionData):
        if not isinstance(data.options, (tuple, list)) or any(not isinstance(option, MultipleChoiceOption) for option in data.options):
            raise GeneratorValidationError("Generated options must be typed options.")
        # Canonicalize dataclass input back to a raw mapping so both input
        # kinds traverse identical validation: alternate adapters cannot
        # bypass option/rubric/unit bounds, type consistency, or recomputed
        # duration/fingerprint by handing us a dataclass directly.
        raw_type = data.question_type
        data = {
            "prompt": data.prompt,
            "question_type": raw_type.value if isinstance(raw_type, QuestionType) else raw_type,
            "max_marks": data.max_marks,
            "options": [opt.to_dict() for opt in data.options],
            "correct_option_id": data.correct_option_id,
            "grading_rubric": data.grading_rubric,
            "worked_explanation": data.worked_explanation,
            "original_extract": data.original_extract,
        }
    if not isinstance(data, Mapping):
        raise GeneratorValidationError(
            f"Question at position {position} must be an object."
        )
    if set(data) != {"question_type", "prompt", "max_marks", "options", "correct_option_id", "grading_rubric", "worked_explanation", "original_extract"}:
        raise GeneratorValidationError("Question has missing or unexpected keys.")
    prompt = _require_safe_text(
        data.get("prompt"), field="prompt", position=position, max_length=2000
    )
    _require_plain_display_text(prompt, field="prompt", position=position)
    raw_type = data.get("question_type")
    if not isinstance(raw_type, str):
        raise GeneratorValidationError(
            f"Invalid question type at position {position}: must be a string."
        )
    try:
        q_type = QuestionType(raw_type.strip().upper())
    except ValueError:
        raise GeneratorValidationError(
            f"Invalid question type: {raw_type!r} at position {position}."
        ) from None

    raw_marks = data.get("max_marks")
    if type(raw_marks) is not int:
        raise GeneratorValidationError(
            f"Invalid max_marks for question at position {position}: must be an integer."
        )
    max_marks = raw_marks

    raw_options = data.get("options", [])
    if not isinstance(raw_options, list):
        raise GeneratorValidationError(f"options must be a list at position {position}")

    opts_list: list[MultipleChoiceOption] = []
    seen_option_ids: set[str] = set()
    for opt in raw_options:
        if not isinstance(opt, dict):
            raise GeneratorValidationError(
                f"Malformed option in question at position {position}: must be an object."
            )
        if set(opt) != {"id", "label"}:
            raise GeneratorValidationError("Option has missing or unexpected keys.")
        opt_id = _require_safe_text(
            opt.get("id"), field="option id", position=position, max_length=64
        )
        opt_label = _require_safe_text(
            opt.get("label"), field="option label", position=position, max_length=500
        )
        _require_plain_display_text(opt_label, field="option label", position=position)
        if opt_id in seen_option_ids:
            raise GeneratorValidationError(
                f"Question at position {position} has duplicate option ID {opt_id!r}."
            )
        seen_option_ids.add(opt_id)
        opts_list.append(MultipleChoiceOption(id=opt_id, label=opt_label))
    options = tuple(opts_list)
    raw_correct = data.get("correct_option_id")
    if raw_correct is None:
        correct_option_id = None
    elif not isinstance(raw_correct, str) or not raw_correct.strip():
        raise GeneratorValidationError(
            f"correct_option_id at position {position} must be a nonblank string or null."
        )
    elif len(raw_correct.strip()) > 64:
        raise GeneratorValidationError(
            f"correct_option_id at position {position} exceeds 64 characters."
        )
    else:
        correct_option_id = raw_correct.strip()
    rubric_raw = data.get("grading_rubric")
    if not isinstance(rubric_raw, dict):
        raise GeneratorValidationError(f"grading_rubric must be an object at position {position}")
    if set(rubric_raw) != {"criteria", "expected_value", "absolute_tolerance", "allowed_units", "value_marks", "unit_marks", "unit_dependency"}:
        raise GeneratorValidationError("Rubric has missing or unexpected keys.")
    criteria = rubric_raw.get("criteria")
    if not isinstance(criteria, list):
        raise GeneratorValidationError("Rubric criteria must be an array.")
    for criterion in criteria:
        if not isinstance(criterion, dict) or set(criterion) != {"id", "marks", "marking_point", "accepted_meaning", "spelling_sensitive", "explanation"}:
            raise GeneratorValidationError("Criterion has missing or unexpected keys.")

    worked_explanation = _require_safe_text(
        data.get("worked_explanation"),
        field="worked_explanation",
        position=position,
        max_length=4000,
    )
    _require_plain_display_text(
        worked_explanation, field="worked_explanation", position=position
    )
    raw_extract = data.get("original_extract")
    if raw_extract is None:
        original_extract = None
    else:
        original_extract = _require_safe_text(
            raw_extract, field="original_extract", position=position, max_length=4000
        )
        _require_plain_display_text(
            original_extract, field="original_extract", position=position
        )

    # Common field bounds
    if not (MIN_QUESTION_MARKS <= max_marks <= MAX_QUESTION_MARKS):
        raise GeneratorValidationError(
            f"Question at position {position} has marks {max_marks} outside 1–6."
        )
    if not prompt:
        raise GeneratorValidationError(f"Question at position {position} has empty prompt.")
    if len(prompt) > 2000:
        raise GeneratorValidationError(f"Question prompt at position {position} exceeds 2000 characters.")
    if not worked_explanation:
        raise GeneratorValidationError(f"Question at position {position} has empty worked_explanation.")
    if len(worked_explanation) > 4000:
        raise GeneratorValidationError(f"Worked explanation at position {position} exceeds 4000 characters.")
    if original_extract and len(original_extract) > 4000:
        raise GeneratorValidationError(f"Original extract at position {position} exceeds 4000 characters.")

    # Duration check
    duration_seconds = calculate_question_duration_seconds(max_marks)

    # Repeat exclusion check
    validate_repeat_exclusions(prompt, exclusion_prompts)

    # Type-specific invariants
    if q_type == QuestionType.MULTIPLE_CHOICE:
        if max_marks != 1:
            raise GeneratorValidationError(
                f"MULTIPLE_CHOICE question at position {position} must be exactly 1 mark."
            )
        if not (2 <= len(options) <= 6):
            raise GeneratorValidationError(
                f"MULTIPLE_CHOICE question at position {position} must have 2–6 options."
            )
        if not correct_option_id:
            raise GeneratorValidationError(
                f"MULTIPLE_CHOICE question at position {position} missing correct_option_id."
            )
        option_ids = {opt.id for opt in options}
        if len(option_ids) != len(options):
            raise GeneratorValidationError(
                f"MULTIPLE_CHOICE question at position {position} has duplicate option IDs."
            )
        if correct_option_id not in option_ids:
            raise GeneratorValidationError(
                f"correct_option_id '{correct_option_id}' not found in options at position {position}."
            )
        raw_criteria = rubric_raw.get("criteria", [])
        if not isinstance(raw_criteria, list) or raw_criteria:
            raise GeneratorValidationError(
                f"MULTIPLE_CHOICE question at position {position} must carry no written criteria."
            )
        _require_unused_rubric_sentinels(rubric_raw, position=position, kind="MULTIPLE_CHOICE")

    elif q_type == QuestionType.NUMERICAL:
        if len(options) != 0 or correct_option_id is not None:
            raise GeneratorValidationError(
                f"NUMERICAL question at position {position} must not have selectable options."
            )
        raw_num_criteria = rubric_raw.get("criteria", [])
        if not isinstance(raw_num_criteria, list) or raw_num_criteria:
            raise GeneratorValidationError(
                f"NUMERICAL question at position {position} must carry no written criteria."
            )
        try:
            num_rubric = NumericalRubric.from_dict(rubric_raw)
        except (ValueError, KeyError, TypeError, InvalidOperation) as err:
            raise GeneratorValidationError(
                f"Invalid numerical rubric at position {position}: {err}"
            ) from err

        if num_rubric.total_marks() != max_marks:
            raise GeneratorValidationError(
                f"Numerical rubric total marks ({num_rubric.total_marks()}) != question max_marks ({max_marks}) at position {position}."
            )
        if num_rubric.absolute_tolerance < Decimal("0"):
            raise GeneratorValidationError(
                f"Numerical rubric tolerance must be non-negative at position {position}."
            )
        if any(not is_supported_numerical_unit(unit) for unit in num_rubric.allowed_units):
            raise GeneratorValidationError(
                f"Numerical rubric at position {position} contains an unsupported unit alias."
            )

    elif q_type == QuestionType.WRITTEN:
        if len(options) != 0 or correct_option_id is not None:
            raise GeneratorValidationError(
                f"WRITTEN question at position {position} must not have selectable options."
            )
        _require_unused_rubric_sentinels(rubric_raw, position=position, kind="WRITTEN")
        try:
            written_rubric = WrittenRubric.from_dict(rubric_raw)
        except (ValueError, KeyError, TypeError) as err:
            raise GeneratorValidationError(
                f"Invalid written rubric at position {position}: {err}"
            ) from err

        if not written_rubric.criteria:
            raise GeneratorValidationError(
                f"Written question at position {position} must have at least one criterion."
            )
        if written_rubric.total_marks() != max_marks:
            raise GeneratorValidationError(
                f"Written rubric criteria sum ({written_rubric.total_marks()}) != question max_marks ({max_marks}) at position {position}."
            )
        criterion_ids = {c.id for c in written_rubric.criteria}
        if len(criterion_ids) != len(written_rubric.criteria):
            raise GeneratorValidationError(
                f"Written question at position {position} has duplicate criterion IDs."
            )
        for c in written_rubric.criteria:
            _require_safe_text(c.id, field="criterion id", position=position, max_length=64)
            if not c.id.strip() or len(c.id) > 64:
                raise GeneratorValidationError(
                    f"Criterion IDs must be nonblank strings of at most 64 characters at position {position}."
                )
            if c.marks < 1 or c.marks > max_marks:
                raise GeneratorValidationError(
                    f"Criterion '{c.id}' has invalid marks {c.marks} at position {position}."
                )
            _require_safe_text(
                c.marking_point, field=f"marking point '{c.id}'",
                position=position, max_length=2000,
            )
            _require_plain_display_text(
                c.marking_point, field="marking point", position=position
            )
            _require_safe_text(
                c.accepted_meaning, field=f"accepted meaning '{c.id}'",
                position=position, max_length=2000,
            )
            _require_plain_display_text(
                c.accepted_meaning, field="accepted meaning", position=position
            )
            if c.spelling_sensitive and (len(c.accepted_meaning) > 64 or len(c.accepted_meaning.split()) > 8 or any(char in c.accepted_meaning for char in "\n\r\t")):
                raise GeneratorValidationError("Spelling-sensitive target must be a short single-line literal.")
            _require_safe_text(
                c.explanation, field=f"criterion explanation '{c.id}'",
                position=position, max_length=2000,
            )
            _require_plain_display_text(
                c.explanation, field="criterion explanation", position=position
            )

    fingerprint = compute_content_fingerprint(
        prompt=prompt,
        question_type=q_type,
        max_marks=max_marks,
        options=options if q_type == QuestionType.MULTIPLE_CHOICE else None,
        correct_option_id=correct_option_id,
        extract=original_extract,
    )

    return GeneratedQuestionData(
        position=position,
        question_type=q_type,
        prompt=prompt,
        max_marks=max_marks,
        duration_seconds=duration_seconds,
        options=options,
        correct_option_id=correct_option_id,
        grading_rubric=rubric_raw,
        worked_explanation=worked_explanation,
        original_extract=original_extract,
        content_fingerprint=fingerprint,
    )


def validate_generated_quiz_set(
    questions: Sequence[Mapping[str, Any] | GeneratedQuestionData],
    target_total_marks: int,
    exclusion_prompts: Sequence[str] = (),
) -> tuple[GeneratedQuestionData, ...]:
    """Validate a complete generated question set against all product and database invariants."""
    if not isinstance(questions, (tuple, list)):
        raise GeneratorValidationError("Generated questions must be an array.")
    if not (MIN_MARK_BUDGET <= target_total_marks <= MAX_MARK_BUDGET):
        raise GeneratorValidationError(
            f"target_total_marks {target_total_marks} must be between {MIN_MARK_BUDGET} and {MAX_MARK_BUDGET}."
        )

    if not (1 <= len(questions) <= 40):
        raise GeneratorValidationError(
            f"Question count {len(questions)} must be between 1 and 40."
        )

    validated: list[GeneratedQuestionData] = []
    seen_fingerprints: set[str] = set()
    seen_prompts: list[str] = []

    for idx, q_data in enumerate(questions):
        q = validate_single_question(q_data, position=idx, exclusion_prompts=exclusion_prompts)
        if q.content_fingerprint in seen_fingerprints:
            raise GeneratorValidationError(
                f"Duplicate question detected within the generated set at position {idx}."
            )
        seen_fingerprints.add(q.content_fingerprint)
        # Fingerprints include options/answers, so two identical or
        # near-identical prompts with different distractors would still
        # pass: compare prompts within the set with the same normalized
        # exact and Jaccard rules used for external history.
        for prior in seen_prompts:
            norm_new = re.sub(r"\s+", " ", q.prompt.strip().lower())
            norm_prior = re.sub(r"\s+", " ", prior.strip().lower())
            if norm_new == norm_prior:
                raise GeneratorValidationError(
                    f"Generated question at position {idx} repeats an earlier prompt in the set."
                )
            if _jaccard_similarity(_tokenize_prompt(norm_new), _tokenize_prompt(norm_prior)) >= 0.8:
                raise GeneratorValidationError(
                    f"Generated question at position {idx} is too similar to an earlier prompt in the set."
                )
        seen_prompts.append(q.prompt)
        validated.append(q)

    total_marks_sum = sum(q.max_marks for q in validated)
    if total_marks_sum != target_total_marks:
        raise GeneratorValidationError(
            f"Generated questions marks sum ({total_marks_sum}) does not equal target budget ({target_total_marks})."
        )

    return tuple(validated)
