import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import * as ts from "typescript";

import { createApiClient, type StudyRoomApiClient } from "./client";
import * as apiErrors from "./errors";
import {
  BackendApiError,
  getUserFacingErrorMessage,
  MalformedResponseError,
} from "./errors";
import {
  getLearningSummary,
  parseLearningSummaryResponse,
} from "./learningSummary";

function unauthorizedResponse(code = "invalid_auth_token"): Response {
  return new Response(JSON.stringify({ error: { code, message: "Synthetic 401" } }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });
}

async function exerciseUnauthorizedRequest(
  nextToken: string,
  code = "invalid_auth_token",
): Promise<number> {
  const originalFetch = globalThis.fetch;
  let currentToken = "synthetic-old-token";
  let tokenReads = 0;
  let resolveFetch: ((response: Response) => void) | undefined;
  let notifySent: (() => void) | undefined;
  const sent = new Promise<void>((resolve) => { notifySent = resolve; });
  globalThis.fetch = async (_input, init) => {
    assert.equal(new Headers(init?.headers).get("Authorization"), "Bearer synthetic-old-token");
    notifySent?.();
    return new Promise<Response>((resolve) => { resolveFetch = resolve; });
  };
  try {
    const client = createApiClient("https://example.invalid", {
      getAccessToken: async () => {
        tokenReads += 1;
        return currentToken;
      },
    });
    const request = client.requestJson("/me/learning-summary");
    await sent;
    currentToken = nextToken;
    assert.ok(resolveFetch);
    resolveFetch(unauthorizedResponse(code));
    await assert.rejects(request, (error: unknown) => {
      assert.ok(error instanceof BackendApiError);
      assert.equal(error.code, code);
      if (code === "invalid_auth_token") {
        assert.equal(getUserFacingErrorMessage(error), "Your session has expired. Please sign in again.");
      }
      return true;
    });
    assert.equal(currentToken, nextToken);
    return tokenReads;
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test("late summary 401 rejects the issuing request without re-reading replacement credentials", async () => {
  assert.equal(await exerciseUnauthorizedRequest("synthetic-refreshed-token"), 1);
  assert.equal(await exerciseUnauthorizedRequest("synthetic-user-B-token"), 1);
});

test("current 401 and recent-authentication 401 both reject without changing provider state", async () => {
  assert.equal(await exerciseUnauthorizedRequest("synthetic-old-token"), 1);
  assert.equal(await exerciseUnauthorizedRequest("synthetic-old-token", "recent_authentication_required"), 1);
});

test("production default HTTP client cannot enter deferred SDK cleanup after a 401", async () => {
  let currentToken = "synthetic-token-A";
  let tokenReads = 0;
  let cleanupEntered = 0;
  const revoked: string[] = [];
  const source = readFileSync(
    fileURLToPath(new URL("./client.ts", import.meta.url).href),
    "utf8",
  );
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} as Record<string, unknown> };
  const response = unauthorizedResponse();
  const destructiveCleanup = async () => {
    cleanupEntered += 1;
    // A replacement arrives after the old request's last token check while
    // provider lock/storage work is deferred. Neither old cleanup entry point
    // is permitted to reach this boundary from an HTTP 401.
    await Promise.resolve();
    currentToken = "synthetic-token-B";
    revoked.push(currentToken);
    currentToken = "removed";
  };
  runInNewContext(compiled, {
    module,
    exports: module.exports,
    require: (specifier: string) => {
      if (specifier === "./errors") return apiErrors;
      if (specifier === "../auth/session") {
        return {
          getCurrentAccessToken: async () => {
            tokenReads += 1;
            return currentToken;
          },
          clearSessionAfterUnauthorized: destructiveCleanup,
          clearSessionAfterUnauthorizedForAccessToken: destructiveCleanup,
        };
      }
      throw new Error(`Unexpected module: ${specifier}`);
    },
    fetch: async (_input: unknown, init: RequestInit) => {
      assert.equal(new Headers(init.headers).get("Authorization"), "Bearer synthetic-token-A");
      return response;
    },
    URL,
    Headers,
    AbortController,
    setTimeout,
    clearTimeout,
    process: { env: {} },
  });
  const client = module.exports.apiClient as StudyRoomApiClient;
  await assert.rejects(getLearningSummary(client), (error: unknown) => {
    assert.ok(error instanceof BackendApiError);
    assert.equal(error.code, "invalid_auth_token");
    return true;
  });
  assert.equal(tokenReads, 1);
  assert.equal(cleanupEntered, 0);
  assert.deepEqual(revoked, []);
  assert.equal(currentToken, "synthetic-token-A");
});

function topic(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    subject: "physics",
    topic: "forces",
    evidence_status: "observed",
    finished_session_count: 2,
    presented_question_count: 5,
    answered_attempt_count: 5,
    graded_attempt_count: 5,
    ungraded_attempt_count: 0,
    unanswered_question_count: 0,
    distinct_question_count: 5,
    repeat_attempt_count: 0,
    earned_marks: 4,
    possible_marks: 5,
    accuracy_on_graded_answers_percent: 80,
    full_credit_attempt_count: 4,
    partial_credit_attempt_count: 0,
    zero_credit_attempt_count: 1,
    ...overrides,
  };
}

function summary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    status: "observed",
    session_window: { limit: 100, included: 2, truncated: false },
    topics: [topic()],
    strongest_topics: [],
    weakest_topics: [],
    ...overrides,
  };
}

