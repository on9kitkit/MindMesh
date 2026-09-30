import assert from "node:assert/strict";
import test from "node:test";

import {
  ProtocolIncompatibilityError,
  RealtimeNetworkError,
} from "../../realtime/errors";
import { parseServerEvent, type StateSnapshotPayload } from "../../realtime/protocol";
import {
  initialSessionState,
  sessionReducer,
  socketIsEstablished,
  type SessionState,
  type SnapshotSource,
} from "./sessionState";
import {
  makeAdaptiveRoomState,
  makeFinishedSnapshot,
  makeGradingSnapshot,
  makeLobbySnapshot,
  makeOpenSnapshot,
  makeRevealSnapshot,
  makeRoomState,
  NEW_SESSION_ID,
  NEXT_QUESTION_ID,
  QUESTION_ID,
  ROOM_ID,
  serverEventFrame,
  SESSION_ID,
} from "./sessionTestFixtures";

const GENERATION = 1;

function selectedConnectingState(): SessionState {
  return sessionReducer(initialSessionState, {
    type: "ROOM_SELECTED",
    roomId: ROOM_ID,
    generation: GENERATION,
  });
}

function authenticatedState(): SessionState {
  const lobby = makeLobbySnapshot();
  return sessionReducer(selectedConnectingState(), {
    type: "CONNECTED_RECEIVED",
    generation: GENERATION,
    serverTime: lobby.server_time,
  });
}

function withSnapshot(
  snapshot: StateSnapshotPayload,
  source: SnapshotSource = "new-socket",
): SessionState {
  return sessionReducer(authenticatedState(), {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot,
    source,
  });
}

function answerAcknowledgement(
  selectedOptionId: string | null = "newton",
  sessionQuestionId = QUESTION_ID,
  answerText: string | null = null,
) {
  const parsed = parseServerEvent(
    serverEventFrame("ANSWER_ACCEPTED", {
      session_id: SESSION_ID,
      state_version: 1,
      session_question_id: sessionQuestionId,
      selected_option_id: selectedOptionId,
      answer_text: answerText,
      grading_status: "GRADED",
      accepted_at: "2030-01-01T12:00:05Z",
    }),
  );
  if (parsed.type !== "ANSWER_ACCEPTED") {
    throw new Error("Expected an answer acknowledgement fixture.");
  }
  return parsed.payload;
}

test("initial state is explicitly idle", () => {
  assert.equal(initialSessionState.phase, "idle");
  assert.equal(initialSessionState.roomId, null);
  assert.equal(initialSessionState.snapshot, null);
});

test("active-room recovery has explicit recovering and selected states", () => {
  const recovering = sessionReducer(initialSessionState, {
    type: "RECOVERY_STARTED",
    generation: 1,
  });
  assert.equal(recovering.phase, "recovering-room");
  const selected = sessionReducer(recovering, {
    type: "ROOM_SELECTED",
    roomId: ROOM_ID,
    generation: 1,
  });
  assert.equal(selected.phase, "connecting");
  assert.equal(selected.roomId, ROOM_ID);
});

test("ROOM_STATE completely replaces current lobby presence state", () => {
  const initialRoom = makeRoomState({ memberName: "Old Name" });
  let state = withSnapshot(makeLobbySnapshot(initialRoom));
  const replacement = makeRoomState({ includeMember: false });
  const previousSnapshot = state.snapshot;
  state = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: replacement,
  });
  assert.equal(state.roomState, replacement);
  assert.equal(state.roomState.participants.length, 1);
  assert.equal(state.snapshot, previousSnapshot);
});

test("first snapshots enter waiting, open, reveal, and finished phases", () => {
  const cases: Array<[StateSnapshotPayload, SessionState["phase"]]> = [
    [makeLobbySnapshot(), "waiting"],
    [makeOpenSnapshot(), "question-open"],
    [makeRevealSnapshot(), "reveal"],
    [makeFinishedSnapshot(), "finished"],
  ];
  for (const [snapshot, expectedPhase] of cases) {
    assert.equal(withSnapshot(snapshot).phase, expectedPhase);
  }
});

