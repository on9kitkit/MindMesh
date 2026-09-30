export type RealtimeErrorKind =
  | "configuration"
  | "protocol-incompatibility"
  | "malformed-server-message"
  | "authentication"
  | "membership-or-room"
  | "connection-limit"
  | "network"
  | "reconnect-exhausted"
  | "command-unavailable"
  | "command-rejected";

type RealtimeErrorOptions = {
  code?: string;
  closeCode?: number;
};

export class StudyRoomRealtimeError extends Error {
  readonly kind: RealtimeErrorKind;
  readonly code?: string;
  readonly closeCode?: number;

  constructor(
    message: string,
    kind: RealtimeErrorKind,
    options: RealtimeErrorOptions = {},
  ) {
    super(message);
    this.name = "StudyRoomRealtimeError";
    this.kind = kind;
    this.code = options.code;
    this.closeCode = options.closeCode;
  }
}

export class RealtimeConfigurationError extends StudyRoomRealtimeError {
  constructor(message = "Realtime configuration is invalid.") {
    super(message, "configuration");
    this.name = "RealtimeConfigurationError";
  }
}

export class ProtocolIncompatibilityError extends StudyRoomRealtimeError {
  constructor(
    message = "The MindMesh realtime protocol is incompatible with this app.",
    closeCode?: number,
  ) {
    super(message, "protocol-incompatibility", {
      code: "protocol_incompatibility",
      closeCode,
    });
    this.name = "ProtocolIncompatibilityError";
  }
}

export class MalformedServerMessageError extends StudyRoomRealtimeError {
  constructor(message = "The MindMesh server sent an invalid realtime message.") {
    super(message, "malformed-server-message", {
      code: "malformed_server_message",
    });
    this.name = "MalformedServerMessageError";
  }
}

export class RealtimeAuthenticationError extends StudyRoomRealtimeError {
  constructor(
    message = "The realtime authentication session is unavailable.",
    code = "authentication_required",
    closeCode?: number,
  ) {
    super(message, "authentication", { code, closeCode });
    this.name = "RealtimeAuthenticationError";
  }
}

export class RealtimeRoomError extends StudyRoomRealtimeError {
  constructor(
    message = "The active MindMesh room is unavailable.",
    code = "room_unavailable",
    closeCode?: number,
  ) {
    super(message, "membership-or-room", { code, closeCode });
    this.name = "RealtimeRoomError";
  }
}

export class RealtimeConnectionLimitError extends StudyRoomRealtimeError {
  constructor(closeCode?: number) {
    super(
      "The realtime connection limit has been reached.",
      "connection-limit",
      { code: "connection_limit_reached", closeCode },
    );
    this.name = "RealtimeConnectionLimitError";
  }
}

export class RealtimeNetworkError extends StudyRoomRealtimeError {
  constructor(
    message = "The realtime connection was interrupted.",
    closeCode?: number,
  ) {
    super(message, "network", {
      code: "realtime_network_error",
      closeCode,
    });
    this.name = "RealtimeNetworkError";
  }
}

export class ReconnectExhaustedError extends StudyRoomRealtimeError {
  constructor() {
    super(
      "The realtime connection could not be restored automatically.",
      "reconnect-exhausted",
      { code: "reconnect_exhausted" },
    );
    this.name = "ReconnectExhaustedError";
  }
}

export class CommandUnavailableError extends StudyRoomRealtimeError {
  readonly command: string;

  constructor(command: string, message: string) {
    super(message, "command-unavailable", {
      code: "command_unavailable",
    });
    this.name = "CommandUnavailableError";
    this.command = command;
  }
}

export class CommandRejectedError extends StudyRoomRealtimeError {
  constructor(code: string, safeMessage: string) {
    super(safeMessage, "command-rejected", { code });
    this.name = "CommandRejectedError";
  }
}
