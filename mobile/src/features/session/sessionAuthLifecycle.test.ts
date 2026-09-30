import assert from "node:assert/strict";
import test from "node:test";

import type { AuthState } from "../../auth/authFlow";
import {
  synchronizeSessionAuthentication,
  type SessionAuthenticationController,
} from "./sessionAuthLifecycle";

class FakeSessionAuthenticationController
  implements SessionAuthenticationController
{
  readonly authenticatedCalls: Array<{
    authRevision: number;
    authenticatedUserId: string;
  }> = [];
  signedOutCalls = 0;

  setAuthenticated(
    authRevision: number,
    authenticatedUserId: string,
  ): void {
    this.authenticatedCalls.push({ authRevision, authenticatedUserId });
  }

  setSignedOut(): void {
    this.signedOutCalls += 1;
  }
}

test("auth initialization does not start room recovery", () => {
  const controller = new FakeSessionAuthenticationController();
  const initializing: AuthState = { status: "initializing" };
  synchronizeSessionAuthentication(controller, initializing, 0);
  assert.deepEqual(controller.authenticatedCalls, []);
  assert.equal(controller.signedOutCalls, 0);
});

test("signed-in auth forwards identity and session revision", () => {
  const controller = new FakeSessionAuthenticationController();
  const signedIn: AuthState = {
    status: "signed-in",
    user: {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      email: "student@example.com",
    },
    profileBootstrap: { status: "ready" },
  };
  synchronizeSessionAuthentication(controller, signedIn, 3);
  assert.deepEqual(controller.authenticatedCalls, [
    {
      authRevision: 3,
      authenticatedUserId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    },
  ]);
  assert.equal(controller.signedOutCalls, 0);
});

test("room recovery waits for authenticated profile bootstrap", () => {
  const controller = new FakeSessionAuthenticationController();
  for (const profileBootstrap of [
    { status: "pending" },
    { status: "syncing" },
    {
      status: "recoverable-error",
      message: "Could not reach the StudyRoom server.",
    },
  ] as const) {
    synchronizeSessionAuthentication(
      controller,
      {
        status: "signed-in",
        user: {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          email: "student@example.com",
          displayName: "Study Student",
        },
        profileBootstrap,
      },
      0,
    );
  }
  assert.deepEqual(controller.authenticatedCalls, []);
  assert.equal(controller.signedOutCalls, 0);
});

test("signed-out and terminal unauthenticated states clear session state", () => {
  const controller = new FakeSessionAuthenticationController();
  const states: AuthState[] = [
    { status: "signed-out" },
    { status: "confirmation-required", email: "student@example.com" },
    {
      status: "suspended",
      message: "Your StudyRoom account is currently unavailable.",
      user: {
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        email: "student@example.com",
      },
    },
    { status: "error", message: "Session unavailable." },
  ];
  for (const state of states) {
    synchronizeSessionAuthentication(controller, state, 0);
  }
  assert.equal(controller.signedOutCalls, states.length);
  assert.deepEqual(controller.authenticatedCalls, []);
});
