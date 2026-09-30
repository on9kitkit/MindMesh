import {
  MalformedServerMessageError,
  type StudyRoomRealtimeError,
} from "../../realtime/errors";
import type {
  AnswerAcceptedEvent,
  CanonicalUuid,
  GradingStatus,
  OpenStateSnapshotPayload,
  QuizPreparationStatus,
  RoomStatePayload,
  StateSnapshotPayload,
  ZonedIsoTimestamp,
} from "../../realtime/protocol";

export type ConnectionStage =
  | "disconnected"
  | "connecting"
  | "authenticated"
  | "established";

export type SnapshotRequestReason = "manual" | "transition" | "answer";

export type SnapshotSource =
  | "unsolicited"
  | "requested"
  | "new-socket"
  | "room-recovery";

export type PendingSessionCommand =
  | { kind: "ready"; ready: boolean; generation: number }
  | {
      kind: "start";
      previousSessionId: CanonicalUuid | null;
      generation: number;
    }
  | {
      kind: "answer";
      sessionId: CanonicalUuid;
      sessionQuestionId: CanonicalUuid;
      selectedOptionId: string | null;
      answerText: string | null;
      generation: number;
    }
  | { kind: "prepare"; requestId: string; generation: number }
  | { kind: "retry-grading"; generation: number };

export type RoomExitKind = "leave" | "close";

export type AcknowledgedAnswer = {
  sessionId: CanonicalUuid;
  sessionQuestionId: CanonicalUuid;
  selectedOptionId: string | null;
  answerText: string | null;
  gradingStatus: GradingStatus;
  acceptedAt: ZonedIsoTimestamp;
  generation: number;
};

export type ExpectedSnapshot = {
  sessionId: CanonicalUuid;
  stateVersion: number;
};

export type PendingSnapshotRequest = {
  generation: number;
  reason: SnapshotRequestReason;
};

type SessionStateFields = {
  roomId: string | null;
  roomState: RoomStatePayload | null;
  snapshot: StateSnapshotPayload | null;
  socketGeneration: number;
  connectionStage: ConnectionStage;
  reconnectAttempt: number;
  pendingCommand: PendingSessionCommand | null;
  pendingRoomExit: RoomExitKind | null;
  acknowledgedAnswer: AcknowledgedAnswer | null;
  pendingSnapshotRequest: PendingSnapshotRequest | null;
  expectedSnapshot: ExpectedSnapshot | null;
  lastSnapshotGeneration: number | null;
  dismissedFinishedSessionId: CanonicalUuid | null;
  preparationStatus: QuizPreparationStatus | null;
  preparationVersion: number | null;
  preparationErrorCategory: string | null;
  lastError: StudyRoomRealtimeError | null;
};

type SessionPhase =
  | { phase: "idle" }
  | { phase: "recovering-room" }
  | { phase: "connecting" }
  | { phase: "waiting" }
  | { phase: "question-open" }
  | { phase: "submitting" }
  | { phase: "submitted" }
  | { phase: "grading" }
  | { phase: "reveal" }
  | { phase: "finished" }
  | { phase: "reconnecting" }
  | { phase: "recoverable-error" }
  | { phase: "fatal-error" };

export type SessionState = SessionStateFields & SessionPhase;