test("viewer-only summary parses bounded graded marks and excludes missing attempts", () => {
  const parsed = parseLearningSummaryResponse(
    summary({
      topics: [
        topic({
          presented_question_count: 7,
          answered_attempt_count: 6,
          ungraded_attempt_count: 1,
          unanswered_question_count: 1,
          distinct_question_count: 4,
          repeat_attempt_count: 1,
          evidence_status: "insufficient_evidence",
          earned_marks: 5,
          possible_marks: 7,
          accuracy_on_graded_answers_percent: 71.4,
          full_credit_attempt_count: 3,
          partial_credit_attempt_count: 1,
          zero_credit_attempt_count: 1,
        }),
      ],
      status: "insufficient_evidence",
    }),
  );
  assert.equal(parsed.topics[0]?.earned_marks, 5);
  assert.equal(parsed.topics[0]?.possible_marks, 7);
  assert.equal(parsed.topics[0]?.unanswered_question_count, 1);
  assert.equal(parsed.topics[0]?.ungraded_attempt_count, 1);
  assert.equal(parsed.topics[0]?.repeat_attempt_count, 1);
  assert.equal(parsed.status, "insufficient_evidence");
});

test("zero graded answers remain no-data while coverage is visible", () => {
  const parsed = parseLearningSummaryResponse(
    summary({
      status: "no_data",
      session_window: { limit: 100, included: 1, truncated: false },
      topics: [
        topic({
          evidence_status: "no_data",
          finished_session_count: 1,
          presented_question_count: 2,
          answered_attempt_count: 1,
          graded_attempt_count: 0,
          ungraded_attempt_count: 1,
          unanswered_question_count: 1,
          distinct_question_count: 0,
          repeat_attempt_count: 0,
          earned_marks: 0,
          possible_marks: 0,
          accuracy_on_graded_answers_percent: null,
          full_credit_attempt_count: 0,
          partial_credit_attempt_count: 0,
          zero_credit_attempt_count: 0,
        }),
      ],
    }),
  );
  assert.equal(parsed.topics[0]?.accuracy_on_graded_answers_percent, null);
  assert.equal(parsed.topics[0]?.presented_question_count, 2);
});

test("parser rejects extra private content and unknown subject/topic pairs", () => {
  for (const candidate of [
    summary({ user_id: "someone-else" }),
    summary({ topics: [topic({ answer_text: "private answer" })] }),
    summary({ topics: [topic({ subject: "mathematics", topic: "forces" })] }),
    summary({ strongest_topics: [{ subject: "physics", topic: "energy", room_id: "private" }] }),
  ]) {
    assert.throws(() => parseLearningSummaryResponse(candidate), MalformedResponseError);
  }
});

test("parser rejects inconsistent attempt partitions and fabricated percentages", () => {
  for (const override of [
    { presented_question_count: 4 },
    { ungraded_attempt_count: 1 },
    { repeat_attempt_count: 2 },
    { partial_credit_attempt_count: 1 },
    { earned_marks: 6 },
    { possible_marks: 2 },
    { possible_marks: 31 },
    { accuracy_on_graded_answers_percent: 95 },
    { evidence_status: "insufficient_evidence" },
  ]) {
    assert.throws(
      () => parseLearningSummaryResponse(summary({ topics: [topic(override)] })),
      MalformedResponseError,
    );
  }
});

test("parser rejects unbounded/duplicate topics and a foreign strongest key", () => {
  for (const candidate of [
    summary({ session_window: { limit: 100, included: 101, truncated: true } }),
    summary({ session_window: { limit: 100, included: 3, truncated: false } }),
    summary({ topics: [topic(), topic()] }),
    summary({ strongest_topics: [{ subject: "physics", topic: "energy" }] }),
    summary({ topics: [topic({ presented_question_count: 4001 })] }),
  ]) {
    assert.throws(() => parseLearningSummaryResponse(candidate), MalformedResponseError);
  }
});

test("relative higher/lower topic labels require within-subject evidence and preserve ties", () => {
  const rows = [
    topic({ subject: "physics", topic: "forces", earned_marks: 4 }),
    topic({ subject: "physics", topic: "energy", earned_marks: 4 }),
  ];
  const tied = summary({
    session_window: { limit: 100, included: 4, truncated: false },
    topics: rows,
    strongest_topics: [
      { subject: "physics", topic: "forces" },
      { subject: "physics", topic: "energy" },
    ],
    weakest_topics: [
      { subject: "physics", topic: "forces" },
      { subject: "physics", topic: "energy" },
    ],
  });
  assert.equal(parseLearningSummaryResponse(tied).strongest_topics.length, 2);
  assert.throws(
    () => parseLearningSummaryResponse({ ...tied, weakest_topics: [] }),
    MalformedResponseError,
  );
  assert.throws(
    () => parseLearningSummaryResponse({ ...tied, topics: [topic()] }),
    MalformedResponseError,
  );
});

test("client requests only the authenticated viewer route and validates payload", async () => {
  const paths: string[] = [];
  const client: StudyRoomApiClient = {
    baseUrl: "https://example.invalid",
    async requestJson(path) {
      paths.push(path);
      return summary();
    },
  };
  const parsed = await getLearningSummary(client);
  assert.deepEqual(paths, ["/me/learning-summary"]);
  assert.equal(parsed.status, "observed");
});
