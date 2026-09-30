import type {
  CanonicalUuid,
  LeaderboardEntryPayload,
  ZonedIsoTimestamp,
} from "../../realtime/protocol";
import type { SessionState } from "../session/sessionState";

export type ResultsLeaderboardRow = {
  entry: LeaderboardEntryPayload;
  placement: number;
  isCurrentUser: boolean;
};

export type ResultsPresentation = {
  sessionId: CanonicalUuid;
  roomId: CanonicalUuid;
  totalQuestions: number;
  finishedAt: ZonedIsoTimestamp;
  quizMode: "LEGACY_PHYSICS" | "ADAPTIVE";
  totalEarnedMarks: number;
  totalAvailableMarks: number;
  leaderboard: ResultsLeaderboardRow[];
};

export function buildResultsPresentation(
  state: SessionState,
  authenticatedUserId: string,
): ResultsPresentation | null {
  const snapshot = state.snapshot;
  if (
    state.roomId === null ||
    snapshot?.status !== "FINISHED" ||
    snapshot.room_state.room_id !== state.roomId ||
    !snapshot.viewer_participated
  ) {
    return null;
  }
  const viewerRow = snapshot.leaderboard.find(
    (entry) => entry.user_id === authenticatedUserId,
  );
  return {
    sessionId: snapshot.session_id,
    roomId: snapshot.room_state.room_id,
    totalQuestions: snapshot.total_question_count,
    finishedAt: snapshot.finished_at,
    quizMode: snapshot.quiz_mode,
    totalEarnedMarks: viewerRow?.earned_marks ?? 0,
    totalAvailableMarks: snapshot.total_available_marks,
    leaderboard: snapshot.leaderboard.map((entry) => ({
      entry,
      placement: entry.rank,
      isCurrentUser: entry.user_id === authenticatedUserId,
    })),
  };
}

export function formatLeaderboardMarks(entry: {
  earned_marks: number;
  total_available_marks: number;
}): string {
  return `${entry.earned_marks}/${entry.total_available_marks} marks`;
}

/**
 * Adaptive `correct_answers` counts only full-mark questions, so pairing it
 * with raw marks as "N correct" would hide partial credit. Adaptive surfaces
 * say "N full-mark answer(s)"; legacy keeps the exact "N correct" wording.
 */
export function formatCorrectAnswersLabel(
  correctAnswers: number,
  quizMode: "LEGACY_PHYSICS" | "ADAPTIVE",
): string {
  if (quizMode !== "ADAPTIVE") {
    return `${correctAnswers} correct`;
  }
  return correctAnswers === 1 ? "1 full-mark answer" : `${correctAnswers} full-mark answers`;
}

export function canDismissFinishedSession(state: SessionState): boolean {
  return (
    state.roomId !== null &&
    state.snapshot?.status === "FINISHED" &&
    state.snapshot.room_state.room_id === state.roomId &&
    state.dismissedFinishedSessionId !== state.snapshot.session_id
  );
}
