import assert from "node:assert/strict";
import test from "node:test";

import type { SoloAttempt } from "../../api/solo";
import { createDrawingLifecycle, reconcileDrawingLifecycle } from "../drawing/lifecycle";
import { soloDrawingBinding } from "./soloDrawingBinding";

const ATTEMPT_ID = "11111111-1111-4111-8111-111111111111";
const QUESTION_ID = "33333333-3333-4333-8333-333333333333";

function attempt(overrides: Partial<SoloAttempt> = {}): SoloAttempt {
  return {
    id: ATTEMPT_ID,
    request_id: "22222222-2222-4222-8222-222222222222",
    status: "IN_PROGRESS",
    state_version: 1,
    subject: "physics",
    topic: "forces",
    total_marks: 5,
    current_question_position: 0,
    created_at: "2026-09-27T09:00:00Z",
    started_at: "2026-09-27T09:01:00Z",
    terminal_at: null,
    questions: [{
      id: QUESTION_ID, position: 0, question_type: "WRITTEN", max_marks: 5,
      prompt: "Explain", options: [], original_extract: null,
    }],
    answers: [],
    ...overrides,
  };
}

test("solo drawing is scoped to one owner and question; a saved answer makes it read only", () => {
  const open = soloDrawingBinding("learner-a", attempt(), true, false);
  assert.deepEqual(open.scope, {
    userId: "learner-a", mode: "solo", sessionId: ATTEMPT_ID, questionId: QUESTION_ID,
  });
  assert.equal(open.phase, "answer-open");
  assert.equal(open.connected, true);

  const answered = attempt({ answers: [{
    question_id: QUESTION_ID, selected_option_id: null, answer_text: "Saved answer",
    accepted_at: "2026-09-27T09:02:00Z", grading_status: "PENDING",
    mark_provenance: "AI_RUBRIC", earned_marks: null, feedback: {},
  }] });
  const locked = soloDrawingBinding("learner-a", answered, true, false);
  assert.equal(locked.phase, "read-only");
  assert.deepEqual(locked.scope, open.scope);

  assert.equal(soloDrawingBinding("learner-a", attempt(), false, false).connected, false);
  assert.equal(soloDrawingBinding("learner-a", attempt(), true, true).connected, false);
  assert.equal(soloDrawingBinding("learner-b", attempt(), true, false).scope?.userId, "learner-b");
  assert.equal(soloDrawingBinding(null, attempt(), true, false).scope, null);
  assert.equal(soloDrawingBinding("learner-a", attempt({ status: "FINISHED" }), true, false).scope, null);
});

test("leaving a solo question clears local drawing scope and invalidates stale callbacks", () => {
  const open = soloDrawingBinding("learner-a", attempt(), true, false);
  const working = reconcileDrawingLifecycle(
    createDrawingLifecycle(), open.scope, open.phase, open.connected,
  );
  assert.equal(working.visible, true);
  const closed = soloDrawingBinding("learner-a", attempt({ status: "AWAITING_MARKING" }), true, false);
  const cleared = reconcileDrawingLifecycle(
    working, closed.scope, closed.phase, closed.connected,
  );
  assert.equal(cleared.scope, null);
  assert.equal(cleared.visible, false);
  assert.ok(cleared.epoch > working.epoch);
  assert.equal(cleared.document.strokes.length, 0);
});
