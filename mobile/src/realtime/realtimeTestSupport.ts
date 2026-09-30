import type {
  RealtimeTransport,
  RealtimeTransportClose,
  RealtimeTransportFactory,
  RealtimeTransportHandlers,
} from "./transport";

export class FakeRealtimeTransport implements RealtimeTransport {
  readonly url: string;
  readonly handlers: RealtimeTransportHandlers;
  readonly frames: string[] = [];
  readonly closeCalls: Array<{ code?: number; reason?: string }> = [];
  readyState = 0;
  sendHook: ((frame: string) => void) | null = null;

  constructor(url: string, handlers: RealtimeTransportHandlers) {
    this.url = url;
    this.handlers = handlers;
  }

  send(frame: string): void {
    if (this.readyState !== 1) {
      throw new Error("Fake socket is not open.");
    }
    this.frames.push(frame);
    this.sendHook?.(frame);
  }

  close(code?: number, reason?: string): void {
    this.closeCalls.push({ code, reason });
    this.readyState = 3;
  }

  open(): void {
    this.readyState = 1;
    this.handlers.onOpen();
  }

  message(frame: string): void {
    this.handlers.onMessage(frame);
  }

  binaryMessage(value: unknown): void {
    this.handlers.onMessage(value);
  }

  error(): void {
    this.handlers.onError();
  }

  serverClose(
    code: number,
    reason = "",
    wasClean = false,
  ): void {
    this.readyState = 3;
    const event: RealtimeTransportClose = { code, reason, wasClean };
    this.handlers.onClose(event);
  }
}

export class FakeRealtimeTransportFactory
  implements RealtimeTransportFactory
{
  readonly sockets: FakeRealtimeTransport[] = [];

  create(
    url: string,
    handlers: RealtimeTransportHandlers,
  ): RealtimeTransport {
    const socket = new FakeRealtimeTransport(url, handlers);
    this.sockets.push(socket);
    return socket;
  }

  latest(): FakeRealtimeTransport {
    const socket = this.sockets.at(-1);
    if (socket === undefined) {
      throw new Error("No fake realtime socket exists.");
    }
    return socket;
  }
}

export function parseFrame(frame: string): Record<string, unknown> {
  const value = JSON.parse(frame) as unknown;
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Expected an object frame.");
  }
  return value as Record<string, unknown>;
}
