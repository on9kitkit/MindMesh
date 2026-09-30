import {
  ProtocolIncompatibilityError,
  RealtimeAuthenticationError,
  RealtimeConnectionLimitError,
  RealtimeNetworkError,
  RealtimeRoomError,
  type StudyRoomRealtimeError,
} from "./errors";

export const REALTIME_CLOSE_CODES = {
  badProtocol: 4400,
  authenticationFailure: 4401,
  forbidden: 4403,
  notFound: 4404,
  connectionConflict: 4409,
  goingAway: 1001,
  abnormalClosure: 1006,
  unexpectedServerError: 1011,
} as const;

export type RealtimeCloseAction =
  | "retry"
  | "refresh-authentication"
  | "stop-room"
  | "stop-connection-limit"
  | "stop-protocol";

export type RealtimeCloseClassification = {
  action: RealtimeCloseAction;
  error: StudyRoomRealtimeError;
};

export function classifyRealtimeClose(
  closeCode: number,
  serverErrorCode?: string,
): RealtimeCloseClassification {
  switch (closeCode) {
    case REALTIME_CLOSE_CODES.badProtocol:
      return {
        action: "stop-protocol",
        error: new ProtocolIncompatibilityError(undefined, closeCode),
      };
    case REALTIME_CLOSE_CODES.authenticationFailure:
      return {
        action: "refresh-authentication",
        error: new RealtimeAuthenticationError(
          "The realtime authentication session expired.",
          serverErrorCode ?? "invalid_auth_token",
          closeCode,
        ),
      };
    case REALTIME_CLOSE_CODES.forbidden:
      return {
        action: "stop-room",
        error: new RealtimeRoomError(
          serverErrorCode === "room_left"
            ? "You left this room."
            : serverErrorCode === "account_suspended"
              ? "Your MindMesh account is currently unavailable."
            : "You are not an active member of this room.",
          serverErrorCode ?? "not_room_member",
          closeCode,
        ),
      };
    case REALTIME_CLOSE_CODES.notFound:
      return {
        action: "stop-room",
        error: new RealtimeRoomError(
          serverErrorCode === "profile_required"
            ? "Complete your MindMesh profile before using rooms."
            : serverErrorCode === "account_suspended"
              ? "Your MindMesh account is currently unavailable."
            : serverErrorCode === "room_closed"
              ? "This room is closed."
              : "This room is no longer available.",
          serverErrorCode ?? "room_not_found",
          closeCode,
        ),
      };
    case REALTIME_CLOSE_CODES.connectionConflict:
      return {
        action: "stop-connection-limit",
        error: new RealtimeConnectionLimitError(closeCode),
      };
    case REALTIME_CLOSE_CODES.goingAway:
    case REALTIME_CLOSE_CODES.abnormalClosure:
    case REALTIME_CLOSE_CODES.unexpectedServerError:
      return {
        action: "retry",
        error: new RealtimeNetworkError(undefined, closeCode),
      };
    default:
      if (closeCode >= 4400 && closeCode <= 4499) {
        return {
          action: "stop-protocol",
          error: new ProtocolIncompatibilityError(undefined, closeCode),
        };
      }
      return {
        action: "retry",
        error: new RealtimeNetworkError(undefined, closeCode),
      };
  }
}
