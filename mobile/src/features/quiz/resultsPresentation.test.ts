import assert from "node:assert/strict";
import test from "node:test";

import {
  initialSessionState,
  sessionReducer,
  type SessionState,
} from "../session/sessionState";
import {
  makeFinishedSnapshot,
  MEMBER_ID,
  NEW_SESSION_ID,
  ROOM_ID,
  SESSION_ID,
} from "../session/sessionTestFixtures";
import {
  buildResultsPresentation,
  canDismissFinishedSession,
  formatCorrectAnswersLabel,
  formatLeaderboardMarks,
} from "./resultsPresentation";

function finishedState(): SessionState {
  const snapshot = makeFinishedSnapshot({
    leaderboard: [
      {
        user_id: MEMBER_ID,
        display_name: "Second User",
        total_points: 300,
        correct_answers: 3,
        rank: 2,
        earned_marks: 3,
        total_available_marks: 5,
      },
      {
        user_id: ROOM_ID,
        display_name: "Room Owner",
        total_points: 500,
        correct_answers: 5,
        rank: 1,
        earned_marks: 5,
        total_available_marks: 5,
      },
    ],
  });
  let state = sessionReducer(initialSessionState, {
    type: "ROOM_SELECTED",
    roomId: ROOM_ID,
    generation: 1,
  });
  return sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: 1,
    snapshot,
    source: "new-socket",
  });
}

test("results preserve authoritative backend leaderboard order", () => {
  const presentation = buildResultsPresentation(finishedState(), MEMBER_ID);
  assert.ok(presentation !== null);
  assert.deepEqual(
    presentation.leaderboard.map((row) => row.entry.user_id),
    [MEMBER_ID, ROOM_ID],
  );
  assert.deepEqual(
    presentation.leaderboard.map((row) => row.placement),
    [2, 1],
  );
});

test("current user highlighting uses authenticated UUID identity", () => {
  const presentation = buildResultsPresentation(finishedState(), MEMBER_ID);
  assert.ok(presentation !== null);
  assert.deepEqual(
    presentation.leaderboard.map((row) => row.isCurrentUser),
    [true, false],
  );
});

test("finished dismissal changes presentation only and retains snapshot", () => {
  const state = finishedState();
  const snapshot = state.snapshot;
  assert.equal(canDismissFinishedSession(state), true);
  const dismissed = sessionReducer(state, {
    type: "DISMISS_FINISHED_SESSION",
  });
  assert.equal(dismissed.phase, "waiting");
  assert.equal(dismissed.snapshot, snapshot);
  assert.equal(dismissed.dismissedFinishedSessionId, SESSION_ID);
  assert.equal(canDismissFinishedSession(dismissed), false);
});

test("a new session ID clears finished dismissal", () => {
  let state = sessionReducer(finishedState(), {
    type: "DISMISS_FINISHED_SESSION",
  });
  const nextSnapshot = makeFinishedSnapshot({
    sessionId: NEW_SESSION_ID,
    stateVersion: 12,
  });
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: 1,
    snapshot: nextSnapshot,
    source: "requested",
  });
  assert.equal(state.dismissedFinishedSessionId, null);
  assert.equal(state.snapshot?.session_id, NEW_SESSION_ID);
});

test("results are unavailable without a matching FINISHED snapshot", () => {
  assert.equal(
    buildResultsPresentation(initialSessionState, MEMBER_ID),
    null,
  );
});

test("results expose raw earned marks without local scoring", () => {
  const presentation = buildResultsPresentation(finishedState(), MEMBER_ID);
  assert.ok(presentation !== null);
  assert.equal(presentation.quizMode, "LEGACY_PHYSICS");
  assert.equal(presentation.totalEarnedMarks, 3);
  assert.equal(presentation.totalAvailableMarks, 5);
  assert.equal(
    formatLeaderboardMarks({
      earned_marks: 3,
      total_available_marks: 5,
    }),
    "3/5 marks",
  );
});

test("adaptive rows name full-mark answers while legacy keeps N correct", () => {
  assert.equal(formatCorrectAnswersLabel(0, "ADAPTIVE"), "0 full-mark answers");
  assert.equal(formatCorrectAnswersLabel(1, "ADAPTIVE"), "1 full-mark answer");
  assert.equal(formatCorrectAnswersLabel(3, "ADAPTIVE"), "3 full-mark answers");
  assert.equal(formatCorrectAnswersLabel(3, "LEGACY_PHYSICS"), "3 correct");
  assert.equal(formatCorrectAnswersLabel(1, "LEGACY_PHYSICS"), "1 correct");
});
