import assert from "node:assert/strict";
import test from "node:test";

import {
  buildQuizPresentation,
  initialQuizSelectionState,
} from "../quiz/quizPresentation";
import {
  initialSessionState,
  sessionReducer,
  type SessionState,
} from "../session/sessionState";
import {
  makeOpenSnapshot,
  makeRevealSnapshot,
  NEXT_QUESTION_ID,
  QUESTION_ID,
  ROOM_ID,
  SESSION_ID,
} from "../session/sessionTestFixtures";
import { roomDrawingBinding } from "./roomBinding";

function established(snapshot = makeOpenSnapshot()): SessionState {
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

test("room drawing binds only the authenticated current authoritative question", () => {
  const state = established();
  const presentation = buildQuizPresentation(state, initialQuizSelectionState, false);
  const binding = roomDrawingBinding("learner-a", ROOM_ID, state, presentation, true);
  assert.deepEqual(binding, {
    scope: {
      userId: "learner-a",
      mode: "room",
      sessionId: SESSION_ID,
      questionId: QUESTION_ID,
    },
    phase: "answer-open",
    connected: true,
  });
  assert.equal(roomDrawingBinding(null, ROOM_ID, state, presentation, true).scope, null);
  assert.equal(roomDrawingBinding("learner-a", "other-room", state, presentation, true).scope, null);
  assert.equal(roomDrawingBinding("learner-a", ROOM_ID, state, null, true).scope, null);
});

test("submission lock, deadline, reveal and background make drawing noneditable", () => {
  const state = established();
  const open = buildQuizPresentation(state, initialQuizSelectionState, false);
  const expired = buildQuizPresentation(state, initialQuizSelectionState, true);
  assert.equal(roomDrawingBinding("learner-a", ROOM_ID, state, expired, true).phase, "read-only");
  assert.equal(roomDrawingBinding("learner-a", ROOM_ID, state, open, false).connected, false);

  const revealState = established(makeRevealSnapshot());
  const reveal = buildQuizPresentation(revealState, initialQuizSelectionState, false);
  const binding = roomDrawingBinding("learner-a", ROOM_ID, revealState, reveal, true);
  assert.equal(binding.phase, "read-only");
  assert.equal(binding.scope?.questionId, QUESTION_ID);
});

test("question advance changes scope while the room and user remain the same", () => {
  const first = established();
  const next = established(makeOpenSnapshot({ questionId: NEXT_QUESTION_ID, questionNumber: 2 }));
  const firstBinding = roomDrawingBinding(
    "learner-a",
    ROOM_ID,
    first,
    buildQuizPresentation(first, initialQuizSelectionState, false),
    true,
  );
  const nextBinding = roomDrawingBinding(
    "learner-a",
    ROOM_ID,
    next,
    buildQuizPresentation(next, initialQuizSelectionState, false),
    true,
  );
  assert.notEqual(firstBinding.scope?.questionId, nextBinding.scope?.questionId);
  assert.equal(firstBinding.scope?.sessionId, nextBinding.scope?.sessionId);
});
