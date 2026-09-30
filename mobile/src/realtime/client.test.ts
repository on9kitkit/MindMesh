import assert from "node:assert/strict";
import test from "node:test";

import {
  RoomRealtimeClient,
  serializeRealtimeCommand,
  type RealtimeClientClose,
} from "./client";
import { classifyRealtimeClose, REALTIME_CLOSE_CODES } from "./closeCodes";
import {
  CommandUnavailableError,
  MalformedServerMessageError,
  ProtocolIncompatibilityError,
  type StudyRoomRealtimeError,
} from "./errors";
import {
  FakeRealtimeTransportFactory,
  parseFrame,
} from "./realtimeTestSupport";
import {
  makeLobbySnapshot,
  ROOM_ID,
  serverEventFrame,
} from "../features/session/sessionTestFixtures";
import type { ServerEvent } from "./protocol";

const ACCESS_TOKEN = "private-access-token-value";
const CONNECTED_FRAME = serverEventFrame("CONNECTED", {
  server_time: "2030-01-01T12:00:00Z",
});

type ClientHarness = {
  client: RoomRealtimeClient;
  factory: FakeRealtimeTransportFactory;
  events: ServerEvent[];
  failures: StudyRoomRealtimeError[];
  closes: RealtimeClientClose[];
  established: number[];
  setCurrentGeneration(generation: number): void;
};

function createHarness(generation = 1): ClientHarness {
  const factory = new FakeRealtimeTransportFactory();
  const events: ServerEvent[] = [];
  const failures: StudyRoomRealtimeError[] = [];
  const closes: RealtimeClientClose[] = [];
  const established: number[] = [];
  let currentGeneration = generation;
  const client = new RoomRealtimeClient({
    apiBaseUrl: "http://127.0.0.1:8000?unsafe=removed",
    roomId: ROOM_ID,
    accessToken: ACCESS_TOKEN,
    generation,
    isGenerationCurrent: (candidate) => candidate === currentGeneration,
    callbacks: {
      onEvent: (event) => events.push(event),
      onEstablished: (value) => established.push(value),
      onFailure: (error) => failures.push(error),
      onTransportError: (error) => failures.push(error),
      onClose: (close) => closes.push(close),
    },
    transportFactory: factory,
  });
  return {
    client,
    factory,
    events,
    failures,
    closes,
    established,
    setCurrentGeneration(value) {
      currentGeneration = value;
    },
  };
}

test("socket URL is token-free and strips API query parameters", () => {
  const harness = createHarness();
  harness.client.connect();
  const url = harness.factory.latest().url;
  assert.equal(url.includes(ACCESS_TOKEN), false);
  assert.equal(url.includes("?"), false);
  assert.equal(url, `ws://127.0.0.1:8000/ws/rooms/${ROOM_ID}`);
});

test("AUTHENTICATE is the first transport frame", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.open();
  assert.equal(socket.frames.length, 1);
  const frame = parseFrame(socket.frames[0] ?? "");
  assert.equal(frame.type, "AUTHENTICATE");
});

test("commands cannot be sent before CONNECTED", () => {
  const harness = createHarness();
  harness.client.connect();
  harness.factory.latest().open();
  assert.throws(
    () => harness.client.sendCommand({ type: "REQUEST_STATE" }),
    CommandUnavailableError,
  );
});

test("every incoming text frame passes through the strict parser", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.open();
  socket.message(CONNECTED_FRAME);
  socket.message(
    serverEventFrame("STATE_SNAPSHOT", makeLobbySnapshot()),
  );
  assert.deepEqual(
    harness.events.map((event) => event.type),
    ["CONNECTED", "STATE_SNAPSHOT"],
  );
  assert.deepEqual(harness.established, [1]);
});

test("CONNECTED and the initial snapshot can arrive immediately after authentication", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.sendHook = (frame) => {
    if (parseFrame(frame).type !== "AUTHENTICATE") {
      return;
    }
    socket.message(CONNECTED_FRAME);
    socket.message(serverEventFrame("STATE_SNAPSHOT", makeLobbySnapshot()));
  };

  socket.open();

  assert.deepEqual(
    harness.events.map((event) => event.type),
    ["CONNECTED", "STATE_SNAPSHOT"],
  );
  assert.deepEqual(harness.established, [1]);
});

test("malformed JSON becomes a fatal typed protocol failure", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.open();
  socket.message("{");
  assert.ok(harness.failures[0] instanceof MalformedServerMessageError);
  assert.equal(socket.closeCalls[0]?.code, 1002);
});

test("unsupported protocol versions become incompatibility failures", () => {
  for (const protocolVersion of [1, 3]) {
    const harness = createHarness();
    harness.client.connect();
    const socket = harness.factory.latest();
    socket.open();
    socket.message(
      JSON.stringify({
        protocol_version: protocolVersion,
        type: "CONNECTED",
        payload: {},
      }),
    );
    assert.ok(harness.failures[0] instanceof ProtocolIncompatibilityError);
  }
});

