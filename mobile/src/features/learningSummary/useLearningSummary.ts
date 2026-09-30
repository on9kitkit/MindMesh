import { useCallback, useEffect, useRef, useState } from "react";

import {
  getLearningSummary,
  type LearningSummaryResponse,
} from "../../api/learningSummary";
import { getUserFacingErrorMessage } from "../../api/errors";

export type LearningSummaryLoadState =
  | { status: "inactive" }
  | { status: "loading"; ownerId: string }
  | { status: "ready"; ownerId: string; summary: LearningSummaryResponse }
  | { status: "error"; ownerId: string; message?: string };

export function learningSummaryFailureMessage(error: unknown): string {
  return getUserFacingErrorMessage(error);
}

/** Prevent a prior identity or request from committing a late summary. */
export class LearningSummaryRequestTracker {
  private generation = 0;
  private ownerId: string | null = null;

  begin(ownerId: string | null): number {
    this.generation += 1;
    this.ownerId = ownerId;
    return this.generation;
  }

  isCurrent(generation: number, ownerId: string): boolean {
    return this.generation === generation && this.ownerId === ownerId;
  }

  invalidate(generation: number): void {
    if (this.generation === generation) {
      this.generation += 1;
      this.ownerId = null;
    }
  }
}

export function visibleLearningSummaryState(
  ownerId: string | null,
  stored: LearningSummaryLoadState,
): LearningSummaryLoadState {
  if (ownerId === null) return { status: "inactive" };
  if (stored.status === "inactive" || stored.ownerId !== ownerId) {
    return { status: "loading", ownerId };
  }
  return stored;
}

/** Transient, viewer-bound Account request; never persisted across identities. */
export function useLearningSummary(
  ownerId: string | null,
  load: () => Promise<LearningSummaryResponse> = getLearningSummary,
): {
  state: LearningSummaryLoadState;
  retry: () => void;
} {
  const [stored, setStored] = useState<LearningSummaryLoadState>({ status: "inactive" });
  const [retryVersion, setRetryVersion] = useState(0);
  const tracker = useRef<LearningSummaryRequestTracker | null>(null);
  if (tracker.current === null) {
    tracker.current = new LearningSummaryRequestTracker();
  }
  useEffect(() => {
    const currentTracker = tracker.current;
    if (currentTracker === null) return;
    const generation = currentTracker.begin(ownerId);
    if (ownerId === null) {
      setStored({ status: "inactive" });
      return () => currentTracker.invalidate(generation);
    }
    setStored({ status: "loading", ownerId });
    void load().then(
      (summary) => {
        if (currentTracker.isCurrent(generation, ownerId)) {
          setStored({ status: "ready", ownerId, summary });
        }
      },
      (error: unknown) => {
        if (currentTracker.isCurrent(generation, ownerId)) {
          setStored({
            status: "error",
            ownerId,
            message: learningSummaryFailureMessage(error),
          });
        }
      },
    );
    return () => currentTracker.invalidate(generation);
  }, [load, ownerId, retryVersion]);
  const retry = useCallback(() => setRetryVersion((version) => version + 1), []);
  return { state: visibleLearningSummaryState(ownerId, stored), retry };
}