test("a new session ID starts a fresh version sequence", () => {
  let state = withSnapshot(makeFinishedSnapshot({ stateVersion: 10 }));
  const next = makeOpenSnapshot({
    sessionId: NEW_SESSION_ID,
    stateVersion: 1,
  });
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: next,
    source: "unsolicited",
  });
  assert.equal(state.snapshot, next);
  assert.equal(state.phase, "question-open");
});

test("a higher same-session state version applies", () => {
  let state = withSnapshot(makeOpenSnapshot({ stateVersion: 1 }));
  const reveal = makeRevealSnapshot({ stateVersion: 2 });
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: reveal,
    source: "unsolicited",
  });
  assert.equal(state.snapshot, reveal);
  assert.equal(state.phase, "reveal");
});

test("a lower same-session state version is ignored", () => {
  const current = makeRevealSnapshot({ stateVersion: 3 });
  let state = withSnapshot(current);
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: makeOpenSnapshot({ stateVersion: 2 }),
    source: "requested",
  });
  assert.equal(state.snapshot, current);
  assert.equal(state.phase, "reveal");
});

test("a duplicate transition hint is ignored", () => {
  const state = withSnapshot(makeOpenSnapshot({ stateVersion: 2 }));
  const next = sessionReducer(state, {
    type: "TRANSITION_HINT_RECEIVED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    stateVersion: 2,
  });
  assert.equal(next, state);
});

test("a newer transition hint requests one authoritative snapshot", () => {
  let state = withSnapshot(makeOpenSnapshot({ stateVersion: 1 }));
  state = sessionReducer(state, {
    type: "TRANSITION_HINT_RECEIVED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    stateVersion: 2,
  });
  assert.equal(state.pendingSnapshotRequest?.reason, "transition");
  const pending = state.pendingSnapshotRequest;
  state = sessionReducer(state, {
    type: "TRANSITION_HINT_RECEIVED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    stateVersion: 3,
  });
  assert.equal(state.pendingSnapshotRequest, pending);
  assert.equal(state.expectedSnapshot?.stateVersion, 3);
});

test("an equal-version explicitly requested snapshot can replace viewer state", () => {
  let state = withSnapshot(makeOpenSnapshot({ stateVersion: 1 }));
  state = sessionReducer(state, {
    type: "SNAPSHOT_REQUEST_STARTED",
    generation: GENERATION,
    reason: "manual",
  });
  const replacement = makeOpenSnapshot({
    stateVersion: 1,
    selectedOptionId: "newton",
  });
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: replacement,
    source: "requested",
  });
  assert.equal(state.snapshot, replacement);
  assert.equal(state.phase, "submitted");
});

test("an equal-version snapshot on a new socket generation applies", () => {
  let state = withSnapshot(makeOpenSnapshot({ stateVersion: 1 }));
  state = sessionReducer(state, {
    type: "SOCKET_INVALIDATED",
    generation: 2,
  });
  state = sessionReducer(state, {
    type: "CONNECTED_RECEIVED",
    generation: 2,
    serverTime: makeOpenSnapshot().server_time,
  });
  const replacement = makeOpenSnapshot({
    stateVersion: 1,
    selectedOptionId: "newton",
  });
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: 2,
    snapshot: replacement,
    source: "new-socket",
  });
  assert.equal(state.snapshot, replacement);
  assert.equal(state.phase, "submitted");
});

test("an unsolicited stale snapshot cannot roll state back", () => {
  const current = makeFinishedSnapshot({ stateVersion: 10 });
  let state = withSnapshot(current);
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: makeRevealSnapshot({ stateVersion: 9 }),
    source: "unsolicited",
  });
  assert.equal(state.snapshot, current);
});

test("a legitimate room recovery can replace an old session with no session", () => {
  let state = withSnapshot(makeFinishedSnapshot());
  const lobby = makeLobbySnapshot();
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: lobby,
    source: "room-recovery",
  });
  assert.equal(state.snapshot, lobby);
  assert.equal(state.phase, "waiting");
});

