import assert from "node:assert/strict";
import test from "node:test";

import {
  AuthenticationApiError,
  BackendApiError,
  getUserFacingErrorMessage,
  MalformedResponseError,
  NetworkApiError,
  TimeoutApiError,
} from "./errors";
import { createApiClient, normalizeApiBaseUrl } from "./client";
import {
  closeRoom,
  createRoom,
  createRoomMember,
  getActiveRoom,
  getRoom,
  getRoomMembers,
  InvalidJoinCodeError,
  joinRoomByCode,
  leaveRoom,
} from "./rooms";
import { updateProfile } from "./profile";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setFetch(
  handler: (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => Promise<Response>,
): () => void {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = handler;
  return () => {
    globalThis.fetch = originalFetch;
  };
}

function authenticatedClient() {
  return createApiClient("http://127.0.0.1:8000", {
    getAccessToken: async () => "access-token",
  });
}

const room = {
  id: "room-123",
  name: "Physics Sprint",
  join_code: "PHYS42",
  maximum_members: 8,
  member_count: 1,
  quiz_mode: "LEGACY_PHYSICS",
  education_level: null,
  quiz_subject: null,
  quiz_topic: null,
  target_total_marks: null,
};

test("createRoom sends only the room contract and bearer token", async () => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const restoreFetch = setFetch(async (input, init) => {
    calls.push({ input, init });
    return jsonResponse(room, 201);
  });

  try {
    const response = await createRoom(
      { name: "Physics Sprint", maximum_members: 8 },
      authenticatedClient(),
    );

    assert.deepEqual(response, room);
    assert.equal(String(calls[0]?.input), "http://127.0.0.1:8000/rooms");
    assert.equal(calls[0]?.init?.method, "POST");
    assert.equal(
      calls[0]?.init?.body,
      JSON.stringify({ name: "Physics Sprint", maximum_members: 8 }),
    );
    const headers = new Headers(calls[0]?.init?.headers);
    assert.equal(headers.get("authorization"), "Bearer access-token");
    assert.equal(headers.get("content-type"), "application/json");
  } finally {
    restoreFetch();
  }
});

test("large room creation sends capacity twenty and no premium authority field", async () => {
  const calls: Array<{ init?: RequestInit }> = [];
  const restoreFetch = setFetch(async (_input, init) => {
    calls.push({ init });
    return jsonResponse({ ...room, maximum_members: 20 }, 201);
  });

  try {
    await createRoom(
      { name: "Physics Sprint", maximum_members: 20 },
      authenticatedClient(),
    );
    const body = String(calls[0]?.init?.body);
    assert.equal(
      body,
      JSON.stringify({ name: "Physics Sprint", maximum_members: 20 }),
    );
    for (const forbidden of [
      "is_pro",
      "isPro",
      "hasPremium",
      "entitlementActive",
      "entitlement",
      "product_id",
      "subscription_status",
      "subscriptionStatus",
      "customer_id",
    ]) {
      assert.equal(body.includes(forbidden), false);
    }
  } finally {
    restoreFetch();
  }
});

test("createRoom rejects a malformed successful response", async () => {
  const restoreFetch = setFetch(async () =>
    jsonResponse({ id: "room-123", name: "Physics Sprint" }, 201),
  );

  try {
    await assert.rejects(
      createRoom(
        { name: "Physics Sprint", maximum_members: 8 },
        authenticatedClient(),
      ),
      (error: unknown) => error instanceof MalformedResponseError,
    );
  } finally {
    restoreFetch();
  }
});

test("room responses reject capacity above the server maximum", async () => {
  const restoreFetch = setFetch(async () =>
    jsonResponse({ ...room, maximum_members: 21 }, 201),
  );

  try {
    await assert.rejects(
      createRoom(
        { name: "Physics Sprint", maximum_members: 20 },
        authenticatedClient(),
      ),
      (error: unknown) => error instanceof MalformedResponseError,
    );
  } finally {
    restoreFetch();
  }
});

test("joinRoomByCode normalizes the code and uses the authenticated contract", async () => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const joinedMember = {
    user_id: "11111111-1111-4111-8111-111111111111",
    display_name: "Room Owner",
    room_id: room.id,
  };
  const restoreFetch = setFetch(async (input, init) => {
    calls.push({ input, init });
    return jsonResponse({ room, member: joinedMember }, 201);
  });

  try {
    const response = await joinRoomByCode("  phys42  ", authenticatedClient());

    assert.deepEqual(response, { room, member: joinedMember });
    assert.equal(
      String(calls[0]?.input),
      "http://127.0.0.1:8000/rooms/join",
    );
    assert.equal(calls[0]?.init?.method, "POST");
    assert.equal(calls[0]?.init?.body, JSON.stringify({ join_code: "PHYS42" }));
    const headers = new Headers(calls[0]?.init?.headers);
    assert.equal(headers.get("authorization"), "Bearer access-token");
    assert.equal(String(calls[0]?.init?.body).includes("user_id"), false);
    assert.equal(String(calls[0]?.init?.body).includes("display_name"), false);
  } finally {
    restoreFetch();
  }
});

