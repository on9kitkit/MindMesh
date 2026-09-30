import assert from "node:assert/strict";
import test from "node:test";

import type { SoloAnswer, SoloAttempt, SoloSelfCheck } from "../../api/solo";
import { BackendApiError } from "../../api/errors";
import { SoloController, soloFailureMessage, visibleSoloState, type SoloApi } from "./soloController";

const ATTEMPT_ID = "11111111-1111-4111-8111-111111111111";
const REQUEST_ID = "22222222-2222-4222-8222-222222222222";
const FIRST_QUESTION_ID = "33333333-3333-4333-8333-333333333333";
const SECOND_QUESTION_ID = "44444444-4444-4444-8444-444444444444";
const SELECTION = { subject: "physics", topic: "forces", totalMarks: 5 } as const;

function attempt(overrides: Partial<SoloAttempt> = {}): SoloAttempt {
  return {
    id: ATTEMPT_ID,
    request_id: REQUEST_ID,
    status: "IN_PROGRESS",
    state_version: 3,
    subject: "physics",
    topic: "forces",
    total_marks: 5,
    current_question_position: 0,
    created_at: "2026-09-27T09:00:00Z",
    started_at: "2026-09-27T09:01:00Z",
    terminal_at: null,
    questions: [
      {
        id: FIRST_QUESTION_ID, position: 0, question_type: "WRITTEN",
        max_marks: 3, prompt: "Explain a force.", options: [], original_extract: null,
      },
      {
        id: SECOND_QUESTION_ID, position: 1, question_type: "MULTIPLE_CHOICE",
        max_marks: 2, prompt: "Choose a force.",
        options: [{ id: "a", label: "Gravity" }, { id: "b", label: "Friction" }],
        original_extract: null,
      },
    ],
    answers: [],
    ...overrides,
  };
}

function lockedAnswer(): SoloAnswer {
  return {
    question_id: FIRST_QUESTION_ID, selected_option_id: null,
    answer_text: "My explanation", accepted_at: "2026-09-27T09:02:00Z",
    grading_status: "SELF_CHECK_PENDING", mark_provenance: "SELF_ASSESSED",
    earned_marks: null, feedback: {},
  };
}

function check(): SoloSelfCheck {
  return {
    question_id: FIRST_QUESTION_ID, locked_answer: "My explanation",
    intended_answer: "Reference answer", max_marks: 3,
    criteria: [
      { id: "one", marks: 2, marking_point: "Principle", explanation: "State it" },
      { id: "two", marks: 1, marking_point: "Application", explanation: "Apply it" },
    ],
  };
}

function unexpected(): never {
  throw new Error("Unexpected solo API request");
}