test("an unsolicited no-session snapshot cannot erase an active session", () => {
  const current = makeOpenSnapshot();
  let state = withSnapshot(current);
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: makeLobbySnapshot(),
    source: "unsolicited",
  });
  assert.equal(state.snapshot, current);
});

test("ANSWER_ACCEPTED updates only the targeted acknowledgement", () => {
  let state = withSnapshot(makeOpenSnapshot());
  state = sessionReducer(state, {
    type: "ANSWER_COMMAND_STARTED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: "newton",
    answerText: null,
  });
  state = sessionReducer(state, {
    type: "ANSWER_ACCEPTED_RECEIVED",
    generation: GENERATION,
    acknowledgement: answerAcknowledgement(),
  });
  assert.equal(state.pendingCommand, null);
  assert.equal(state.acknowledgedAnswer?.selectedOptionId, "newton");
  assert.equal(state.phase, "submitted");
  assert.equal(state.snapshot?.status, "QUESTION_OPEN");
});

test("ANSWER_ACCEPTED acknowledgement exposes no correctness or points", () => {
  let state = withSnapshot(makeOpenSnapshot());
  state = sessionReducer(state, {
    type: "ANSWER_COMMAND_STARTED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: "newton",
    answerText: null,
  });
  state = sessionReducer(state, {
    type: "ANSWER_ACCEPTED_RECEIVED",
    generation: GENERATION,
    acknowledgement: answerAcknowledgement(),
  });
  assert.equal(Object.hasOwn(state.acknowledgedAnswer ?? {}, "isCorrect"), false);
  assert.equal(Object.hasOwn(state.acknowledgedAnswer ?? {}, "points"), false);
});

test("a matching acknowledgement coalesces one snapshot request", () => {
  let state = withSnapshot(makeOpenSnapshot());
  state = sessionReducer(state, {
    type: "ANSWER_COMMAND_STARTED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: "newton",
    answerText: null,
  });
  state = sessionReducer(state, {
    type: "ANSWER_ACCEPTED_RECEIVED",
    generation: GENERATION,
    acknowledgement: answerAcknowledgement(),
  });
  const request = state.pendingSnapshotRequest;
  state = sessionReducer(state, {
    type: "ANSWER_ACCEPTED_RECEIVED",
    generation: GENERATION,
    acknowledgement: answerAcknowledgement(),
  });
  assert.equal(request?.reason, "answer");
  assert.equal(state.pendingSnapshotRequest, request);
});

test("a mismatched acknowledgement records uncertainty and requests repair", () => {
  let state = withSnapshot(makeOpenSnapshot());
  state = sessionReducer(state, {
    type: "ANSWER_COMMAND_STARTED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: "newton",
    answerText: null,
  });
  state = sessionReducer(state, {
    type: "ANSWER_ACCEPTED_RECEIVED",
    generation: GENERATION,
    acknowledgement: answerAcknowledgement("joule"),
  });
  assert.equal(state.acknowledgedAnswer, null);
  assert.equal(state.pendingSnapshotRequest?.reason, "answer");
  assert.equal(state.lastError?.kind, "malformed-server-message");
});

test("a newer question snapshot clears the previous answer acknowledgement", () => {
  let state = withSnapshot(makeOpenSnapshot());
  state = sessionReducer(state, {
    type: "ANSWER_COMMAND_STARTED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: "newton",
    answerText: null,
  });
  state = sessionReducer(state, {
    type: "ANSWER_ACCEPTED_RECEIVED",
    generation: GENERATION,
    acknowledgement: answerAcknowledgement(),
  });
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: makeOpenSnapshot({
      stateVersion: 3,
      questionId: NEXT_QUESTION_ID,
      questionNumber: 2,
    }),
    source: "unsolicited",
  });
  assert.equal(state.acknowledgedAnswer, null);
  assert.equal(state.phase, "question-open");
});

