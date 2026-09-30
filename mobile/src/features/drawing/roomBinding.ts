import type { QuizPresentation } from "../quiz/quizPresentation";
import type { SessionState } from "../session/sessionState";
import type { DrawingPhase, DrawingScope } from "./types";

export type RoomDrawingBinding = Readonly<{
  scope: DrawingScope | null;
  phase: DrawingPhase;
  connected: boolean;
}>;

/** Derive private working authority from the same room snapshot as the answer UI. */
export function roomDrawingBinding(
  userId: string | null,
  routeRoomId: string | null,
  state: SessionState,
  presentation: QuizPresentation | null,
  appActive: boolean,
): RoomDrawingBinding {
  if (
    userId === null ||
    routeRoomId === null ||
    routeRoomId !== state.roomId ||
    presentation === null
  ) {
    return { scope: null, phase: "closed", connected: false };
  }

  const scope: DrawingScope = {
    userId,
    mode: "room",
    sessionId: presentation.sessionId,
    questionId: presentation.sessionQuestionId,
  };
  const connected =
    appActive &&
    state.connectionStage === "established" &&
    state.pendingSnapshotRequest === null &&
    presentation.connected;
  const phase: DrawingPhase =
    presentation.status === "question-open" && presentation.canInteract
      ? "answer-open"
      : "read-only";
  return { scope, phase, connected };
}
