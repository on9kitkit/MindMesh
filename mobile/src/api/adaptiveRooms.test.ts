import assert from "node:assert/strict";
import test from "node:test";

import { createApiClient } from "./client";
import { MalformedResponseError } from "./errors";
import { prepareQuiz, QUIZ_PREPARATION_TIMEOUT_MS } from "./rooms";
import {
  parseQuizPreparationResponse,
  parseRoomResponse,
  parseSessionReviewResponse,
} from "./schemas";
import { getSessionReview } from "./sessionReview";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setFetch(
  handler: (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => Promise<Response>,
): () => void {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = handler;
  return () => {
    globalThis.fetch = originalFetch;
  };
}

function authenticatedClient() {
  return createApiClient("http://127.0.0.1:8000", {
    getAccessToken: async () => "access-token",
  });
}

const ROOM_ID = "11111111-1111-4111-8111-111111111111";
const SESSION_ID = "22222222-2222-4222-8222-222222222222";
const QUESTION_ID = "33333333-3333-4333-8333-333333333333";

test("only preparation supplies its bounded 100 second timeout", async () => {
  await prepareQuiz(ROOM_ID, QUESTION_ID, {
    baseUrl: "http://localhost",
    async requestJson(path, options) {
      assert.equal(path, `/rooms/${ROOM_ID}/quiz-preparations`);
      assert.equal(QUIZ_PREPARATION_TIMEOUT_MS, 100_000);
      assert.equal(options?.timeoutMs, QUIZ_PREPARATION_TIMEOUT_MS);
      return { id: QUESTION_ID, room_id: ROOM_ID, request_id: QUESTION_ID,
        status: "READY", state_version: 2, error_category: null };
    },
  });
});

test("adaptive room responses parse immutable quiz settings", () => {
  const parsed = parseRoomResponse({
    id: ROOM_ID,
    name: "GCSE Physics",
    join_code: "PHYS42",
    maximum_members: 8,
    member_count: 1,
    quiz_mode: "ADAPTIVE",
    education_level: "GCSE",
    quiz_subject: "physics",
    quiz_topic: "energy",
    target_total_marks: 20,
  });
  assert.equal(parsed.quiz_mode, "ADAPTIVE");
  assert.equal(parsed.education_level, "GCSE");
  assert.equal(parsed.quiz_subject, "physics");
  assert.equal(parsed.quiz_topic, "energy");
  assert.equal(parsed.target_total_marks, 20);
});

test("legacy room responses without quiz settings keep the demo shape", () => {
  const parsed = parseRoomResponse({
    id: ROOM_ID,
    name: "Physics Sprint",
    join_code: "PHYS42",
    maximum_members: 8,
    member_count: 1,
  });
  assert.equal(parsed.quiz_mode, "LEGACY_PHYSICS");
  assert.equal(parsed.education_level, null);
  assert.equal(parsed.quiz_subject, null);
  assert.equal(parsed.quiz_topic, null);
  assert.equal(parsed.target_total_marks, null);
});

test("room responses reject invalid quiz settings", () => {
  const base = {
    id: ROOM_ID,
    name: "GCSE Physics",
    join_code: "PHYS42",
    maximum_members: 8,
    member_count: 1,
  };
  assert.throws(() =>
    parseRoomResponse({ ...base, quiz_mode: "ARCADE" }),
  );
  assert.throws(() =>
    parseRoomResponse({
      ...base,
      quiz_mode: "ADAPTIVE",
      target_total_marks: 4,
    }),
  );
  assert.throws(() =>
    parseRoomResponse({
      ...base,
      quiz_mode: "ADAPTIVE",
      target_total_marks: 41,
    }),
  );
});

test("prepareQuiz sends the host request ID and parses the durable state", async () => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const requestId = "44444444-4444-4444-8444-444444444444";
  const restoreFetch = setFetch(async (input, init) => {
    calls.push({ input, init });
    return jsonResponse(
      {
        id: "55555555-5555-4555-8555-555555555555",
        room_id: ROOM_ID,
        request_id: requestId,
        status: "GENERATING",
        state_version: 1,
        error_category: null,
      },
      200,
    );
  });

  try {
    const response = await prepareQuiz(
      ROOM_ID,
      requestId,
      authenticatedClient(),
    );
    assert.equal(response.status, "GENERATING");
    assert.equal(response.request_id, requestId);
    assert.equal(response.state_version, 1);
    assert.equal(
      String(calls[0]?.input),
      `http://127.0.0.1:8000/rooms/${ROOM_ID}/quiz-preparations`,
    );
    assert.equal(calls[0]?.init?.method, "POST");
    assert.equal(
      calls[0]?.init?.body,
      JSON.stringify({ request_id: requestId }),
    );
  } finally {
    restoreFetch();
  }
});

