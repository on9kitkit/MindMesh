import {
  BackendApiError,
  getUserFacingErrorMessage,
} from "../../api/errors";
import {
  InvalidJoinCodeError,
  normalizeJoinCode,
} from "../../api/rooms";
import type {
  CreateRoomInput,
  JoinByCodeResponse,
  QuizSettingsInput,
  RoomResponse,
} from "../../api/schemas";
import {
  DEFAULT_TOTAL_MARKS,
  getAdaptiveSelectionValidationMessage,
  getSubjectLabel,
  getTopicLabel,
  type AdaptiveSubject,
  type AdaptiveTopic,
} from "../quiz/adaptiveQuiz";
import { getSessionErrorMessage } from "../session/sessionErrorMessages";
import type { SessionState } from "../session/sessionState";

export type RoomCapacityPreset = "standard" | "large";

export const DEFAULT_ROOM_CAPACITY_PRESET: RoomCapacityPreset = "standard";

const ROOM_CAPACITIES: Readonly<Record<RoomCapacityPreset, number>> = {
  standard: 8,
  large: 20,
};

export function createRoomInputForPreset(
  preset: RoomCapacityPreset,
): CreateRoomInput {
  return {
    name: "Physics Sprint",
    maximum_members: ROOM_CAPACITIES[preset],
  };
}

export type QuizModeSelection =
  | { mode: "legacy" }
  | {
      mode: "adaptive";
      subject: AdaptiveSubject;
      topic: AdaptiveTopic;
      totalMarks: number;
    };

export const DEFAULT_QUIZ_MODE_SELECTION: QuizModeSelection = {
  mode: "legacy",
};

export const DEFAULT_ADAPTIVE_SELECTION: Extract<
  QuizModeSelection,
  { mode: "adaptive" }
> = {
  mode: "adaptive",
  subject: "physics",
  topic: "energy",
  totalMarks: DEFAULT_TOTAL_MARKS,
};

export function getQuizSelectionValidationMessage(
  selection: QuizModeSelection,
): string | null {
  if (selection.mode === "legacy") {
    return null;
  }
  return getAdaptiveSelectionValidationMessage(selection);
}

export function isQuizSelectionValid(selection: QuizModeSelection): boolean {
  return getQuizSelectionValidationMessage(selection) === null;
}

function adaptiveRoomName(
  subject: AdaptiveSubject,
  topic: AdaptiveTopic,
): string {
  const subjectLabel = getSubjectLabel(subject) ?? subject;
  const topicLabel = getTopicLabel(topic) ?? topic;
  return `GCSE ${subjectLabel}: ${topicLabel}`.slice(0, 60);
}

export function createRoomInputForSelection(
  preset: RoomCapacityPreset,
  selection: QuizModeSelection,
): CreateRoomInput {
  if (selection.mode === "legacy") {
    return createRoomInputForPreset(preset);
  }
  const quizSettings: QuizSettingsInput = {
    mode: "adaptive",
    level: "gcse",
    subject: selection.subject,
    topic: selection.topic,
    total_marks: selection.totalMarks,
  };
  return {
    name: adaptiveRoomName(selection.subject, selection.topic),
    maximum_members: ROOM_CAPACITIES[preset],
    quiz_settings: quizSettings,
  };
}

export function roomCapacityIsAvailable(
  preset: RoomCapacityPreset,
  isPro: boolean,
): boolean {
  return preset === "standard" || isPro;
}

export function reconcileRoomCapacityPreset(
  preset: RoomCapacityPreset,
  isPro: boolean,
): RoomCapacityPreset {
  return roomCapacityIsAvailable(preset, isPro)
    ? preset
    : DEFAULT_ROOM_CAPACITY_PRESET;
}

const EXISTING_ROOM_CONFLICTS = new Set([
  "already_room_member",
  "user_already_in_another_room",
]);

export const JOIN_CODE_HELP = "Use six characters: A–Z and 2–9.";

export type HomeOperationState =
  | { status: "idle"; joinCode: string; joinTouched: boolean }
  | { status: "creating-room"; joinCode: string; joinTouched: boolean }
  | { status: "joining-room"; joinCode: string; joinTouched: boolean }
  | { status: "selecting-room"; roomId: string; joinCode: ""; joinTouched: false }
  | {
      status: "error";
      joinCode: string;
      joinTouched: boolean;
      message: string;
      code?: string;
    };

