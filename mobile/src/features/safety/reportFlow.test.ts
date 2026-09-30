import assert from "node:assert/strict";
import test from "node:test";

import { BackendApiError, NetworkApiError } from "../../api/errors";
import {
  ParticipantReportController,
  reportDetailsError,
} from "./reportFlow";

test("report review requires a reason and trims bounded details", () => {
  const controller = new ParticipantReportController({
    submitReport: async () => ({ status: "report_received" }),
  });
  controller.review();
  const selectingState = controller.getState();
  assert.equal(selectingState.status, "selecting");
  assert.equal(
    selectingState.status === "selecting"
      ? selectingState.errorMessage
      : null,
    "Choose a reason before reviewing the report.",
  );
  controller.setReason("other_safety_concern");
  controller.setDetails("  Keep this short.  ");
  controller.review();
  assert.deepEqual(controller.getState(), {
    status: "reviewing",
    draft: { reason: "other_safety_concern", details: "Keep this short." },
  });
});

test("report details reject excessive and invisible content", () => {
  assert.notEqual(reportDetailsError("x".repeat(501)), null);
  assert.notEqual(reportDetailsError("visible\u200btext"), null);
  assert.equal(reportDetailsError("visible text"), null);
});

test("duplicate report taps produce one request", async () => {
  let calls = 0;
  let resolveRequest: (() => void) | undefined;
  const pending = new Promise<void>((resolve) => {
    resolveRequest = resolve;
  });
  const controller = new ParticipantReportController({
    submitReport: async () => {
      calls += 1;
      await pending;
      return { status: "report_received" };
    },
  });
  controller.setReason("disruptive_room_behaviour");
  controller.review();
  const first = controller.submit({
    room_id: "room-id",
    reported_user_id: "target-id",
  });
  const second = controller.submit({
    room_id: "room-id",
    reported_user_id: "target-id",
  });
  assert.equal(calls, 1);
  resolveRequest?.();
  await Promise.all([first, second]);
  assert.deepEqual(controller.getState(), { status: "success" });
});

test("authorization failure is not offered as an endless retry", async () => {
  const controller = new ParticipantReportController({
    submitReport: async () => {
      throw new BackendApiError(
        "safety_report_not_allowed",
        "This safety report could not be submitted.",
        403,
      );
    },
  });
  controller.setReason("other_safety_concern");
  controller.review();
  await controller.submit({
    room_id: "room-id",
    reported_user_id: "target-id",
  });
  const errorState = controller.getState();
  assert.equal(errorState.status, "error");
  assert.equal(
    errorState.status === "error"
      ? errorState.retryable
      : true,
    false,
  );
});

test("network report failure remains recoverable", async () => {
  const controller = new ParticipantReportController({
    submitReport: async () => {
      throw new NetworkApiError();
    },
  });
  controller.setReason("other_safety_concern");
  controller.review();
  await controller.submit({ room_id: "room-id", reported_user_id: "target-id" });
  const errorState = controller.getState();
  assert.equal(
    errorState.status === "error"
      ? errorState.retryable
      : false,
    true,
  );
});
