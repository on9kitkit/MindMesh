import type { SoloAttempt } from "../../api/solo";
import type { DrawingPhase, DrawingScope } from "../drawing/types";

export type SoloDrawingBinding = Readonly<{
  scope: DrawingScope | null;
  phase: DrawingPhase;
  connected: boolean;
}>;

/** Untimed, local-only drawing authority follows the current saved solo question. */
export function soloDrawingBinding(
  ownerId: string | null,
  attempt: SoloAttempt | null,
  appActive: boolean,
  needsReconcile: boolean,
): SoloDrawingBinding {
  if (ownerId === null || attempt?.status !== "IN_PROGRESS") {
    return { scope: null, phase: "closed", connected: false };
  }
  const question = attempt.questions[attempt.current_question_position];
  if (question === undefined) {
    return { scope: null, phase: "closed", connected: false };
  }
  const answered = attempt.answers.some((answer) => answer.question_id === question.id);
  return {
    scope: {
      userId: ownerId,
      mode: "solo",
      sessionId: attempt.id,
      questionId: question.id,
    },
    phase: answered ? "read-only" : "answer-open",
    connected: appActive && !needsReconcile,
  };
}
