import assert from "node:assert/strict";
import test from "node:test";

import { BackendApiError, MalformedResponseError } from "./errors";
import { createApiClient } from "./client";
import { submitSafetyReport } from "./safetyReports";

function jsonResponse(value: unknown, status = 202): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function client() {
  return createApiClient("http://127.0.0.1:8000", {
    getAccessToken: async () => "access-token",
  });
}

test("submitSafetyReport sends only the bounded report contract", async () => {
  const originalFetch = globalThis.fetch;
  let request: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    request = init;
    return jsonResponse({ status: "report_received" });
  };
  try {
    assert.deepEqual(
      await submitSafetyReport(
        {
          reported_user_id: "target-id",
          room_id: "room-id",
          reason: "other_safety_concern",
        },
        client(),
      ),
      { status: "report_received" },
    );
    assert.equal(
      request?.body,
      JSON.stringify({
        reported_user_id: "target-id",
        room_id: "room-id",
        reason: "other_safety_concern",
      }),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("submitSafetyReport preserves the generic authorization failure", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    jsonResponse(
      {
        error: {
          code: "safety_report_not_allowed",
          message: "This safety report could not be submitted.",
        },
      },
      403,
    );
  try {
    await assert.rejects(
      submitSafetyReport(
        {
          reported_user_id: "target-id",
          room_id: "room-id",
          reason: "other_safety_concern",
        },
        client(),
      ),
      (error: unknown) =>
        error instanceof BackendApiError &&
        error.code === "safety_report_not_allowed",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("submitSafetyReport rejects malformed success responses", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => jsonResponse({ status: "open" });
  try {
    await assert.rejects(
      submitSafetyReport(
        {
          reported_user_id: "target-id",
          room_id: "room-id",
          reason: "other_safety_concern",
        },
        client(),
      ),
      (error: unknown) => error instanceof MalformedResponseError,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
