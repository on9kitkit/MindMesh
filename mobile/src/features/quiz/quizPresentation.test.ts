import assert from "node:assert/strict";
import test from "node:test";

import type { ZonedIsoTimestamp } from "../../realtime/protocol";
import {
  initialSessionState,
  sessionReducer,
  type SessionState,
} from "../session/sessionState";
import {
  makeAdaptiveRoomState,
  makeFinishedSnapshot,
  makeGradingSnapshot,
  makeOpenSnapshot,
  makeRevealSnapshot,
  NEXT_QUESTION_ID,
  QUESTION_ID,
  ROOM_ID,
  SESSION_ID,
} from "../session/sessionTestFixtures";
import {
  buildQuizPresentation,
  getQuizCountdownInput,
  getQuizOptionAppearance,
  initialQuizSelectionState,
  quizSelectionReducer,
} from "./quizPresentation";

function establishedState(snapshot = makeOpenSnapshot()): SessionState {
  let state = sessionReducer(initialSessionState, {
    type: "ROOM_SELECTED",
    roomId: ROOM_ID,
    generation: 1,
  });
  state = sessionReducer(state, {
    type: "CONNECTED_RECEIVED",
    generation: 1,
    serverTime: snapshot.server_time,
  });
  return sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: 1,
    snapshot,
    source: "new-socket",
  });
}

test("open presentation uses only authoritative question content", () => {
  const state = establishedState();
  const presentation = buildQuizPresentation(
    state,
    initialQuizSelectionState,
    false,
  );
  assert.ok(presentation?.status === "question-open");
  assert.equal(presentation.prompt, "What is the SI unit of force?");
  assert.equal(presentation.questionNumber, 1);
  assert.equal(presentation.totalQuestions, 5);
  assert.equal(Object.hasOwn(presentation, "correctOptionId"), false);
  assert.equal(Object.hasOwn(state.snapshot?.question ?? {}, "correct_option_id"), false);
});

test("unsubmitted selection remains scoped local presentation state", () => {
  const state = establishedState();
  const selection = quizSelectionReducer(initialQuizSelectionState, {
    type: "OPTION_SELECTED",
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: "joule",
  });
  const presentation = buildQuizPresentation(state, selection, false);
  assert.ok(presentation?.status === "question-open");
  assert.equal(presentation.selectedOptionId, "joule");
  assert.equal(presentation.canSubmit, true);
  assert.equal(state.snapshot?.viewer_submission, null);
});

test("pending and acknowledged answers expose no correctness or points", () => {
  let state = establishedState();
  state = sessionReducer(state, {
    type: "ANSWER_COMMAND_STARTED",
    generation: 1,
    sessionId: SESSION_ID,
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: "newton",
    answerText: null,
  });
  let presentation = buildQuizPresentation(
    state,
    initialQuizSelectionState,
    false,
  );
  assert.ok(presentation?.status === "question-open");
  assert.equal(presentation.submissionStatus, "submitting");
  assert.equal(Object.hasOwn(presentation, "isCorrect"), false);
  assert.equal(Object.hasOwn(presentation, "points"), false);

  state = sessionReducer(state, {
    type: "ANSWER_ACCEPTED_RECEIVED",
    generation: 1,
    acknowledgement: {
      session_id: SESSION_ID,
      state_version: 1,
      session_question_id: QUESTION_ID,
      selected_option_id: "newton",
      answer_text: null,
      grading_status: "GRADED",
      accepted_at: "2030-01-01T12:00:05Z" as ZonedIsoTimestamp,
    },
  });
  presentation = buildQuizPresentation(
    state,
    initialQuizSelectionState,
    false,
  );
  assert.ok(presentation?.status === "question-open");
  assert.equal(presentation.submissionStatus, "submitted");
  assert.equal(Object.hasOwn(presentation, "isCorrect"), false);
  assert.equal(Object.hasOwn(presentation, "points"), false);
});

test("accepted viewer submission restores selection after reconnect", () => {
  const state = establishedState(
    makeOpenSnapshot({ selectedOptionId: "newton" }),
  );
  const presentation = buildQuizPresentation(
    state,
    initialQuizSelectionState,
    false,
  );
  assert.ok(presentation?.status === "question-open");
  assert.equal(presentation.selectedOptionId, "newton");
  assert.equal(presentation.submissionStatus, "submitted");
  assert.equal(presentation.canInteract, false);
});