test("preparation responses reject unknown statuses", () => {
  assert.throws(() =>
    parseQuizPreparationResponse({
      id: "55555555-5555-4555-8555-555555555555",
      room_id: ROOM_ID,
      request_id: "44444444-4444-4444-8444-444444444444",
      status: "DREAMING",
      state_version: 1,
      error_category: null,
    }),
  );
});

const enrichedFeedback = {
  summary: "Good start; mention conduction.",
  awarded: [{ id: "c1", marks: 2, explanation: "Named heat flow." }],
  missing: [{ id: "c2", marks: 2, explanation: "Explain particle role." }],
  awarded_count: 1,
  total_criteria: 2,
};

const reviewQuestion = {
  session_question_id: QUESTION_ID,
  position: 0,
  question_type: "WRITTEN",
  prompt: "Explain energy transfer.",
  max_marks: 4,
  options: [],
  correct_option_id: null,
  worked_explanation: "Heat moves from hot to cold.",
  original_extract: null,
  selected_option_id: null,
  answer_text: "Heat flows.",
  earned_marks: 2,
  feedback: enrichedFeedback,
  awarded_criterion_ids: ["c1"],
};

const review = {
  session_id: SESSION_ID,
  room_id: ROOM_ID,
  viewer_user_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  total_earned_marks: 2,
  total_available_marks: 4,
  questions: [reviewQuestion],
};

test("private review accepts numerical producer grades and the unanswered empty case", () => {
  for (const [earned_marks, feedback, answer_text] of [
    [3, { value_awarded: true, unit_awarded: true, earned_marks: 3, max_marks: 3 }, "12 N"],
    [2, { value_awarded: true, unit_awarded: false, earned_marks: 2, max_marks: 3 }, "12"],
    [0, { value_awarded: false, unit_awarded: false, explanation: "Could not parse a valid number from the answer." }, "unknown"],
    [0, {}, null],
  ] as const) {
    assert.doesNotThrow(() => parseSessionReviewResponse({ ...review, total_available_marks: 3,
      total_earned_marks: earned_marks, questions: [{ ...reviewQuestion, question_type: "NUMERICAL",
        max_marks: 3, earned_marks, feedback, answer_text, awarded_criterion_ids: [] }] }));
  }
});

test("private numerical review rejects feedback mismatches, extras and invented unanswered grades", () => {
  const question = { ...reviewQuestion, question_type: "NUMERICAL", max_marks: 3,
    earned_marks: 2, awarded_criterion_ids: [],
    feedback: { value_awarded: true, unit_awarded: false, earned_marks: 2, max_marks: 3 } };
  for (const overrides of [
    { feedback: {} }, { feedback: { ...question.feedback, max_marks: 2 } },
    { feedback: { ...question.feedback, earned_marks: 1 } },
    { feedback: { ...question.feedback, value_awarded: "yes" } },
    { feedback: { ...question.feedback, extra: true } },
    { feedback: enrichedFeedback }, { answer_text: null }, { awarded_criterion_ids: ["c1"] },
  ]) {
    assert.throws(() => parseSessionReviewResponse({ ...review, total_available_marks: 3,
      questions: [{ ...question, ...overrides }] }), MalformedResponseError);
  }
});

test("session review parses the viewer's private finished outcome", () => {
  const parsed = parseSessionReviewResponse(review);
  assert.equal(parsed.total_earned_marks, 2);
  assert.equal(parsed.total_available_marks, 4);
  assert.equal(parsed.questions.length, 1);
  assert.equal(parsed.questions[0]?.position, 0);
  assert.equal(parsed.questions[0]?.answer_text, "Heat flows.");
  assert.deepEqual(parsed.questions[0]?.awarded_criterion_ids, ["c1"]);
});

