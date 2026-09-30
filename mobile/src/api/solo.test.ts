import assert from "node:assert/strict";
import test from "node:test";

import type { StudyRoomApiClient } from "./client";
import { MalformedResponseError } from "./errors";
import {
  createSoloAttempt,
  getActiveSoloAttempt,
  getSoloSelfCheck,
  parseSoloAttempt,
  parseSoloReview,
  parseSoloSelfCheck,
  submitSoloAnswer,
} from "./solo";

const ATTEMPT_ID = "11111111-1111-4111-8111-111111111111";
const REQUEST_ID = "22222222-2222-4222-8222-222222222222";
const QUESTION_ID = "33333333-3333-4333-8333-333333333333";

function attempt(status: string = "IN_PROGRESS") {
  return {
    id: ATTEMPT_ID,
    request_id: REQUEST_ID,
    status,
    state_version: 3,
    subject: "physics",
    topic: "forces",
    total_marks: 5,
    current_question_position: 0,
    created_at: "2026-09-27T09:00:00Z",
    started_at: "2026-09-27T09:01:00Z",
    terminal_at: null,
    questions: [{
      id: QUESTION_ID,
      position: 0,
      question_type: "WRITTEN",
      max_marks: 5,
      prompt: "Explain the force.",
      options: [],
      original_extract: null,
    }],
    answers: [],
  };
}

function selfCheck() {
  return {
    question_id: QUESTION_ID,
    locked_answer: "My locked response",
    intended_answer: "Reference explanation",
    max_marks: 3,
    criteria: [
      { id: "principle", marks: 2, marking_point: "State the principle", explanation: "Principle" },
      { id: "application", marks: 1, marking_point: "Apply it", explanation: "Application" },
    ],
  };
}

test("strict progress parser drops no hidden solution field and requires canonical saved state", () => {
  assert.equal(parseSoloAttempt(attempt()).questions[0]?.prompt, "Explain the force.");
  assert.throws(() => parseSoloAttempt({ ...attempt(), grading_rubric: { secret: true } }), MalformedResponseError);
  assert.throws(() => parseSoloAttempt({ ...attempt(), questions: [{ ...attempt().questions[0], correct_option_id: "secret" }] }), MalformedResponseError);
  assert.throws(() => parseSoloAttempt({ ...attempt(), topic: "algebra" }), MalformedResponseError);
  assert.throws(() => parseSoloAttempt({ ...attempt(), status: "FINISHED", terminal_at: "not-a-time" }), MalformedResponseError);
});

test("self-check parses only a bounded saved rubric; review requires terminal finish", () => {
  assert.equal(parseSoloSelfCheck(selfCheck()).criteria.reduce((sum, criterion) => sum + criterion.marks, 0), 3);
  assert.throws(() => parseSoloSelfCheck({ ...selfCheck(), criteria: [selfCheck().criteria[0]] }), MalformedResponseError);
  assert.throws(() => parseSoloSelfCheck({ ...selfCheck(), grading_rubric: { secret: true } }), MalformedResponseError);
  assert.throws(() => parseSoloReview({ attempt: attempt(), questions: [] }), MalformedResponseError);
});

test("typed solo client uses authenticated shared request transport and sends no drawing or owner data", async () => {
  const calls: Array<{ path: string; options: unknown }> = [];
  const client: StudyRoomApiClient = {
    baseUrl: "https://example.invalid",
    async requestJson(path, options) {
      calls.push({ path, options });
      if (path.endsWith("/active")) return null;
      if (path.endsWith("/self-check")) return selfCheck();
      if (path.endsWith("/answers")) return {
        question_id: QUESTION_ID, selected_option_id: null, answer_text: "My answer",
        accepted_at: "2026-09-27T09:02:00Z", grading_status: "PENDING",
        mark_provenance: "AI_RUBRIC", earned_marks: null, feedback: {},
      };
      return { ...attempt("PREPARING"), current_question_position: 0, started_at: null, questions: [] };
    },
  };
  assert.equal(await getActiveSoloAttempt(client), null);
  const created = await createSoloAttempt({
    request_id: REQUEST_ID, subject: "physics", topic: "forces", total_marks: 5,
  }, client);
  assert.equal(created.status, "PREPARING");
  assert.equal(calls[1]?.path, "/me/solo-attempts");
  assert.deepEqual(calls[1]?.options, {
    method: "POST",
    body: { request_id: REQUEST_ID, subject: "physics", topic: "forces", total_marks: 5 },
    timeoutMs: 15_000,
  });
  const response = await submitSoloAnswer(ATTEMPT_ID, { question_id: QUESTION_ID, text: "My answer" }, client);
  assert.equal(response.grading_status, "PENDING");
  assert.deepEqual(calls[2]?.options, { method: "POST", body: { question_id: QUESTION_ID, text: "My answer" } });
  assert.equal((await getSoloSelfCheck(ATTEMPT_ID, QUESTION_ID, client)).locked_answer, "My locked response");
});