test("joinRoomByCode maps structured backend errors", async () => {
  const restoreFetch = setFetch(async () =>
    jsonResponse(
      {
        error: {
          code: "room_not_found",
          message: "Room was not found.",
        },
      },
      404,
    ),
  );

  try {
    await assert.rejects(
      joinRoomByCode("PHYS42", authenticatedClient()),
      (error: unknown) => {
        assert.ok(error instanceof BackendApiError);
        assert.equal(error.code, "room_not_found");
        assert.equal(error.status, 404);
        return true;
      },
    );
  } finally {
    restoreFetch();
  }
});

test("joinRoomByCode rejects codes outside the backend alphabet before fetch", async () => {
  let fetchCalled = false;
  const restoreFetch = setFetch(async () => {
    fetchCalled = true;
    return jsonResponse({});
  });

  try {
    await assert.rejects(
      joinRoomByCode("ROOM01", authenticatedClient()),
      (error: unknown) => error instanceof InvalidJoinCodeError,
    );
    assert.equal(fetchCalled, false);
  } finally {
    restoreFetch();
  }
});

test("getActiveRoom parses an active room summary", async () => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const restoreFetch = setFetch(async (input, init) => {
    calls.push({ input, init });
    return jsonResponse(room);
  });

  try {
    assert.deepEqual(await getActiveRoom(authenticatedClient()), room);
    assert.equal(
      String(calls[0]?.input),
      "http://127.0.0.1:8000/me/active-room",
    );
    assert.equal(calls[0]?.init?.method, "GET");
    assert.equal(
      new Headers(calls[0]?.init?.headers).get("authorization"),
      "Bearer access-token",
    );
  } finally {
    restoreFetch();
  }
});

test("getActiveRoom accepts the backend null representation", async () => {
  const restoreFetch = setFetch(async () => jsonResponse(null));

  try {
    assert.equal(await getActiveRoom(authenticatedClient()), null);
  } finally {
    restoreFetch();
  }
});

test("getActiveRoom rejects a malformed room summary", async () => {
  const restoreFetch = setFetch(async () =>
    jsonResponse({ id: "room-123", name: "Physics Sprint" }),
  );

  try {
    await assert.rejects(
      getActiveRoom(authenticatedClient()),
      (error: unknown) => error instanceof MalformedResponseError,
    );
  } finally {
    restoreFetch();
  }
});

test("getRoom maps a structured room_not_found response", async () => {
  const restoreFetch = setFetch(async () =>
    jsonResponse(
      {
        error: {
          code: "room_not_found",
          message: "Room was not found.",
        },
      },
      404,
    ),
  );

  try {
    await assert.rejects(
      getRoom("missing-room", authenticatedClient()),
      (error: unknown) => {
        assert.ok(error instanceof BackendApiError);
        assert.equal(error.code, "room_not_found");
        assert.equal(error.status, 404);
        return true;
      },
    );
  } finally {
    restoreFetch();
  }
});

test("room lifecycle commands use authenticated POST endpoints with no body", async () => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const restoreFetch = setFetch(async (input, init) => {
    calls.push({ input, init });
    return new Response(null, { status: 204 });
  });

  try {
    await leaveRoom("room/id", authenticatedClient());
    await closeRoom("room/id", authenticatedClient());

    assert.deepEqual(
      calls.map((call) => ({
        url: String(call.input),
        method: call.init?.method,
        body: call.init?.body,
        authorization: new Headers(call.init?.headers).get("authorization"),
      })),
      [
        {
          url: "http://127.0.0.1:8000/rooms/room%2Fid/leave",
          method: "POST",
          body: undefined,
          authorization: "Bearer access-token",
        },
        {
          url: "http://127.0.0.1:8000/rooms/room%2Fid/close",
          method: "POST",
          body: undefined,
          authorization: "Bearer access-token",
        },
      ],
    );
  } finally {
    restoreFetch();
  }
});

test("room lifecycle commands reject an unexpected success body", async () => {
  const restoreFetch = setFetch(async () => jsonResponse({ status: "closed" }));

  try {
    await assert.rejects(
      closeRoom("room-123", authenticatedClient()),
      (error: unknown) => error instanceof MalformedResponseError,
    );
  } finally {
    restoreFetch();
  }
});

test("membership creation sends no client identity fields", async () => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const restoreFetch = setFetch(async (input, init) => {
    calls.push({ input, init });
    return jsonResponse(
      {
        user_id: "11111111-1111-4111-8111-111111111111",
        display_name: "Room Owner",
        room_id: "room-123",
      },
      201,
    );
  });

  try {
    const response = await createRoomMember(
      "room-123",
      authenticatedClient(),
    );

    assert.equal(response.room_id, "room-123");
    assert.equal(
      String(calls[0]?.input),
      "http://127.0.0.1:8000/rooms/room-123/members",
    );
    assert.equal(calls[0]?.init?.method, "POST");
    assert.equal(calls[0]?.init?.body, JSON.stringify({}));
    assert.equal(
      JSON.stringify(calls[0]?.init?.body).includes("display_name"),
      false,
    );
  } finally {
    restoreFetch();
  }
});

