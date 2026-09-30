import {
  BackendApiError,
  getUserFacingErrorMessage,
  StudyRoomApiError,
} from "../../api/errors";
import {
  RoomRealtimeClient,
  type RealtimeClientClose,
  type RealtimeCommand,
} from "../../realtime/client";
import { classifyRealtimeClose } from "../../realtime/closeCodes";
import {
  CommandRejectedError,
  CommandUnavailableError,
  MalformedServerMessageError,
  RealtimeAuthenticationError,
  RealtimeConfigurationError,
  RealtimeNetworkError,
  RealtimeRoomError,
  ReconnectExhaustedError,
  StudyRoomRealtimeError,
} from "../../realtime/errors";
import type {
  CanonicalUuid,
  ServerEvent,
} from "../../realtime/protocol";
import type { RealtimeTransportFactory } from "../../realtime/transport";
import {
  initialSessionState,
  sessionReducer,
  socketIsAuthenticated,
  socketIsEstablished,
  type SessionAction,
  type SessionState,
  type RoomExitKind,
  type SnapshotSource,
} from "./sessionState";

const RECONNECT_BASE_DELAYS_MS = [500, 1_000, 2_000, 4_000, 8_000] as const;
export const REALTIME_BOOTSTRAP_DEADLINE_MS = 8_000;
const JITTER_MINIMUM = 0.8;
const JITTER_RANGE = 0.4;
const COMMAND_ERRORS_REQUIRING_STATE_REPAIR = new Set([
  "answer_too_late",
  "answer_already_submitted",
  "stale_session_question",
  "invalid_option",
  "question_not_open",
  "session_not_active",
  "session_already_active",
  "quiz_not_ready",
  "preparation_conflict",
  "preparation_failed",
  "ai_generation_unavailable",
]);

export type ActiveRoomReference = { id: string };

export type ScheduleTimeout = (
  callback: () => void,
  delayMs: number,
) => () => void;

export type SessionControllerDependencies = {
  apiBaseUrl: string;
  getAccessToken(): Promise<string | null>;
  getActiveRoom(): Promise<ActiveRoomReference | null>;
  refreshAccessToken(): Promise<boolean>;
  onAuthenticationFailure(): Promise<void>;
  leaveRoom(roomId: string): Promise<void>;
  closeRoom(roomId: string): Promise<void>;
  transportFactory?: RealtimeTransportFactory;
  scheduleTimeout?: ScheduleTimeout;
  random?: () => number;
};

export type SessionCommandResult = { status: "sent" };
export type RoomLifecycleCommandResult = { status: "completed" };
export type RequestStateResult =
  | SessionCommandResult
  | { status: "coalesced" };

export type SessionControllerListener = () => void;

function defaultScheduleTimeout(
  callback: () => void,
  delayMs: number,
): () => void {
  const timeout = setTimeout(callback, delayMs);
  return () => clearTimeout(timeout);
}

function mapRecoveryError(error: unknown): StudyRoomRealtimeError {
  if (error instanceof StudyRoomRealtimeError) {
    return error;
  }
  if (error instanceof StudyRoomApiError) {
    switch (error.kind) {
      case "configuration":
        return new RealtimeConfigurationError(
          "MindMesh server configuration is invalid.",
        );
      case "authentication":
        return new RealtimeAuthenticationError(
          "Authentication is required to recover an active room.",
          error.code,
        );
      case "backend":
        if (error instanceof BackendApiError) {
          if (
            error.code === "authentication_required" ||
            error.code === "invalid_auth_token"
          ) {
            return new RealtimeAuthenticationError(
              "Authentication is required to recover an active room.",
              error.code,
            );
          }
          if (
            error.code === "room_not_found" ||
            error.code === "room_closed" ||
            error.code === "not_room_member" ||
            error.code === "profile_required" ||
            error.code === "account_deleted" ||
            error.code === "account_suspended"
          ) {
            return new RealtimeRoomError(
              getUserFacingErrorMessage(error),
              error.code,
            );
          }
        }
        return new RealtimeNetworkError(
          "The active room could not be recovered.",
        );
      case "malformed-response":
        return new MalformedServerMessageError(
          "The MindMesh server returned an invalid active-room response.",
        );
      case "network":
      case "timeout":
        return new RealtimeNetworkError(
          "The active room could not be recovered.",
        );
    }
  }
  return new RealtimeNetworkError("The active room could not be recovered.");
}

function mapLifecycleError(error: unknown): StudyRoomRealtimeError {
  if (error instanceof StudyRoomRealtimeError) {
    return error;
  }
  if (error instanceof BackendApiError) {
    if (
      error.code === "authentication_required" ||
      error.code === "invalid_auth_token"
    ) {
      return new RealtimeAuthenticationError(
        "Authentication is required to update the room lifecycle.",
        error.code,
      );
    }
    return new CommandRejectedError(
      error.code ?? "request_failed",
      getUserFacingErrorMessage(error),
    );
  }
  if (error instanceof StudyRoomApiError) {
    switch (error.kind) {
      case "configuration":
        return new RealtimeConfigurationError(
          "MindMesh server configuration is invalid.",
        );
      case "authentication":
        return new RealtimeAuthenticationError(
          "Authentication is required to update the room lifecycle.",
          error.code ?? "authentication_required",
        );
      case "malformed-response":
        return new MalformedServerMessageError(
          "The MindMesh server returned an invalid room lifecycle response.",
        );
      case "backend":
      case "network":
      case "timeout":
        return new RealtimeNetworkError(
          "The room lifecycle request could not be confirmed.",
        );
    }
  }
  return new RealtimeNetworkError(
    "The room lifecycle request could not be confirmed.",
  );
}

