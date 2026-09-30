import assert from "node:assert/strict";
import test from "node:test";

import {
  createDrawingLifecycle,
  dispatchDrawingLifecycle,
  isSameDrawingScope,
  reconcileDrawingLifecycle,
  type DrawingLifecycleState,
} from "./lifecycle";
import type { DrawingPoint, DrawingScope } from "./types";

const SCOPE_Q1: DrawingScope = {
  userId: "user-alice",
  mode: "room",
  sessionId: "session-101",
  questionId: "question-1",
};

const SCOPE_Q2: DrawingScope = {
  userId: "user-alice",
  mode: "room",
  sessionId: "session-101",
  questionId: "question-2",
};

const SCOPE_SOLO: DrawingScope = {
  userId: "user-alice",
  mode: "solo",
  sessionId: "solo-session-202",
  questionId: "solo-q1",
};

const P1: DrawingPoint = { x: 100, y: 150 };
const P2: DrawingPoint = { x: 200, y: 250 };

function drawSampleStroke(state: DrawingLifecycleState): DrawingLifecycleState {
  let s = dispatchDrawingLifecycle(state, state.epoch, {
    type: "BEGIN",
    point: P1,
    ink: "primary",
    kind: "freehand",
  });
  s = dispatchDrawingLifecycle(s, s.epoch, {
    type: "EXTEND",
    point: P2,
  });
  s = dispatchDrawingLifecycle(s, s.epoch, {
    type: "END",
  });
  return s;
}

test("createDrawingLifecycle initializes default and customized lifecycle states", () => {
  // 1. Default creation
  const defaultState = createDrawingLifecycle();
  assert.equal(defaultState.scope, null);
  assert.equal(defaultState.epoch, 1);
  assert.equal(defaultState.phase, "closed");
  assert.equal(defaultState.visible, false);
  assert.equal(defaultState.document.strokes.length, 0);

  // 2. Active room creation
  const activeState = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  assert.deepEqual(activeState.scope, SCOPE_Q1);
  assert.equal(activeState.epoch, 1);
  assert.equal(activeState.phase, "answer-open");
  assert.equal(activeState.visible, true);

  // 3. Disconnected on mount
  const disconnectedState = createDrawingLifecycle(SCOPE_Q1, "answer-open", false);
  assert.equal(disconnectedState.visible, false);

  // 4. Closed phase on mount
  const closedState = createDrawingLifecycle(SCOPE_Q1, "closed", true);
  assert.equal(closedState.visible, false);
});

test("isSameDrawingScope verifies all four identity dimensions strictly", () => {
  assert.equal(isSameDrawingScope(SCOPE_Q1, SCOPE_Q1), true);
  assert.equal(isSameDrawingScope(SCOPE_Q1, { ...SCOPE_Q1 }), true);

  // 1. Different question
  assert.equal(isSameDrawingScope(SCOPE_Q1, SCOPE_Q2), false);

  // 2. Different user
  assert.equal(
    isSameDrawingScope(SCOPE_Q1, { ...SCOPE_Q1, userId: "user-bob" }),
    false,
  );

  // 3. Different mode
  assert.equal(
    isSameDrawingScope(SCOPE_Q1, { ...SCOPE_Q1, mode: "solo" }),
    false,
  );

  // 4. Different session
  assert.equal(
    isSameDrawingScope(SCOPE_Q1, { ...SCOPE_Q1, sessionId: "session-999" }),
    false,
  );

  // 5. Null guards
  assert.equal(isSameDrawingScope(SCOPE_Q1, null), false);
  assert.equal(isSameDrawingScope(null, SCOPE_Q1), false);
  assert.equal(isSameDrawingScope(null, null), true);
});

test("reconcileDrawingLifecycle advances question: clears document and increments epoch", () => {
  const initial = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  const withStrokes = drawSampleStroke(initial);
  assert.equal(withStrokes.document.strokes.length, 1);

  // Reconcile with next question in same session
  const nextQ = reconcileDrawingLifecycle(withStrokes, SCOPE_Q2, "answer-open", true);
  assert.equal(nextQ.document.strokes.length, 0);
  assert.equal(nextQ.document.past.length, 0);
  assert.equal(nextQ.document.active, null);
  assert.equal(nextQ.epoch, withStrokes.epoch + 1);
  assert.deepEqual(nextQ.scope, SCOPE_Q2);
  assert.equal(nextQ.visible, true);
});

