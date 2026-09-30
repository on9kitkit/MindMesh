import type { SessionStatus } from "../../realtime/protocol";

export type StudyRoomRoute =
  | "sign-in"
  | "home"
  | "waiting-room"
  | "quiz"
  | "results"
  | "pro"
  | "solo"
  | "pets"
  | "account"
  | "privacy"
  | "support"
  | "report";

export type SessionRouteRecommendation =
  | StudyRoomRoute
  | "retain-current-route";

export type SessionNavigationInput = {
  authentication: "initializing" | "signed-in" | "signed-out" | "suspended";
  activeRoomId: string | null;
  sessionId: string | null;
  sessionStatus: SessionStatus | null;
  reconnecting: boolean;
  dismissedFinishedSessionId: string | null;
  fatalRoomLoss: boolean;
  currentRoute: StudyRoomRoute;
  currentRouteRoomId: string | null;
};

const ROOM_ROUTES: ReadonlySet<StudyRoomRoute> = new Set([
  "waiting-room",
  "quiz",
  "results",
]);

const PUBLIC_ROUTES: ReadonlySet<StudyRoomRoute> = new Set([
  "privacy",
  "support",
]);

function recommendIfDifferent(
  target: StudyRoomRoute,
  input: SessionNavigationInput,
): SessionRouteRecommendation {
  if (target !== input.currentRoute) {
    return target;
  }
  if (
    ROOM_ROUTES.has(target) &&
    input.activeRoomId !== input.currentRouteRoomId
  ) {
    return target;
  }
  return "retain-current-route";
}

export function recommendSessionRoute(
  input: SessionNavigationInput,
): SessionRouteRecommendation {
  if (input.authentication === "initializing") {
    return "retain-current-route";
  }
  if (input.authentication === "signed-out") {
    if (PUBLIC_ROUTES.has(input.currentRoute)) {
      return "retain-current-route";
    }
    return recommendIfDifferent("sign-in", input);
  }
  if (input.authentication === "suspended") {
    if (
      input.currentRoute === "support" ||
      input.currentRoute === "account" ||
      input.currentRoute === "privacy"
    ) {
      return "retain-current-route";
    }
    return recommendIfDifferent("sign-in", input);
  }
  if (PUBLIC_ROUTES.has(input.currentRoute)) {
    return "retain-current-route";
  }
  if (
    input.currentRoute === "report" &&
    input.activeRoomId !== null &&
    input.currentRouteRoomId === input.activeRoomId
  ) {
    return "retain-current-route";
  }
  if (input.fatalRoomLoss) {
    return recommendIfDifferent("home", input);
  }
  if (input.activeRoomId === null) {
    if (
      input.currentRoute === "pro" ||
      input.currentRoute === "account" ||
      input.currentRoute === "solo" ||
      input.currentRoute === "pets"
    ) {
      return "retain-current-route";
    }
    return recommendIfDifferent("home", input);
  }
  if (input.sessionStatus === null || input.sessionId === null) {
    return recommendIfDifferent("waiting-room", input);
  }
  if (
    input.sessionStatus === "QUESTION_OPEN" ||
    input.sessionStatus === "QUESTION_GRADING" ||
    input.sessionStatus === "QUESTION_REVEAL"
  ) {
    return recommendIfDifferent("quiz", input);
  }
  if (input.dismissedFinishedSessionId === input.sessionId) {
    return recommendIfDifferent("waiting-room", input);
  }
  return recommendIfDifferent("results", input);
}