test("finished dismissal returns presentation to waiting without changing authority", () => {
  const snapshot = makeFinishedSnapshot();
  let state = withSnapshot(snapshot);
  state = sessionReducer(state, { type: "DISMISS_FINISHED_SESSION" });
  assert.equal(state.dismissedFinishedSessionId, SESSION_ID);
  assert.equal(state.snapshot, snapshot);
  assert.equal(state.phase, "waiting");
});

test("a new session clears the previous finished dismissal", () => {
  let state = withSnapshot(makeFinishedSnapshot());
  state = sessionReducer(state, { type: "DISMISS_FINISHED_SESSION" });
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: makeOpenSnapshot({ sessionId: NEW_SESSION_ID }),
    source: "unsolicited",
  });
  assert.equal(state.dismissedFinishedSessionId, null);
});

test("reconnect retains the last authoritative snapshot", () => {
  const snapshot = makeOpenSnapshot();
  let state = withSnapshot(snapshot);
  state = sessionReducer(state, {
    type: "CONNECTION_LOST",
    generation: GENERATION,
    attempt: 1,
    error: new RealtimeNetworkError(),
  });
  assert.equal(state.phase, "reconnecting");
  assert.equal(state.snapshot, snapshot);
  assert.equal(state.reconnectAttempt, 1);
});

test("fatal error disables commands without inventing server state", () => {
  let state = withSnapshot(makeOpenSnapshot());
  state = sessionReducer(state, {
    type: "FATAL_FAILURE",
    generation: GENERATION,
    error: new ProtocolIncompatibilityError(),
    clearRoom: false,
  });
  assert.equal(state.phase, "fatal-error");
  assert.equal(socketIsEstablished(state), false);
  assert.equal(state.pendingCommand, null);
  assert.equal(state.snapshot?.session_id, SESSION_ID);
});

test("grading snapshots enter an explicit grading phase", () => {
  const grading = makeGradingSnapshot({
    selectedOptionId: null,
    answerText: "Heat flows.",
    gradingStatus: "PENDING",
  });
  const state = withSnapshot(grading);
  assert.equal(state.phase, "grading");
  assert.equal(state.snapshot?.status, "QUESTION_GRADING");
});

test("text answer commands match text acknowledgements only", () => {
  let state = withSnapshot(
    makeOpenSnapshot({ questionType: "WRITTEN", maxMarks: 4 }),
  );
  state = sessionReducer(state, {
    type: "ANSWER_COMMAND_STARTED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: null,
    answerText: "Heat flows.",
  });
  state = sessionReducer(state, {
    type: "ANSWER_ACCEPTED_RECEIVED",
    generation: GENERATION,
    acknowledgement: answerAcknowledgement(null, QUESTION_ID, "Heat flows."),
  });
  assert.equal(state.acknowledgedAnswer?.answerText, "Heat flows.");
  assert.equal(state.acknowledgedAnswer?.selectedOptionId, null);
  assert.equal(state.acknowledgedAnswer?.gradingStatus, "GRADED");
});

test("a choice acknowledgement never matches a pending text answer", () => {
  let state = withSnapshot(
    makeOpenSnapshot({ questionType: "WRITTEN", maxMarks: 4 }),
  );
  state = sessionReducer(state, {
    type: "ANSWER_COMMAND_STARTED",
    generation: GENERATION,
    sessionId: SESSION_ID,
    sessionQuestionId: QUESTION_ID,
    selectedOptionId: null,
    answerText: "Heat flows.",
  });
  state = sessionReducer(state, {
    type: "ANSWER_ACCEPTED_RECEIVED",
    generation: GENERATION,
    acknowledgement: answerAcknowledgement("newton"),
  });
  assert.equal(state.acknowledgedAnswer, null);
  assert.equal(state.lastError?.kind, "malformed-server-message");
});

function preparationReadyState(): SessionState {
  let state = withSnapshot(
    makeLobbySnapshot(makeAdaptiveRoomState({ preparationStatus: null })),
  );
  state = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: makeAdaptiveRoomState({
      preparationStatus: "GENERATING",
      preparationVersion: 3,
    }),
  });
  state = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: makeAdaptiveRoomState({
      preparationStatus: "READY",
      preparationVersion: 4,
    }),
  });
  assert.equal(state.preparationStatus, "READY");
  assert.equal(state.preparationVersion, 4);
  return state;
}