test("a new authoritative question cannot reuse an old local selection", () => {
  let selection = quizSelectionReducer(initialQuizSelectionState, {
    type: "OPTION_SELECTED",
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: "newton",
  });
  const nextState = establishedState(
    makeOpenSnapshot({
      stateVersion: 3,
      questionId: NEXT_QUESTION_ID,
      questionNumber: 2,
    }),
  );
  const beforeEffect = buildQuizPresentation(nextState, selection, false);
  assert.ok(beforeEffect?.status === "question-open");
  assert.equal(beforeEffect.selectedOptionId, null);

  selection = quizSelectionReducer(selection, {
    type: "QUESTION_CHANGED",
    sessionQuestionId: NEXT_QUESTION_ID,
  });
  assert.equal(selection.selectedOptionId, null);
});

test("countdown zero disables submission without changing the question", () => {
  const state = establishedState();
  const selection = quizSelectionReducer(initialQuizSelectionState, {
    type: "OPTION_SELECTED",
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: "newton",
  });
  const presentation = buildQuizPresentation(state, selection, true);
  assert.ok(presentation?.status === "question-open");
  assert.equal(presentation.canSubmit, false);
  assert.equal(presentation.sessionQuestionId, QUESTION_ID);
  assert.equal(state.snapshot?.status, "QUESTION_OPEN");
});

test("an expired local reveal countdown cannot override authoritative FINISHED", () => {
  let state = establishedState(makeRevealSnapshot({ stateVersion: 8 }));
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: 1,
    snapshot: makeFinishedSnapshot({ stateVersion: 10 }),
    source: "unsolicited",
  });

  assert.equal(state.phase, "finished");
  assert.equal(
    buildQuizPresentation(state, initialQuizSelectionState, true),
    null,
  );

  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: 1,
    snapshot: makeRevealSnapshot({ stateVersion: 9 }),
    source: "unsolicited",
  });
  assert.equal(state.phase, "finished");
  assert.equal(
    buildQuizPresentation(state, initialQuizSelectionState, true),
    null,
  );
});

test("reveal styling uses only correct option and viewer-private result", () => {
  const state = establishedState(makeRevealSnapshot({ selectedOptionId: "joule" }));
  const presentation = buildQuizPresentation(
    state,
    initialQuizSelectionState,
    false,
  );
  assert.ok(presentation?.status === "question-reveal");
  assert.equal(presentation.viewerSubmission?.is_correct, false);
  assert.equal(presentation.viewerSubmission?.points, 0);
  assert.equal(getQuizOptionAppearance(presentation, "newton"), "correct");
  assert.equal(
    getQuizOptionAppearance(presentation, "joule"),
    "incorrect-selected",
  );
  assert.equal(
    Object.hasOwn(presentation, "otherParticipantSubmission"),
    false,
  );
});

test("open and reveal countdown inputs use snapshot server time", () => {
  const openInput = getQuizCountdownInput(establishedState());
  assert.equal(openInput?.deadline, "2030-01-01T12:00:20Z");
  const revealInput = getQuizCountdownInput(
    establishedState(makeRevealSnapshot()),
  );
  assert.equal(revealInput?.deadline, "2030-01-01T12:00:23Z");
});

test("typed questions expose text drafts instead of option selection", () => {
  const state = establishedState(
    makeOpenSnapshot({ questionType: "WRITTEN", maxMarks: 4 }),
  );
  const empty = buildQuizPresentation(state, initialQuizSelectionState, false);
  assert.ok(empty?.status === "question-open");
  assert.equal(empty.questionType, "WRITTEN");
  assert.equal(empty.maxMarks, 4);
  assert.deepEqual(empty.options, []);
  assert.equal(empty.selectedOptionId, null);
  assert.equal(empty.canSubmit, false);

  const selection = quizSelectionReducer(initialQuizSelectionState, {
    type: "TEXT_CHANGED",
    sessionQuestionId: QUESTION_ID,
    text: "Heat flows.",
  });
  const ready = buildQuizPresentation(state, selection, false);
  assert.ok(ready?.status === "question-open");
  assert.equal(ready.draftText, "Heat flows.");
  assert.equal(ready.canSubmit, true);
  assert.equal(ready.submissionStatus, "draft");

  const blank = quizSelectionReducer(initialQuizSelectionState, {
    type: "TEXT_CHANGED",
    sessionQuestionId: QUESTION_ID,
    text: "   ",
  });
  const blocked = buildQuizPresentation(state, blank, false);
  assert.ok(blocked?.status === "question-open");
  assert.equal(blocked.canSubmit, false);
});

