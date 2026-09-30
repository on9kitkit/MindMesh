import assert from "node:assert/strict";
import test from "node:test";

import { parseSessionReviewResponse } from "../../api/schemas";
import {
  buildReviewPresentation,
  describeRoomSelection,
  presentReviewItem,
} from "./reviewPresentation";

const QUESTION_ID = "33333333-3333-4333-8333-333333333333";

const review = {
  session_id: "22222222-2222-4222-8222-222222222222",
  room_id: "11111111-1111-4111-8111-111111111111",
  viewer_user_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  total_earned_marks: 3,
  total_available_marks: 5,
  questions: [
    {
      session_question_id: QUESTION_ID,
      position: 0,
      question_type: "MULTIPLE_CHOICE",
      prompt: "What is the SI unit of force?",
      max_marks: 1,
      options: [
        { id: "joule", label: "Joule" },
        { id: "newton", label: "Newton" },
      ],
      correct_option_id: "newton",
      worked_explanation: "Force is measured in newtons.",
      original_extract: null,
      selected_option_id: "newton",
      answer_text: null,
      earned_marks: 1,
      feedback: {},
      awarded_criterion_ids: [],
    },
    {
      session_question_id: "33333333-3333-4333-8333-444444444444",
      position: 1,
      question_type: "WRITTEN",
      prompt: "Explain conduction.",
      max_marks: 4,
      options: [],
      correct_option_id: null,
      worked_explanation: "Conduction needs particles.",
      original_extract: null,
      selected_option_id: null,
      answer_text: "Particles vibrate.",
      earned_marks: 2,
      feedback: {
        summary: "Mention energy transfer.",
        awarded: [{ id: "c1", marks: 2, explanation: "Named vibration." }],
        missing: [{ id: "c2", marks: 2, explanation: "Link to energy." }],
        awarded_count: 1,
        total_criteria: 2,
      },
      awarded_criterion_ids: ["c1"],
    },
  ],
};

test("review presents only the viewer's own responses and marks", () => {
  const parsed = parseSessionReviewResponse(review);
  const presentation = buildReviewPresentation(parsed);
  assert.equal(presentation.totalsLabel, "3/5 marks");
  assert.equal(presentation.questions.length, 2);

  const choice = presentation.questions[0];
  assert.ok(choice !== undefined);
  assert.equal(choice.questionTypeLabel, "Multiple choice");
  assert.equal(choice.ownResponseLabel, "Newton");
  assert.equal(choice.correctOptionLabel, "Newton");
  assert.equal(choice.marksLabel, "1/1 marks");
  assert.equal(choice.feedbackSummary, null);

  const written = presentation.questions[1];
  assert.ok(written !== undefined);
  assert.equal(written.questionTypeLabel, "Written");
  assert.equal(written.questionNumber, 2);
  assert.equal(written.ownResponseLabel, "Particles vibrate.");
  assert.equal(written.correctOptionLabel, null);
  assert.equal(written.marksLabel, "2/4 marks");
  assert.equal(written.feedbackSummary, "Mention energy transfer.");
  assert.equal(written.awardedCriterionCount, 1);
  assert.ok(written.enrichedFeedback !== null);
  assert.equal(written.enrichedFeedback.awarded.length, 1);
  assert.equal(
    written.enrichedFeedback.awarded[0]?.explanation,
    "Named vibration.",
  );
  assert.equal(written.enrichedFeedback.missing.length, 1);
  assert.equal(
    written.enrichedFeedback.missing[0]?.marks,
    2,
  );
  assert.equal(choice.enrichedFeedback, null);

  const serialized = JSON.stringify(presentation);
  assert.equal(serialized.includes("other"), false);
});

test("review keeps server question order without local scoring", () => {
  const parsed = parseSessionReviewResponse(review);
  const presentation = buildReviewPresentation(parsed);
  assert.deepEqual(
    presentation.questions.map((item) => item.position),
    [0, 1],
  );
  assert.deepEqual(
    presentation.questions.map((item) => item.questionNumber),
    [1, 2],
  );
  assert.equal(presentation.totalEarnedMarks, 3);
  assert.equal(presentation.totalAvailableMarks, 5);
});

test("unanswered questions render without inventing a response", () => {
  const parsed = parseSessionReviewResponse({
    ...review,
    total_earned_marks: 0,
    total_available_marks: 1,
    questions: [
      {
        ...review.questions[0],
        selected_option_id: null,
        answer_text: null,
        earned_marks: 0,
      },
    ],
  });
  const item = presentReviewItem(parsed.questions[0]!);
  assert.equal(item.ownResponseLabel, null);
  assert.equal(item.marksLabel, "0/1 marks");
});

test("room selection labels render friendly names", () => {
  assert.equal(
    describeRoomSelection("physics", "energy"),
    "Physics · Energy",
  );
  assert.equal(
    describeRoomSelection("english_literature", "poetry_analysis"),
    "English Literature · Poetry analysis",
  );
  assert.equal(describeRoomSelection(null, "energy"), null);
});
