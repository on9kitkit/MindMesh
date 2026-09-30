import assert from "node:assert/strict";
import test from "node:test";

import {
  LearningSummaryRequestTracker,
  learningSummaryFailureMessage,
  visibleLearningSummaryState,
} from "./useLearningSummary";
import type { LearningSummaryResponse } from "../../api/learningSummary";
import { BackendApiError, NetworkApiError } from "../../api/errors";

const SUMMARY: LearningSummaryResponse = {
  status: "no_data",
  session_window: { limit: 100, included: 0, truncated: false },
  topics: [],
  strongest_topics: [],
  weakest_topics: [],
};

test("a prior learner's data is invisible synchronously after auth changes", () => {
  const oldState = { status: "ready" as const, ownerId: "learner-a", summary: SUMMARY };
  assert.deepEqual(visibleLearningSummaryState("learner-b", oldState), {
    status: "loading",
    ownerId: "learner-b",
  });
  assert.deepEqual(visibleLearningSummaryState(null, oldState), { status: "inactive" });
  assert.equal(visibleLearningSummaryState("learner-a", oldState), oldState);
});

test("request generations reject late prior-identity, retry and unmount completions", () => {
  const tracker = new LearningSummaryRequestTracker();
  const first = tracker.begin("learner-a");
  assert.equal(tracker.isCurrent(first, "learner-a"), true);
  tracker.invalidate(first);
  const second = tracker.begin("learner-b");
  assert.equal(tracker.isCurrent(first, "learner-a"), false);
  assert.equal(tracker.isCurrent(second, "learner-a"), false);
  assert.equal(tracker.isCurrent(second, "learner-b"), true);
  tracker.invalidate(second);
  const retry = tracker.begin("learner-b");
  assert.equal(tracker.isCurrent(second, "learner-b"), false);
  assert.equal(tracker.isCurrent(retry, "learner-b"), true);
  tracker.invalidate(retry);
  assert.equal(tracker.isCurrent(retry, "learner-b"), false);
});

test("a genuine summary 401 surfaces existing relogin guidance without raw backend text", () => {
  assert.equal(
    learningSummaryFailureMessage(
      new BackendApiError("invalid_auth_token", "Synthetic backend detail", 401),
    ),
    "Your session has expired. Please sign in again.",
  );
  assert.equal(
    learningSummaryFailureMessage(new NetworkApiError()),
    "Could not reach the StudyRoom server.",
  );
});
