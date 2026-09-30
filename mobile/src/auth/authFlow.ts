export type AuthenticatedUser = {
  id: string;
  email: string | null;
  displayName?: string;
};

export type ProfileBootstrapState =
  | { status: "not-required" }
  | { status: "pending" }
  | { status: "syncing" }
  | { status: "ready" }
  | { status: "recoverable-error"; message: string };

export type AuthState =
  | { status: "initializing" }
  | { status: "signed-out" }
  | { status: "signing-in" }
  | { status: "signing-up" }
  | {
      status: "signed-in";
      user: AuthenticatedUser;
      profileBootstrap: ProfileBootstrapState;
    }
  | { status: "confirmation-required"; email: string }
  | { status: "suspended"; message: string; user: AuthenticatedUser }
  | { status: "error"; message: string };

export type AuthAction =
  | { type: "SESSION_RESTORED"; user: AuthenticatedUser }
  | { type: "SESSION_ABSENT" }
  | { type: "SIGN_IN_REQUESTED" }
  | { type: "SIGN_UP_REQUESTED" }
  | { type: "AUTHENTICATED"; user: AuthenticatedUser }
  | { type: "CONFIRMATION_REQUIRED"; email: string }
  | { type: "PROFILE_BOOTSTRAP_REQUESTED"; userId: string }
  | { type: "PROFILE_BOOTSTRAP_SUCCEEDED"; userId: string }
  | {
      type: "PROFILE_BOOTSTRAP_FAILED";
      userId: string;
      message: string;
    }
  | { type: "PROFILE_BOOTSTRAP_RETRY_REQUESTED"; userId: string }
  | { type: "SIGNED_OUT" }
  | { type: "ACCOUNT_SUSPENDED"; message: string }
  | { type: "AUTH_FAILED"; message: string };

export const initialAuthState: AuthState = { status: "initializing" };

export function authReducer(
  state: AuthState,
  action: AuthAction,
): AuthState {
  switch (action.type) {
    case "SESSION_RESTORED":
    case "AUTHENTICATED": {
      if (state.status === "signed-in" && state.user.id === action.user.id) {
        return { ...state, user: action.user };
      }
      return {
        status: "signed-in",
        user: action.user,
        profileBootstrap: action.user.displayName
          ? { status: "pending" }
          : { status: "not-required" },
      };
    }
    case "SESSION_ABSENT":
    case "SIGNED_OUT":
      return { status: "signed-out" };
    case "ACCOUNT_SUSPENDED":
      if (state.status !== "signed-in") {
        return state;
      }
      return {
        status: "suspended",
        message: action.message,
        user: state.user,
      };
    case "SIGN_IN_REQUESTED":
      return { status: "signing-in" };
    case "SIGN_UP_REQUESTED":
      return { status: "signing-up" };
    case "CONFIRMATION_REQUIRED":
      return { status: "confirmation-required", email: action.email };
    case "PROFILE_BOOTSTRAP_REQUESTED":
      if (
        state.status !== "signed-in" ||
        state.user.id !== action.userId ||
        state.profileBootstrap.status !== "pending"
      ) {
        return state;
      }
      return { ...state, profileBootstrap: { status: "syncing" } };
    case "PROFILE_BOOTSTRAP_SUCCEEDED":
      if (state.status !== "signed-in" || state.user.id !== action.userId) {
        return state;
      }
      return { ...state, profileBootstrap: { status: "ready" } };
    case "PROFILE_BOOTSTRAP_FAILED":
      if (state.status !== "signed-in" || state.user.id !== action.userId) {
        return state;
      }
      return {
        ...state,
        profileBootstrap: {
          status: "recoverable-error",
          message: action.message,
        },
      };
    case "PROFILE_BOOTSTRAP_RETRY_REQUESTED":
      if (
        state.status !== "signed-in" ||
        state.user.id !== action.userId ||
        state.profileBootstrap.status !== "recoverable-error"
      ) {
        return state;
      }
      return { ...state, profileBootstrap: { status: "pending" } };
    case "AUTH_FAILED":
      return { status: "error", message: action.message };
    default:
      return state;
  }
}

export function authenticatedUserFromSupabaseUser(
  user: {
    id: string;
    email?: string | null;
    user_metadata?: Record<string, unknown>;
  },
  displayName = readDisplayName(user.user_metadata),
): AuthenticatedUser {
  return {
    id: user.id,
    email: user.email ?? null,
    ...(displayName ? { displayName } : {}),
  };
}

function readDisplayName(metadata?: Record<string, unknown>): string | undefined {
  const value = metadata?.display_name;
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

export function getAuthErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "Authentication could not be completed. Please try again.";
}
