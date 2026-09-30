import { InvalidGradingFeedbackError } from "./gradingFeedback";

export type NumericalFeedback =
  | { value_awarded: boolean; unit_awarded: boolean; earned_marks: number; max_marks: number }
  | { value_awarded: false; unit_awarded: false; explanation: string };

/** Validate producer results without deriving marks from hidden rubric weights. */
export function parseNumericalFeedback(
  value: unknown,
  earnedMarks: number,
  maxMarks: number,
): NumericalFeedback {
  const invalid = (): never => { throw new InvalidGradingFeedbackError(); };
  if (typeof value !== "object" || value === null || Array.isArray(value)) return invalid();
  const record = value as Record<string, unknown>;
  if (!Number.isSafeInteger(earnedMarks) || !Number.isSafeInteger(maxMarks) ||
      maxMarks < 1 || maxMarks > 6 || earnedMarks < 0 || earnedMarks > maxMarks) return invalid();
  const keys = "explanation" in record
    ? ["value_awarded", "unit_awarded", "explanation"]
    : ["value_awarded", "unit_awarded", "earned_marks", "max_marks"];
  if (Object.keys(record).length !== keys.length ||
      !Object.keys(record).every((key) => keys.includes(key))) return invalid();
  if ("explanation" in record) {
    if (record.value_awarded !== false || record.unit_awarded !== false || earnedMarks !== 0 ||
        typeof record.explanation !== "string" || record.explanation.trim().length === 0) return invalid();
    return { value_awarded: false, unit_awarded: false, explanation: record.explanation };
  }
  if (typeof record.value_awarded !== "boolean" || typeof record.unit_awarded !== "boolean" ||
      record.earned_marks !== earnedMarks || record.max_marks !== maxMarks) return invalid();
  return { value_awarded: record.value_awarded, unit_awarded: record.unit_awarded,
    earned_marks: earnedMarks, max_marks: maxMarks };
}
