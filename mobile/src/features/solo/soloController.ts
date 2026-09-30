import {
  abandonSoloAttempt,
  createSoloAttempt,
  finalizeSoloSelfCheck,
  getActiveSoloAttempt,
  getSoloAttempt,
  getSoloReview,
  getSoloSelfCheck,
  retrySoloMarking,
  startSoloAttempt,
  submitSoloAnswer,
  type SoloAnswerInput,
  type SoloAttempt,
  type SoloCreateInput,
  type SoloReview,
  type SoloSelfCheck,
} from "../../api/solo";
import { BackendApiError, getUserFacingErrorMessage } from "../../api/errors";
import {
  createPreparationRequestId,
  getAdaptiveSelectionValidationMessage,
  type AdaptiveQuizSelection,
} from "../quiz/adaptiveQuiz";

export type SoloCommand =
  | "load" | "refresh" | "create" | "start" | "answer" | "self-check"
  | "finalize-check" | "retry-marking" | "review" | "abandon";

export type SoloControllerState = Readonly<{
  ownerId: string | null;
  loaded: boolean;
  attempt: SoloAttempt | null;
  selfCheck: SoloSelfCheck | null;
  review: SoloReview | null;
  busy: SoloCommand | null;
  error: string | null;
  /** A mutation may have committed even when its acknowledgement failed. */
  needsReconcile: boolean;
}>;

export type SoloApi = Readonly<{
  getActive(): Promise<SoloAttempt | null>;
  getAttempt(attemptId: string): Promise<SoloAttempt>;
  create(input: SoloCreateInput): Promise<SoloAttempt>;
  start(attemptId: string): Promise<SoloAttempt>;
  answer(attemptId: string, input: SoloAnswerInput): Promise<unknown>;
  selfCheck(attemptId: string, questionId: string): Promise<SoloSelfCheck>;
  finalizeCheck(attemptId: string, questionId: string, selectedIds: readonly string[]): Promise<unknown>;
  retryMarking(attemptId: string): Promise<number>;
  abandon(attemptId: string): Promise<SoloAttempt>;
  review(attemptId: string): Promise<SoloReview>;
}>;

const productionApi: SoloApi = {
  getActive: getActiveSoloAttempt,
  getAttempt: getSoloAttempt,
  create: createSoloAttempt,
  start: startSoloAttempt,
  answer: submitSoloAnswer,
  selfCheck: getSoloSelfCheck,
  finalizeCheck: finalizeSoloSelfCheck,
  retryMarking: retrySoloMarking,
  abandon: abandonSoloAttempt,
  review: getSoloReview,
};

const INITIAL_STATE: SoloControllerState = {
  ownerId: null,
  loaded: false,
  attempt: null,
  selfCheck: null,
  review: null,
  busy: null,
  error: null,
  needsReconcile: false,
};

type RequestToken = Readonly<{ ownerId: string; generation: number }>;

function sameSelection(
  left: AdaptiveQuizSelection,
  right: AdaptiveQuizSelection,
): boolean {
  return left.subject === right.subject && left.topic === right.topic && left.totalMarks === right.totalMarks;
}

export function soloFailureMessage(error: unknown): string {
  if (error instanceof BackendApiError) {
    switch (error.code) {
      case "solo_active_room":
        return "Return to or leave your active room before starting solo study.";
      case "solo_active_attempt":
        return "Resume or abandon your saved solo quiz first.";
      case "solo_home_zone_required":
        return "Choose your home timezone on Home before starting solo study.";
      case "solo_marking_pending":
        return "Written marking is still in progress. Your answers are saved.";
      case "solo_generation_unavailable":
        return "Quiz preparation is temporarily unavailable. Please try again.";
      case "solo_conflict":
        return "This action conflicts with saved progress. Refresh the quiz before continuing.";
      case "solo_not_ready":
        return "The quiz is still preparing. Refresh to check its status.";
      case "solo_not_found":
        return "This solo quiz is no longer available.";
    }
  }
  return getUserFacingErrorMessage(error);
}

/** All responses are bound to an identity and newest request generation. */
export function visibleSoloState(
  ownerId: string | null,
  state: SoloControllerState,
): SoloControllerState {
  if (ownerId === null) return INITIAL_STATE;
  if (state.ownerId !== ownerId) {
    return { ...INITIAL_STATE, ownerId, busy: "load" };
  }
  return state;
}

export class SoloController {
  private state: SoloControllerState = INITIAL_STATE;
  private readonly listeners = new Set<() => void>();
  private generation = 0;
  private pendingCreate: { selection: AdaptiveQuizSelection; requestId: string } | null = null;

