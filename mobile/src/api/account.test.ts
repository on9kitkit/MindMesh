import assert from "node:assert/strict";
import test from "node:test";

import { createApiClient } from "./client";
import { deleteAccount } from "./account";
import { BackendApiError, MalformedResponseError } from "./errors";

function jsonResponse(value: unknown, status = 202): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function authenticatedClient() {
  return createApiClient("http://127.0.0.1:8000", {
    getAccessToken: async () => "access-token",
  });
}

test("deleteAccount sends the exact local deletion contract", async () => {
  const originalFetch = globalThis.fetch;
  let request: RequestInit | undefined;
  let requestUrl = "";
  globalThis.fetch = async (input, init) => {
    requestUrl = String(input);
    request = init;
    return jsonResponse({
      status: "account_deleted",
      local_deletion_complete: true,
      provider_cleanup_pending: true,
    });
  };

  try {
    assert.deepEqual(await deleteAccount(authenticatedClient()), {
      status: "account_deleted",
      local_deletion_complete: true,
      provider_cleanup_pending: true,
    });
    assert.equal(requestUrl, "http://127.0.0.1:8000/me");
    assert.equal(request?.method, "DELETE");
    assert.equal(request?.body, JSON.stringify({ confirmation: "DELETE" }));
    assert.equal(
      new Headers(request?.headers).get("authorization"),
      "Bearer access-token",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("deleteAccount preserves the recent-authentication contract", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    jsonResponse(
      {
        error: {
          code: "recent_authentication_required",
          message: "Recent authentication is required.",
        },
      },
      401,
    );

  try {
    await assert.rejects(
      deleteAccount(
        createApiClient("http://127.0.0.1:8000", {
          getAccessToken: async () => "access-token",
        }),
      ),
      (error: unknown) => {
        assert.ok(error instanceof BackendApiError);
        assert.equal(error.code, "recent_authentication_required");
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("deleteAccount rejects a malformed success response", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => jsonResponse({ status: "account_deleted" });

  try {
    await assert.rejects(
      deleteAccount(authenticatedClient()),
      (error: unknown) => error instanceof MalformedResponseError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