test("a late GENERATING room update cannot overwrite READY", () => {
  const state = preparationReadyState();
  const unchanged = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: makeAdaptiveRoomState({
      preparationStatus: "GENERATING",
      preparationVersion: 3,
    }),
  });
  assert.deepEqual(unchanged, state);
});

test("stale FAILED, READY, and CONSUMED updates cannot replace newer status", () => {
  const ready = preparationReadyState();
  for (const staleStatus of ["GENERATING", "READY", "FAILED", "CONSUMED"] as const) {
    const unchanged = sessionReducer(ready, {
      type: "ROOM_STATE_RECEIVED",
      generation: GENERATION,
      roomState: makeAdaptiveRoomState({
        preparationStatus: staleStatus,
        preparationVersion: 2,
        preparationErrorCategory:
          staleStatus === "FAILED" ? "generation_failed" : null,
      }),
    });
    assert.deepEqual(unchanged, ready, `stale ${staleStatus} must be ignored`);
  }
  assert.equal(ready.preparationStatus, "READY");
  assert.equal(ready.preparationVersion, 4);

  let consumed = ready;
  consumed = sessionReducer(consumed, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: makeAdaptiveRoomState({
      preparationStatus: "CONSUMED",
      preparationVersion: 6,
    }),
  });
  assert.equal(consumed.preparationStatus, "CONSUMED");
  const lateReady = sessionReducer(consumed, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: makeAdaptiveRoomState({
      preparationStatus: "READY",
      preparationVersion: 5,
    }),
  });
  assert.deepEqual(lateReady, consumed);
});

test("equal versions only accept identical status and error replays", () => {
  const ready = preparationReadyState();
  const identical = sessionReducer(ready, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: makeAdaptiveRoomState({
      preparationStatus: "READY",
      preparationVersion: 4,
    }),
  });
  assert.notEqual(identical, ready);
  assert.equal(identical.preparationStatus, "READY");

  for (const disagreement of [
    makeAdaptiveRoomState({
      preparationStatus: "FAILED",
      preparationVersion: 4,
      preparationErrorCategory: "generation_failed",
    }),
    makeAdaptiveRoomState({
      preparationStatus: "CONSUMED",
      preparationVersion: 4,
    }),
    makeAdaptiveRoomState({
      preparationStatus: "READY",
      preparationVersion: 4,
      preparationErrorCategory: "timeout",
    }),
  ]) {
    const unchanged = sessionReducer(ready, {
      type: "ROOM_STATE_RECEIVED",
      generation: GENERATION,
      roomState: disagreement,
    });
    assert.deepEqual(unchanged, ready);
  }
});

test("newer preparation versions always advance the tracked state", () => {
  let state = preparationReadyState();
  state = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: makeAdaptiveRoomState({
      preparationStatus: "FAILED",
      preparationVersion: 5,
      preparationErrorCategory: "timeout",
    }),
  });
  assert.equal(state.preparationStatus, "FAILED");
  assert.equal(state.preparationVersion, 5);
  assert.equal(state.preparationErrorCategory, "timeout");

  state = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: makeAdaptiveRoomState({
      preparationStatus: "GENERATING",
      preparationVersion: 6,
    }),
  });
  assert.equal(state.preparationStatus, "GENERATING");
  assert.equal(state.preparationVersion, 6);
  assert.equal(state.preparationErrorCategory, null);
});

test("a snapshot with stale preparation keeps the tracked room state", () => {
  const ready = preparationReadyState();
  const staleRoom = makeAdaptiveRoomState({
    preparationStatus: "GENERATING",
    preparationVersion: 2,
  });
  const freshSession = makeOpenSnapshot({
    stateVersion: 2,
    roomState: staleRoom,
  });
  const state = sessionReducer(ready, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: freshSession,
    source: "requested",
  });
  assert.deepEqual(state.snapshot?.question, freshSession.question);
  assert.equal(state.snapshot?.room_state.active_preparation_status, "READY");
  assert.equal(state.roomState?.active_preparation_status, "READY");
  assert.equal(state.preparationStatus, "READY");
  assert.equal(state.preparationVersion, 4);
});

