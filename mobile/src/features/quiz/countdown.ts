import { useEffect, useMemo, useReducer } from "react";

import type { ZonedIsoTimestamp } from "../../realtime/protocol";

export type CountdownCalibration = {
  remainingAtCalibrationMs: number;
  monotonicAtCalibrationMs: number;
};

export type CountdownDisplay = {
  remainingMs: number;
  remainingWholeSeconds: number;
  expired: boolean;
};

export function calibrateServerCountdown(
  serverTime: ZonedIsoTimestamp,
  deadline: ZonedIsoTimestamp,
  monotonicAtCalibrationMs: number,
): CountdownCalibration {
  const remainingAtCalibrationMs =
    Date.parse(deadline) - Date.parse(serverTime);
  if (!Number.isFinite(remainingAtCalibrationMs)) {
    throw new RangeError("Countdown timestamps must be valid server values.");
  }
  return {
    remainingAtCalibrationMs: Math.max(0, remainingAtCalibrationMs),
    monotonicAtCalibrationMs,
  };
}

export function getCountdownDisplay(
  calibration: CountdownCalibration,
  monotonicNowMs: number,
): CountdownDisplay {
  const elapsedMs = Math.max(
    0,
    monotonicNowMs - calibration.monotonicAtCalibrationMs,
  );
  const remainingMs = Math.max(
    0,
    calibration.remainingAtCalibrationMs - elapsedMs,
  );
  return {
    remainingMs,
    remainingWholeSeconds: Math.ceil(remainingMs / 1_000),
    expired: remainingMs === 0,
  };
}

function monotonicNow(): number {
  return globalThis.performance.now();
}

export function useServerCountdown(
  serverTime: ZonedIsoTimestamp | null,
  deadline: ZonedIsoTimestamp | null,
): CountdownDisplay {
  const calibration = useMemo(
    () =>
      serverTime === null || deadline === null
        ? null
        : calibrateServerCountdown(serverTime, deadline, monotonicNow()),
    [deadline, serverTime],
  );
  const [, requestTick] = useReducer((tick: number) => tick + 1, 0);

  useEffect(() => {
    if (calibration === null) {
      return;
    }
    requestTick();
    const interval = setInterval(requestTick, 250);
    return () => clearInterval(interval);
  }, [calibration]);

  if (calibration === null) {
    return { remainingMs: 0, remainingWholeSeconds: 0, expired: true };
  }
  return getCountdownDisplay(calibration, monotonicNow());
}