test("reconcileDrawingLifecycle retains strokes on same-question reveal and cancels active stroke", () => {
  const initial = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  let withActive = drawSampleStroke(initial);

  // Start an unfinished stroke
  withActive = dispatchDrawingLifecycle(withActive, withActive.epoch, {
    type: "BEGIN",
    point: P1,
    ink: "ink",
    kind: "freehand",
  });
  assert.notEqual(withActive.document.active, null);

  // Question reveals: same question, phase becomes read-only
  const revealed = reconcileDrawingLifecycle(withActive, SCOPE_Q1, "read-only", true);
  assert.equal(revealed.document.strokes.length, 1, "Completed strokes must be retained");
  assert.equal(revealed.document.active, null, "In-flight stroke must be cleanly cancelled");
  assert.equal(revealed.epoch, withActive.epoch, "Epoch must not advance on same question reveal");
  assert.equal(revealed.phase, "read-only");
  assert.equal(revealed.visible, true);
});

test("reconcileDrawingLifecycle hides working when disconnected and restores on reconnect without stroke loss", () => {
  const initial = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  const withStrokes = drawSampleStroke(initial);

  // 1. Connection drops
  const disconnected = reconcileDrawingLifecycle(withStrokes, SCOPE_Q1, "answer-open", false);
  assert.equal(disconnected.visible, false, "Must hide while disconnected");
  assert.equal(disconnected.document.strokes.length, 1, "Must retain existing strokes");
  assert.equal(disconnected.epoch, withStrokes.epoch, "Must not increment epoch");

  // 2. Authoritative reconnect on same question
  const reconnected = reconcileDrawingLifecycle(disconnected, SCOPE_Q1, "answer-open", true);
  assert.equal(reconnected.visible, true, "Must unhide upon reconnect");
  assert.equal(reconnected.document.strokes.length, 1, "Strokes intact upon reconnect");
  assert.equal(reconnected.epoch, withStrokes.epoch);
});

test("reconcileDrawingLifecycle clears and invalidates on room abandon or account change", () => {
  const initial = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  const withStrokes = drawSampleStroke(initial);

  // 1. Leave room: scope becomes null
  const abandoned = reconcileDrawingLifecycle(withStrokes, null, "closed", true);
  assert.equal(abandoned.scope, null);
  assert.equal(abandoned.document.strokes.length, 0);
  assert.equal(abandoned.epoch, withStrokes.epoch + 1);
  assert.equal(abandoned.visible, false);

  // 2. Account change on active question
  const initial2 = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  const withStrokes2 = drawSampleStroke(initial2);
  const switchedUserScope: DrawingScope = { ...SCOPE_Q1, userId: "user-charlie" };
  const switched = reconcileDrawingLifecycle(withStrokes2, switchedUserScope, "answer-open", true);
  assert.equal(switched.document.strokes.length, 0);
  assert.equal(switched.epoch, withStrokes2.epoch + 1);
  assert.deepEqual(switched.scope, switchedUserScope);
});

test("reconcileDrawingLifecycle clears document when phase transitions to closed on same scope", () => {
  const initial = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  const withStrokes = drawSampleStroke(initial);

  // Session finishes or room closes
  const closed = reconcileDrawingLifecycle(withStrokes, SCOPE_Q1, "closed", true);
  assert.equal(closed.phase, "closed");
  assert.equal(closed.visible, false);
  assert.equal(closed.document.strokes.length, 0);
  assert.equal(closed.epoch, withStrokes.epoch + 1);
});

test("reconcileDrawingLifecycle supports solo practice scope seam identically", () => {
  const soloInitial = createDrawingLifecycle(SCOPE_SOLO, "answer-open", true);
  assert.equal(soloInitial.scope?.mode, "solo");

  const withStrokes = drawSampleStroke(soloInitial);
  assert.equal(withStrokes.document.strokes.length, 1);

  // Next solo question
  const nextSoloScope: DrawingScope = { ...SCOPE_SOLO, questionId: "solo-q2" };
  const nextSolo = reconcileDrawingLifecycle(withStrokes, nextSoloScope, "answer-open", true);
  assert.equal(nextSolo.document.strokes.length, 0);
  assert.equal(nextSolo.epoch, withStrokes.epoch + 1);
});

test("dispatchDrawingLifecycle blocks stale callbacks from earlier epochs", () => {
  const state = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  const staleEpoch = state.epoch - 1;

  const result = dispatchDrawingLifecycle(state, staleEpoch, {
    type: "BEGIN",
    point: P1,
    ink: "primary",
    kind: "freehand",
  });

  assert.equal(result, state, "Must return identical state on epoch mismatch");
  assert.equal(result.document.active, null);
});

test("dispatchDrawingLifecycle blocks editing in read-only and closed phases", () => {
  // 1. Read-only phase (reveal state)
  const openState = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  const withStrokes = drawSampleStroke(openState);
  const readOnlyState = reconcileDrawingLifecycle(withStrokes, SCOPE_Q1, "read-only", true);

  const blockedEdit = dispatchDrawingLifecycle(readOnlyState, readOnlyState.epoch, {
    type: "BEGIN",
    point: P1,
    ink: "primary",
    kind: "freehand",
  });
  assert.equal(blockedEdit, readOnlyState, "Editing must be rejected in read-only phase");

  const blockedClear = dispatchDrawingLifecycle(readOnlyState, readOnlyState.epoch, {
    type: "CLEAR",
  });
  assert.equal(blockedClear, readOnlyState, "Clear must be rejected in read-only phase");

  // 2. Closed phase
  const closedState = reconcileDrawingLifecycle(withStrokes, SCOPE_Q1, "closed", true);
  const blockedOnClosed = dispatchDrawingLifecycle(closedState, closedState.epoch, {
    type: "BEGIN",
    point: P1,
    ink: "primary",
    kind: "freehand",
  });
  assert.equal(blockedOnClosed, closedState, "Editing must be rejected in closed phase");
});

