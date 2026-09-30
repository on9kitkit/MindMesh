import type {
  QuizPreparationStatus,
  RoomStateParticipant,
  SessionStatus,
} from "../../realtime/protocol";
import type { SessionState } from "../session/sessionState";
import { getSubjectLabel, getTopicLabel } from "../quiz/adaptiveQuiz";

export type ParticipantPresentation = RoomStateParticipant & {
  roleLabel: "Host" | "Member";
  readinessLabel: "Ready automatically" | "Ready" | "Not ready";
  presenceLabel: "Online" | "Offline";
};

export type AdaptiveRoomSummary = {
  educationLevel: string | null;
  subject: string;
  topic: string;
  subjectLabel: string;
  topicLabel: string;
  targetTotalMarks: number | null;
};

export type WaitingRoomPresentation = {
  roomId: string;
  name: string;
  joinCode: string;
  participantCount: number;
  maximumMembers: number;
  viewerRole: "host" | "member";
  participants: ParticipantPresentation[];
  sessionStatus: SessionStatus | null;
  quizMode: "LEGACY_PHYSICS" | "ADAPTIVE";
  adaptiveSummary: AdaptiveRoomSummary | null;
  preparationStatus: QuizPreparationStatus | null;
  preparationVersion: number | null;
};

export function presentParticipant(
  participant: RoomStateParticipant,
): ParticipantPresentation {
  return {
    ...participant,
    roleLabel: participant.role === "host" ? "Host" : "Member",
    readinessLabel:
      participant.role === "host"
        ? "Ready automatically"
        : participant.ready
          ? "Ready"
          : "Not ready",
    presenceLabel: participant.online ? "Online" : "Offline",
  };
}

export function buildAdaptiveRoomSummary(
  sessionState: SessionState,
): AdaptiveRoomSummary | null {
  const roomState = sessionState.roomState;
  if (
    roomState === null ||
    roomState.quiz_mode !== "ADAPTIVE" ||
    roomState.quiz_subject === null ||
    roomState.quiz_topic === null
  ) {
    return null;
  }
  return {
    educationLevel: roomState.education_level,
    subject: roomState.quiz_subject,
    topic: roomState.quiz_topic,
    subjectLabel: getSubjectLabel(roomState.quiz_subject) ?? roomState.quiz_subject,
    topicLabel: getTopicLabel(roomState.quiz_topic) ?? roomState.quiz_topic,
    targetTotalMarks: roomState.target_total_marks,
  };
}

export function buildWaitingRoomPresentation(
  sessionState: SessionState,
): WaitingRoomPresentation | null {
  const roomState = sessionState.roomState;
  if (roomState === null || roomState.room_id !== sessionState.roomId) {
    return null;
  }
  return {
    roomId: roomState.room_id,
    name: roomState.name,
    joinCode: roomState.join_code,
    participantCount: roomState.participants.length,
    maximumMembers: roomState.maximum_members,
    viewerRole: roomState.viewer_role,
    participants: roomState.participants.map(presentParticipant),
    sessionStatus: sessionState.snapshot?.status ?? null,
    quizMode: roomState.quiz_mode,
    adaptiveSummary: buildAdaptiveRoomSummary(sessionState),
    preparationStatus: roomState.active_preparation_status,
    preparationVersion: roomState.active_preparation_version,
  };
}

const PREPARATION_FAILED_CODES: ReadonlySet<string> = new Set([
  "preparation_failed",
  "ai_generation_unavailable",
]);

export type PreparationControl =
  | { status: "legacy" }
  | { status: "generate-available"; label: string }
  | { status: "generate-pending"; label: string }
  | { status: "generating"; label: string }
  | { status: "ready"; label: string }
  | { status: "failed"; label: string; canRetry: boolean }
  | { status: "waiting-host"; label: string };

function preparationLobbyAvailable(sessionState: SessionState): boolean {
  return (
    sessionState.connectionStage === "established" &&
    sessionState.pendingCommand === null &&
    sessionState.pendingRoomExit === null &&
    lobbyCommandsAreAvailable(sessionState)
  );
}