export type HomeOperationAction =
  | { type: "JOIN_CODE_CHANGED"; value: string }
  | { type: "CREATE_REQUESTED" }
  | { type: "JOIN_REQUESTED" }
  | { type: "ROOM_SELECTED"; roomId: string }
  | { type: "REQUEST_COMPLETED" }
  | { type: "REQUEST_FAILED"; message: string; code?: string };

export const initialHomeOperationState: HomeOperationState = {
  status: "idle",
  joinCode: "",
  joinTouched: false,
};

function requestIsPending(state: HomeOperationState): boolean {
  return (
    state.status === "creating-room" ||
    state.status === "joining-room" ||
    state.status === "selecting-room"
  );
}

export function normalizeJoinCodeInput(value: string): string {
  return value.trim().toUpperCase().slice(0, 6);
}

export function getJoinCodeValidationMessage(value: string): string | null {
  if (value.length !== 6) {
    return "Room codes contain six characters.";
  }
  try {
    normalizeJoinCode(value);
    return null;
  } catch {
    return JOIN_CODE_HELP;
  }
}

export function homeOperationReducer(
  state: HomeOperationState,
  action: HomeOperationAction,
): HomeOperationState {
  switch (action.type) {
    case "JOIN_CODE_CHANGED":
      if (requestIsPending(state)) {
        return state;
      }
      return {
        status: "idle",
        joinCode: normalizeJoinCodeInput(action.value),
        joinTouched: true,
      };
    case "CREATE_REQUESTED":
      if (requestIsPending(state)) {
        return state;
      }
      return {
        status: "creating-room",
        joinCode: state.joinCode,
        joinTouched: state.joinTouched,
      };
    case "JOIN_REQUESTED":
      if (
        requestIsPending(state) ||
        getJoinCodeValidationMessage(state.joinCode) !== null
      ) {
        return state;
      }
      return {
        status: "joining-room",
        joinCode: state.joinCode,
        joinTouched: true,
      };
    case "ROOM_SELECTED":
      return {
        status: "selecting-room",
        roomId: action.roomId,
        joinCode: "",
        joinTouched: false,
      };
    case "REQUEST_COMPLETED":
      return initialHomeOperationState;
    case "REQUEST_FAILED":
      return {
        status: "error",
        joinCode: state.joinCode,
        joinTouched: state.joinTouched,
        message: action.message,
        ...(action.code === undefined ? {} : { code: action.code }),
      };
  }
}

export type HomeRoomRequestDependencies = {
  createRoom(input: CreateRoomInput): Promise<RoomResponse>;
  joinRoomByCode(joinCode: string): Promise<JoinByCodeResponse>;
  selectRoom(roomId: string): void;
  recoverActiveRoom(): Promise<void>;
  getSelectedRoomId(): string | null;
  resultIsCurrent(): boolean;
};

export type HomeRoomRequestOutcome =
  | { status: "blocked" }
  | { status: "cancelled" }
  | { status: "selected"; roomId: string }
  | { status: "recovery-requested" }
  | { status: "failed"; message: string; code?: string };

function getHomeRequestErrorMessage(error: unknown): string {
  if (error instanceof InvalidJoinCodeError) {
    return JOIN_CODE_HELP;
  }
  if (error instanceof BackendApiError) {
    switch (error.code) {
      case "room_not_found":
        return "This room could not be found.";
      case "room_join_unavailable":
        return "This room is not available to join.";
      case "room_join_rate_limited":
        return "Too many join attempts. Please wait a moment.";
      case "room_full":
        return "This room is full.";
      case "session_already_active":
        return "This quiz has already started.";
      case "rate_limited":
        return "Too many requests. Please wait a moment and try again.";
      case "pro_required":
        return "StudyRoom Pro could not be verified for a Large Room. Open StudyRoom Pro to refresh your status.";
      case "premium_verification_unavailable":
        return "We couldn't verify StudyRoom Pro right now. Try again shortly.";
    }
  }
  return getUserFacingErrorMessage(error);
}

function failedOutcome(error: unknown): HomeRoomRequestOutcome {
  const code = error instanceof BackendApiError ? error.code : undefined;
  return {
    status: "failed",
    message: getHomeRequestErrorMessage(error),
    ...(code === undefined ? {} : { code }),
  };
}

export class HomeRoomRequestCoordinator {
  private requestInFlight = false;

  createRoom(
    dependencies: HomeRoomRequestDependencies,
    preset: RoomCapacityPreset = DEFAULT_ROOM_CAPACITY_PRESET,
  ): Promise<HomeRoomRequestOutcome> {
    return this.runRequest(
      async () => dependencies.createRoom(createRoomInputForPreset(preset)),
      dependencies,
    );
  }

