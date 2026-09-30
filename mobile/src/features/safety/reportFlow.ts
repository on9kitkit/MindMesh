import {
  getApiErrorCode,
  getUserFacingErrorMessage,
  NetworkApiError,
  TimeoutApiError,
} from "../../api/errors";
import type {
  SafetyReportInput,
  SafetyReportReason,
  SafetyReportResponse,
} from "../../api/schemas";

export const MAX_REPORT_DETAILS_LENGTH = 500;

export type ReportDraft = {
  reason: SafetyReportReason | null;
  details: string;
};

export type ParticipantReportState =
  | { status: "selecting"; draft: ReportDraft; errorMessage: string | null }
  | { status: "reviewing"; draft: ReportDraft }
  | { status: "submitting"; draft: ReportDraft }
  | { status: "success" }
  | {
      status: "error";
      draft: ReportDraft;
      message: string;
      retryable: boolean;
    };

export type ParticipantReportDependencies = {
  submitReport(input: SafetyReportInput): Promise<SafetyReportResponse>;
};

const INITIAL_STATE: ParticipantReportState = {
  status: "selecting",
  draft: { reason: null, details: "" },
  errorMessage: null,
};

export function reportDetailsError(value: string): string | null {
  if (value.length > MAX_REPORT_DETAILS_LENGTH) {
    return `Keep details under ${MAX_REPORT_DETAILS_LENGTH} characters.`;
  }
  if ([...value].some((character) => /[\u0000-\u001F\u007F\u200B-\u200D\uFEFF]/u.test(character))) {
    return "Remove invisible or control characters from the details.";
  }
  return null;
}

export function normalizeReportDetails(value: string): string {
  return value.trim();
}

export class ParticipantReportController {
  private state: ParticipantReportState = INITIAL_STATE;
  private readonly listeners = new Set<() => void>();
  private operation = 0;
  private disposed = false;

  constructor(private readonly dependencies: ParticipantReportDependencies) {}

  readonly getState = (): ParticipantReportState => this.state;

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  setReason(reason: SafetyReportReason): void {
    if (this.disposed) return;
    if (this.state.status === "selecting") {
      this.setState({
        status: "selecting",
        draft: { ...this.state.draft, reason },
        errorMessage: null,
      });
    }
  }

  setDetails(details: string): void {
    if (this.disposed) return;
    if (this.state.status === "selecting") {
      this.setState({
        status: "selecting",
        draft: { ...this.state.draft, details },
        errorMessage: null,
      });
    }
  }

  review(): void {
    if (this.disposed || this.state.status !== "selecting") return;
    const detailsError = reportDetailsError(this.state.draft.details);
    if (detailsError !== null) {
      this.setState({ ...this.state, errorMessage: detailsError });
      return;
    }
    if (this.state.draft.reason === null) {
      this.setState({
        ...this.state,
        errorMessage: "Choose a reason before reviewing the report.",
      });
      return;
    }
    this.setState({
      status: "reviewing",
      draft: {
        ...this.state.draft,
        details: normalizeReportDetails(this.state.draft.details),
      },
    });
  }

  edit(): void {
    if (this.disposed) return;
    if (this.state.status === "reviewing" || this.state.status === "error") {
      this.setState({
        status: "selecting",
        draft: this.state.draft,
        errorMessage: null,
      });
    }
  }

  submit(input: Omit<SafetyReportInput, "reason" | "details">): Promise<void> {
    if (this.disposed) return Promise.resolve();
    const draft = this.state.status === "reviewing" || this.state.status === "error"
      ? this.state.draft
      : null;
    if (draft === null || draft.reason === null) return Promise.resolve();
    if (this.state.status === "error" && !this.state.retryable) {
      return Promise.resolve();
    }

    const operation = ++this.operation;
    const normalizedDetails = normalizeReportDetails(draft.details);
    this.setState({
      status: "submitting",
      draft: { ...draft, details: normalizedDetails },
    });
    return this.dependencies
      .submitReport({
        ...input,
        reason: draft.reason,
        ...(normalizedDetails ? { details: normalizedDetails } : {}),
      })
      .then(() => {
        if (this.isCurrent(operation)) this.setState({ status: "success" });
      })
      .catch((error: unknown) => {
        if (!this.isCurrent(operation)) return;
        const code = getApiErrorCode(error);
        const retryable =
          code !== "safety_report_not_allowed" &&
          code !== "validation_error";
        const message =
          code === "safety_report_not_allowed"
            ? "This concern could not be reported from this room."
            : getUserFacingErrorMessage(error);
        this.setState({
          status: "error",
          draft: { ...draft, details: normalizedDetails },
          message,
          retryable,
        });
      });
  }

  reset(): void {
    if (this.disposed || this.state.status === "submitting") return;
    this.operation += 1;
    this.setState(INITIAL_STATE);
  }

  dispose(): void {
    this.disposed = true;
    this.operation += 1;
    this.listeners.clear();
  }

  private isCurrent(operation: number): boolean {
    return !this.disposed && operation === this.operation;
  }

  private setState(state: ParticipantReportState): void {
    if (this.disposed) return;
    this.state = state;
    for (const listener of this.listeners) listener();
  }
}

export function isRetryableReportError(error: unknown): boolean {
  return error instanceof NetworkApiError || error instanceof TimeoutApiError;
}