export function derivePreparationControl(
  sessionState: SessionState,
  httpPreparationPending = false,
): PreparationControl {
  const roomState = sessionState.roomState;
  if (roomState === null || roomState.quiz_mode !== "ADAPTIVE") {
    return { status: "legacy" };
  }
  if (httpPreparationPending || sessionState.pendingCommand?.kind === "prepare") {
    return { status: "generate-pending", label: "Generating quiz..." };
  }
  const preparationStatus = roomState.active_preparation_status;
  if (preparationStatus === "GENERATING") {
    return { status: "generating", label: "Generating quiz..." };
  }
  if (preparationStatus === "READY") {
    return { status: "ready", label: "Quiz ready" };
  }
  const viewerIsHost = roomState.viewer_role === "host";
  // FAILED is durable room state: the latest preparation row stays
  // observable with its safe error category instead of disappearing.
  // A transient command rejection is only a fallback for the window before
  // the first post-failure room state arrives.
  const failedDurably = preparationStatus === "FAILED";
  const failedTransiently =
    !failedDurably &&
    preparationStatus === null &&
    sessionState.lastError?.kind === "command-rejected" &&
    sessionState.lastError.code !== undefined &&
    PREPARATION_FAILED_CODES.has(sessionState.lastError.code);
  if (failedDurably || failedTransiently) {
    const unavailable =
      roomState.active_preparation_error_category ===
      "ai_generation_unavailable";
    const canRetry = viewerIsHost && preparationLobbyAvailable(sessionState);
    return {
      status: "failed",
      label: unavailable
        ? "AI quiz generation is currently unavailable."
        : "Quiz generation failed.",
      canRetry,
    };
  }
  if (viewerIsHost && preparationLobbyAvailable(sessionState)) {
    return { status: "generate-available", label: "Generate Quiz" };
  }
  if (viewerIsHost) {
    return { status: "waiting-host", label: "Quiz generation unavailable right now." };
  }
  return { status: "waiting-host", label: "Waiting for the host to generate the quiz." };
}

export type ReadinessControl =
  | { status: "host" }
  | { status: "pending"; desiredReady: boolean; label: string }
  | { status: "available"; desiredReady: boolean; label: string }
  | { status: "disabled"; label: string };

export function deriveReadinessControl(
  sessionState: SessionState,
): ReadinessControl {
  const roomState = sessionState.roomState;
  if (roomState?.viewer_role === "host") {
    return { status: "host" };
  }
  const pending = sessionState.pendingCommand;
  if (pending?.kind === "ready") {
    return {
      status: "pending",
      desiredReady: pending.ready,
      label: pending.ready ? "Setting ready..." : "Setting not ready...",
    };
  }
  if (
    roomState === null ||
    sessionState.connectionStage !== "established" ||
    !lobbyCommandsAreAvailable(sessionState)
  ) {
    return {
      status: "disabled",
      label:
        sessionState.phase === "reconnecting"
          ? "Readiness unavailable while reconnecting"
          : "Readiness unavailable",
    };
  }
  const desiredReady = !roomState.viewer_ready;
  return {
    status: "available",
    desiredReady,
    label: desiredReady ? "I'm ready" : "I'm not ready",
  };
}

export type StartEligibility = {
  eligible: boolean;
  viewerIsHost: boolean;
  hasMinimumParticipants: boolean;
  allMembersReady: boolean;
  hasNoActiveSession: boolean;
  quizContentReady: boolean;
  connectionEstablished: boolean;
  noCommandPending: boolean;
  lobbyAvailable: boolean;
};

function sessionIsActive(status: SessionStatus | null): boolean {
  return (
    status === "QUESTION_OPEN" ||
    status === "QUESTION_GRADING" ||
    status === "QUESTION_REVEAL"
  );
}

export function lobbyCommandsAreAvailable(
  sessionState: SessionState,
): boolean {
  if (
    sessionState.phase !== "waiting" ||
    sessionState.pendingRoomExit !== null
  ) {
    return false;
  }
  const snapshot = sessionState.snapshot;
  if (snapshot?.status !== "FINISHED") {
    return snapshot?.session_id === null;
  }
  return sessionState.dismissedFinishedSessionId === snapshot.session_id;
}