  createRoomWithSelection(
    dependencies: HomeRoomRequestDependencies,
    preset: RoomCapacityPreset,
    selection: QuizModeSelection,
  ): Promise<HomeRoomRequestOutcome> {
    if (!isQuizSelectionValid(selection)) {
      return Promise.resolve({
        status: "failed",
        message:
          getQuizSelectionValidationMessage(selection) ??
          "Choose a valid quiz subject, topic, and mark budget.",
      });
    }
    return this.runRequest(
      async () =>
        dependencies.createRoom(createRoomInputForSelection(preset, selection)),
      dependencies,
    );
  }

  joinRoom(
    joinCode: string,
    dependencies: HomeRoomRequestDependencies,
  ): Promise<HomeRoomRequestOutcome> {
    return this.runRequest(async () => {
      const response = await dependencies.joinRoomByCode(
        normalizeJoinCode(joinCode),
      );
      return response.room;
    }, dependencies);
  }

  private async runRequest(
    request: () => Promise<RoomResponse>,
    dependencies: HomeRoomRequestDependencies,
  ): Promise<HomeRoomRequestOutcome> {
    if (this.requestInFlight || dependencies.getSelectedRoomId() !== null) {
      return { status: "blocked" };
    }

    this.requestInFlight = true;
    try {
      const room = await request();
      if (!dependencies.resultIsCurrent()) {
        return { status: "cancelled" };
      }
      dependencies.selectRoom(room.id);
      return { status: "selected", roomId: room.id };
    } catch (error: unknown) {
      if (!dependencies.resultIsCurrent()) {
        return { status: "cancelled" };
      }
      if (
        error instanceof BackendApiError &&
        error.code !== undefined &&
        EXISTING_ROOM_CONFLICTS.has(error.code)
      ) {
        try {
          await dependencies.recoverActiveRoom();
          return dependencies.resultIsCurrent()
            ? { status: "recovery-requested" }
            : { status: "cancelled" };
        } catch (recoveryError: unknown) {
          return failedOutcome(recoveryError);
        }
      }
      return failedOutcome(error);
    } finally {
      this.requestInFlight = false;
    }
  }
}

export type HomeScreenState =
  | { status: "checking-active-room" }
  | { status: "no-active-room" }
  | { status: "creating-room" }
  | { status: "joining-room" }
  | { status: "active-room-found"; roomId: string; coherent: boolean }
  | {
      status: "recoverable-error";
      source: "session" | "request";
      message: string;
    };

export function getCoherentWaitingRoomId(
  sessionState: SessionState,
): string | null {
  if (
    sessionState.roomId === null ||
    sessionState.connectionStage !== "established" ||
    sessionState.roomState?.room_id !== sessionState.roomId ||
    sessionState.snapshot?.room_state.room_id !== sessionState.roomId
  ) {
    return null;
  }
  return sessionState.roomId;
}

export function deriveHomeScreenState(
  sessionState: SessionState,
  operationState: HomeOperationState,
): HomeScreenState {
  if (sessionState.roomId !== null) {
    if (
      sessionState.phase === "recoverable-error" ||
      sessionState.phase === "fatal-error"
    ) {
      return {
        status: "recoverable-error",
        source: "session",
        message: getSessionErrorMessage(sessionState.lastError),
      };
    }
    return {
      status: "active-room-found",
      roomId: sessionState.roomId,
      coherent: getCoherentWaitingRoomId(sessionState) !== null,
    };
  }

  if (sessionState.phase === "recovering-room") {
    return { status: "checking-active-room" };
  }
  if (operationState.status === "creating-room") {
    return { status: "creating-room" };
  }
  if (operationState.status === "joining-room") {
    return { status: "joining-room" };
  }
  if (operationState.status === "selecting-room") {
    return {
      status: "active-room-found",
      roomId: operationState.roomId,
      coherent: false,
    };
  }
  if (
    sessionState.phase === "recoverable-error" ||
    sessionState.phase === "fatal-error"
  ) {
    return {
      status: "recoverable-error",
      source: "session",
      message: getSessionErrorMessage(sessionState.lastError),
    };
  }
  if (operationState.status === "error") {
    return {
      status: "recoverable-error",
      source: "request",
      message: operationState.message,
    };
  }
  return { status: "no-active-room" };
}
