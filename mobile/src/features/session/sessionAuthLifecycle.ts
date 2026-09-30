import type { AuthState } from "../../auth/authFlow";

export type SessionAuthenticationController = {
  setAuthenticated(authRevision: number, authenticatedUserId: string): void;
  setSignedOut(): void;
};

export function synchronizeSessionAuthentication(
  controller: SessionAuthenticationController,
  authState: AuthState,
  sessionRevision: number,
): void {
  switch (authState.status) {
    case "signed-in":
      if (
        authState.profileBootstrap.status === "ready" ||
        authState.profileBootstrap.status === "not-required"
      ) {
        controller.setAuthenticated(sessionRevision, authState.user.id);
      }
      return;
    case "signed-out":
    case "confirmation-required":
    case "suspended":
    case "error":
      controller.setSignedOut();
      return;
    case "initializing":
    case "signing-in":
    case "signing-up":
      return;
  }
}