export type SessionAction =
  | { type: "RECOVERY_STARTED"; generation: number }
  | { type: "RECOVERY_FOUND_NO_ROOM"; generation: number }
  | {
      type: "RECOVERY_FAILED";
      generation: number;
      error: StudyRoomRealtimeError;
    }
  | { type: "ROOM_SELECTED"; roomId: string; generation: number }
  | { type: "ROOM_CLEARED"; generation: number }
  | {
      type: "ROOM_EXIT_STARTED";
      generation: number;
      kind: RoomExitKind;
    }
  | { type: "ROOM_EXIT_SOCKET_CLOSED"; generation: number }
  | {
      type: "ROOM_EXIT_FAILED";
      generation: number;
      error: StudyRoomRealtimeError;
    }
  | {
      type: "SOCKET_CONNECTING";
      generation: number;
      reconnecting: boolean;
    }
  | { type: "SOCKET_INVALIDATED"; generation: number }
  | {
      type: "CONNECTED_RECEIVED";
      generation: number;
      serverTime: ZonedIsoTimestamp;
    }
  | {
      type: "ROOM_STATE_RECEIVED";
      generation: number;
      roomState: RoomStatePayload;
    }
  | {
      type: "SNAPSHOT_RECEIVED";
      generation: number;
      snapshot: StateSnapshotPayload;
      source: SnapshotSource;
    }
  | {
      type: "TRANSITION_HINT_RECEIVED";
      generation: number;
      sessionId: CanonicalUuid;
      stateVersion: number;
    }
  | {
      type: "READY_COMMAND_STARTED";
      generation: number;
      ready: boolean;
    }
  | {
      type: "START_COMMAND_STARTED";
      generation: number;
      previousSessionId: CanonicalUuid | null;
    }
  | {
      type: "ANSWER_COMMAND_STARTED";
      generation: number;
      sessionId: CanonicalUuid;
      sessionQuestionId: CanonicalUuid;
      selectedOptionId: string | null;
      answerText: string | null;
    }
  | {
      type: "PREPARE_COMMAND_STARTED";
      generation: number;
      requestId: string;
    }
  | { type: "RETRY_GRADING_COMMAND_STARTED"; generation: number }
  | {
      type: "ANSWER_ACCEPTED_RECEIVED";
      generation: number;
      acknowledgement: AnswerAcceptedEvent["payload"];
    }
  | {
      type: "SNAPSHOT_REQUEST_STARTED";
      generation: number;
      reason: SnapshotRequestReason;
    }
  | { type: "SNAPSHOT_REQUEST_FAILED"; generation: number }
  | {
      type: "COMMAND_REJECTED";
      generation: number;
      error: StudyRoomRealtimeError;
    }
  | {
      type: "CONNECTION_LOST";
      generation: number;
      attempt: number;
      error: StudyRoomRealtimeError;
    }
  | {
      type: "RECOVERABLE_FAILURE";
      generation: number;
      error: StudyRoomRealtimeError;
    }
  | {
      type: "FATAL_FAILURE";
      generation: number;
      error: StudyRoomRealtimeError;
      clearRoom: boolean;
    }
  | { type: "DISMISS_FINISHED_SESSION" }
  | { type: "SIGNED_OUT"; generation: number };

const emptyFields: SessionStateFields = {
  roomId: null,
  roomState: null,
  snapshot: null,
  socketGeneration: 0,
  connectionStage: "disconnected",
  reconnectAttempt: 0,
  pendingCommand: null,
  pendingRoomExit: null,
  acknowledgedAnswer: null,
  pendingSnapshotRequest: null,
  expectedSnapshot: null,
  lastSnapshotGeneration: null,
  dismissedFinishedSessionId: null,
  preparationStatus: null,
  preparationVersion: null,
  preparationErrorCategory: null,
  lastError: null,
};

export const initialSessionState: SessionState = {
  ...emptyFields,
  phase: "idle",
};

function buildState(
  fields: SessionStateFields,
  phase: SessionPhase,
): SessionState {
  return { ...fields, ...phase };
}

function isAnswerForOpenQuestion(
  answer: AcknowledgedAnswer,
  snapshot: OpenStateSnapshotPayload,
): boolean {
  return (
    answer.sessionId === snapshot.session_id &&
    answer.sessionQuestionId === snapshot.question.session_question_id
  );
}

function stablePhase(fields: SessionStateFields): SessionPhase {
  if (fields.roomId === null) {
    return { phase: "idle" };
  }
  if (fields.connectionStage !== "established") {
    return fields.snapshot === null
      ? { phase: "connecting" }
      : { phase: "reconnecting" };
  }

  const snapshot = fields.snapshot;
  if (snapshot === null || snapshot.status === null) {
    return { phase: "waiting" };
  }
  if (snapshot.status === "QUESTION_GRADING") {
    return { phase: "grading" };
  }
  if (snapshot.status === "QUESTION_REVEAL") {
    return { phase: "reveal" };
  }
  if (snapshot.status === "FINISHED") {
    return fields.dismissedFinishedSessionId === snapshot.session_id
      ? { phase: "waiting" }
      : { phase: "finished" };
  }
  if (snapshot.viewer_submission !== null) {
    return { phase: "submitted" };
  }
  if (fields.pendingCommand?.kind === "answer") {
    return { phase: "submitting" };
  }
  if (
    fields.acknowledgedAnswer !== null &&
    isAnswerForOpenQuestion(fields.acknowledgedAnswer, snapshot)
  ) {
    return { phase: "submitted" };
  }
  return { phase: "question-open" };
}

