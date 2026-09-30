import { deriveRoomWebSocketUrl } from "./url";
import { ApiConfigurationError } from "../api/errors";
import {
  REALTIME_PROTOCOL_VERSION,
  RealtimeProtocolError,
  UnsupportedProtocolVersionError,
  parseServerEvent,
  type CanonicalUuid,
  type ErrorEvent,
  type ServerEvent,
} from "./protocol";
import {
  CommandUnavailableError,
  MalformedServerMessageError,
  ProtocolIncompatibilityError,
  RealtimeConfigurationError,
  RealtimeNetworkError,
  StudyRoomRealtimeError,
} from "./errors";
import {
  globalWebSocketTransportFactory,
  type RealtimeTransport,
  type RealtimeTransportClose,
  type RealtimeTransportFactory,
} from "./transport";

export const WEB_SOCKET_OPEN = 1;

export type SubmitChoiceCommand = {
  type: "SUBMIT_ANSWER";
  sessionQuestionId: CanonicalUuid;
  answer: { type: "choice"; optionId: string };
};

export type SubmitTextCommand = {
  type: "SUBMIT_ANSWER";
  sessionQuestionId: CanonicalUuid;
  answer: { type: "text"; text: string };
};

export type RealtimeCommand =
  | { type: "SET_READY"; ready: boolean }
  | { type: "START_SESSION" }
  | { type: "PREPARE_QUIZ"; requestId: string }
  | { type: "RETRY_GRADING" }
  | SubmitChoiceCommand
  | SubmitTextCommand
  | { type: "REQUEST_STATE" };

export type RealtimeClientClose = RealtimeTransportClose & {
  intentional: boolean;
  serverError?: ErrorEvent["payload"];
};

export type RoomRealtimeClientCallbacks = {
  onEvent(event: ServerEvent, generation: number): void;
  onEstablished(generation: number): void;
  onFailure(error: StudyRoomRealtimeError, generation: number): void;
  onTransportError(error: RealtimeNetworkError, generation: number): void;
  onClose(event: RealtimeClientClose, generation: number): void;
};

export type RoomRealtimeClientOptions = {
  apiBaseUrl: string;
  roomId: string;
  accessToken: string;
  generation: number;
  isGenerationCurrent(generation: number): boolean;
  callbacks: RoomRealtimeClientCallbacks;
  transportFactory?: RealtimeTransportFactory;
};

function serializeAuthentication(accessToken: string): string {
  return JSON.stringify({
    protocol_version: REALTIME_PROTOCOL_VERSION,
    type: "AUTHENTICATE",
    payload: { access_token: accessToken },
  });
}

export function serializeRealtimeCommand(command: RealtimeCommand): string {
  switch (command.type) {
    case "SET_READY":
      return JSON.stringify({
        protocol_version: REALTIME_PROTOCOL_VERSION,
        type: command.type,
        payload: { ready: command.ready },
      });
    case "START_SESSION":
    case "RETRY_GRADING":
    case "REQUEST_STATE":
      return JSON.stringify({
        protocol_version: REALTIME_PROTOCOL_VERSION,
        type: command.type,
        payload: {},
      });
    case "PREPARE_QUIZ":
      return JSON.stringify({
        protocol_version: REALTIME_PROTOCOL_VERSION,
        type: command.type,
        payload: { request_id: command.requestId },
      });
    case "SUBMIT_ANSWER": {
      const answerPayload =
        command.answer.type === "choice"
          ? {
              session_question_id: command.sessionQuestionId,
              type: "choice",
              option_id: command.answer.optionId,
            }
          : {
              session_question_id: command.sessionQuestionId,
              type: "text",
              text: command.answer.text,
            };
      return JSON.stringify({
        protocol_version: REALTIME_PROTOCOL_VERSION,
        type: command.type,
        payload: answerPayload,
      });
    }
  }
}

export class RoomRealtimeClient {
  private readonly options: RoomRealtimeClientOptions;
  private readonly transportFactory: RealtimeTransportFactory;
  private transport: RealtimeTransport | null = null;
  private started = false;
  private intentionallyClosed = false;
  private connectedEventReceived = false;
  private established = false;
  private lastServerError: ErrorEvent["payload"] | undefined;

  constructor(options: RoomRealtimeClientOptions) {
    this.options = options;
    this.transportFactory =
      options.transportFactory ?? globalWebSocketTransportFactory;
  }

  get isAuthenticated(): boolean {
    return this.connectedEventReceived && !this.intentionallyClosed;
  }

  get isEstablished(): boolean {
    return this.established && !this.intentionallyClosed;
  }

