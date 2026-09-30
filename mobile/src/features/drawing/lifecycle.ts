import {
  createDrawingDocument,
  reduceDrawingDocument,
} from "./model";
import type {
  DrawingAction,
  DrawingDocument,
  DrawingPhase,
  DrawingScope,
} from "./types";

export type DrawingLifecycleState = Readonly<{
  scope: DrawingScope | null;
  epoch: number;
  document: DrawingDocument;
  phase: DrawingPhase;
  visible: boolean;
}>;

/**
 * Compares two drawing scopes across all four required dimensions:
 * userId, mode, sessionId, and questionId.
 */
export function isSameDrawingScope(
  a: DrawingScope | null,
  b: DrawingScope | null,
): boolean {
  if (a === b) {
    return true;
  }
  if (a === null || b === null) {
    return false;
  }
  return (
    a.userId === b.userId &&
    a.mode === b.mode &&
    a.sessionId === b.sessionId &&
    a.questionId === b.questionId
  );
}

/**
 * Creates an initial drawing lifecycle state.
 */
export function createDrawingLifecycle(
  initialScope: DrawingScope | null = null,
  initialPhase: DrawingPhase = "closed",
  connected = true,
): DrawingLifecycleState {
  const isUsable = initialScope !== null && initialPhase !== "closed";
  return {
    scope: initialScope,
    epoch: 1,
    document: createDrawingDocument(),
    phase: initialPhase,
    visible: isUsable && connected,
  };
}

/**
 * Reconciles the drawing lifecycle with the authoritative room or solo state.
 *
 * Rules:
 * 1. Scope change (question, session, mode, or user changed) or null scope:
 *    clears all drawing and history, increments epoch (invalidating callbacks).
 * 2. Closed phase: clears all drawing and history, increments epoch, hides drawing.
 * 3. Read-only phase on same question (reveal state): retains current work,
 *    cancels active in-flight stroke, keeps epoch, visible while connected.
 * 4. Disconnected / background: hides workspace (visible = false) without clearing
 *    current work; unhides once authoritatively reconnected with the same scope.
 */
function hasDrawingContent(document: DrawingDocument): boolean {
  return (
    document.strokes.length > 0 ||
    document.active !== null ||
    document.past.length > 0 ||
    document.future.length > 0
  );
}

export function reconcileDrawingLifecycle(
  state: DrawingLifecycleState,
  scope: DrawingScope | null,
  phase: DrawingPhase,
  connected: boolean,
): DrawingLifecycleState {
  const scopeChanged = !isSameDrawingScope(state.scope, scope);

  // 1. Target scope is null (e.g. exit, abandon, unauthenticated)
  if (scope === null) {
    const hasContent = hasDrawingContent(state.document);
    const isAlreadyClean =
      state.scope === null &&
      state.phase === "closed" &&
      !hasContent &&
      !state.visible;

    if (isAlreadyClean) {
      return state;
    }

    return {
      scope: null,
      epoch: state.epoch + 1,
      document: createDrawingDocument(),
      phase: "closed",
      visible: false,
    };
  }

  // 2. Different non-null scope (question advance, session change, user change, mode change)
  if (scopeChanged) {
    const isUsable = phase !== "closed";
    return {
      scope,
      epoch: state.epoch + 1,
      document: createDrawingDocument(),
      phase,
      visible: isUsable && connected,
    };
  }

  // 3. Same scope, closed phase (session finish, question finished)
  if (phase === "closed") {
    const hasContent = hasDrawingContent(state.document);
    const isAlreadyClean =
      state.phase === "closed" &&
      !hasContent &&
      !state.visible;

    if (isAlreadyClean) {
      return state;
    }

    return {
      scope,
      epoch: state.epoch + 1,
      document: createDrawingDocument(),
      phase: "closed",
      visible: false,
    };
  }

  // 4. Same scope, read-only phase (e.g. same-question answer reveal)
  if (phase === "read-only") {
    const targetVisible = connected;
    let doc = state.document;
    if (doc.active !== null) {
      doc = reduceDrawingDocument(doc, { type: "CANCEL" });
    }

    if (
      state.phase === "read-only" &&
      state.visible === targetVisible &&
      doc === state.document
    ) {
      return state;
    }

    return {
      scope,
      epoch: state.epoch,
      document: doc,
      phase: "read-only",
      visible: targetVisible,
    };
  }

  // 5. Same scope, answer-open phase
  const targetVisible = connected;
  if (
    state.phase === "answer-open" &&
    state.visible === targetVisible
  ) {
    return state;
  }

  return {
    scope,
    epoch: state.epoch,
    document: state.document,
    phase: "answer-open",
    visible: targetVisible,
  };
}

/**
 * Dispatches an editing action to the drawing document if and only if
 * the lifecycle state permits editing.
 *
 * Editing is rejected if:
 * - The captured epoch does not match the current state epoch (stale callback)
 * - The current phase is not 'answer-open' (e.g. 'read-only' or 'closed')
 * - The scope is null
 * - The workspace is not visible (e.g. disconnected or backgrounded)
 */
export function dispatchDrawingLifecycle(
  state: DrawingLifecycleState,
  capturedEpoch: number,
  action: DrawingAction,
): DrawingLifecycleState {
  // Reject stale callbacks from previous questions or invalidated sessions
  if (capturedEpoch !== state.epoch) {
    return state;
  }

  // Reject editing when not in answer-open phase (read-only reveal or closed)
  if (state.phase !== "answer-open") {
    return state;
  }

  // Reject editing when workspace is hidden (disconnected, backgrounded, or null scope)
  if (state.scope === null || !state.visible) {
    return state;
  }

  const nextDocument = reduceDrawingDocument(state.document, action);
  if (nextDocument === state.document) {
    return state;
  }

  return {
    ...state,
    document: nextDocument,
  };
}