function generationMatches(state: SessionState, generation: number): boolean {
  return state.socketGeneration === generation;
}

/**
 * Reject out-of-order preparation updates. Backend preparation
 * state_version is room-global monotonic: every transition on any row
 * increments it and each fresh row starts above every prior version. So any
 * incoming non-null version below the stored one is stale regardless of
 * status — a late FAILED, CONSUMED, or READY must never replace a newer
 * status. For equal versions only an identical status/error replay may
 * pass; a different payload for the same version is stale or corrupt.
 * Null versions on either side cannot be ordered, preserving legacy and
 * lobby semantics.
 */
function preparationUpdateIsStale(
  state: SessionState,
  roomState: RoomStatePayload,
): boolean {
  const incomingVersion = roomState.active_preparation_version;
  if (state.preparationVersion === null) {
    return false;
  }
  if (incomingVersion === null) return true;
  if (incomingVersion !== state.preparationVersion) {
    return incomingVersion < state.preparationVersion;
  }
  return (
    roomState.active_preparation_status !== state.preparationStatus ||
    (roomState.active_preparation_error_category ?? null) !==
      (state.preparationErrorCategory ?? null)
  );
}

function mergePreparation(state: SessionState, incoming: RoomStatePayload): RoomStatePayload {
  if (!preparationUpdateIsStale(state, incoming)) return incoming;
  return {
    ...incoming,
    active_preparation_status: state.preparationStatus,
    active_preparation_version: state.preparationVersion,
    active_preparation_error_category: state.preparationErrorCategory,
  };
}

function trackPreparation(
  fields: SessionStateFields,
  roomState: RoomStatePayload,
): SessionStateFields {
  return {
    ...fields,
    preparationStatus: roomState.active_preparation_status,
    preparationVersion: roomState.active_preparation_version,
    preparationErrorCategory: roomState.active_preparation_error_category,
  };
}

function shouldAcceptSnapshot(
  state: SessionState,
  snapshot: StateSnapshotPayload,
  source: SnapshotSource,
  generation: number,
): boolean {
  const current = state.snapshot;
  if (current === null) {
    return true;
  }
  if (snapshot.session_id === null) {
    if (current.session_id === null) {
      return true;
    }
    return source === "room-recovery";
  }
  if (current.session_id === null || current.session_id !== snapshot.session_id) {
    return true;
  }
  if (snapshot.state_version > current.state_version) {
    return true;
  }
  if (snapshot.state_version < current.state_version) {
    return false;
  }
  return (
    source === "requested" || state.lastSnapshotGeneration !== generation
  );
}

function resolvePendingCommand(
  state: SessionState,
  snapshot: StateSnapshotPayload,
  accepted: boolean,
  source: SnapshotSource,
): PendingSessionCommand | null {
  const pending = state.pendingCommand;
  if (!accepted || pending === null) {
    return pending;
  }
  if (pending.kind === "ready") {
    return snapshot.room_state.viewer_ready === pending.ready ? null : pending;
  }
  if (pending.kind === "start") {
    return snapshot.session_id === null ||
      snapshot.session_id === pending.previousSessionId
      ? pending
      : null;
  }
  if (pending.kind === "prepare" || pending.kind === "retry-grading") {
    // Any accepted authoritative state arrives causally after our command
    // on the same ordered connection and resolves the pending control.
    return null;
  }
  if (
    snapshot.session_id !== pending.sessionId ||
    (snapshot.status !== "QUESTION_OPEN" &&
      snapshot.status !== "QUESTION_GRADING") ||
    snapshot.question.session_question_id !== pending.sessionQuestionId
  ) {
    return null;
  }
  const submission = snapshot.viewer_submission;
  if (
    submission?.session_question_id === pending.sessionQuestionId &&
    ((pending.selectedOptionId !== null &&
      submission.selected_option_id === pending.selectedOptionId) ||
      (pending.answerText !== null &&
        submission.answer_text === pending.answerText))
  ) {
    return null;
  }
  return source === "unsolicited" ? pending : null;
}

