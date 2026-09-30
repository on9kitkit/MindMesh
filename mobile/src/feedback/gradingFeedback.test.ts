import assert from "node:assert/strict";
import test from "node:test";

import {
  awardedMarksTotal,
  InvalidGradingFeedbackError,
  looksLikeEnrichedFeedback,
  parseEnrichedWrittenFeedback,
} from "./gradingFeedback";

const awardedPoint = { id: "c1", marks: 2, explanation: "Named heat flow." };
const missingPoint = {
  id: "c2",
  marks: 2,
  explanation: "Explain particle role.",
};

const enriched = {
  summary: "Good start; mention conduction.",
  awarded: [awardedPoint],
  missing: [missingPoint],
  awarded_count: 1,
  total_criteria: 2,
};

test("empty feedback stays absent for deterministic and legacy outcomes", () => {
  assert.equal(parseEnrichedWrittenFeedback({}), null);
});

test("enriched written feedback parses awarded and missing points", () => {
  const parsed = parseEnrichedWrittenFeedback(enriched);
  assert.ok(parsed !== null);
  assert.equal(parsed.summary, "Good start; mention conduction.");
  assert.equal(parsed.awarded.length, 1);
  assert.equal(parsed.missing.length, 1);
  assert.equal(parsed.awarded[0]?.marks, 2);
  assert.equal(awardedMarksTotal(parsed), 2);
  assert.equal(parsed.awardedCount, 1);
  assert.equal(parsed.totalCriteria, 2);
});

test("arbitrary extra keys are rejected", () => {
  assert.throws(
    () => parseEnrichedWrittenFeedback({ ...enriched, trace_id: "x" }),
    InvalidGradingFeedbackError,
  );
  assert.throws(
    () =>
      parseEnrichedWrittenFeedback({
        ...enriched,
        awarded: [{ ...awardedPoint, rubric: "hidden" }],
      }),
    InvalidGradingFeedbackError,
  );
});

test("blank or oversized summaries and explanations are rejected", () => {
  for (const summary of ["", "   ", "x".repeat(1001)]) {
    assert.throws(
      () => parseEnrichedWrittenFeedback({ ...enriched, summary }),
      InvalidGradingFeedbackError,
    );
  }
  assert.throws(
    () =>
      parseEnrichedWrittenFeedback({
        ...enriched,
        awarded: [{ ...awardedPoint, explanation: "  " }],
      }),
    InvalidGradingFeedbackError,
  );
  assert.throws(
    () =>
      parseEnrichedWrittenFeedback({
        ...enriched,
        missing: [{ ...missingPoint, explanation: "x".repeat(2001) }],
      }),
    InvalidGradingFeedbackError,
  );
});

test("zero, unbounded, or non-integer point marks are rejected", () => {
  for (const marks of [0, 7, 100, 1.5, "2", null]) {
    assert.throws(
      () =>
        parseEnrichedWrittenFeedback({
          ...enriched,
          awarded: [{ ...awardedPoint, marks }],
        }),
      InvalidGradingFeedbackError,
    );
  }
});

test("blank or oversized criterion IDs are rejected", () => {
  for (const id of ["", "   ", "c".repeat(65), 42, null]) {
    assert.throws(
      () =>
        parseEnrichedWrittenFeedback({
          ...enriched,
          awarded: [{ ...awardedPoint, id }],
        }),
      InvalidGradingFeedbackError,
    );
  }
});

test("duplicate IDs within and across awarded and missing are rejected", () => {
  assert.throws(
    () =>
      parseEnrichedWrittenFeedback({
        ...enriched,
        awarded: [awardedPoint, { ...awardedPoint }],
      }),
    InvalidGradingFeedbackError,
  );
  assert.throws(
    () =>
      parseEnrichedWrittenFeedback({
        ...enriched,
        missing: [missingPoint, { ...awardedPoint, marks: 1 }],
      }),
    InvalidGradingFeedbackError,
  );
  assert.throws(
    () =>
      parseEnrichedWrittenFeedback({
        summary: enriched.summary,
        awarded: [],
        missing: [],
        awarded_count: 0,
        total_criteria: 0,
      }),
    InvalidGradingFeedbackError,
  );
});

test("counts must match the arrays exactly within 1..6 total criteria", () => {
  assert.throws(
    () => parseEnrichedWrittenFeedback({ ...enriched, awarded_count: 0 }),
    InvalidGradingFeedbackError,
  );
  assert.throws(
    () => parseEnrichedWrittenFeedback({ ...enriched, total_criteria: 3 }),
    InvalidGradingFeedbackError,
  );
  assert.throws(
    () =>
      parseEnrichedWrittenFeedback({
        summary: enriched.summary,
        awarded: Array.from({ length: 4 }, (_, index) => ({
          id: `a${index}`,
          marks: 1,
          explanation: `Point ${index}.`,
        })),
        missing: Array.from({ length: 3 }, (_, index) => ({
          id: `m${index}`,
          marks: 1,
          explanation: `Missing ${index}.`,
        })),
        awarded_count: 4,
        total_criteria: 7,
      }),
    InvalidGradingFeedbackError,
  );
});

test("malformed envelopes are rejected, never cast", () => {
  const cases: unknown[] = [
    null,
    [],
    "summary",
    { summary: 42, awarded: [], missing: [] },
    { summary: "x" },
    { summary: "x", awarded: {}, missing: [] },
    { summary: "x", awarded: [], missing: null },
    {
      summary: "x",
      awarded: [{ id: "c1", marks: 1 }],
      missing: [],
      awarded_count: 1,
      total_criteria: 1,
    },
  ];
  for (const value of cases) {
    assert.throws(
      () => parseEnrichedWrittenFeedback(value),
      (error: unknown) => error instanceof InvalidGradingFeedbackError,
    );
  }
});

test("enriched shape detection flags misattributed deterministic feedback", () => {
  assert.equal(looksLikeEnrichedFeedback({}), false);
  assert.equal(
    looksLikeEnrichedFeedback({ value_awarded: true, unit_awarded: true }),
    false,
  );
  assert.equal(looksLikeEnrichedFeedback({ awarded: [] }), true);
  assert.equal(looksLikeEnrichedFeedback({ missing: [] }), true);
});