  constructor(
    private readonly api: SoloApi = productionApi,
    private readonly makeRequestId: () => string = createPreparationRequestId,
  ) {}

  getState = (): SoloControllerState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private publish(next: SoloControllerState): void {
    this.state = next;
    for (const listener of this.listeners) listener();
  }

  setOwner(ownerId: string | null): void {
    if (this.state.ownerId === ownerId) return;
    this.generation += 1;
    this.pendingCreate = null;
    this.publish({
      ...INITIAL_STATE,
      ownerId,
    });
  }

  dispose(): void {
    this.generation += 1;
    this.pendingCreate = null;
    this.state = INITIAL_STATE;
    this.listeners.clear();
  }

  private begin(command: SoloCommand, mayHaveCommitted: boolean): RequestToken | null {
    const ownerId = this.state.ownerId;
    if (ownerId === null || this.state.busy !== null) return null;
    this.generation += 1;
    this.publish({
      ...this.state,
      busy: command,
      error: null,
      needsReconcile: this.state.needsReconcile || mayHaveCommitted,
    });
    return { ownerId, generation: this.generation };
  }

  private current(token: RequestToken): boolean {
    return this.generation === token.generation && this.state.ownerId === token.ownerId;
  }

  private failed(token: RequestToken, error: unknown): void {
    if (!this.current(token)) return;
    this.publish({ ...this.state, busy: null, error: soloFailureMessage(error) });
  }

  private acceptAttempt(token: RequestToken, attempt: SoloAttempt): void {
    if (!this.current(token)) return;
    const previous = this.state.attempt;
    const sameQuestion = previous?.id === attempt.id &&
      previous.current_question_position === attempt.current_question_position &&
      previous.questions[attempt.current_question_position]?.id === attempt.questions[attempt.current_question_position]?.id;
    this.publish({
      ...this.state,
      loaded: true,
      attempt,
      selfCheck: sameQuestion && attempt.status === "IN_PROGRESS" ? this.state.selfCheck : null,
      review: attempt.status === "FINISHED" && previous?.id === attempt.id ? this.state.review : null,
      busy: null,
      error: null,
      needsReconcile: false,
    });
  }

