export type ApiErrorKind =
  | "configuration"
  | "authentication"
  | "network"
  | "timeout"
  | "backend"
  | "malformed-response";

export class StudyRoomApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly code?: string;
  readonly status?: number;

  constructor(
    message: string,
    kind: ApiErrorKind,
    options: { code?: string; status?: number } = {},
  ) {
    super(message);
    this.name = "StudyRoomApiError";
    this.kind = kind;
    this.code = options.code;
    this.status = options.status;
  }
}

export class ApiConfigurationError extends StudyRoomApiError {
  constructor(message: string) {
    super(message, "configuration");
    this.name = "ApiConfigurationError";
  }
}

export class AuthenticationApiError extends StudyRoomApiError {
  constructor(message = "Authentication is required.") {
    super(message, "authentication", {
      code: "authentication_required",
      status: 401,
    });
    this.name = "AuthenticationApiError";
  }
}

export class NetworkApiError extends StudyRoomApiError {
  constructor() {
    super("Could not reach the MindMesh server.", "network");
    this.name = "NetworkApiError";
  }
}

export class TimeoutApiError extends StudyRoomApiError {
  constructor() {
    super("The server took too long to respond.", "timeout");
    this.name = "TimeoutApiError";
  }
}

export class BackendApiError extends StudyRoomApiError {
  constructor(code: string, message: string, status: number) {
    super(message, "backend", { code, status });
    this.name = "BackendApiError";
  }
}

export class MalformedResponseError extends StudyRoomApiError {
  constructor(message = "The MindMesh server returned an invalid response.") {
    super(message, "malformed-response");
    this.name = "MalformedResponseError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function parseBackendErrorPayload(
  value: unknown,
): { code: string; message: string } | undefined {
  if (!isRecord(value) || !isRecord(value.error)) {
    return undefined;
  }

  const code = value.error.code;
  const message = value.error.message;
  if (typeof code !== "string" || typeof message !== "string") {
    return undefined;
  }

  const trimmedCode = code.trim();
  const trimmedMessage = message.trim();
  if (!trimmedCode || !trimmedMessage) {
    return undefined;
  }

  return { code: trimmedCode, message: trimmedMessage };
}

export function getApiErrorCode(error: unknown): string | undefined {
  return error instanceof StudyRoomApiError ? error.code : undefined;
}

export function getUserFacingErrorMessage(error: unknown): string {
  if (error instanceof BackendApiError) {
    switch (error.code) {
      case "room_not_found":
        return "This room no longer exists.";
      case "room_full":
        return "This room is full.";
      case "room_closed":
        return "This room is closed.";
      case "room_owner_must_close":
        return "The room host must close the room instead of leaving it.";
      case "session_already_active":
        return "Finish the current quiz before leaving the room.";
      case "not_room_member":
        return "You are no longer a member of this room.";
      case "room_owner_required":
        return "Only the room host can close this room.";
      case "already_room_member":
        return "You are already in this room.";
      case "user_already_in_another_room":
        return "You are already active in another room.";
      case "authentication_required":
      case "invalid_auth_token":
        return "Your session has expired. Please sign in again.";
      case "account_deleted":
        return "Your MindMesh account has been deleted. Please sign in again.";
      case "account_suspended":
        return "Your MindMesh account is currently unavailable. Open Support & Safety for help.";
      case "invalid_display_name":
        return "Choose a different display name.";
      case "room_join_unavailable":
        return "This room is not available to join.";
      case "room_join_rate_limited":
        return "Too many join attempts. Please wait a moment.";
      case "recent_authentication_required":
        return "Please confirm your password before deleting your account.";
      case "account_deletion_blocked_active_quiz":
        return "You cannot delete your account while a quiz is in progress. Finish or leave the active quiz first.";
      case "safety_report_not_allowed":
        return "This concern could not be reported from this room.";
      case "quiz_not_ready":
        return "Quiz content is not ready yet. Generate the quiz and wait for it to be ready.";
      case "preparation_conflict":
        return "Quiz preparation is already in progress for this room.";
      case "preparation_failed":
        return "Quiz generation failed. Please try generating again.";
      case "ai_generation_unavailable":
        return "AI quiz generation is currently unavailable. Please try again later.";
      case "session_not_active":
        return "The quiz session is no longer active.";
      case "not_session_participant":
        return "You did not take part in this quiz session.";
      case "question_not_open":
        return "This question is not open for answers.";
      default:
        return "The MindMesh server could not complete that request.";
    }
  }

  if (error instanceof AuthenticationApiError) {
    return "Please sign in before using MindMesh rooms.";
  }

  if (error instanceof NetworkApiError) {
    return "Could not reach the MindMesh server.";
  }

  if (error instanceof TimeoutApiError) {
    return "The server took too long to respond.";
  }

  if (error instanceof MalformedResponseError) {
    return "The MindMesh server returned an invalid response.";
  }

  if (error instanceof ApiConfigurationError) {
    return "MindMesh server configuration is invalid.";
  }

  return "Something went wrong. Please try again.";
}
