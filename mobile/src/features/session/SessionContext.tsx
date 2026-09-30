import {
  createContext,
  type PropsWithChildren,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from "react";
import { AppState, type AppStateStatus } from "react-native";

import { resolveApiBaseUrl } from "../../api/client";
import {
  closeRoom,
  getActiveRoom,
  leaveRoom,
} from "../../api/rooms";
import { useAuth } from "../../auth/AuthContext";
import {
  clearSessionAfterUnauthorized,
  getCurrentAccessToken,
  refreshCurrentSession,
} from "../../auth/session";
import type { CanonicalUuid } from "../../realtime/protocol";
import {
  SessionController,
  type RequestStateResult,
  type RoomLifecycleCommandResult,
  type SessionCommandResult,
} from "./sessionController";
import { synchronizeSessionAuthentication } from "./sessionAuthLifecycle";
import type { SessionState } from "./sessionState";

export type SessionContextValue = {
  state: SessionState;
  recoverActiveRoom(): Promise<void>;
  selectRoom(roomId: string): void;
  clearRoom(): void;
  terminateAuthenticatedState(): void;
  retryConnection(): void;
  requestState(): RequestStateResult;
  setReady(ready: boolean): SessionCommandResult;
  startSession(): SessionCommandResult;
  leaveCurrentRoom(): Promise<RoomLifecycleCommandResult>;
  closeCurrentRoom(): Promise<RoomLifecycleCommandResult>;
  submitAnswer(
    sessionQuestionId: CanonicalUuid,
    selectedOptionId: string,
  ): SessionCommandResult;
  submitTextAnswer(
    sessionQuestionId: CanonicalUuid,
    text: string,
  ): SessionCommandResult;
  prepareQuiz(requestId: string): SessionCommandResult;
  retryGrading(): SessionCommandResult;
  dismissFinishedSession(): void;
};

type SessionProviderProps = PropsWithChildren<{
  controller?: SessionController;
}>;

const SessionContext = createContext<SessionContextValue | undefined>(
  undefined,
);

function createProductionSessionController(): SessionController {
  return new SessionController({
    apiBaseUrl: resolveApiBaseUrl(process.env.EXPO_PUBLIC_API_BASE_URL),
    getAccessToken: getCurrentAccessToken,
    getActiveRoom,
    refreshAccessToken: refreshCurrentSession,
    onAuthenticationFailure: clearSessionAfterUnauthorized,
    leaveRoom,
    closeRoom,
  });
}

function normalizeAppState(state: AppStateStatus) {
  if (state === "active" || state === "inactive") {
    return state;
  }
  return "background" as const;
}

export function SessionProvider({
  children,
  controller: providedController,
}: SessionProviderProps) {
  const controllerRef = useRef<SessionController | null>(null);
  const ownsControllerRef = useRef(providedController === undefined);
  if (controllerRef.current === null) {
    controllerRef.current =
      providedController ?? createProductionSessionController();
  }
  const controller = controllerRef.current;
  const { state: authState, sessionRevision } = useAuth();
  const authenticatedUserId =
    authState.status === "signed-in" ? authState.user.id : null;
  const profileBootstrapStatus =
    authState.status === "signed-in"
      ? authState.profileBootstrap.status
      : null;
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getState,
    controller.getState,
  );

  useLayoutEffect(() => {
    synchronizeSessionAuthentication(controller, authState, sessionRevision);
  }, [
    authState.status,
    authenticatedUserId,
    controller,
    profileBootstrapStatus,
    sessionRevision,
  ]);

  useEffect(() => {
    controller.setAppState(normalizeAppState(AppState.currentState));
    const subscription = AppState.addEventListener("change", (nextState) => {
      controller.setAppState(normalizeAppState(nextState));
    });
    return () => subscription.remove();
  }, [controller]);

  useEffect(
    () => () => {
      if (ownsControllerRef.current) {
        controller.dispose();
      }
    },
    [controller],
  );

  const value = useMemo<SessionContextValue>(
    () => ({
      state,
      recoverActiveRoom: () => controller.recoverActiveRoom(),
      selectRoom: (roomId) => controller.selectRoom(roomId),
      clearRoom: () => controller.clearRoom(),
      terminateAuthenticatedState: () => controller.setSignedOut(),
      retryConnection: () => controller.retryConnection(),
      requestState: () => controller.requestState(),
      setReady: (ready) => controller.setReady(ready),
      startSession: () => controller.startSession(),
      leaveCurrentRoom: () => controller.leaveCurrentRoom(),
      closeCurrentRoom: () => controller.closeCurrentRoom(),
      submitAnswer: (sessionQuestionId, selectedOptionId) =>
        controller.submitAnswer(sessionQuestionId, selectedOptionId),
      submitTextAnswer: (sessionQuestionId, text) =>
        controller.submitTextAnswer(sessionQuestionId, text),
      prepareQuiz: (requestId) => controller.prepareQuiz(requestId),
      retryGrading: () => controller.retryGrading(),
      dismissFinishedSession: () => controller.dismissFinishedSession(),
    }),
    [controller, state],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (context === undefined) {
    throw new Error("useSession must be used inside SessionProvider");
  }
  return context;
}