test("session review enforces zero-based ordering, identity, and exact totals", () => {
  const secondQuestion = {
    ...reviewQuestion,
    session_question_id: "33333333-3333-4333-8333-444444444444",
    position: 1,
    prompt: "Second written prompt.",
    max_marks: 2,
    earned_marks: 1,
    answer_text: "Second answer.",
    feedback: {
      summary: "Partial.",
      awarded: [{ id: "c1", marks: 1, explanation: "One point." }],
      missing: [{ id: "c2", marks: 1, explanation: "One missing." }],
      awarded_count: 1,
      total_criteria: 2,
    },
  };
  const twoQuestion = {
    ...review,
    total_earned_marks: 3,
    total_available_marks: 6,
    questions: [reviewQuestion, secondQuestion],
  };
  const parsed = parseSessionReviewResponse(twoQuestion);
  assert.equal(parsed.questions.length, 2);

  assert.throws(() =>
    parseSessionReviewResponse({
      ...twoQuestion,
      questions: [secondQuestion, reviewQuestion],
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...twoQuestion,
      questions: [reviewQuestion, { ...secondQuestion, position: 0 }],
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...twoQuestion,
      questions: [
        reviewQuestion,
        { ...secondQuestion, session_question_id: QUESTION_ID },
      ],
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({ ...twoQuestion, total_available_marks: 7 }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({ ...twoQuestion, total_earned_marks: 4 }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({ ...twoQuestion, session_id: "room-123" }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...twoQuestion,
      questions: [
        reviewQuestion,
        {
          ...secondQuestion,
          options: [{ id: "a", label: "A" }],
        },
      ],
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      questions: [
        {
          ...reviewQuestion,
          feedback: {
            summary: "Wrong sum.",
            awarded: [{ id: "c1", marks: 1, explanation: "One point." }],
            missing: [],
          },
        },
      ],
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      questions: [
        {
          ...reviewQuestion,
          feedback: { summary: "Missing points arrays." },
        },
      ],
    }),
  );
});

test("session review enforces written grade coherence exactly", () => {
  // Empty written feedback is legitimate only without an earned grade.
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      questions: [{ ...reviewQuestion, feedback: {} }],
    }),
  );
  // Awarded IDs must exactly match the enriched awarded points.
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      questions: [{ ...reviewQuestion, awarded_criterion_ids: [] }],
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      questions: [
        { ...reviewQuestion, awarded_criterion_ids: ["c1", "c2"] },
      ],
    }),
  );
  // Enriched-shaped feedback on a non-written question is misattributed.
  assert.throws(() =>
    parseSessionReviewResponse({
      session_id: SESSION_ID,
      room_id: ROOM_ID,
      viewer_user_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      total_earned_marks: 1,
      total_available_marks: 1,
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
          feedback: enrichedFeedback,
          awarded_criterion_ids: [],
        },
      ],
    }),
  );
  // Exact record keys throughout the review objects.
  assert.throws(() =>
    parseSessionReviewResponse({ ...review, trace_id: "x" }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      questions: [{ ...reviewQuestion, trace_id: "x" }],
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      questions: [
        {
          ...reviewQuestion,
          options: [{ id: "joule", label: "Joule", hint: "x" }],
        },
      ],
    }),
  );
});

test("getSessionReview uses the private authenticated review route", async () => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const restoreFetch = setFetch(async (input, init) => {
    calls.push({ input, init });
    return jsonResponse(review, 200);
  });

  try {
    const parsed = await getSessionReview(
      ROOM_ID,
      SESSION_ID,
      authenticatedClient(),
    );
    assert.equal(parsed.session_id, SESSION_ID);
    assert.equal(
      String(calls[0]?.input),
      `http://127.0.0.1:8000/rooms/${ROOM_ID}/sessions/${SESSION_ID}/review`,
    );
    assert.equal(calls[0]?.init?.method ?? "GET", "GET");
    const body = calls[0]?.init?.body;
    assert.equal(body === undefined || body === null, true);
  } finally {
    restoreFetch();
  }
});

test("session review rejects over-awarded and malformed payloads", () => {
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      total_earned_marks: 5,
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({ ...review, questions: [] }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      questions: [{ ...reviewQuestion, earned_marks: 9 }],
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse({
      ...review,
      questions: [{ ...reviewQuestion, question_type: "ESSAY" }],
    }),
  );
  assert.throws(() =>
    parseSessionReviewResponse("not-a-review"),
  );
  assert.throws(
    () => parseSessionReviewResponse(null),
    (error: unknown) => error instanceof MalformedResponseError,
  );
});