type ExpectedRoomExit = {
  requestId: number;
  roomId: string;
  kind: RoomExitKind;
};

type InFlightRoomExit = {
  requestId: number;
  kind: RoomExitKind;
  promise: Promise<RoomLifecycleCommandResult>;
};

function reconnectDelayMs(attempt: number, randomValue: number): number {
  const baseDelay = RECONNECT_BASE_DELAYS_MS[attempt - 1];
  if (baseDelay === undefined) {
    throw new RangeError("Reconnect attempt is outside the supported range.");
  }
  const boundedRandom = Math.min(1, Math.max(0, randomValue));
  return Math.round(
    baseDelay * (JITTER_MINIMUM + boundedRandom * JITTER_RANGE),
  );
}

export class SessionController {
  private state: SessionState = initialSessionState;
  private readonly dependencies: SessionControllerDependencies;
  private readonly listeners = new Set<SessionControllerListener>();
  private socketClient: RoomRealtimeClient | null = null;
  private selectedRoomId: string | null = null;
  private generation = 0;
  private connectionInFlight = false;
  private authenticated = false;
  private authenticatedUserId: string | null = null;
  private authRevision = -1;
  private appIsActive = true;
  private reconnectAttempts = 0;
  private cancelReconnect: (() => void) | null = null;
  private cancelBootstrapDeadline: (() => void) | null = null;
  private recoveryRequest = 0;
  private refreshRequest = 0;
  private refreshGeneration: number | null = null;
  private refreshInProgress = false;
  private refreshRevisionObserved = false;
  private suppressNextAuthRevision = false;
  private refreshAttemptedSinceEstablishment = false;
  private initialSnapshotSource: SnapshotSource = "new-socket";
  private roomExitRequest = 0;
  private completedRoomExitRequest = 0;
  private expectedRoomExit: ExpectedRoomExit | null = null;
  private inFlightRoomExit: InFlightRoomExit | null = null;
  private disposed = false;

  constructor(dependencies: SessionControllerDependencies) {
    this.dependencies = dependencies;
  }

  readonly getState = (): SessionState => this.state;