test("dispatchDrawingLifecycle blocks editing when disconnected or hidden", () => {
  const openState = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  const disconnectedState = reconcileDrawingLifecycle(openState, SCOPE_Q1, "answer-open", false);

  const result = dispatchDrawingLifecycle(disconnectedState, disconnectedState.epoch, {
    type: "BEGIN",
    point: P1,
    ink: "primary",
    kind: "freehand",
  });

  assert.equal(result, disconnectedState, "Editing must be rejected when workspace is hidden");
  assert.equal(result.document.active, null);
});
test("reconcileDrawingLifecycle is idempotent across repeated identical inputs without epoch/document churn", () => {
  // 1. Repeated null / closed / false calls on clean initial state
  const initial = createDrawingLifecycle();
  const r1 = reconcileDrawingLifecycle(initial, null, "closed", false);
  assert.equal(r1, initial, "Initial null/closed reconcile must return identical state reference");
  assert.equal(r1.epoch, initial.epoch, "Epoch must not advance on repeated null/closed");
  assert.equal(r1.document, initial.document, "Document reference must not be recreated");

  const r2 = reconcileDrawingLifecycle(r1, null, "closed", false);
  assert.equal(r2, r1);

  // 2. Repeated reconcile on active same-scope answer-open
  const q1Open = reconcileDrawingLifecycle(r2, SCOPE_Q1, "answer-open", true);
  const q1Repeated = reconcileDrawingLifecycle(q1Open, SCOPE_Q1, "answer-open", true);
  assert.equal(q1Repeated, q1Open, "Unchanged answer-open must return identical state reference");
  assert.equal(q1Repeated.epoch, q1Open.epoch);
  assert.equal(q1Repeated.document, q1Open.document);

  // 3. Repeated reconcile on active same-scope read-only
  const q1ReadOnly = reconcileDrawingLifecycle(q1Open, SCOPE_Q1, "read-only", true);
  const q1ReadOnlyRepeated = reconcileDrawingLifecycle(q1ReadOnly, SCOPE_Q1, "read-only", true);
  assert.equal(q1ReadOnlyRepeated, q1ReadOnly, "Unchanged read-only must return identical state reference");
  assert.equal(q1ReadOnlyRepeated.epoch, q1ReadOnly.epoch);

  // 4. Repeated reconcile on disconnected state
  const q1Disconnected = reconcileDrawingLifecycle(q1Open, SCOPE_Q1, "answer-open", false);
  const q1DisconnectedRepeated = reconcileDrawingLifecycle(q1Disconnected, SCOPE_Q1, "answer-open", false);
  assert.equal(q1DisconnectedRepeated, q1Disconnected, "Unchanged disconnected must return identical state reference");

  // 5. Repeated reconcile on closed state
  const q1Closed = reconcileDrawingLifecycle(q1Open, SCOPE_Q1, "closed", true);
  const q1ClosedRepeated = reconcileDrawingLifecycle(q1Closed, SCOPE_Q1, "closed", true);
  assert.equal(q1ClosedRepeated, q1Closed, "Unchanged closed must return identical state reference");
});

test("closed-state content detection includes future history so no stale redo survives", () => {
  const openState = createDrawingLifecycle(SCOPE_Q1, "answer-open", true);
  const withStroke = drawSampleStroke(openState);
  assert.equal(withStroke.document.strokes.length, 1);

  // User hits UNDO: strokes is now empty, but future redo history exists
  const undoneState = dispatchDrawingLifecycle(withStroke, withStroke.epoch, {
    type: "UNDO",
  });
  assert.equal(undoneState.document.strokes.length, 0);
  assert.ok(undoneState.document.future.length > 0, "Future redo history must be present after UNDO");

  // Close question: future history must trigger clear and advance epoch
  const closedState = reconcileDrawingLifecycle(undoneState, SCOPE_Q1, "closed", true);
  assert.equal(closedState.document.future.length, 0, "Future redo history must be wiped on closure");
  assert.equal(closedState.epoch, undoneState.epoch + 1, "Epoch must advance to invalidate redo callbacks");

  // Subsequent reconciliation must be idempotent
  const repeatedClosed = reconcileDrawingLifecycle(closedState, SCOPE_Q1, "closed", true);
  assert.equal(repeatedClosed, closedState);
});