function resolveAcknowledgement(
  state: SessionState,
  snapshot: StateSnapshotPayload,
  accepted: boolean,
  source: SnapshotSource,
): AcknowledgedAnswer | null {
  const acknowledgement = state.acknowledgedAnswer;
  if (!accepted || acknowledgement === null) {
    return acknowledgement;
  }
  if (snapshot.session_id !== acknowledgement.sessionId) {
    return null;
  }
  if (
    snapshot.status !== "QUESTION_OPEN" &&
    snapshot.status !== "QUESTION_GRADING"
  ) {
    return null;
  }
  if (
    snapshot.question.session_question_id !==
    acknowledgement.sessionQuestionId
  ) {
    return null;
  }
  if (
    snapshot.viewer_submission?.session_question_id ===
      acknowledgement.sessionQuestionId &&
    ((acknowledgement.selectedOptionId !== null &&
      snapshot.viewer_submission.selected_option_id ===
        acknowledgement.selectedOptionId) ||
      (acknowledgement.answerText !== null &&
        snapshot.viewer_submission.answer_text === acknowledgement.answerText))
  ) {
    return acknowledgement;
  }
  return source === "unsolicited" ? acknowledgement : null;
}

function requestForHint(
  state: SessionState,
  generation: number,
): PendingSnapshotRequest | null {
  return state.pendingSnapshotRequest ?? {
    generation,
    reason: "transition",
  };
}