  readonly subscribe = (listener: SessionControllerListener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  setAuthenticated(authRevision: number, authenticatedUserId: string): void {
    if (this.disposed) {
      return;
    }
    if (!this.authenticated) {
      this.authenticated = true;
      this.authenticatedUserId = authenticatedUserId;
      this.authRevision = authRevision;
      void this.recoverActiveRoom();
      return;
    }
    if (authenticatedUserId !== this.authenticatedUserId) {
      this.authenticatedUserId = authenticatedUserId;
      this.authRevision = authRevision;
      this.suppressNextAuthRevision = false;
      this.refreshAttemptedSinceEstablishment = false;
      void this.recoverActiveRoom();
      return;
    }
    if (authRevision === this.authRevision) {
      return;
    }

    this.authRevision = authRevision;
    if (this.suppressNextAuthRevision) {
      this.suppressNextAuthRevision = false;
      return;
    }
    if (this.refreshInProgress) {
      this.refreshRevisionObserved = true;
      return;
    }
    this.refreshAttemptedSinceEstablishment = false;
    if (this.selectedRoomId !== null && this.appIsActive) {
      this.rotateSelectedRoomSocket("new-socket");
    }
  }

  setSignedOut(): void {
    if (this.disposed || (!this.authenticated && this.selectedRoomId === null)) {
      return;
    }
    this.authenticated = false;
    this.authenticatedUserId = null;
    this.authRevision = -1;
    this.suppressNextAuthRevision = false;
    this.refreshAttemptedSinceEstablishment = false;
    this.cancelRoomExitRequest();
    this.selectedRoomId = null;
    this.reconnectAttempts = 0;
    this.recoveryRequest += 1;
    this.refreshRequest += 1;
    const generation = this.invalidateSocket();
    this.dispatch({ type: "SIGNED_OUT", generation });
  }

  async recoverActiveRoom(): Promise<void> {
    if (this.disposed) {
      return;
    }
    if (!this.authenticated) {
      throw new CommandUnavailableError(
        "RECOVER_ACTIVE_ROOM",
        "Authentication is required to recover an active room.",
      );
    }

    this.cancelRoomExitRequest();
    this.selectedRoomId = null;
    this.reconnectAttempts = 0;
    this.refreshAttemptedSinceEstablishment = false;
    const generation = this.invalidateSocket();
    const request = ++this.recoveryRequest;
    this.dispatch({ type: "RECOVERY_STARTED", generation });

    try {
      const room = await this.dependencies.getActiveRoom();
      if (!this.recoveryIsCurrent(request, generation)) {
        return;
      }
      if (room === null) {
        this.dispatch({ type: "RECOVERY_FOUND_NO_ROOM", generation });
        return;
      }
      this.selectedRoomId = room.id;
      this.dispatch({ type: "ROOM_SELECTED", roomId: room.id, generation });
      if (this.appIsActive) {
        void this.openSocket("room-recovery", false);
      }
    } catch (error: unknown) {
      if (!this.recoveryIsCurrent(request, generation)) {
        return;
      }
      this.dispatch({
        type: "RECOVERY_FAILED",
        generation,
        error: mapRecoveryError(error),
      });
    }
  }

  selectRoom(roomId: string): void {
    if (this.disposed) {
      return;
    }
    if (!this.authenticated) {
      throw new CommandUnavailableError(
        "SELECT_ROOM",
        "Authentication is required to select a room.",
      );
    }
    if (roomId === this.selectedRoomId) {
      if (
        this.socketClient === null &&
        !this.connectionInFlight &&
        this.appIsActive
      ) {
        void this.openSocket("new-socket", this.state.snapshot !== null);
      }
      return;
    }

    this.cancelRoomExitRequest();
    this.recoveryRequest += 1;
    this.reconnectAttempts = 0;
    this.refreshAttemptedSinceEstablishment = false;
    const generation = this.invalidateSocket();
    this.selectedRoomId = roomId;
    this.dispatch({ type: "ROOM_SELECTED", roomId, generation });
    if (this.appIsActive) {
      void this.openSocket("new-socket", false);
    }
  }

  clearRoom(): void {
    if (this.disposed) {
      return;
    }
    this.cancelRoomExitRequest();
    this.selectedRoomId = null;
    this.recoveryRequest += 1;
    this.reconnectAttempts = 0;
    this.refreshAttemptedSinceEstablishment = false;
    const generation = this.invalidateSocket();
    this.dispatch({ type: "ROOM_CLEARED", generation });
  }

  retryConnection(): void {
    if (
      this.disposed ||
      !this.authenticated ||
      this.expectedRoomExit !== null
    ) {
      return;
    }
    if (this.selectedRoomId === null) {
      void this.recoverActiveRoom();
      return;
    }
    this.reconnectAttempts = 0;
    this.refreshAttemptedSinceEstablishment = false;
    const generation = this.invalidateSocket();
    this.dispatch({
      type: "SOCKET_CONNECTING",
      generation,
      reconnecting: this.state.snapshot !== null,
    });
    if (this.appIsActive) {
      void this.openSocket("new-socket", true);
    }
  }

  setAppState(appState: "active" | "inactive" | "background"): void {
    if (this.disposed) {
      return;
    }
    const nextActive = appState === "active";
    if (nextActive === this.appIsActive) {
      return;
    }
    this.appIsActive = nextActive;
    if (!nextActive) {
      this.reconnectAttempts = 0;
      this.invalidateSocket();
      return;
    }
    if (this.authenticated && this.selectedRoomId !== null) {
      void this.openSocket("new-socket", true);
    }
  }

  requestState(): RequestStateResult {
    this.requireAuthenticatedSocket("REQUEST_STATE");
    if (this.state.pendingSnapshotRequest !== null) {
      return { status: "coalesced" };
    }
    const generation = this.generation;
    this.dispatch({
      type: "SNAPSHOT_REQUEST_STARTED",
      generation,
      reason: "manual",
    });
    try {
      this.sendCommand({ type: "REQUEST_STATE" });
      return { status: "sent" };
    } catch (error: unknown) {
      this.dispatch({ type: "SNAPSHOT_REQUEST_FAILED", generation });
      throw error;
    }
  }

  setReady(ready: boolean): SessionCommandResult {
    this.requireEstablishedSocket("SET_READY");
    if (this.state.phase !== "waiting") {
      throw new CommandUnavailableError(
        "SET_READY",
        "Readiness can only change in the waiting room.",
      );
    }
    this.requireNoPendingCommand("SET_READY");
    const generation = this.generation;
    this.dispatch({ type: "READY_COMMAND_STARTED", generation, ready });
    return this.sendGuardedCommand({ type: "SET_READY", ready }, generation);
  }

  startSession(): SessionCommandResult {
    this.requireEstablishedSocket("START_SESSION");
    if (this.state.phase !== "waiting") {
      throw new CommandUnavailableError(
        "START_SESSION",
        "A quiz can only start from the waiting room.",
      );
    }
    if (this.state.roomState?.viewer_role !== "host") {
      throw new CommandUnavailableError(
        "START_SESSION",
        "Only the room host can start the quiz.",
      );
    }
    this.requireNoPendingCommand("START_SESSION");
    const generation = this.generation;
    this.dispatch({
      type: "START_COMMAND_STARTED",
      generation,
      previousSessionId: this.state.snapshot?.session_id ?? null,
    });
    return this.sendGuardedCommand({ type: "START_SESSION" }, generation);
  }

  submitAnswer(
    sessionQuestionId: CanonicalUuid,
    selectedOptionId: string,
  ): SessionCommandResult {
    this.requireEstablishedSocket("SUBMIT_ANSWER");
    const snapshot = this.state.snapshot;
    if (this.state.phase !== "question-open" || snapshot?.status !== "QUESTION_OPEN") {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "An answer can only be submitted while the current question is open.",
      );
    }
    if (snapshot.question.session_question_id !== sessionQuestionId) {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "The answer does not belong to the current question.",
      );
    }
    if (snapshot.question.question_type !== "MULTIPLE_CHOICE") {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "This question requires a typed answer.",
      );
    }
    if (
      !snapshot.question.options.some((option) => option.id === selectedOptionId)
    ) {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "The selected answer is not an option for the current question.",
      );
    }
    if (snapshot.viewer_submission !== null || this.state.acknowledgedAnswer !== null) {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "An answer has already been accepted for the current question.",
      );
    }
    this.requireNoPendingCommand("SUBMIT_ANSWER");

    const generation = this.generation;
    this.dispatch({
      type: "ANSWER_COMMAND_STARTED",
      generation,
      sessionId: snapshot.session_id,
      sessionQuestionId,
      selectedOptionId,
      answerText: null,
    });
    return this.sendGuardedCommand(
      {
        type: "SUBMIT_ANSWER",
        sessionQuestionId,
        answer: { type: "choice", optionId: selectedOptionId },
      },
      generation,
    );
  }

  submitTextAnswer(
    sessionQuestionId: CanonicalUuid,
    text: string,
  ): SessionCommandResult {
    this.requireEstablishedSocket("SUBMIT_ANSWER");
    const snapshot = this.state.snapshot;
    if (this.state.phase !== "question-open" || snapshot?.status !== "QUESTION_OPEN") {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "An answer can only be submitted while the current question is open.",
      );
    }
    if (snapshot.question.session_question_id !== sessionQuestionId) {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "The answer does not belong to the current question.",
      );
    }
    if (snapshot.question.question_type === "MULTIPLE_CHOICE") {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "This question requires choosing one of the listed options.",
      );
    }
    const answerText = text.trim();
    if (answerText.length === 0) {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "Type an answer before submitting.",
      );
    }
    if (answerText.length > 1000) {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "The answer is too long. Written answers allow up to 1000 characters.",
      );
    }
    if (snapshot.viewer_submission !== null || this.state.acknowledgedAnswer !== null) {
      throw new CommandUnavailableError(
        "SUBMIT_ANSWER",
        "An answer has already been accepted for the current question.",
      );
    }
    this.requireNoPendingCommand("SUBMIT_ANSWER");

    const generation = this.generation;
    this.dispatch({
      type: "ANSWER_COMMAND_STARTED",
      generation,
      sessionId: snapshot.session_id,
      sessionQuestionId,
      selectedOptionId: null,
      answerText,
    });
    return this.sendGuardedCommand(
      {
        type: "SUBMIT_ANSWER",
        sessionQuestionId,
        answer: { type: "text", text: answerText },
      },
      generation,
    );
  }

  prepareQuiz(requestId: string): SessionCommandResult {
    this.requireEstablishedSocket("PREPARE_QUIZ");
    if (this.state.phase !== "waiting") {
      throw new CommandUnavailableError(
        "PREPARE_QUIZ",
        "Quiz preparation is only available in the waiting room.",
      );
    }
    if (this.state.roomState?.quiz_mode !== "ADAPTIVE") {
      throw new CommandUnavailableError(
        "PREPARE_QUIZ",
        "Quiz preparation is only available for adaptive GCSE rooms.",
      );
    }
    if (this.state.roomState?.viewer_role !== "host") {
      throw new CommandUnavailableError(
        "PREPARE_QUIZ",
        "Only the room host can generate the quiz.",
      );
    }
    if (requestId.trim().length === 0) {
      throw new CommandUnavailableError(
        "PREPARE_QUIZ",
        "A preparation request ID is required.",
      );
    }
    this.requireNoPendingCommand("PREPARE_QUIZ");
    const generation = this.generation;
    this.dispatch({ type: "PREPARE_COMMAND_STARTED", generation, requestId });
    return this.sendGuardedCommand({ type: "PREPARE_QUIZ", requestId }, generation);
  }

  retryGrading(): SessionCommandResult {
    this.requireEstablishedSocket("RETRY_GRADING");
    if (this.state.phase !== "grading") {
      throw new CommandUnavailableError(
        "RETRY_GRADING",
        "Grading can only be retried while marking is delayed.",
      );
    }
    if (this.state.roomState?.viewer_role !== "host") {
      throw new CommandUnavailableError(
        "RETRY_GRADING",
        "Only the room host can retry marking.",
      );
    }
    this.requireNoPendingCommand("RETRY_GRADING");
    const generation = this.generation;
    this.dispatch({ type: "RETRY_GRADING_COMMAND_STARTED", generation });
    return this.sendGuardedCommand({ type: "RETRY_GRADING" }, generation);
  }

  dismissFinishedSession(): void {
    this.dispatch({ type: "DISMISS_FINISHED_SESSION" });
  }

  leaveCurrentRoom(): Promise<RoomLifecycleCommandResult> {
    return this.beginRoomExit("leave");
  }

  closeCurrentRoom(): Promise<RoomLifecycleCommandResult> {
    return this.beginRoomExit("close");
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.setSignedOut();
    this.disposed = true;
    this.listeners.clear();
  }

  private dispatch(action: SessionAction): void {
    const nextState = sessionReducer(this.state, action);
    if (nextState === this.state) {
      return;
    }
    this.state = nextState;
    for (const listener of this.listeners) {
      listener();
    }
  }

  private beginRoomExit(
    kind: RoomExitKind,
  ): Promise<RoomLifecycleCommandResult> {
    const inFlight = this.inFlightRoomExit;
    if (inFlight !== null) {
      if (inFlight.kind === kind) {
        return inFlight.promise;
      }
      throw new CommandUnavailableError(
        kind === "leave" ? "LEAVE_ROOM" : "CLOSE_ROOM",
        "Another room lifecycle request is already pending.",
      );
    }
    this.requireEstablishedSocket(
      kind === "leave" ? "LEAVE_ROOM" : "CLOSE_ROOM",
    );
    const roomId = this.selectedRoomId;
    if (roomId === null || this.state.roomState?.room_id !== roomId) {
      throw new CommandUnavailableError(
        kind === "leave" ? "LEAVE_ROOM" : "CLOSE_ROOM",
        "An authoritative room is required for this action.",
      );
    }
    const activeStatus = this.state.snapshot?.status;
    if (
      activeStatus === "QUESTION_OPEN" ||
      activeStatus === "QUESTION_GRADING" ||
      activeStatus === "QUESTION_REVEAL"
    ) {
      throw new CommandUnavailableError(
        kind === "leave" ? "LEAVE_ROOM" : "CLOSE_ROOM",
        "Finish the current quiz before leaving the room.",
      );
    }
    if (this.state.pendingCommand !== null) {
      throw new CommandUnavailableError(
        kind === "leave" ? "LEAVE_ROOM" : "CLOSE_ROOM",
        "Another authoritative command is still unresolved.",
      );
    }
    const viewerRole = this.state.roomState.viewer_role;
    if (kind === "leave" && viewerRole !== "member") {
      throw new CommandUnavailableError(
        "LEAVE_ROOM",
        "The room host must close the room instead of leaving it.",
      );
    }
    if (kind === "close" && viewerRole !== "host") {
      throw new CommandUnavailableError(
        "CLOSE_ROOM",
        "Only the room host can close the room.",
      );
    }

    const requestId = ++this.roomExitRequest;
    this.expectedRoomExit = {
      requestId,
      roomId,
      kind,
    };
    this.dispatch({
      type: "ROOM_EXIT_STARTED",
      generation: this.generation,
      kind,
    });
    const promise = this.executeRoomExit(requestId, roomId, kind);
    this.inFlightRoomExit = { requestId, kind, promise };
    return promise;
  }

  private async executeRoomExit(
    requestId: number,
    roomId: string,
    kind: RoomExitKind,
  ): Promise<RoomLifecycleCommandResult> {
    try {
      if (kind === "leave") {
        await this.dependencies.leaveRoom(roomId);
      } else {
        await this.dependencies.closeRoom(roomId);
      }
      if (this.roomExitIsCurrent(requestId, roomId)) {
        this.completeRoomExit(requestId);
      }
      return { status: "completed" };
    } catch (error: unknown) {
      if (this.completedRoomExitRequest === requestId) {
        return { status: "completed" };
      }
      const safeError = mapLifecycleError(error);
      if (this.roomExitIsCurrent(requestId, roomId)) {
        this.expectedRoomExit = null;
        this.dispatch({
          type: "ROOM_EXIT_FAILED",
          generation: this.generation,
          error: safeError,
        });
        if (
          this.appIsActive &&
          (this.socketClient === null || !this.socketClient.isEstablished)
        ) {
          this.rotateSelectedRoomSocket("new-socket");
        }
      }
      throw safeError;
    } finally {
      if (this.inFlightRoomExit?.requestId === requestId) {
        this.inFlightRoomExit = null;
      }
    }
  }

  private roomExitIsCurrent(requestId: number, roomId: string): boolean {
    return (
      !this.disposed &&
      this.expectedRoomExit?.requestId === requestId &&
      this.expectedRoomExit.roomId === roomId &&
      this.selectedRoomId === roomId
    );
  }

  private completeRoomExit(requestId: number): void {
    const expected = this.expectedRoomExit;
    if (expected === null || expected.requestId !== requestId) {
      return;
    }
    this.completedRoomExitRequest = requestId;
    this.expectedRoomExit = null;
    this.selectedRoomId = null;
    this.recoveryRequest += 1;
    this.reconnectAttempts = 0;
    this.refreshAttemptedSinceEstablishment = false;
    const generation = this.invalidateSocket();
    this.dispatch({ type: "ROOM_CLEARED", generation });
  }

  private cancelRoomExitRequest(): void {
    this.roomExitRequest += 1;
    this.expectedRoomExit = null;
    this.inFlightRoomExit = null;
  }

  private serverErrorConfirmsRoomExit(code: string): boolean {
    const expected = this.expectedRoomExit;
    if (expected === null) {
      return false;
    }
    const matches =
      (expected.kind === "leave" && code === "room_left") ||
      (expected.kind === "close" && code === "room_closed");
    return matches;
  }

  private recoveryIsCurrent(request: number, generation: number): boolean {
    return (
      !this.disposed &&
      this.authenticated &&
      request === this.recoveryRequest &&
      generation === this.generation
    );
  }

  private invalidateSocket(): number {
    this.cancelReconnectTimer();
    this.cancelConnectionBootstrapDeadline();
    this.refreshRequest += 1;
    this.refreshGeneration = null;
    this.refreshInProgress = false;
    this.refreshRevisionObserved = false;
    const previousClient = this.socketClient;
    this.socketClient = null;
    this.connectionInFlight = false;
    this.generation += 1;
    this.dispatch({ type: "SOCKET_INVALIDATED", generation: this.generation });
    previousClient?.close();
    return this.generation;
  }

  private rotateSelectedRoomSocket(source: SnapshotSource): void {
    if (this.selectedRoomId === null) {
      return;
    }
    const generation = this.invalidateSocket();
    this.dispatch({
      type: "SOCKET_CONNECTING",
      generation,
      reconnecting: true,
    });
    if (this.appIsActive) {
      void this.openSocket(source, true);
    }
  }

  private async openSocket(
    source: SnapshotSource,
    reconnecting: boolean,
  ): Promise<void> {
    if (
      this.disposed ||
      !this.authenticated ||
      !this.appIsActive ||
      this.selectedRoomId === null ||
      this.expectedRoomExit !== null ||
      this.socketClient !== null ||
      this.connectionInFlight
    ) {
      return;
    }

    const generation = this.generation;
    const roomId = this.selectedRoomId;
    this.connectionInFlight = true;
    this.initialSnapshotSource = source;
    this.dispatch({ type: "SOCKET_CONNECTING", generation, reconnecting });
    this.startConnectionBootstrapDeadline(generation);

    let accessToken: string | null;
    try {
      accessToken = await this.dependencies.getAccessToken();
    } catch {
      accessToken = null;
    }
    if (
      this.disposed ||
      generation !== this.generation ||
      roomId !== this.selectedRoomId ||
      !this.authenticated ||
      !this.appIsActive ||
      this.expectedRoomExit !== null
    ) {
      return;
    }
    this.connectionInFlight = false;
    if (accessToken === null) {
      await this.failAuthentication(
        new RealtimeAuthenticationError(
          "A valid authentication session is required for realtime rooms.",
        ),
      );
      return;
    }

    const client = new RoomRealtimeClient({
      apiBaseUrl: this.dependencies.apiBaseUrl,
      roomId,
      accessToken,
      generation,
      isGenerationCurrent: (candidate) => candidate === this.generation,
      callbacks: {
        onEvent: (event, callbackGeneration) =>
          this.handleServerEvent(event, callbackGeneration),
        onEstablished: (callbackGeneration) =>
          this.handleEstablished(callbackGeneration),
        onFailure: (error, callbackGeneration) =>
          this.handleClientFailure(error, callbackGeneration),
        onTransportError: (error, callbackGeneration) =>
          this.handleClientFailure(error, callbackGeneration),
        onClose: (event, callbackGeneration) =>
          this.handleSocketClose(event, callbackGeneration),
      },
      ...(this.dependencies.transportFactory === undefined
        ? {}
        : { transportFactory: this.dependencies.transportFactory }),
    });
    this.socketClient = client;
    client.connect();
  }

  private handleServerEvent(event: ServerEvent, generation: number): void {
    if (generation !== this.generation || this.disposed) {
      return;
    }
    switch (event.type) {
      case "CONNECTED":
        this.dispatch({
          type: "CONNECTED_RECEIVED",
          generation,
          serverTime: event.payload.server_time,
        });
        return;
      case "ROOM_STATE":
        this.dispatch({
          type: "ROOM_STATE_RECEIVED",
          generation,
          roomState: event.payload,
        });
        return;
      case "STATE_SNAPSHOT": {
        const source = this.snapshotSource(generation);
        this.dispatch({
          type: "SNAPSHOT_RECEIVED",
          generation,
          snapshot: event.payload,
          source,
        });
        this.requestExpectedSnapshotRepair(generation);
        return;
      }
      case "SESSION_STARTED":
      case "QUESTION_OPENED":
      case "QUESTION_REVEALED":
      case "SESSION_FINISHED": {
        const hadPendingRequest = this.state.pendingSnapshotRequest !== null;
        this.dispatch({
          type: "TRANSITION_HINT_RECEIVED",
          generation,
          sessionId: event.payload.session_id,
          stateVersion: event.payload.state_version,
        });
        this.sendReducerRequestedSnapshot(hadPendingRequest, generation);
        return;
      }
      case "ANSWER_ACCEPTED": {
        const hadPendingRequest = this.state.pendingSnapshotRequest !== null;
        this.dispatch({
          type: "ANSWER_ACCEPTED_RECEIVED",
          generation,
          acknowledgement: event.payload,
        });
        this.sendReducerRequestedSnapshot(hadPendingRequest, generation);
        return;
      }
      case "ERROR":
        if (this.serverErrorConfirmsRoomExit(event.payload.code)) {
          const requestId = this.expectedRoomExit?.requestId;
          if (requestId !== undefined) {
            this.completeRoomExit(requestId);
          }
          return;
        }
        this.dispatch({
          type: "COMMAND_REJECTED",
          generation,
          error: new CommandRejectedError(
            event.payload.code,
            event.payload.message,
          ),
        });
        if (COMMAND_ERRORS_REQUIRING_STATE_REPAIR.has(event.payload.code)) {
          this.requestStateAfterCommandError(generation);
        }
        return;
    }
  }

  private snapshotSource(generation: number): SnapshotSource {
    if (this.state.pendingSnapshotRequest?.generation === generation) {
      return "requested";
    }
    if (this.state.lastSnapshotGeneration !== generation) {
      return this.initialSnapshotSource;
    }
    return "unsolicited";
  }

  private sendReducerRequestedSnapshot(
    hadPendingRequest: boolean,
    generation: number,
  ): void {
    if (
      hadPendingRequest ||
      this.state.pendingSnapshotRequest?.generation !== generation
    ) {
      return;
    }
    try {
      this.sendCommand({ type: "REQUEST_STATE" });
    } catch (error: unknown) {
      this.dispatch({ type: "SNAPSHOT_REQUEST_FAILED", generation });
      if (error instanceof RealtimeNetworkError) {
        this.scheduleReconnect(error, generation);
      }
    }
  }

  private requestExpectedSnapshotRepair(generation: number): void {
    if (
      generation !== this.generation ||
      this.disposed ||
      this.state.pendingSnapshotRequest !== null
    ) {
      return;
    }
    const expectedSnapshot = this.state.expectedSnapshot;
    if (expectedSnapshot === null) {
      return;
    }
    const snapshot = this.state.snapshot;
    if (
      snapshot !== null &&
      snapshot.session_id === expectedSnapshot.sessionId &&
      snapshot.state_version >= expectedSnapshot.stateVersion
    ) {
      return;
    }

    this.dispatch({
      type: "SNAPSHOT_REQUEST_STARTED",
      generation,
      reason: "transition",
    });
    try {
      this.sendCommand({ type: "REQUEST_STATE" });
    } catch (error: unknown) {
      this.dispatch({ type: "SNAPSHOT_REQUEST_FAILED", generation });
      if (error instanceof RealtimeNetworkError) {
        this.scheduleReconnect(error, generation);
      }
    }
  }

  private requestStateAfterCommandError(generation: number): void {
    if (
      generation !== this.generation ||
      this.state.pendingSnapshotRequest !== null
    ) {
      return;
    }
    this.dispatch({
      type: "SNAPSHOT_REQUEST_STARTED",
      generation,
      reason: "manual",
    });
    try {
      this.sendCommand({ type: "REQUEST_STATE" });
    } catch {
      this.dispatch({ type: "SNAPSHOT_REQUEST_FAILED", generation });
    }
  }

  private handleEstablished(generation: number): void {
    if (generation !== this.generation || this.disposed) {
      return;
    }
    if (this.expectedRoomExit !== null) {
      return;
    }
    this.cancelConnectionBootstrapDeadline();
    this.reconnectAttempts = 0;
    this.refreshAttemptedSinceEstablishment = false;
    this.suppressNextAuthRevision = false;
  }

  private handleClientFailure(
    error: StudyRoomRealtimeError,
    generation: number,
  ): void {
    if (generation !== this.generation || this.disposed) {
      return;
    }
    if (this.expectedRoomExit !== null) {
      return;
    }
    if (error.kind === "network") {
      this.scheduleReconnect(error, generation);
      return;
    }
    this.stopWithFatalError(error, false);
  }

  private handleSocketClose(
    close: RealtimeClientClose,
    generation: number,
  ): void {
    if (generation !== this.generation || this.disposed || close.intentional) {
      return;
    }
    this.socketClient = null;
    this.connectionInFlight = false;
    const classification = classifyRealtimeClose(
      close.code,
      close.serverError?.code,
    );
    const expectedExit = this.expectedRoomExit;
    if (expectedExit !== null) {
      if (classification.action === "stop-room") {
        this.completeRoomExit(expectedExit.requestId);
      } else {
        this.dispatch({ type: "ROOM_EXIT_SOCKET_CLOSED", generation });
      }
      return;
    }
    switch (classification.action) {
      case "retry":
        this.scheduleReconnect(classification.error, generation);
        return;
      case "refresh-authentication":
        this.dispatch({
          type: "CONNECTION_LOST",
          generation,
          attempt: this.reconnectAttempts,
          error: classification.error,
        });
        void this.refreshAuthentication(generation);
        return;
      case "stop-room":
        this.selectedRoomId = null;
        this.stopWithFatalError(classification.error, true);
        return;
      case "stop-connection-limit":
      case "stop-protocol":
        this.stopWithFatalError(classification.error, false);
        return;
    }
  }

  private scheduleReconnect(
    error: StudyRoomRealtimeError,
    generation: number,
  ): void {
    if (
      generation !== this.generation ||
      this.disposed ||
      !this.authenticated ||
      !this.appIsActive ||
      this.selectedRoomId === null ||
      this.expectedRoomExit !== null
    ) {
      return;
    }
    if (this.cancelReconnect !== null) {
      return;
    }
    if (this.reconnectAttempts >= RECONNECT_BASE_DELAYS_MS.length) {
      const nextGeneration = this.invalidateSocket();
      this.dispatch({
        type: "RECOVERABLE_FAILURE",
        generation: nextGeneration,
        error: new ReconnectExhaustedError(),
      });
      return;
    }

    this.reconnectAttempts += 1;
    const attempt = this.reconnectAttempts;
    const nextGeneration = this.invalidateSocket();
    this.dispatch({
      type: "CONNECTION_LOST",
      generation: nextGeneration,
      attempt,
      error,
    });
    const delay = reconnectDelayMs(attempt, this.random());
    this.cancelReconnect = this.scheduleTimeout(() => {
      this.cancelReconnect = null;
      if (
        this.disposed ||
        nextGeneration !== this.generation ||
        !this.authenticated ||
        !this.appIsActive ||
        this.selectedRoomId === null ||
        this.expectedRoomExit !== null
      ) {
        return;
      }
      void this.openSocket("new-socket", true);
    }, delay);
  }

  private async refreshAuthentication(generation: number): Promise<void> {
    if (
      generation !== this.generation ||
      this.refreshGeneration === generation ||
      this.disposed
    ) {
      return;
    }
    if (this.refreshAttemptedSinceEstablishment) {
      await this.failAuthentication(
        new RealtimeAuthenticationError(
          "The refreshed authentication session was rejected.",
        ),
      );
      return;
    }
    this.refreshAttemptedSinceEstablishment = true;
    this.refreshGeneration = generation;
    this.refreshInProgress = true;
    this.refreshRevisionObserved = false;
    const request = ++this.refreshRequest;

    let refreshed = false;
    try {
      refreshed = await this.dependencies.refreshAccessToken();
    } catch {
      refreshed = false;
    }
    if (
      this.disposed ||
      request !== this.refreshRequest ||
      generation !== this.generation
    ) {
      return;
    }
    this.refreshInProgress = false;
    if (!refreshed) {
      await this.failAuthentication(
        new RealtimeAuthenticationError(
          "The authentication session could not be refreshed.",
        ),
      );
      return;
    }

    this.suppressNextAuthRevision = !this.refreshRevisionObserved;
    this.rotateSelectedRoomSocket("new-socket");
  }

  private async failAuthentication(
    error: RealtimeAuthenticationError,
  ): Promise<void> {
    this.selectedRoomId = null;
    const generation = this.invalidateSocket();
    this.dispatch({
      type: "FATAL_FAILURE",
      generation,
      error,
      clearRoom: true,
    });
    try {
      await this.dependencies.onAuthenticationFailure();
    } finally {
      if (!this.disposed) {
        this.authenticated = false;
        this.dispatch({ type: "SIGNED_OUT", generation: this.generation });
      }
    }
  }

  private stopWithFatalError(
    error: StudyRoomRealtimeError,
    clearRoom: boolean,
  ): void {
    const generation = this.invalidateSocket();
    this.dispatch({
      type: "FATAL_FAILURE",
      generation,
      error,
      clearRoom,
    });
  }

  private requireAuthenticatedSocket(command: string): void {
    if (
      !socketIsAuthenticated(this.state) ||
      this.socketClient === null ||
      !this.socketClient.isAuthenticated
    ) {
      throw new CommandUnavailableError(
        command,
        "The realtime command requires an authenticated connection.",
      );
    }
  }

  private requireEstablishedSocket(command: string): void {
    this.requireAuthenticatedSocket(command);
    if (!socketIsEstablished(this.state) || !this.socketClient?.isEstablished) {
      throw new CommandUnavailableError(
        command,
        "The realtime command requires an authoritative server snapshot.",
      );
    }
  }

  private requireNoPendingCommand(command: string): void {
    if (
      this.state.pendingCommand !== null ||
      this.state.pendingRoomExit !== null
    ) {
      throw new CommandUnavailableError(
        command,
        "Another authoritative command is still unresolved.",
      );
    }
  }

  private sendGuardedCommand(
    command: RealtimeCommand,
    generation: number,
  ): SessionCommandResult {
    try {
      this.sendCommand(command);
      return { status: "sent" };
    } catch (error: unknown) {
      const safeError =
        error instanceof StudyRoomRealtimeError
          ? error
          : new RealtimeNetworkError("The realtime command could not be sent.");
      this.dispatch({ type: "COMMAND_REJECTED", generation, error: safeError });
      throw safeError;
    }
  }

  private sendCommand(command: RealtimeCommand): void {
    const client = this.socketClient;
    if (client === null) {
      throw new CommandUnavailableError(
        command.type,
        "The realtime connection is unavailable.",
      );
    }
    client.sendCommand(command);
  }

  private cancelReconnectTimer(): void {
    const cancel = this.cancelReconnect;
    this.cancelReconnect = null;
    cancel?.();
  }

  private startConnectionBootstrapDeadline(generation: number): void {
    this.cancelConnectionBootstrapDeadline();
    this.cancelBootstrapDeadline = this.scheduleTimeout(() => {
      this.cancelBootstrapDeadline = null;
      if (
        generation !== this.generation ||
        this.disposed ||
        !this.authenticated ||
        !this.appIsActive ||
        this.selectedRoomId === null ||
        this.expectedRoomExit !== null ||
        socketIsEstablished(this.state)
      ) {
        return;
      }
      this.scheduleReconnect(
        new RealtimeNetworkError(
          "The realtime connection did not establish in time.",
        ),
        generation,
      );
    }, REALTIME_BOOTSTRAP_DEADLINE_MS);
  }

  private cancelConnectionBootstrapDeadline(): void {
    const cancel = this.cancelBootstrapDeadline;
    this.cancelBootstrapDeadline = null;
    cancel?.();
  }

  private random(): number {
    return (this.dependencies.random ?? Math.random)();
  }

  private scheduleTimeout(callback: () => void, delayMs: number): () => void {
    return (this.dependencies.scheduleTimeout ?? defaultScheduleTimeout)(
      callback,
      delayMs,
    );
  }
}

export { reconnectDelayMs };