test("prepare and retry-grading commands resolve on fresh state", () => {
  let state = withSnapshot(makeLobbySnapshot(makeAdaptiveRoomState()));
  state = sessionReducer(state, {
    type: "PREPARE_COMMAND_STARTED",
    generation: GENERATION,
    requestId: "44444444-4444-4444-8444-444444444444",
  });
  assert.equal(state.pendingCommand?.kind, "prepare");
  state = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: GENERATION,
    roomState: makeAdaptiveRoomState({
      preparationStatus: "GENERATING",
      preparationVersion: 1,
    }),
  });
  assert.equal(state.pendingCommand, null);
  assert.equal(state.preparationStatus, "GENERATING");

  state = withSnapshot(makeGradingSnapshot({ gradingStatus: "UNAVAILABLE" }));
  state = sessionReducer(state, {
    type: "RETRY_GRADING_COMMAND_STARTED",
    generation: GENERATION,
  });
  assert.equal(state.pendingCommand?.kind, "retry-grading");
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: GENERATION,
    snapshot: makeGradingSnapshot({
      stateVersion: 4,
      gradingStatus: "PENDING",
    }),
    source: "requested",
  });
  assert.equal(state.pendingCommand, null);
  assert.equal(state.phase, "grading");
});

test("delayed null preparation merges fresh readiness and membership through room and snapshot interleavings", () => {
  for (const transport of ["room", "snapshot"] as const) {
    let state = preparationReadyState();
    const incoming = { ...makeAdaptiveRoomState(), viewer_ready: true,
      participants: makeAdaptiveRoomState().participants.slice(0, 1) };
    state = sessionReducer(state, transport === "room"
      ? { type: "ROOM_STATE_RECEIVED", generation: GENERATION, roomState: incoming }
      : { type: "SNAPSHOT_RECEIVED", generation: GENERATION,
          snapshot: makeLobbySnapshot(incoming), source: "requested" });
    assert.equal(state.preparationStatus, "READY");
    assert.equal(state.preparationVersion, 4);
    assert.equal(state.roomState?.active_preparation_status, "READY");
    assert.equal(state.roomState?.viewer_ready, true);
    assert.equal(state.roomState?.participants.length, 1);
    if (transport === "snapshot") assert.equal(state.snapshot?.room_state.active_preparation_version, 4);
    state = sessionReducer(state, { type: "ROOM_STATE_RECEIVED", generation: GENERATION,
      roomState: makeAdaptiveRoomState({ preparationStatus: "FAILED", preparationVersion: 5,
        preparationErrorCategory: "timeout" }) });
    state = sessionReducer(state, { type: "SNAPSHOT_RECEIVED", generation: GENERATION,
      snapshot: makeLobbySnapshot(incoming), source: "requested" });
    assert.equal(state.preparationStatus, "FAILED");
    assert.equal(state.preparationErrorCategory, "timeout");
    assert.equal(state.snapshot?.room_state.active_preparation_error_category, "timeout");
  }
});

test("explicit room selection, closure and reset clear known preparation", () => {
  for (const action of [
    { type: "ROOM_SELECTED", roomId: "other-room", generation: GENERATION + 1 },
    { type: "ROOM_CLEARED", generation: GENERATION + 1 },
    { type: "SIGNED_OUT", generation: GENERATION + 1 },
    { type: "RECOVERY_STARTED", generation: GENERATION + 1 },
  ] as const) {
    const state = sessionReducer(preparationReadyState(), action);
    assert.equal(state.preparationStatus, null);
    assert.equal(state.preparationVersion, null);
    assert.equal(state.preparationErrorCategory, null);
    assert.equal(state.roomState, null);
  }
});