test("getRoomMembers parses the authoritative member list", async () => {
  const restoreFetch = setFetch(async () =>
    jsonResponse({
      room_id: "room-123",
      members: [
        {
          user_id: "11111111-1111-4111-8111-111111111111",
          display_name: "Room Owner",
        },
      ],
      member_count: 1,
      maximum_members: 8,
    }),
  );

  try {
    const response = await getRoomMembers("room-123", authenticatedClient());

    assert.deepEqual(response.members, [
      {
        user_id: "11111111-1111-4111-8111-111111111111",
        display_name: "Room Owner",
      },
    ]);
    assert.equal(response.member_count, 1);
  } finally {
    restoreFetch();
  }
});

test("profile update sends only the safe display-name field", async () => {
  const calls: Array<{ init?: RequestInit }> = [];
  const restoreFetch = setFetch(async (_input, init) => {
    calls.push({ init });
    return jsonResponse({
      id: "11111111-1111-4111-8111-111111111111",
      display_name: "Updated Name",
    });
  });

  try {
    await updateProfile("Updated Name", authenticatedClient());
    assert.equal(calls[0]?.init?.method, "PUT");
    assert.equal(
      calls[0]?.init?.body,
      JSON.stringify({ display_name: "Updated Name" }),
    );
  } finally {
    restoreFetch();
  }
});

test("missing access token prevents a protected request", async () => {
  let fetchCalled = false;
  const restoreFetch = setFetch(async () => {
    fetchCalled = true;
    return jsonResponse({ status: "ok" });
  });

  try {
    await assert.rejects(
      createApiClient("http://127.0.0.1:8000", {
        getAccessToken: async () => null,
      }).requestJson("/rooms", { method: "POST", body: {} }),
      (error: unknown) => error instanceof AuthenticationApiError,
    );
    assert.equal(fetchCalled, false);
  } finally {
    restoreFetch();
  }
});

test("a 401 rejects with relogin guidance without automatic session mutation", async () => {
  const restoreFetch = setFetch(async () =>
    jsonResponse(
      {
        error: {
          code: "invalid_auth_token",
          message: "The authentication token is invalid.",
        },
      },
      401,
    ),
  );

  try {
    await assert.rejects(
      getRoom(
        "room-123",
        authenticatedClient(),
      ),
      (error: unknown) => {
        assert.ok(error instanceof BackendApiError);
        assert.equal(error.status, 401);
        assert.equal(error.code, "invalid_auth_token");
        assert.equal(getUserFacingErrorMessage(error), "Your session has expired. Please sign in again.");
        return true;
      },
    );
  } finally {
    restoreFetch();
  }
});

test("non-JSON backend errors become a safe typed fallback", async () => {
  const restoreFetch = setFetch(async () =>
    new Response("upstream stack trace", { status: 500 }),
  );

  try {
    await assert.rejects(
      getRoom("room-123", authenticatedClient()),
      (error: unknown) => {
        assert.ok(error instanceof BackendApiError);
        assert.equal(error.code, "request_failed");
        assert.equal(
          error.message,
          "The MindMesh server returned an unexpected error.",
        );
        assert.equal(error.message.includes("upstream"), false);
        return true;
      },
    );
  } finally {
    restoreFetch();
  }
});

test("a timeout becomes a typed timeout error", async () => {
  const restoreFetch = setFetch(async (_input, init) => {
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        const abortError = new Error("aborted");
        abortError.name = "AbortError";
        reject(abortError);
      });
    });
  });

  try {
    await assert.rejects(
      authenticatedClient().requestJson("/health", { timeoutMs: 5 }),
      (error: unknown) => error instanceof TimeoutApiError,
    );
  } finally {
    restoreFetch();
  }
});

test("a network failure becomes a typed network error", async () => {
  const restoreFetch = setFetch(async () => {
    throw new Error("connection refused");
  });

  try {
    await assert.rejects(
      getRoom("room-123", authenticatedClient()),
      (error: unknown) => error instanceof NetworkApiError,
    );
  } finally {
    restoreFetch();
  }
});

test("API base URLs trim trailing slashes", () => {
  assert.equal(
    normalizeApiBaseUrl("  http://localhost:8000/// "),
    "http://localhost:8000",
  );
});

test("a custom API client uses its normalized base URL", async () => {
  const calls: Array<RequestInfo | URL> = [];
  const restoreFetch = setFetch(async (input) => {
    calls.push(input);
    return jsonResponse({ status: "ok" });
  });

  try {
    await createApiClient("https://api.example.test///", {
      getAccessToken: async () => "access-token",
    }).requestJson("health");
    assert.equal(String(calls[0]), "https://api.example.test/health");
  } finally {
    restoreFetch();
  }
});
