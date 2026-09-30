import assert from "node:assert/strict";
import test from "node:test";

import type { AuthState } from "../auth/authFlow";
import {
  synchronizeRevenueCatAuthentication,
  type RevenueCatAuthenticationController,
} from "./authLifecycle";

class FakeAuthenticationController
  implements RevenueCatAuthenticationController
{
  readonly appUserIds: string[] = [];
  signedOutCalls = 0;

  async setAuthenticated(appUserId: string): Promise<void> {
    this.appUserIds.push(appUserId);
  }

  async setSignedOut(): Promise<void> {
    this.signedOutCalls += 1;
  }
}

test("signed-out auth does not identify a RevenueCat customer", () => {
  const controller = new FakeAuthenticationController();
  synchronizeRevenueCatAuthentication(controller, { status: "signed-out" });
  assert.deepEqual(controller.appUserIds, []);
  assert.equal(controller.signedOutCalls, 1);
});

test("suspended auth clears the RevenueCat identity", () => {
  const controller = new FakeAuthenticationController();
  synchronizeRevenueCatAuthentication(controller, {
    status: "suspended",
    message: "Your StudyRoom account is currently unavailable.",
    user: {
      id: "11111111-1111-4111-8111-111111111111",
      email: "student@example.com",
    },
  });
  assert.deepEqual(controller.appUserIds, []);
  assert.equal(controller.signedOutCalls, 1);
});

test("the Supabase UUID, never email, becomes the RevenueCat App User ID", () => {
  const controller = new FakeAuthenticationController();
  const authState: AuthState = {
    status: "signed-in",
    user: {
      id: "11111111-1111-4111-8111-111111111111",
      email: "student@example.com",
    },
    profileBootstrap: { status: "pending" },
  };
  synchronizeRevenueCatAuthentication(controller, authState);
  assert.deepEqual(controller.appUserIds, [authState.user.id]);
  assert.equal(controller.appUserIds.includes("student@example.com"), false);
});

test("transient auth states do not create RevenueCat identity loops", () => {
  const controller = new FakeAuthenticationController();
  for (const state of [
    { status: "initializing" },
    { status: "signing-in" },
    { status: "signing-up" },
  ] as const) {
    synchronizeRevenueCatAuthentication(controller, state);
  }
  assert.deepEqual(controller.appUserIds, []);
  assert.equal(controller.signedOutCalls, 0);
});
