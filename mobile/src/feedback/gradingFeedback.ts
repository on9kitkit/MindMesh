/**
 * Strict runtime validation for server-derived written-answer feedback.
 *
 * The backend computes this exact shape itself from the hidden rubric and
 * the validated awarded criterion IDs: a bounded learner-facing summary
 * plus per-marking-point explanations with marks, split into awarded and
 * missing points. The frozen producer bounds are mirrored here: criterion
 * IDs are nonblank strings of at most 64 characters, each criterion carries
 * 1..6 marks, explanations are nonblank strings of at most 2000 characters,
 * IDs are globally unique, and the counts match the arrays exactly with
 * 1..6 total criteria.
 *
 * Deterministic (multiple-choice/numerical) and legacy outcomes keep an
 * empty object or their own small record; only non-empty written feedback
 * must match this shape.
 */

export type FeedbackMarkingPoint = {
  id: string;
  marks: number;
  explanation: string;
};

export type EnrichedWrittenFeedback = {
  summary: string;
  awarded: FeedbackMarkingPoint[];
  missing: FeedbackMarkingPoint[];
  awardedCount: number;
  totalCriteria: number;
};

const ENRICHED_FEEDBACK_KEYS = [
  "summary",
  "awarded",
  "missing",
  "awarded_count",
  "total_criteria",
] as const;

const MARKING_POINT_KEYS = ["id", "marks", "explanation"] as const;

const MAX_CRITERION_ID_LENGTH = 64;
const MAX_CRITERION_MARKS = 6;
const MAX_EXPLANATION_LENGTH = 2000;
const MAX_SUMMARY_LENGTH = 1000;
const MAX_TOTAL_CRITERIA = 6;

export class InvalidGradingFeedbackError extends Error {
  constructor(message = "The server returned invalid grading feedback.") {
    super(message);
    this.name = "InvalidGradingFeedbackError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonBlank(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: ReadonlyArray<string>,
): boolean {
  const actual = Object.keys(value);
  return (
    actual.length === keys.length && actual.every((key) => keys.includes(key))
  );
}

function parseMarkingPoint(
  value: unknown,
  context: string,
): FeedbackMarkingPoint {
  if (!isRecord(value) || !hasExactKeys(value, MARKING_POINT_KEYS)) {
    throw new InvalidGradingFeedbackError(
      `The server returned an invalid grading feedback ${context}.`,
    );
  }
  if (
    !isNonBlank(value.id) ||
    (value.id as string).length > MAX_CRITERION_ID_LENGTH
  ) {
    throw new InvalidGradingFeedbackError(
      `The server returned an invalid grading feedback ${context} ID.`,
    );
  }
  if (
    typeof value.marks !== "number" ||
    !Number.isSafeInteger(value.marks) ||
    (value.marks as number) < 1 ||
    (value.marks as number) > MAX_CRITERION_MARKS
  ) {
    throw new InvalidGradingFeedbackError(
      `The server returned invalid grading feedback ${context} marks.`,
    );
  }
  if (
    !isNonBlank(value.explanation) ||
    (value.explanation as string).length > MAX_EXPLANATION_LENGTH
  ) {
    throw new InvalidGradingFeedbackError(
      `The server returned an invalid grading feedback ${context} explanation.`,
    );
  }
  return {
    id: value.id as string,
    marks: value.marks as number,
    explanation: value.explanation as string,
  };
}

function parseMarkingPointList(
  value: unknown,
  context: string,
): FeedbackMarkingPoint[] {
  if (!Array.isArray(value)) {
    throw new InvalidGradingFeedbackError(
      `The server returned invalid grading feedback ${context}.`,
    );
  }
  return value.map((entry, index) =>
    parseMarkingPoint(entry, `${context} at index ${index}`),
  );
}

/**
 * Validate enriched written feedback. Returns null when feedback is absent
 * (empty object), the parsed shape when present, and throws when a
 * non-empty record does not match the known server-derived exact shape.
 */
export function parseEnrichedWrittenFeedback(
  value: unknown,
): EnrichedWrittenFeedback | null {
  if (!isRecord(value)) {
    throw new InvalidGradingFeedbackError();
  }
  if (Object.keys(value).length === 0) {
    return null;
  }
  if (!hasExactKeys(value, ENRICHED_FEEDBACK_KEYS)) {
    throw new InvalidGradingFeedbackError(
      "The server returned grading feedback with unexpected fields.",
    );
  }
  if (
    !isNonBlank(value.summary) ||
    (value.summary as string).length > MAX_SUMMARY_LENGTH
  ) {
    throw new InvalidGradingFeedbackError(
      "The server returned invalid grading feedback summary.",
    );
  }
  const awarded = parseMarkingPointList(value.awarded, "awarded points");
  const missing = parseMarkingPointList(value.missing, "missing points");
  if (
    typeof value.awarded_count !== "number" ||
    !Number.isSafeInteger(value.awarded_count) ||
    value.awarded_count !== awarded.length
  ) {
    throw new InvalidGradingFeedbackError(
      "The server returned an inconsistent grading feedback awarded count.",
    );
  }
  if (
    typeof value.total_criteria !== "number" ||
    !Number.isSafeInteger(value.total_criteria) ||
    value.total_criteria !== awarded.length + missing.length ||
    value.total_criteria < 1 ||
    value.total_criteria > MAX_TOTAL_CRITERIA
  ) {
    throw new InvalidGradingFeedbackError(
      "The server returned an inconsistent grading feedback criteria total.",
    );
  }
  const seenIds = new Set<string>();
  for (const point of [...awarded, ...missing]) {
    if (seenIds.has(point.id)) {
      throw new InvalidGradingFeedbackError(
        "The server returned duplicate grading feedback criterion IDs.",
      );
    }
    seenIds.add(point.id);
  }
  return {
    summary: value.summary as string,
    awarded,
    missing,
    awardedCount: value.awarded_count as number,
    totalCriteria: value.total_criteria as number,
  };
}

export function awardedMarksTotal(feedback: EnrichedWrittenFeedback): number {
  return feedback.awarded.reduce((total, point) => total + point.marks, 0);
}

/**
 * Detect an enriched-shaped record on a non-written outcome. Deterministic
 * feedback never carries awarded/missing point lists; their presence means
 * the payload is misattributed and must be rejected, not rendered.
 */
export function looksLikeEnrichedFeedback(value: Record<string, unknown>): boolean {
  return "awarded" in value || "missing" in value;
}