  connect(): void {
    if (this.started || this.intentionallyClosed) {
      return;
    }
    this.started = true;

    try {
      const url = deriveRoomWebSocketUrl(
        this.options.apiBaseUrl,
        this.options.roomId,
      );
      this.transport = this.transportFactory.create(url, {
        onOpen: () => this.handleOpen(),
        onMessage: (data) => this.handleMessage(data),
        onClose: (event) => this.handleClose(event),
        onError: () => this.handleTransportError(),
      });
    } catch (error: unknown) {
      const safeError =
        error instanceof StudyRoomRealtimeError
          ? error
          : error instanceof ApiConfigurationError
            ? new RealtimeConfigurationError(error.message)
          : new RealtimeNetworkError("The realtime connection could not open.");
      this.notifyFailure(safeError);
    }
  }

  sendCommand(command: RealtimeCommand): void {
    if (
      !this.isCurrent() ||
      !this.connectedEventReceived ||
      this.transport === null
    ) {
      throw new CommandUnavailableError(
        command.type,
        "The realtime command is unavailable until authentication completes.",
      );
    }
    if (this.transport.readyState !== WEB_SOCKET_OPEN) {
      throw new RealtimeNetworkError(
        "The realtime command could not be sent because the connection is closed.",
      );
    }

    try {
      this.transport.send(serializeRealtimeCommand(command));
    } catch {
      throw new RealtimeNetworkError(
        "The realtime command could not be sent.",
      );
    }
  }

  close(code = 1000, reason = "client lifecycle change"): void {
    if (this.intentionallyClosed) {
      return;
    }
    this.intentionallyClosed = true;
    const transport = this.transport;
    this.transport = null;
    if (transport !== null) {
      try {
        transport.close(code, reason);
      } catch {
        // The generation has already been invalidated by the owner.
      }
    }
  }

  private isCurrent(): boolean {
    return this.options.isGenerationCurrent(this.options.generation);
  }

  private handleOpen(): void {
    if (!this.isCurrent() || this.intentionallyClosed || this.transport === null) {
      return;
    }
    try {
      this.transport.send(serializeAuthentication(this.options.accessToken));
    } catch {
      this.notifyFailure(
        new RealtimeNetworkError("Realtime authentication could not be sent."),
      );
    }
  }

  private handleMessage(data: unknown): void {
    if (!this.isCurrent() || this.intentionallyClosed) {
      return;
    }
    if (typeof data !== "string") {
      this.failProtocol(
        new MalformedServerMessageError(
          "The MindMesh server sent a non-text realtime message.",
        ),
      );
      return;
    }

    let event: ServerEvent;
    try {
      event = parseServerEvent(data);
    } catch (error: unknown) {
      if (error instanceof UnsupportedProtocolVersionError) {
        this.failProtocol(new ProtocolIncompatibilityError(error.message));
      } else if (error instanceof RealtimeProtocolError) {
        this.failProtocol(new MalformedServerMessageError(error.message));
      } else {
        this.failProtocol(new MalformedServerMessageError());
      }
      return;
    }

    if (event.type === "ERROR") {
      this.lastServerError = event.payload;
      this.options.callbacks.onEvent(event, this.options.generation);
      return;
    }

    if (event.type === "CONNECTED") {
      if (this.connectedEventReceived) {
        this.failProtocol(
          new MalformedServerMessageError(
            "The MindMesh server sent a duplicate connection event.",
          ),
        );
        return;
      }
      this.connectedEventReceived = true;
      this.options.callbacks.onEvent(event, this.options.generation);
      return;
    }

    if (!this.connectedEventReceived) {
      this.failProtocol(
        new MalformedServerMessageError(
          "The MindMesh server sent state before authentication completed.",
        ),
      );
      return;
    }

    const becameEstablished =
      event.type === "STATE_SNAPSHOT" && !this.established;
    if (becameEstablished) {
      this.established = true;
    }
    this.options.callbacks.onEvent(event, this.options.generation);
    if (becameEstablished) {
      this.options.callbacks.onEstablished(this.options.generation);
    }
  }

  private handleTransportError(): void {
    if (!this.isCurrent() || this.intentionallyClosed) {
      return;
    }
    this.options.callbacks.onTransportError(
      new RealtimeNetworkError(),
      this.options.generation,
    );
  }

  private handleClose(event: RealtimeTransportClose): void {
    if (!this.isCurrent()) {
      return;
    }
    this.transport = null;
    this.options.callbacks.onClose(
      {
        ...event,
        intentional: this.intentionallyClosed,
        ...(this.lastServerError === undefined
          ? {}
          : { serverError: this.lastServerError }),
      },
      this.options.generation,
    );
  }

  private failProtocol(error: StudyRoomRealtimeError): void {
    this.notifyFailure(error);
    try {
      this.transport?.close(1002, "invalid server protocol");
    } catch {
      // The owner receives the typed failure even if closing also fails.
    }
  }

  private notifyFailure(error: StudyRoomRealtimeError): void {
    if (!this.isCurrent() || this.intentionallyClosed) {
      return;
    }
    this.options.callbacks.onFailure(error, this.options.generation);
  }
}
