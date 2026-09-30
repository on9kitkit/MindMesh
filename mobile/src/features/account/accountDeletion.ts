import {
  getApiErrorCode,
  getUserFacingErrorMessage,
  NetworkApiError,
  TimeoutApiError,
} from "../../api/errors";
import type { AccountDeletionResponse } from "../../api/schemas";

export const ACCOUNT_DELETION_CONFIRMATION = "DELETE";

export type AccountDeletionState =
  | { status: "idle" }
  | {
      status: "confirming";
      confirmation: string;
      errorMessage: string | null;
    }
  | {
      status: "reauth_required";
      confirmation: typeof ACCOUNT_DELETION_CONFIRMATION;
      errorMessage: string | null;
    }
  | {
      status: "reauthenticating";
      confirmation: typeof ACCOUNT_DELETION_CONFIRMATION;
    }
  | {
      status: "deleting";
      confirmation: typeof ACCOUNT_DELETION_CONFIRMATION;
      retriedAfterReauthentication: boolean;
    }
  | {
      status: "deleted";
      providerCleanupPending: boolean;
    }
  | {
      status: "error";
      confirmation: string;
      message: string;
      retryable: boolean;
      retriedAfterReauthentication: boolean;
    };

export type AccountDeletionDependencies = {
  deleteAccount(): Promise<AccountDeletionResponse>;
  reauthenticate(password: string): Promise<void>;
  completeLocalCleanup(message: string): Promise<void>;
};

type StateListener = () => void;

const INITIAL_STATE: AccountDeletionState = { status: "idle" };

function isNetworkFailure(error: unknown): boolean {
  return error instanceof NetworkApiError || error instanceof TimeoutApiError;
}

function deletionFailureMessage(
  error: unknown,
  retriedAfterReauthentication: boolean,
): string {
  const code = getApiErrorCode(error);
  if (code === "account_deletion_blocked_active_quiz") {
    return getUserFacingErrorMessage(error);
  }
  if (isNetworkFailure(error)) {
    return getUserFacingErrorMessage(error);
  }
  if (retriedAfterReauthentication) {
    return "Your password was accepted, but the account could not be deleted. Sign in again and try again.";
  }
  return "Account deletion could not be completed. Please try again.";
}

function completionMessage(providerCleanupPending: boolean): string {
  if (providerCleanupPending) {
    return "Your StudyRoom account has been deleted. If you have StudyRoom Pro, cancel the store subscription separately; some linked records may finish clearing shortly.";
  }
  return "Your StudyRoom account has been deleted. If you have StudyRoom Pro, cancel the store subscription separately.";
}

export class AccountDeletionController {
  private state: AccountDeletionState = INITIAL_STATE;
  private readonly listeners = new Set<StateListener>();
  private operation = 0;
  private disposed = false;

  constructor(private readonly dependencies: AccountDeletionDependencies) {}

  readonly getState = (): AccountDeletionState => this.state;

  readonly subscribe = (listener: StateListener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  start(): void {
    if (this.disposed || this.state.status !== "idle") {
      return;
    }
    this.setState({
      status: "confirming",
      confirmation: "",
      errorMessage: null,
    });
  }

  setConfirmation(confirmation: string): void {
    if (this.disposed) {
      return;
    }
    if (
      this.state.status === "confirming" ||
      this.state.status === "error"
    ) {
      this.setState({
        status: "confirming",
        confirmation,
        errorMessage: null,
      });
    }
  }

  submit(): Promise<void> {
    if (this.disposed) {
      return Promise.resolve();
    }
    if (this.state.status === "confirming") {
      if (this.state.confirmation !== ACCOUNT_DELETION_CONFIRMATION) {
        this.setState({
          ...this.state,
          errorMessage: "Type DELETE exactly to confirm account deletion.",
        });
        return Promise.resolve();
      }
      return this.executeDelete(false);
    }
    if (
      this.state.status === "error" &&
      this.state.retryable &&
      this.state.confirmation === ACCOUNT_DELETION_CONFIRMATION
    ) {
      return this.executeDelete(this.state.retriedAfterReauthentication);
    }
    return Promise.resolve();
  }

  submitPassword(password: string): Promise<void> {
    if (this.disposed || this.state.status !== "reauth_required") {
      return Promise.resolve();
    }
    if (!password) {
      this.setState({
        ...this.state,
        errorMessage: "Enter your current password to continue.",
      });
      return Promise.resolve();
    }

    const operation = ++this.operation;
    this.setState({
      status: "reauthenticating",
      confirmation: ACCOUNT_DELETION_CONFIRMATION,
    });
    return this.reauthenticateAndRetry(password, operation);
  }

  reset(): void {
    if (
      this.disposed ||
      this.state.status === "deleting" ||
      this.state.status === "reauthenticating"
    ) {
      return;
    }
    this.operation += 1;
    this.setState(INITIAL_STATE);
  }

  dispose(): void {
    this.disposed = true;
    this.operation += 1;
    this.listeners.clear();
  }

  private async reauthenticateAndRetry(
    password: string,
    operation: number,
  ): Promise<void> {
    try {
      await this.dependencies.reauthenticate(password);
    } catch {
      if (this.isCurrent(operation)) {
        this.setState({
          status: "reauth_required",
          confirmation: ACCOUNT_DELETION_CONFIRMATION,
          errorMessage: "The password could not be confirmed. Check it and try again.",
        });
      }
      return;
    }

    if (!this.isCurrent(operation)) {
      return;
    }
    await this.executeDelete(true);
  }

  private async executeDelete(
    retriedAfterReauthentication: boolean,
  ): Promise<void> {
    const operation = ++this.operation;
    this.setState({
      status: "deleting",
      confirmation: ACCOUNT_DELETION_CONFIRMATION,
      retriedAfterReauthentication,
    });
    try {
      const response = await this.dependencies.deleteAccount();
      if (!this.isCurrent(operation)) {
        return;
      }
      this.completeDeletion(
        operation,
        response.provider_cleanup_pending,
      );
    } catch (error: unknown) {
      if (!this.isCurrent(operation)) {
        return;
      }
      const code = getApiErrorCode(error);
      if (code === "account_deleted") {
        this.completeDeletion(operation, true);
        return;
      }
      if (
        code === "recent_authentication_required" &&
        !retriedAfterReauthentication
      ) {
        this.setState({
          status: "reauth_required",
          confirmation: ACCOUNT_DELETION_CONFIRMATION,
          errorMessage: null,
        });
        return;
      }
      this.setState({
        status: "error",
        confirmation: ACCOUNT_DELETION_CONFIRMATION,
        message: deletionFailureMessage(error, retriedAfterReauthentication),
        retryable: !retriedAfterReauthentication || isNetworkFailure(error),
        retriedAfterReauthentication,
      });
    }
  }

  private completeDeletion(
    operation: number,
    providerCleanupPending: boolean,
  ): void {
    if (!this.isCurrent(operation)) {
      return;
    }
    this.setState({ status: "deleted", providerCleanupPending });
    const message = completionMessage(providerCleanupPending);
    try {
      void this.dependencies.completeLocalCleanup(message).catch(() => {
        // Local deletion is authoritative. Cleanup failures cannot turn it
        // into a reported deletion failure or recreate the account.
      });
    } catch {
      // A synchronous cleanup failure is handled the same way.
    }
  }

  private isCurrent(operation: number): boolean {
    return !this.disposed && operation === this.operation;
  }

  private setState(state: AccountDeletionState): void {
    if (this.disposed) {
      return;
    }
    this.state = state;
    for (const listener of this.listeners) {
      listener();
    }
  }
}
