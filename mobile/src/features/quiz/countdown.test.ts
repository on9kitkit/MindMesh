import assert from "node:assert/strict";
import test from "node:test";

import type { ZonedIsoTimestamp } from "../../realtime/protocol";
import {
  calibrateServerCountdown,
  getCountdownDisplay,
} from "./countdown";

const SERVER_TIME = "2030-01-01T12:00:00Z" as ZonedIsoTimestamp;
const CLOSES_AT = "2030-01-01T12:00:20Z" as ZonedIsoTimestamp;
const REVEAL_ENDS_AT = "2030-01-01T12:00:23Z" as ZonedIsoTimestamp;

test("countdown uses server-time distance and monotonic elapsed time", () => {
  const calibration = calibrateServerCountdown(SERVER_TIME, CLOSES_AT, 500);
  assert.deepEqual(getCountdownDisplay(calibration, 500), {
    remainingMs: 20_000,
    remainingWholeSeconds: 20,
    expired: false,
  });
  assert.equal(
    getCountdownDisplay(calibration, 1_250).remainingWholeSeconds,
    20,
  );
  assert.equal(getCountdownDisplay(calibration, 1_500).remainingWholeSeconds, 19);
});

test("question and reveal deadlines share the same server-clock calculation", () => {
  assert.equal(
    calibrateServerCountdown(SERVER_TIME, CLOSES_AT, 0)
      .remainingAtCalibrationMs,
    20_000,
  );
  assert.equal(
    calibrateServerCountdown(SERVER_TIME, REVEAL_ENDS_AT, 0)
      .remainingAtCalibrationMs,
    23_000,
  );
});

test("device wall-clock skew cannot affect countdown output", () => {
  const calibration = calibrateServerCountdown(SERVER_TIME, CLOSES_AT, 1_000);
  const beforeWallClockChange = getCountdownDisplay(calibration, 4_000);
  const afterWallClockChange = getCountdownDisplay(calibration, 4_000);
  assert.deepEqual(afterWallClockChange, beforeWallClockChange);
  assert.equal(beforeWallClockChange.remainingMs, 17_000);
});

test("countdown clamps at zero without producing a state transition", () => {
  const calibration = calibrateServerCountdown(SERVER_TIME, CLOSES_AT, 50);
  const display = getCountdownDisplay(calibration, 25_000);
  assert.deepEqual(display, {
    remainingMs: 0,
    remainingWholeSeconds: 0,
    expired: true,
  });
  assert.deepEqual(Object.keys(display).sort(), [
    "expired",
    "remainingMs",
    "remainingWholeSeconds",
  ]);
});

test("a fresh snapshot recalibrates from its new server time", () => {
  const first = calibrateServerCountdown(SERVER_TIME, CLOSES_AT, 100);
  assert.equal(getCountdownDisplay(first, 5_100).remainingMs, 15_000);

  const freshServerTime = "2030-01-01T12:00:08Z" as ZonedIsoTimestamp;
  const fresh = calibrateServerCountdown(freshServerTime, CLOSES_AT, 5_100);
  assert.equal(getCountdownDisplay(fresh, 5_100).remainingMs, 12_000);
});
