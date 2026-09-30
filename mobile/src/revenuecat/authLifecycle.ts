import type { AuthState } from "../auth/authFlow";

export type RevenueCatAuthenticationController = {
  setAuthenticated(appUserId: string): Promise<void>;
  setSignedOut(): Promise<void>;
};

export function synchronizeRevenueCatAuthentication(
  controller: RevenueCatAuthenticationController,
  authState: AuthState,
): void {
  switch (authState.status) {
    case "signed-in":
      void controller.setAuthenticated(authState.user.id);
      return;
    case "signed-out":
    case "confirmation-required":
    case "suspended":
    case "error":
      void controller.setSignedOut();
      return;
    case "initializing":
    case "signing-in":
    case "signing-up":
      return;
  }
}