function fakeApi(overrides: Partial<SoloApi> = {}): SoloApi {
  return {
    getActive: async () => null,
    getAttempt: async () => unexpected(),
    create: async () => unexpected(),
    start: async () => unexpected(),
    answer: async () => unexpected(),
    selfCheck: async () => unexpected(),
    finalizeCheck: async () => unexpected(),
    retryMarking: async () => unexpected(),
    abandon: async () => unexpected(),
    review: async () => unexpected(),
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

test("missing fixed home timezone points to the Home control", () => {
  const message = soloFailureMessage(new BackendApiError(
    "solo_home_zone_required", "Choose your home timezone.", 409,
  ));
  assert.match(message, /timezone on Home/);
  assert.doesNotMatch(message, /Account/);
});

test("owner switch hides saved quiz immediately and ignores the prior identity response", async () => {
  const pending = deferred<SoloAttempt | null>();
  let loads = 0;
  const controller = new SoloController(fakeApi({
    getActive: async () => {
      loads += 1;
      return pending.promise;
    },
  }));
  controller.setOwner("learner-a");
  const loading = controller.loadActive();
  assert.equal(loads, 1);
  controller.setOwner("learner-b");
  assert.equal(visibleSoloState("learner-b", controller.getState()).attempt, null);
  assert.equal(visibleSoloState("learner-a", controller.getState()).attempt, null);
  pending.resolve(attempt());
  await loading;
  assert.equal(controller.getState().ownerId, "learner-b");
  assert.equal(controller.getState().attempt, null);
  assert.equal(controller.getState().loaded, false);
});

test("failed initial resume keeps loading unresolved until a successful retry", async () => {
  let calls = 0;
  const controller = new SoloController(fakeApi({
    getActive: async () => {
      calls += 1;
      if (calls === 1) throw new Error("Offline");
      return attempt();
    },
  }));
  controller.setOwner("learner-a");
  await controller.loadActive();
  assert.equal(controller.getState().loaded, false);
  assert.equal(controller.getState().attempt, null);
  assert.ok(controller.getState().error);
  await controller.refresh();
  assert.equal(controller.getState().loaded, true);
  assert.equal(controller.getState().attempt?.id, ATTEMPT_ID);
});

test("uncertain create reuses one request ID after active lookup confirms no attempt", async () => {
  const requestIds: string[] = [];
  let creates = 0;
  const controller = new SoloController(fakeApi({
    create: async (input) => {
      requestIds.push(input.request_id);
      creates += 1;
      if (creates === 1) throw new Error("Acknowledgement lost");
      return attempt({ status: "PREPARING", started_at: null, questions: [] });
    },
  }), () => REQUEST_ID);
  controller.setOwner("learner-a");
  await controller.loadActive();
  await controller.create(SELECTION);
  assert.equal(controller.getState().needsReconcile, true);
  await controller.refresh();
  assert.equal(controller.getState().needsReconcile, false);
  assert.equal(controller.getState().attempt, null);
  await controller.create(SELECTION);
  assert.deepEqual(requestIds, [REQUEST_ID, REQUEST_ID]);
  assert.equal(controller.getState().attempt?.status, "PREPARING");
});

test("submitted answer locks before self-check; zero selected points finalizes without changing accepted answer", async () => {
  let saved = attempt();
  let answerCalls = 0;
  let checkReads = 0;
  let selected: readonly string[] | null = null;
  const controller = new SoloController(fakeApi({
    getActive: async () => saved,
    getAttempt: async () => saved,
    answer: async () => {
      answerCalls += 1;
      saved = attempt({ answers: [lockedAnswer()], state_version: 4 });
      return lockedAnswer();
    },
    selfCheck: async () => { checkReads += 1; return check(); },
    finalizeCheck: async (_attemptId, _questionId, ids) => {
      selected = ids;
      saved = attempt({
        answers: [{ ...lockedAnswer(), grading_status: "GRADED", earned_marks: 0 }],
        current_question_position: 1, state_version: 5,
      });
      return saved.answers[0];
    },
  }));
  controller.setOwner("learner-a");
  await controller.loadActive();
  await controller.loadSelfCheck();
  assert.equal(checkReads, 0);
  await controller.submitAnswer({ question_id: FIRST_QUESTION_ID, text: "My explanation" });
  assert.equal(controller.getState().attempt?.answers[0]?.grading_status, "SELF_CHECK_PENDING");
  await controller.submitAnswer({ question_id: FIRST_QUESTION_ID, text: "Changed answer" });
  assert.equal(answerCalls, 1);
  await controller.loadSelfCheck();
  assert.equal(controller.getState().selfCheck?.intended_answer, "Reference answer");
  await controller.finalizeSelfCheck([]);
  assert.deepEqual(selected, []);
  assert.equal(controller.getState().attempt?.answers[0]?.accepted_at, lockedAnswer().accepted_at);
  assert.equal(controller.getState().attempt?.answers[0]?.earned_marks, 0);
  assert.equal(controller.getState().selfCheck, null);
});

test("lost answer acknowledgement blocks replacement until authoritative refresh", async () => {
  let answers = 0;
  let saved = attempt();
  const controller = new SoloController(fakeApi({
    getActive: async () => saved,
    getAttempt: async () => saved,
    answer: async () => {
      answers += 1;
      saved = attempt({ answers: [lockedAnswer()] });
      throw new Error("Connection dropped after save");
    },
  }));
  controller.setOwner("learner-a");
  await controller.loadActive();
  await controller.submitAnswer({ question_id: FIRST_QUESTION_ID, text: "My explanation" });
  assert.equal(controller.getState().needsReconcile, true);
  await controller.submitAnswer({ question_id: FIRST_QUESTION_ID, text: "Replacement" });
  assert.equal(answers, 1);
  await controller.refresh();
  assert.equal(controller.getState().needsReconcile, false);
  assert.equal(controller.getState().attempt?.answers[0]?.answer_text, "My explanation");
  await controller.submitAnswer({ question_id: FIRST_QUESTION_ID, text: "Replacement" });
  assert.equal(answers, 1);
});