  async loadActive(): Promise<void> {
    if (this.state.ownerId === null) return;
    const token = this.begin("load", false);
    if (token === null) return;
    try {
      const attempt = await this.api.getActive();
      if (!this.current(token)) return;
      this.pendingCreate = null;
      this.publish({
        ...this.state, loaded: true, attempt, selfCheck: null, review: null,
        busy: null, error: null, needsReconcile: false,
      });
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  async refresh(): Promise<void> {
    const token = this.begin("refresh", false);
    if (token === null) return;
    const attemptId = this.state.attempt?.id ?? null;
    try {
      const attempt = attemptId === null
        ? await this.api.getActive()
        : await this.api.getAttempt(attemptId);
      if (attempt === null) {
        if (this.current(token)) {
          this.publish({ ...this.state, loaded: true, attempt: null, selfCheck: null,
            review: null, busy: null, error: null, needsReconcile: false });
        }
      } else if (attemptId === null || attempt.id === attemptId) {
        this.acceptAttempt(token, attempt);
      } else {
        this.failed(token, new Error("Solo attempt changed during refresh."));
      }
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  async create(selection: AdaptiveQuizSelection): Promise<void> {
    if (this.state.attempt !== null || getAdaptiveSelectionValidationMessage(selection) !== null) return;
    const token = this.begin("create", true);
    if (token === null) return;
    const pending = this.pendingCreate;
    const requestId = pending !== null && sameSelection(pending.selection, selection)
      ? pending.requestId : this.makeRequestId();
    this.pendingCreate = { selection, requestId };
    try {
      const attempt = await this.api.create({
        request_id: requestId, subject: selection.subject,
        topic: selection.topic, total_marks: selection.totalMarks,
      });
      if (attempt.request_id !== requestId) throw new Error("Solo request identity changed.");
      this.acceptAttempt(token, attempt);
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  async start(): Promise<void> {
    const attempt = this.state.attempt;
    if (attempt?.status !== "READY" || this.state.needsReconcile) return;
    const token = this.begin("start", true);
    if (token === null) return;
    try {
      const started = await this.api.start(attempt.id);
      if (started.id !== attempt.id) throw new Error("Solo attempt changed during start.");
      this.acceptAttempt(token, started);
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  async submitAnswer(input: SoloAnswerInput): Promise<void> {
    const attempt = this.state.attempt;
    const question = attempt?.questions[attempt.current_question_position];
    if (
      attempt?.status !== "IN_PROGRESS" || question === undefined ||
      question.id !== input.question_id || this.state.needsReconcile ||
      attempt.answers.some((answer) => answer.question_id === question.id)
    ) return;
    const token = this.begin("answer", true);
    if (token === null) return;
    try {
      await this.api.answer(attempt.id, input);
      if (!this.current(token)) return;
      const refreshed = await this.api.getAttempt(attempt.id);
      if (refreshed.id !== attempt.id) throw new Error("Solo attempt changed after answer.");
      this.acceptAttempt(token, refreshed);
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  async loadSelfCheck(): Promise<void> {
    const attempt = this.state.attempt;
    const question = attempt?.questions[attempt.current_question_position];
    const answer = attempt?.answers.find((item) => item.question_id === question?.id);
    if (
      attempt?.status !== "IN_PROGRESS" || question === undefined ||
      answer?.grading_status !== "SELF_CHECK_PENDING" ||
      answer.mark_provenance !== "SELF_ASSESSED" || this.state.needsReconcile
    ) return;
    const token = this.begin("self-check", false);
    if (token === null) return;
    try {
      const selfCheck = await this.api.selfCheck(attempt.id, question.id);
      if (selfCheck.question_id !== question.id || selfCheck.locked_answer !== answer.answer_text) {
        throw new Error("Solo marking guide changed question.");
      }
      if (this.current(token)) {
        this.publish({ ...this.state, selfCheck, busy: null, error: null });
      }
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  async finalizeSelfCheck(selectedIds: readonly string[]): Promise<void> {
    const attempt = this.state.attempt;
    const question = attempt?.questions[attempt.current_question_position];
    if (
      attempt?.status !== "IN_PROGRESS" || question === undefined ||
      this.state.selfCheck?.question_id !== question.id || this.state.needsReconcile
    ) return;
    const token = this.begin("finalize-check", true);
    if (token === null) return;
    try {
      await this.api.finalizeCheck(attempt.id, question.id, selectedIds);
      if (!this.current(token)) return;
      const refreshed = await this.api.getAttempt(attempt.id);
      if (refreshed.id !== attempt.id) throw new Error("Solo attempt changed after self-check.");
      this.acceptAttempt(token, refreshed);
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  async retryMarking(): Promise<void> {
    const attempt = this.state.attempt;
    if (
      attempt === null || !["IN_PROGRESS", "AWAITING_MARKING"].includes(attempt.status) ||
      !attempt.answers.some((answer) => answer.grading_status === "UNAVAILABLE") ||
      this.state.needsReconcile
    ) return;
    const token = this.begin("retry-marking", true);
    if (token === null) return;
    try {
      await this.api.retryMarking(attempt.id);
      if (!this.current(token)) return;
      const refreshed = await this.api.getAttempt(attempt.id);
      if (refreshed.id !== attempt.id) throw new Error("Solo attempt changed after retry.");
      this.acceptAttempt(token, refreshed);
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  async loadReview(): Promise<void> {
    const attempt = this.state.attempt;
    if (attempt?.status !== "FINISHED" || this.state.review !== null) return;
    const token = this.begin("review", false);
    if (token === null) return;
    try {
      const review = await this.api.review(attempt.id);
      if (review.attempt.id !== attempt.id) throw new Error("Solo review changed attempt.");
      if (this.current(token)) {
        this.publish({ ...this.state, review, busy: null, error: null });
      }
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  async abandon(): Promise<void> {
    const attempt = this.state.attempt;
    if (
      attempt === null || !["PREPARING", "READY", "IN_PROGRESS", "AWAITING_MARKING"].includes(attempt.status) ||
      this.state.needsReconcile
    ) return;
    const token = this.begin("abandon", true);
    if (token === null) return;
    try {
      const abandoned = await this.api.abandon(attempt.id);
      if (abandoned.id !== attempt.id || abandoned.status !== "ABANDONED") {
        throw new Error("Solo attempt changed during abandonment.");
      }
      this.acceptAttempt(token, abandoned);
    } catch (error: unknown) {
      this.failed(token, error);
    }
  }

  clearTerminal(): void {
    if (this.state.busy !== null || !["ABANDONED", "FAILED"].includes(this.state.attempt?.status ?? "")) return;
    this.generation += 1;
    this.pendingCreate = null;
    this.publish({ ...this.state, attempt: null, selfCheck: null, review: null,
      error: null, needsReconcile: false });
  }
}