test("text drafts never leak into choice questions", () => {
  const state = establishedState();
  const selection = quizSelectionReducer(initialQuizSelectionState, {
    type: "TEXT_CHANGED",
    sessionQuestionId: QUESTION_ID,
    text: "Newton",
  });
  const presentation = buildQuizPresentation(state, selection, false);
  assert.ok(presentation?.status === "question-open");
  assert.equal(presentation.draftText, "");
  assert.equal(presentation.canSubmit, false);
});

test("grading presentation shows the viewer's own response and retry control", () => {
  const hostState = establishedState(
    makeGradingSnapshot({
      selectedOptionId: null,
      answerText: "Heat flows.",
      gradingStatus: "UNAVAILABLE",
      gradingRetryNeeded: true,
    }),
  );
  const presentation = buildQuizPresentation(
    hostState,
    initialQuizSelectionState,
    false,
  );
  assert.ok(presentation?.status === "question-grading");
  assert.equal(presentation.ownAnswerText, "Heat flows.");
  assert.equal(presentation.ownSelectedOptionId, null);
  assert.equal(presentation.ownGradingStatus, "UNAVAILABLE");
  assert.equal(presentation.gradingRetryNeeded, true);
  assert.equal(presentation.canRetryGrading, true);
  assert.equal(
    getQuizOptionAppearance(presentation, "newton"),
    "default",
  );
});

test("grading retry needs the aggregate signal and the host role", () => {
  const hostWithoutSignal = buildQuizPresentation(
    establishedState(makeGradingSnapshot({ gradingStatus: "UNAVAILABLE" })),
    initialQuizSelectionState,
    false,
  );
  assert.ok(hostWithoutSignal?.status === "question-grading");
  assert.equal(hostWithoutSignal.gradingRetryNeeded, false);
  assert.equal(hostWithoutSignal.canRetryGrading, false);

  const memberState = establishedState(
    makeGradingSnapshot({
      roomState: makeAdaptiveRoomState({ viewerRole: "member" }),
      selectedOptionId: null,
      answerText: "Heat flows.",
      gradingStatus: "PENDING",
      gradingRetryNeeded: true,
    }),
  );
  const member = buildQuizPresentation(
    memberState,
    initialQuizSelectionState,
    false,
  );
  assert.ok(member?.status === "question-grading");
  assert.equal(member.gradingRetryNeeded, true);
  assert.equal(member.canRetryGrading, false);
});

test("adaptive reveal carries raw marks and worked explanation", () => {
  const state = establishedState(
    makeRevealSnapshot({
      questionType: "WRITTEN",
      maxMarks: 4,
      selectedOptionId: null,
      answerText: "Particles vibrate.",
      earnedMarks: 2,
      feedback: {
        summary: "Mention energy transfer.",
        awarded: [{ id: "c1", marks: 2, explanation: "Named vibration." }],
        missing: [{ id: "c2", marks: 2, explanation: "Link to energy." }],
        awarded_count: 1,
        total_criteria: 2,
      },
      awardedCriterionIds: ["c1"],
    }),
  );
  const presentation = buildQuizPresentation(
    state,
    initialQuizSelectionState,
    false,
  );
  assert.ok(presentation?.status === "question-reveal");
  assert.equal(presentation.correctOptionId, null);
  assert.equal(
    presentation.workedExplanation,
    "Force is measured in newtons.",
  );
  assert.equal(presentation.viewerSubmission?.earned_marks, 2);
  assert.equal(presentation.viewerSubmission?.max_marks, 4);
  assert.deepEqual(presentation.viewerSubmission?.awarded_criterion_ids, [
    "c1",
  ]);
});
