import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import type { Session } from "@supabase/supabase-js";

import {
  getApiErrorCode,
  getUserFacingErrorMessage,
} from "../api/errors";
import { updateProfile } from "../api/profile";
import {
  authenticatedUserFromSupabaseUser,
  authReducer,
  getAuthErrorMessage,
  initialAuthState,
  type AuthState,
} from "./authFlow";
import { validateDisplayName } from "./displayNamePolicy";
import { getSupabaseClient } from "./supabase";
import {
  AuthCallbackHandler,
  createSignUpOptions,
  getAuthCallbackErrorMessage,
  parseAuthCallbackUrl,
} from "./authCallback";
import * as Linking from "expo-linking";

export type AuthCallbackStatus =
  | "idle"
  | "processing"
  | "failed"
  | "authenticated";

type AuthContextValue = {
  state: AuthState;
  sessionRevision: number;
  authCallbackError: string | null;
  authCallbackStatus: AuthCallbackStatus;
  signedOutMessage: string | null;
  signIn(email: string, password: string): Promise<void>;
  signUp(email: string, password: string, displayName: string): Promise<void>;
  signOut(): Promise<void>;
  reauthenticateCurrentUser(password: string): Promise<void>;
  completeAccountDeletion(message: string): Promise<void>;
  completeAccountSuspension(message: string): void;
  clearAuthCallbackError(): void;
  processAuthCallback(url: string): Promise<void>;
  retryProfileBootstrap(): void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function userFromSession(session: Session) {
  return authenticatedUserFromSupabaseUser(session.user);
}

function userDisplayName(session: Session): string | undefined {
  return authenticatedUserFromSupabaseUser(session.user).displayName;
}

export function AuthProvider({ children }: PropsWithChildren) {
  const [state, dispatch] = useReducer(authReducer, initialAuthState);
  const profileBootstrapInFlightRef = useRef<string | null>(null);
  const authCallbackHandlerRef = useRef<AuthCallbackHandler | null>(null);
  const mountedRef = useRef(true);
  const suspensionActiveRef = useRef(false);
  const authCallbackStatusRef = useRef<AuthCallbackStatus>("idle");
  const [authCallbackError, setAuthCallbackError] = useReducer(
    (_: string | null, next: string | null) => next,
    null,
  );
  const [authCallbackStatus, setAuthCallbackStatusState] =
    useState<AuthCallbackStatus>("idle");
  const [signedOutMessage, setSignedOutMessage] = useState<string | null>(null);
  const [sessionRevision, advanceSessionRevision] = useReducer(
    (revision: number) => revision + 1,
    0,
  );

  const setAuthCallbackStatus = useCallback((next: AuthCallbackStatus) => {
    authCallbackStatusRef.current = next;
    setAuthCallbackStatusState(next);
  }, []);

  const processAuthCallback = useCallback(
    async (url: string): Promise<void> => {
      const parsed = parseAuthCallbackUrl(url);
      if (parsed.status === "not-auth-callback") {
        return;
      }

      const previousStatus = authCallbackStatusRef.current;
      setAuthCallbackStatus("processing");
      setAuthCallbackError(null);

      try {
        const client = getSupabaseClient();
        if (authCallbackHandlerRef.current === null) {
          authCallbackHandlerRef.current = new AuthCallbackHandler(client);
        }
        const result = await authCallbackHandlerRef.current.process(url);
        if (!mountedRef.current) {
          return;
        }
        if (result.status === "ignored") {
          if (result.reason === "duplicate") {
            setAuthCallbackStatus(previousStatus);
          }
          return;
        }
        if (result.status === "failed") {
          setAuthCallbackStatus("failed");
          setAuthCallbackError(result.message);
          try {
            const { data } = await client.auth.getSession();
            if (!data.session) {
              dispatch({ type: "AUTH_FAILED", message: result.message });
            }
          } catch {
            // Preserve the current auth state when the failure check cannot run.
          }
          return;
        }

        setAuthCallbackStatus("authenticated");
        setAuthCallbackError(null);
        dispatch({
          type: "AUTHENTICATED",
          user: userFromSession(result.session),
        });
      } catch (error: unknown) {
        if (!mountedRef.current) {
          return;
        }
        const message = getAuthCallbackErrorMessage(error);
        setAuthCallbackStatus("failed");
        setAuthCallbackError(message);
        try {
          const { data } = await getSupabaseClient().auth.getSession();
          if (!data.session) {
            dispatch({ type: "AUTH_FAILED", message });
          }
        } catch {
          // Preserve the current auth state when the failure check cannot run.
        }
      }
    },
    [setAuthCallbackStatus],
  );

  const completeAccountDeletion = useCallback(async (message: string) => {
    suspensionActiveRef.current = false;
    setSignedOutMessage(message);
    profileBootstrapInFlightRef.current = null;

    // Local deletion is authoritative. Clear the app state immediately and
    // let the local Supabase sign-out finish independently.
    dispatch({ type: "SIGNED_OUT" });
    void getSupabaseClient()
      .auth.signOut({ scope: "local" })
      .catch(() => {
        // A deleted account must not be recreated or reported as a failed
        // deletion because local provider cleanup could not finish.
      });
  }, []);

  const completeAccountSuspension = useCallback((message: string) => {
    suspensionActiveRef.current = true;
    setSignedOutMessage(null);
    profileBootstrapInFlightRef.current = null;
    dispatch({ type: "ACCOUNT_SUSPENDED", message });
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    let unsubscribe: () => void = () => undefined;

    try {
      const client = getSupabaseClient();
      const subscription = client.auth.onAuthStateChange((event, session) => {
        if (!mounted) {
          return;
        }
        if (event === "TOKEN_REFRESHED") {
          advanceSessionRevision();
        }
        if (session && suspensionActiveRef.current) {
          return;
        }
        if (session) {
          dispatch({ type: "AUTHENTICATED", user: userFromSession(session) });
        } else {
          dispatch({ type: "SIGNED_OUT" });
        }
      });
      unsubscribe = () => subscription.data.subscription.unsubscribe();

      void client.auth.getSession().then(({ data, error }) => {
        if (!mounted) {
          return;
        }
        if (error) {
          dispatch({
            type: "AUTH_FAILED",
            message: getAuthErrorMessage(error),
          });
        } else if (data.session) {
          dispatch({
            type: "SESSION_RESTORED",
            user: userFromSession(data.session),
          });
        } else {
          dispatch({ type: "SESSION_ABSENT" });
        }
      });
    } catch (error: unknown) {
      dispatch({ type: "AUTH_FAILED", message: getAuthErrorMessage(error) });
    }

    return () => {
      mounted = false;
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    const subscription = Linking.addEventListener("url", ({ url }) => {
      void processAuthCallback(url);
    });
    void Linking.getInitialURL().then((url) => {
      if (url) {
        void processAuthCallback(url);
      }
    });

    return () => {
      subscription.remove();
    };
  }, [processAuthCallback]);

  useEffect(() => {
    if (
      state.status !== "signed-in" ||
      state.profileBootstrap.status !== "pending" ||
      !state.user.displayName ||
      profileBootstrapInFlightRef.current === state.user.id
    ) {
      return;
    }

    const userId = state.user.id;
    const displayName = state.user.displayName;
    profileBootstrapInFlightRef.current = userId;
    dispatch({ type: "PROFILE_BOOTSTRAP_REQUESTED", userId });
    void updateProfile(displayName)
      .then(() => {
        dispatch({ type: "PROFILE_BOOTSTRAP_SUCCEEDED", userId });
      })
      .catch((error: unknown) => {
        if (getApiErrorCode(error) === "account_deleted") {
          void completeAccountDeletion(
            "Your StudyRoom account has been deleted. Please sign in again.",
          );
          return;
        }
        if (getApiErrorCode(error) === "account_suspended") {
          completeAccountSuspension(
            "Your StudyRoom account is currently unavailable. Open Support & Safety for help.",
          );
          return;
        }
        dispatch({
          type: "PROFILE_BOOTSTRAP_FAILED",
          userId,
          message: getUserFacingErrorMessage(error),
        });
      })
      .finally(() => {
        if (profileBootstrapInFlightRef.current === userId) {
          profileBootstrapInFlightRef.current = null;
        }
      });
  }, [completeAccountDeletion, completeAccountSuspension, state]);

  const signIn = useCallback(async (email: string, password: string) => {
    suspensionActiveRef.current = false;
    setSignedOutMessage(null);
    setAuthCallbackError(null);
    setAuthCallbackStatus("idle");
    dispatch({ type: "SIGN_IN_REQUESTED" });
    try {
      const { data, error } = await getSupabaseClient().auth.signInWithPassword({
        email,
        password,
      });
      if (error) {
        throw error;
      }
      if (!data.session) {
        throw new Error("Sign-in did not return an active session.");
      }
      const displayName = userDisplayName(data.session);
      dispatch({
        type: "AUTHENTICATED",
        user: authenticatedUserFromSupabaseUser(data.session.user, displayName),
      });
    } catch (error: unknown) {
      dispatch({ type: "AUTH_FAILED", message: getAuthErrorMessage(error) });
    }
  }, []);

  const reauthenticateCurrentUser = useCallback(async (password: string) => {
    if (
      (state.status !== "signed-in" && state.status !== "suspended") ||
      !state.user.email
    ) {
      throw new Error("A current authenticated email is required.");
    }

    const { data, error } = await getSupabaseClient().auth.signInWithPassword({
      email: state.user.email,
      password,
    });
    if (error) {
      throw error;
    }
    if (!data.session) {
      throw new Error("Recent authentication did not return an active session.");
    }
    advanceSessionRevision();
    dispatch({
      type: "AUTHENTICATED",
      user: userFromSession(data.session),
    });
  }, [state]);

  const signUp = useCallback(
    async (email: string, password: string, displayName: string) => {
      const displayNameResult = validateDisplayName(displayName);
      if (!displayNameResult.valid) {
        dispatch({ type: "AUTH_FAILED", message: displayNameResult.message });
        return;
      }
      displayName = displayNameResult.value;
      suspensionActiveRef.current = false;
      setSignedOutMessage(null);
      dispatch({ type: "SIGN_UP_REQUESTED" });
      setAuthCallbackError(null);
      setAuthCallbackStatus("idle");
      try {
        const { data, error } = await getSupabaseClient().auth.signUp({
          email,
          password,
          options: createSignUpOptions(displayName),
        });
        if (error) {
          throw error;
        }
        if (!data.session) {
          dispatch({ type: "CONFIRMATION_REQUIRED", email });
          return;
        }

        dispatch({
          type: "AUTHENTICATED",
          user: authenticatedUserFromSupabaseUser(
            data.session.user,
            displayName,
          ),
        });
      } catch (error: unknown) {
        dispatch({ type: "AUTH_FAILED", message: getAuthErrorMessage(error) });
      }
    },
    [],
  );

  const signOut = useCallback(async () => {
    suspensionActiveRef.current = false;
    setSignedOutMessage(null);
    setAuthCallbackError(null);
    setAuthCallbackStatus("idle");
    try {
      const { error } = await getSupabaseClient().auth.signOut({
        scope: "local",
      });
      if (error) {
        throw error;
      }
      dispatch({ type: "SIGNED_OUT" });
    } catch (error: unknown) {
      dispatch({ type: "AUTH_FAILED", message: getAuthErrorMessage(error) });
    }
  }, []);

  const retryProfileBootstrap = useCallback(() => {
    if (state.status !== "signed-in") {
      return;
    }
    dispatch({
      type: "PROFILE_BOOTSTRAP_RETRY_REQUESTED",
      userId: state.user.id,
    });
  }, [state]);

  const clearAuthCallbackError = useCallback(() => {
    setAuthCallbackError(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        state,
        sessionRevision,
        authCallbackError,
        authCallbackStatus,
        signedOutMessage,
        signIn,
        signUp,
        signOut,
        reauthenticateCurrentUser,
        completeAccountDeletion,
        completeAccountSuspension,
        clearAuthCallbackError,
        processAuthCallback,
        retryProfileBootstrap,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