export function selectStartEligibility(
  sessionState: SessionState,
): StartEligibility {
  const roomState = sessionState.roomState;
  const viewerIsHost = roomState?.viewer_role === "host";
  const hasMinimumParticipants = (roomState?.participants.length ?? 0) >= 2;
  const allMembersReady =
    roomState !== null &&
    roomState.participants
      .filter((participant) => participant.role === "member")
      .every((participant) => participant.ready);
  const hasNoActiveSession = !sessionIsActive(
    sessionState.snapshot?.status ?? null,
  );
  const quizContentReady =
    roomState === null ||
    roomState.quiz_mode !== "ADAPTIVE" ||
    roomState.active_preparation_status === "READY";
  const connectionEstablished =
    sessionState.connectionStage === "established";
  const noCommandPending =
    sessionState.pendingCommand === null &&
    sessionState.pendingRoomExit === null;
  const lobbyAvailable = lobbyCommandsAreAvailable(sessionState);
  return {
    eligible:
      viewerIsHost &&
      hasMinimumParticipants &&
      allMembersReady &&
      hasNoActiveSession &&
      quizContentReady &&
      connectionEstablished &&
      noCommandPending &&
      lobbyAvailable,
    viewerIsHost,
    hasMinimumParticipants,
    allMembersReady,
    hasNoActiveSession,
    quizContentReady,
    connectionEstablished,
    noCommandPending,
    lobbyAvailable,
  };
}

export function getStartEligibilityMessage(
  eligibility: StartEligibility,
): string {
  if (!eligibility.hasNoActiveSession) {
    return "A server quiz session is already active.";
  }
  if (!eligibility.quizContentReady) {
    return "Generate the quiz and wait for it to be ready.";
  }
  if (!eligibility.connectionEstablished) {
    return "Reconnect before checking start requirements.";
  }
  if (!eligibility.lobbyAvailable) {
    return "Return to the room before starting another quiz.";
  }
  if (!eligibility.noCommandPending) {
    return "Waiting for the server to confirm the room update.";
  }
  if (!eligibility.hasMinimumParticipants) {
    return "Waiting for at least one more participant.";
  }
  if (!eligibility.allMembersReady) {
    return "Waiting for every member to be ready.";
  }
  if (eligibility.eligible) {
    return "Everyone is ready. You can start the quiz.";
  }
  return "Only the host can start the quiz.";
}

export function getConnectionLabel(sessionState: SessionState): string {
  if (sessionState.phase === "reconnecting") {
    return sessionState.reconnectAttempt > 0
      ? `Reconnecting… attempt ${sessionState.reconnectAttempt}`
      : "Reconnecting…";
  }
  if (sessionState.connectionStage === "established") {
    return "Connected";
  }
  if (sessionState.phase === "recoverable-error") {
    return "Connection paused";
  }
  if (sessionState.phase === "fatal-error") {
    return "Connection unavailable";
  }
  return "Connecting…";
}

export type RoomLifecycleControl = {
  kind: "leave" | "close";
  label: string;
  disabled: boolean;
  message: string;
};

export function deriveRoomLifecycleControl(
  sessionState: SessionState,
): RoomLifecycleControl | null {
  const role = sessionState.roomState?.viewer_role;
  if (role === undefined) {
    return null;
  }
  const kind = role === "host" ? "close" : "leave";
  const active = sessionIsActive(sessionState.snapshot?.status ?? null);
  const pending = sessionState.pendingRoomExit;
  const disconnected = sessionState.connectionStage !== "established";
  const conflictingCommand = sessionState.pendingCommand !== null;

  let message =
    kind === "close"
      ? "Closing the room removes every current member. Completed quiz results will remain saved."
      : "Leaving returns you Home. Completed quiz results remain saved.";
  if (active) {
    message = "Finish the current quiz before leaving the room.";
  } else if (pending !== null) {
    message =
      pending === "close" ? "Closing room…" : "Leaving room…";
  } else if (disconnected) {
    message = "Reconnect before changing room membership.";
  } else if (conflictingCommand) {
    message = "Wait for the current room update to finish.";
  }

  return {
    kind,
    label:
      pending === kind
        ? kind === "close"
          ? "Closing Room..."
          : "Leaving Room..."
        : kind === "close"
          ? "Close Room"
          : "Leave Room",
    disabled:
      active || pending !== null || disconnected || conflictingCommand,
    message,
  };
}

export function waitingRoomRouteMatches(
  routeRoomId: string | null,
  sessionState: SessionState,
): boolean {
  if (routeRoomId === null) {
    return false;
  }
  if (sessionState.roomId === routeRoomId) {
    return true;
  }
  return (
    sessionState.roomId === null && sessionState.phase === "recovering-room"
  );
}
