import {
  router,
  useGlobalSearchParams,
  usePathname,
} from "expo-router";
import { useEffect } from "react";

import { useAuth } from "../../auth/AuthContext";
import { useSession } from "./SessionContext";
import {
  recommendSessionRoute,
  type SessionNavigationInput,
  type StudyRoomRoute,
} from "./navigation";
import type { SessionState } from "./sessionState";

function authenticationForNavigation(
  status: ReturnType<typeof useAuth>["state"]["status"],
): SessionNavigationInput["authentication"] {
  if (status === "initializing") {
    return "initializing";
  }
  if (status === "signed-in") {
    return "signed-in";
  }
  return status === "suspended" ? "suspended" : "signed-out";
}

export function studyRoomRouteFromPathname(
  pathname: string,
): StudyRoomRoute | null {
  switch (pathname) {
    case "/":
      return "home";
    case "/waiting-room":
      return "waiting-room";
    case "/quiz":
      return "quiz";
    case "/results":
      return "results";
    case "/pro":
      return "pro";
    case "/solo":
      return "solo";
    case "/pets":
      return "pets";
    case "/account":
      return "account";
    case "/privacy":
      return "privacy";
    case "/support":
      return "support";
    case "/report":
      return "report";
    case "/sign-in":
    case "/sign-up":
      return "sign-in";
    default:
      return null;
  }
}

export function navigableRoomId(state: SessionState): string | null {
  const roomId = state.roomId;
  if (
    roomId === null ||
    state.roomState?.room_id !== roomId ||
    state.snapshot?.room_state.room_id !== roomId
  ) {
    return null;
  }
  return roomId;
}

function replaceWithRecommendedRoute(
  route: Exclude<
    ReturnType<typeof recommendSessionRoute>,
    "retain-current-route"
  >,
  roomId: string | null,
): void {
  switch (route) {
    case "sign-in":
      router.replace("/sign-in");
      return;
    case "home":
      router.replace("/");
      return;
    case "waiting-room":
      if (roomId !== null) {
        router.replace({ pathname: "/waiting-room", params: { roomId } });
      }
      return;
    case "quiz":
      if (roomId !== null) {
        router.replace({ pathname: "/quiz", params: { roomId } });
      }
      return;
    case "results":
      if (roomId !== null) {
        router.replace({ pathname: "/results", params: { roomId } });
      }
      return;
    case "pro":
      router.replace("/pro");
      return;
    case "account":
      router.replace("/account");
      return;
    case "privacy":
      router.replace("/privacy");
      return;
    case "support":
      router.replace("/support");
      return;
    case "report":
      if (roomId !== null) {
        router.replace({ pathname: "/report", params: { roomId } });
      }
  }
}

export function SessionRouteCoordinator() {
  const {
    completeAccountDeletion,
    completeAccountSuspension,
    state: authState,
  } = useAuth();
  const { state: sessionState } = useSession();
  const pathname = usePathname();
  const { roomId: rawRoomId } = useGlobalSearchParams<{
    roomId?: string | string[];
  }>();
  const routeRoomId = typeof rawRoomId === "string" ? rawRoomId : null;
  const currentRoute = studyRoomRouteFromPathname(pathname);
  const roomId = navigableRoomId(sessionState);

  useEffect(() => {
    if (
      authState.status === "signed-in" &&
      sessionState.lastError?.code === "account_deleted"
    ) {
      void completeAccountDeletion(
        "Your StudyRoom account has been deleted. Please sign in again.",
      );
    }
  }, [
    authState.status,
    completeAccountDeletion,
    sessionState.lastError?.code,
  ]);

  useEffect(() => {
    if (
      authState.status === "signed-in" &&
      sessionState.lastError?.code === "account_suspended"
    ) {
      completeAccountSuspension(
        "Your StudyRoom account is currently unavailable. Open Support & Safety for help.",
      );
    }
  }, [
    authState.status,
    completeAccountSuspension,
    sessionState.lastError?.code,
  ]);

  useEffect(() => {
    if (
      currentRoute === null ||
      sessionState.lastError?.code === "account_deleted"
    ) {
      return;
    }
    const authentication = authenticationForNavigation(authState.status);
    const waitingForInitialRoomSnapshot =
      authentication === "signed-in" &&
      (sessionState.phase === "recovering-room" ||
        (sessionState.roomId !== null && roomId === null));
    if (waitingForInitialRoomSnapshot) {
      return;
    }

    const recommendation = recommendSessionRoute({
      authentication,
      activeRoomId: roomId,
      sessionId: sessionState.snapshot?.session_id ?? null,
      sessionStatus: sessionState.snapshot?.status ?? null,
      reconnecting: sessionState.phase === "reconnecting",
      dismissedFinishedSessionId: sessionState.dismissedFinishedSessionId,
      fatalRoomLoss:
        sessionState.phase === "fatal-error" && sessionState.roomId === null,
      currentRoute,
      currentRouteRoomId: routeRoomId,
    });
    if (recommendation !== "retain-current-route") {
      replaceWithRecommendedRoute(recommendation, roomId);
    }
  }, [
    authState.status,
    currentRoute,
    roomId,
    routeRoomId,
    sessionState.dismissedFinishedSessionId,
    sessionState.phase,
    sessionState.roomId,
    sessionState.snapshot?.session_id,
    sessionState.snapshot?.status,
    sessionState.socketGeneration,
    sessionState.lastError?.code,
  ]);

  return null;
}
