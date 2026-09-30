import assert from "node:assert/strict";
import test from "node:test";

import type { Session } from "@supabase/supabase-js";

import {
  AuthCallbackHandler,
  createSignUpOptions,
  NATIVE_AUTH_REDIRECT_URL,
  parseAuthCallbackUrl,
  type AuthCallbackClient,
} from "./authCallback";

const session = {
  access_token: "test-access-value",
  expires_at: 1_900_000_000,
  expires_in: 3_600,
  refresh_token: "test-refresh-value",
  token_type: "bearer",
  user: {
    app_metadata: {},
    aud: "authenticated",
    created_at: "2026-01-01T00:00:00.000Z",
    id: "11111111-1111-4111-8111-111111111111",
    email: "student@example.com",
    user_metadata: { display_name: "Study Student" },
  },
} as Session;

class FakeAuthClient implements AuthCallbackClient {
  readonly exchangedCodes: string[] = [];
  result: { data: { session: Session | null }; error: { message: string } | null } = {
    data: { session },
    error: null,
  };

  auth = {
    exchangeCodeForSession: async (code: string) => {
      this.exchangedCodes.push(code);
      return this.result;
    },
  };
}

test("native sign-up options use the stable StudyRoom callback", () => {
  assert.deepEqual(createSignUpOptions("Study Student"), {
    data: { display_name: "Study Student" },
    emailRedirectTo: NATIVE_AUTH_REDIRECT_URL,
  });
});

test("valid callback URLs expose only the authorization code", () => {
  assert.deepEqual(
    parseAuthCallbackUrl(
      `${NATIVE_AUTH_REDIRECT_URL}?code=authorization-code&type=signup`,
    ),
    { status: "code", code: "authorization-code" },
  );
});

test("triple-slash native callbacks normalize to the same callback path", () => {
  assert.deepEqual(
    parseAuthCallbackUrl(
      "studyroom-preview:///auth/callback?code=authorization-code&type=signup",
    ),
    { status: "code", code: "authorization-code" },
  );
});

test("other app and web callbacks are ignored", () => {
  assert.deepEqual(
    parseAuthCallbackUrl("studyroom://auth/callback?code=ignored"),
    { status: "not-auth-callback" },
  );
  assert.deepEqual(
    parseAuthCallbackUrl("https://example.com/auth/callback?code=ignored"),
    { status: "not-auth-callback" },
  );
});

test("malformed callbacks receive a recoverable message", () => {
  const result = parseAuthCallbackUrl(NATIVE_AUTH_REDIRECT_URL);
  assert.equal(result.status, "error");
  if (result.status === "error") {
    assert.match(result.message, /incomplete/);
  }
});

test("expired or already-used callbacks do not expose provider details", () => {
  const result = parseAuthCallbackUrl(
    `${NATIVE_AUTH_REDIRECT_URL}?error=access_denied&error_code=otp_expired`,
  );
  assert.deepEqual(result, {
    status: "error",
    message:
      "This confirmation link has expired or was already used. Request a new confirmation email and try again.",
  });
});

test("valid callbacks exchange the code and return the authenticated session", async () => {
  const client = new FakeAuthClient();
  const handler = new AuthCallbackHandler(client);

  const result = await handler.process(
    `${NATIVE_AUTH_REDIRECT_URL}?code=authorization-code`,
  );

  assert.equal(result.status, "authenticated");
  assert.deepEqual(client.exchangedCodes, ["authorization-code"]);
});

test("warm duplicate callbacks are idempotent", async () => {
  const client = new FakeAuthClient();
  const handler = new AuthCallbackHandler(client);
  const url = `${NATIVE_AUTH_REDIRECT_URL}?code=authorization-code`;

  await handler.process(url);
  assert.deepEqual(await handler.process(url), {
    status: "ignored",
    reason: "duplicate",
  });
  assert.deepEqual(client.exchangedCodes, ["authorization-code"]);
});

test("canonical and triple-slash duplicate callbacks exchange only once", async () => {
  const client = new FakeAuthClient();
  const handler = new AuthCallbackHandler(client);

  await handler.process(
    `${NATIVE_AUTH_REDIRECT_URL}?code=authorization-code`,
  );
  assert.deepEqual(
    await handler.process(
      "studyroom-preview:///auth/callback?code=authorization-code",
    ),
    { status: "ignored", reason: "duplicate" },
  );
  assert.deepEqual(client.exchangedCodes, ["authorization-code"]);
});

test("a cold callback handler can process a new callback", async () => {
  const client = new FakeAuthClient();
  const handler = new AuthCallbackHandler(client);

  const result = await handler.process(
    `${NATIVE_AUTH_REDIRECT_URL}?code=cold-start-code`,
  );

  assert.equal(result.status, "authenticated");
  assert.deepEqual(client.exchangedCodes, ["cold-start-code"]);
});

test("exchange failures become safe recoverable errors", async () => {
  const client = new FakeAuthClient();
  client.result = {
    data: { session: null },
    error: { message: "invalid or expired confirmation code" },
  };
  const handler = new AuthCallbackHandler(client);

  const result = await handler.process(
    `${NATIVE_AUTH_REDIRECT_URL}?code=expired-code`,
  );

  assert.deepEqual(result, {
    status: "failed",
    message:
      "This confirmation link has expired or was already used. Request a new confirmation email and try again.",
  });
});

test("a failed exchange can retry the same callback after a network recovery", async () => {
  const client = new FakeAuthClient();
  const handler = new AuthCallbackHandler(client);
  const url = `${NATIVE_AUTH_REDIRECT_URL}?code=retryable-code`;
  client.result = {
    data: { session: null },
    error: { message: "network request failed" },
  };

  assert.equal((await handler.process(url)).status, "failed");
  client.result = { data: { session }, error: null };
  assert.equal((await handler.process(url)).status, "authenticated");
  assert.deepEqual(client.exchangedCodes, ["retryable-code", "retryable-code"]);
});