export function sessionReducer(
  state: SessionState,
  action: SessionAction,
): SessionState {
  switch (action.type) {
    case "RECOVERY_STARTED":
      return buildState(
        {
          ...emptyFields,
          socketGeneration: action.generation,
        },
        { phase: "recovering-room" },
      );
    case "RECOVERY_FOUND_NO_ROOM":
    case "ROOM_CLEARED":
    case "SIGNED_OUT":
      return buildState(
        {
          ...emptyFields,
          socketGeneration: action.generation,
        },
        { phase: "idle" },
      );
    case "RECOVERY_FAILED":
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      return buildState(
        {
          ...state,
          connectionStage: "disconnected",
          lastError: action.error,
        },
        { phase: "recoverable-error" },
      );
    case "ROOM_SELECTED":
      return buildState(
        {
          ...emptyFields,
          roomId: action.roomId,
          socketGeneration: action.generation,
          connectionStage: "connecting",
        },
        { phase: "connecting" },
      );
    case "ROOM_EXIT_STARTED": {
      if (!generationMatches(state, action.generation) || state.roomId === null) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        pendingRoomExit: action.kind,
        lastError: null,
      };
      return buildState(fields, stablePhase(fields));
    }
    case "ROOM_EXIT_SOCKET_CLOSED": {
      if (
        !generationMatches(state, action.generation) ||
        state.pendingRoomExit === null
      ) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        connectionStage: "disconnected",
        pendingCommand: null,
        pendingSnapshotRequest: null,
      };
      return buildState(fields, { phase: "reconnecting" });
    }
    case "ROOM_EXIT_FAILED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        pendingRoomExit: null,
        lastError: action.error,
      };
      return buildState(fields, stablePhase(fields));
    }
    case "SOCKET_CONNECTING": {
      if (!generationMatches(state, action.generation) || state.roomId === null) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        connectionStage: "connecting",
        pendingCommand: null,
        pendingSnapshotRequest: null,
        lastError: null,
      };
      return buildState(
        fields,
        action.reconnecting || fields.snapshot !== null
          ? { phase: "reconnecting" }
          : { phase: "connecting" },
      );
    }
    case "SOCKET_INVALIDATED": {
      if (!generationMatches(state, action.generation - 1)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        socketGeneration: action.generation,
        connectionStage: "disconnected",
        pendingCommand: null,
        pendingSnapshotRequest: null,
      };
      return buildState(
        fields,
        fields.roomId === null
          ? { phase: "idle" }
          : { phase: "reconnecting" },
      );
    }
    case "CONNECTED_RECEIVED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        connectionStage: "authenticated",
      };
      return buildState(
        fields,
        state.snapshot === null
          ? { phase: "connecting" }
          : { phase: "reconnecting" },
      );
    }
    case "ROOM_STATE_RECEIVED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const roomState = mergePreparation(state, action.roomState);
      const pendingCommand =
        state.pendingCommand?.kind === "ready" &&
        state.pendingCommand.ready === action.roomState.viewer_ready
          ? null
          : state.pendingCommand?.kind === "prepare" ||
              state.pendingCommand?.kind === "retry-grading"
            ? null
            : state.pendingCommand;
      const fields: SessionStateFields = trackPreparation(
        {
          ...state,
          roomState,
          pendingCommand,
        },
        roomState,
      );
      return buildState(fields, stablePhase(fields));
    }
    case "SNAPSHOT_RECEIVED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const accepted = shouldAcceptSnapshot(
        state,
        action.snapshot,
        action.source,
        action.generation,
      );
      const roomState = accepted ? mergePreparation(state, action.snapshot.room_state) : state.roomState;
      const nextSnapshot = accepted && roomState !== null
        ? roomState === action.snapshot.room_state
          ? action.snapshot
          : { ...action.snapshot, room_state: roomState }
        : state.snapshot;
      const sessionChanged =
        accepted &&
        state.snapshot?.session_id !== null &&
        state.snapshot?.session_id !== undefined &&
        action.snapshot.session_id !== state.snapshot.session_id;
      const expectedResolved =
        accepted &&
        state.expectedSnapshot !== null &&
        action.snapshot.session_id === state.expectedSnapshot.sessionId &&
        action.snapshot.state_version >= state.expectedSnapshot.stateVersion;
      // The session portion of an accepted snapshot is ordered by
      // session state_version, but its room_state preparation portion is
      // ordered by the room-global preparation version: a stale preparation
      // payload must not replace known preparation fields. Unrelated fresh
      // room fields and session data are still adopted.
      const trackedFields: SessionStateFields = accepted && roomState !== null
        ? trackPreparation(state, roomState)
        : state;
      const fields: SessionStateFields = {
        ...trackedFields,
        roomState,
        snapshot: nextSnapshot,
        connectionStage: "established",
        reconnectAttempt: 0,
        pendingCommand: sessionChanged
          ? null
          : resolvePendingCommand(
              state,
              action.snapshot,
              accepted,
              action.source,
            ),
        acknowledgedAnswer: sessionChanged
          ? null
          : resolveAcknowledgement(
              state,
              action.snapshot,
              accepted,
              action.source,
            ),
        pendingSnapshotRequest: null,
        expectedSnapshot:
          sessionChanged || expectedResolved ? null : state.expectedSnapshot,
        lastSnapshotGeneration: accepted
          ? action.generation
          : state.lastSnapshotGeneration,
        dismissedFinishedSessionId: sessionChanged
          ? null
          : state.dismissedFinishedSessionId,
        lastError: null,
      };
      return buildState(fields, stablePhase(fields));
    }
    case "TRANSITION_HINT_RECEIVED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const appliedVersion =
        state.snapshot?.session_id === action.sessionId
          ? state.snapshot.state_version
          : -1;
      const expectedVersion =
        state.expectedSnapshot?.sessionId === action.sessionId
          ? state.expectedSnapshot.stateVersion
          : -1;
      if (
        action.stateVersion <= appliedVersion ||
        action.stateVersion <= expectedVersion
      ) {
        return state;
      }
      return buildState(
        {
          ...state,
          expectedSnapshot: {
            sessionId: action.sessionId,
            stateVersion: action.stateVersion,
          },
          pendingSnapshotRequest: requestForHint(state, action.generation),
        },
        { phase: state.phase },
      );
    }
    case "READY_COMMAND_STARTED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        pendingCommand: {
          kind: "ready",
          ready: action.ready,
          generation: action.generation,
        },
        lastError: null,
      };
      return buildState(fields, stablePhase(fields));
    }
    case "START_COMMAND_STARTED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        pendingCommand: {
          kind: "start",
          previousSessionId: action.previousSessionId,
          generation: action.generation,
        },
        lastError: null,
      };
      return buildState(fields, stablePhase(fields));
    }
    case "ANSWER_COMMAND_STARTED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        pendingCommand: {
          kind: "answer",
          sessionId: action.sessionId,
          sessionQuestionId: action.sessionQuestionId,
          selectedOptionId: action.selectedOptionId,
          answerText: action.answerText,
          generation: action.generation,
        },
        acknowledgedAnswer: null,
        lastError: null,
      };
      return buildState(fields, stablePhase(fields));
    }
    case "PREPARE_COMMAND_STARTED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        pendingCommand: {
          kind: "prepare",
          requestId: action.requestId,
          generation: action.generation,
        },
        lastError: null,
      };
      return buildState(fields, stablePhase(fields));
    }
    case "RETRY_GRADING_COMMAND_STARTED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        pendingCommand: { kind: "retry-grading", generation: action.generation },
        lastError: null,
      };
      return buildState(fields, stablePhase(fields));
    }
    case "ANSWER_ACCEPTED_RECEIVED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const pending = state.pendingCommand;
      const acknowledgement = action.acknowledgement;
      const matches =
        pending?.kind === "answer" &&
        pending.sessionId === acknowledgement.session_id &&
        pending.sessionQuestionId === acknowledgement.session_question_id &&
        ((pending.selectedOptionId !== null &&
          pending.selectedOptionId ===
            acknowledgement.selected_option_id) ||
          (pending.answerText !== null &&
            pending.answerText === acknowledgement.answer_text));
      const fields: SessionStateFields = {
        ...state,
        pendingCommand: null,
        acknowledgedAnswer: matches
          ? {
              sessionId: acknowledgement.session_id,
              sessionQuestionId: acknowledgement.session_question_id,
              selectedOptionId: acknowledgement.selected_option_id,
              answerText: acknowledgement.answer_text,
              gradingStatus: acknowledgement.grading_status,
              acceptedAt: acknowledgement.accepted_at,
              generation: action.generation,
            }
          : state.acknowledgedAnswer,
        pendingSnapshotRequest: state.pendingSnapshotRequest ?? {
          generation: action.generation,
          reason: "answer",
        },
        lastError: matches
          ? null
          : new MalformedServerMessageError(
              "The server answer acknowledgement did not match the pending answer.",
            ),
      };
      return buildState(fields, stablePhase(fields));
    }
    case "SNAPSHOT_REQUEST_STARTED":
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      if (state.pendingSnapshotRequest !== null) {
        return state;
      }
      return buildState(
        {
          ...state,
          pendingSnapshotRequest: {
            generation: action.generation,
            reason: action.reason,
          },
        },
        { phase: state.phase },
      );
    case "SNAPSHOT_REQUEST_FAILED":
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      return buildState(
        { ...state, pendingSnapshotRequest: null },
        { phase: state.phase },
      );
    case "COMMAND_REJECTED": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        pendingCommand: null,
        pendingSnapshotRequest: null,
        lastError: action.error,
      };
      return buildState(fields, stablePhase(fields));
    }
    case "CONNECTION_LOST": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = {
        ...state,
        connectionStage: "disconnected",
        reconnectAttempt: action.attempt,
        pendingCommand: null,
        pendingSnapshotRequest: null,
        lastError: action.error,
      };
      return buildState(fields, { phase: "reconnecting" });
    }
    case "RECOVERABLE_FAILURE":
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      return buildState(
        {
          ...state,
          connectionStage: "disconnected",
          pendingCommand: null,
          pendingSnapshotRequest: null,
          lastError: action.error,
        },
        { phase: "recoverable-error" },
      );
    case "FATAL_FAILURE": {
      if (!generationMatches(state, action.generation)) {
        return state;
      }
      const fields: SessionStateFields = action.clearRoom
        ? {
            ...emptyFields,
            socketGeneration: action.generation,
            lastError: action.error,
          }
        : {
            ...state,
            connectionStage: "disconnected",
            pendingCommand: null,
            pendingSnapshotRequest: null,
            lastError: action.error,
          };
      return buildState(fields, { phase: "fatal-error" });
    }
    case "DISMISS_FINISHED_SESSION":
      if (state.snapshot?.status !== "FINISHED") {
        return state;
      }
      {
        const fields: SessionStateFields = {
          ...state,
          dismissedFinishedSessionId: state.snapshot.session_id,
        };
        return buildState(fields, stablePhase(fields));
      }
  }
}

export function socketIsAuthenticated(state: SessionState): boolean {
  return (
    state.connectionStage === "authenticated" ||
    state.connectionStage === "established"
  );
}

export function socketIsEstablished(state: SessionState): boolean {
  return state.connectionStage === "established";
}