test("old-generation callbacks are ignored", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.open();
  const frameCount = socket.frames.length;
  harness.setCurrentGeneration(2);
  socket.message(CONNECTED_FRAME);
  socket.serverClose(1006);
  assert.equal(harness.events.length, 0);
  assert.equal(harness.closes.length, 0);
  assert.equal(socket.frames.length, frameCount);
});

test("connect is idempotent within one generation", () => {
  const harness = createHarness();
  harness.client.connect();
  harness.client.connect();
  harness.client.connect();
  assert.equal(harness.factory.sockets.length, 1);
});

test("an intentional local close is reported and sends no reconnect signal", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.open();
  harness.client.close();
  socket.serverClose(1000, "client lifecycle change", true);
  assert.equal(socket.closeCalls.length, 1);
  assert.equal(harness.closes[0]?.intentional, true);
});

test("valid commands serialize only after CONNECTED", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.open();
  socket.message(CONNECTED_FRAME);
  harness.client.sendCommand({ type: "SET_READY", ready: true });
  assert.equal(parseFrame(socket.frames[1] ?? "").type, "SET_READY");
  assert.deepEqual(
    parseFrame(serializeRealtimeCommand({ type: "START_SESSION" })),
    { protocol_version: 2, type: "START_SESSION", payload: {} },
  );
  assert.deepEqual(
    parseFrame(
      serializeRealtimeCommand({
        type: "SUBMIT_ANSWER",
        sessionQuestionId: ROOM_ID,
        answer: { type: "choice", optionId: "newton" },
      }),
    ),
    {
      protocol_version: 2,
      type: "SUBMIT_ANSWER",
      payload: {
        session_question_id: ROOM_ID,
        type: "choice",
        option_id: "newton",
      },
    },
  );
  assert.deepEqual(
    parseFrame(
      serializeRealtimeCommand({
        type: "SUBMIT_ANSWER",
        sessionQuestionId: ROOM_ID,
        answer: { type: "text", text: "42" },
      }),
    ),
    {
      protocol_version: 2,
      type: "SUBMIT_ANSWER",
      payload: {
        session_question_id: ROOM_ID,
        type: "text",
        text: "42",
      },
    },
  );
  assert.deepEqual(
    parseFrame(
      serializeRealtimeCommand({
        type: "PREPARE_QUIZ",
        requestId: "44444444-4444-4444-8444-444444444444",
      }),
    ),
    {
      protocol_version: 2,
      type: "PREPARE_QUIZ",
      payload: { request_id: "44444444-4444-4444-8444-444444444444" },
    },
  );
  assert.deepEqual(
    parseFrame(serializeRealtimeCommand({ type: "RETRY_GRADING" })),
    { protocol_version: 2, type: "RETRY_GRADING", payload: {} },
  );
});

test("ERROR events preserve safe backend diagnostics for the close owner", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.open();
  socket.message(
    serverEventFrame("ERROR", {
      code: "future_safe_code",
      message: "A safe server message.",
    }),
  );
  socket.serverClose(4403);
  assert.equal(harness.events[0]?.type, "ERROR");
  assert.equal(harness.closes[0]?.serverError?.code, "future_safe_code");
});

test("non-text frames fail without including frame or token contents", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.open();
  socket.binaryMessage({ access_token: ACCESS_TOKEN });
  const error = harness.failures[0];
  assert.ok(error instanceof MalformedServerMessageError);
  assert.equal(error.message.includes(ACCESS_TOKEN), false);
  assert.equal(socket.url.includes(ACCESS_TOKEN), false);
});

test("backend application close codes have explicit retry classifications", () => {
  assert.equal(
    classifyRealtimeClose(REALTIME_CLOSE_CODES.badProtocol).action,
    "stop-protocol",
  );
  assert.equal(
    classifyRealtimeClose(REALTIME_CLOSE_CODES.authenticationFailure).action,
    "refresh-authentication",
  );
  assert.equal(
    classifyRealtimeClose(REALTIME_CLOSE_CODES.forbidden).action,
    "stop-room",
  );
  assert.equal(
    classifyRealtimeClose(REALTIME_CLOSE_CODES.notFound).action,
    "stop-room",
  );
  assert.equal(
    classifyRealtimeClose(REALTIME_CLOSE_CODES.connectionConflict).action,
    "stop-connection-limit",
  );
  assert.equal(
    classifyRealtimeClose(REALTIME_CLOSE_CODES.abnormalClosure).action,
    "retry",
  );
  const roomClosed = classifyRealtimeClose(
    REALTIME_CLOSE_CODES.notFound,
    "room_closed",
  );
  assert.equal(roomClosed.action, "stop-room");
  assert.equal(roomClosed.error.code, "room_closed");
  assert.equal(roomClosed.error.message, "This room is closed.");
});

test("transport failures never expose the access token", () => {
  const harness = createHarness();
  harness.client.connect();
  const socket = harness.factory.latest();
  socket.open();
  socket.message(
    JSON.stringify({
      protocol_version: 2,
      type: "CONNECTED",
      payload: { server_time: ACCESS_TOKEN },
    }),
  );
  assert.equal(
    harness.failures.some((error) => error.message.includes(ACCESS_TOKEN)),
    false,
  );
});
