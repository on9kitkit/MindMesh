import assert from "node:assert/strict";
import test from "node:test";

import { ApiConfigurationError } from "../api/errors";
import { deriveRoomWebSocketUrl } from "./url";

const ROOM_ID = "11111111-1111-4111-8111-111111111111";

test("converts local HTTP API URLs to WebSocket URLs", () => {
  assert.equal(
    deriveRoomWebSocketUrl("http://localhost:8000", ROOM_ID),
    `ws://localhost:8000/ws/rooms/${ROOM_ID}`,
  );
});

test("converts deployed HTTPS API URLs and preserves a base path", () => {
  assert.equal(
    deriveRoomWebSocketUrl("https://api.studyroom.example/v1/", ROOM_ID),
    `wss://api.studyroom.example/v1/ws/rooms/${ROOM_ID}`,
  );
});

test("preserves explicit ports and normalizes trailing slashes", () => {
  assert.equal(
    deriveRoomWebSocketUrl("https://api.studyroom.example:8443///", ROOM_ID),
    `wss://api.studyroom.example:8443/ws/rooms/${ROOM_ID}`,
  );
});

test("rejects unsupported URL schemes", () => {
  assert.throws(
    () => deriveRoomWebSocketUrl("ftp://api.studyroom.example", ROOM_ID),
    (error: unknown) => error instanceof ApiConfigurationError,
  );
});

test("never carries query tokens or fragments into the WebSocket URL", () => {
  const secret = "do-not-copy-this-token";
  const result = deriveRoomWebSocketUrl(
    `https://api.studyroom.example/?access_token=${secret}#session`,
    ROOM_ID,
  );

  assert.equal(result, `wss://api.studyroom.example/ws/rooms/${ROOM_ID}`);
  assert.equal(result.includes(secret), false);
  assert.equal(result.includes("access_token"), false);
});

test("rejects API URLs containing embedded credentials", () => {
  assert.throws(
    () =>
      deriveRoomWebSocketUrl(
        "https://user:password@api.studyroom.example",
        ROOM_ID,
      ),
    (error: unknown) => error instanceof ApiConfigurationError,
  );
});
