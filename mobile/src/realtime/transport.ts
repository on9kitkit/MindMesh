import { RealtimeConfigurationError } from "./errors";

export type RealtimeTransportClose = {
  code: number;
  reason: string;
  wasClean: boolean;
};

export type RealtimeTransportHandlers = {
  onOpen(): void;
  onMessage(data: unknown): void;
  onClose(event: RealtimeTransportClose): void;
  onError(): void;
};

export type RealtimeTransport = {
  readonly readyState: number;
  send(frame: string): void;
  close(code?: number, reason?: string): void;
};

export type RealtimeTransportFactory = {
  create(
    url: string,
    handlers: RealtimeTransportHandlers,
  ): RealtimeTransport;
};

export const globalWebSocketTransportFactory: RealtimeTransportFactory = {
  create(url, handlers) {
    if (typeof WebSocket === "undefined") {
      throw new RealtimeConfigurationError(
        "WebSocket transport is unavailable in this runtime.",
      );
    }

    const socket = new WebSocket(url);
    socket.onopen = () => handlers.onOpen();
    socket.onmessage = (event) => handlers.onMessage(event.data);
    socket.onclose = (event) =>
      handlers.onClose({
        code: event.code,
        reason: event.reason,
        wasClean: event.wasClean,
      });
    socket.onerror = () => handlers.onError();

    return {
      get readyState() {
        return socket.readyState;
      },
      send(frame) {
        socket.send(frame);
      },
      close(code, reason) {
        socket.close(code, reason);
      },
    };
  },
};
