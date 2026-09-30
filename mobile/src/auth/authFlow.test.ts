import assert from "node:assert/strict";
import test from "node:test";

import {
  authReducer,
  authenticatedUserFromSupabaseUser,
  initialAuthState,
} from "./authFlow";

const user = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "student@example.com",
};

test("auth starts in initializing state", () => {
  assert.deepEqual(initialAuthState, { status: "initializing" });
});

test("no restored session becomes signed out", () => {
  assert.deepEqual(
    authReducer(initialAuthState, { type: "SESSION_ABSENT" }),
    { status: "signed-out" },
  );
});

test("an existing session becomes signed in", () => {
  assert.deepEqual(
    authReducer(initialAuthState, {
      type: "SESSION_RESTORED",
      user: authenticatedUserFromSupabaseUser(user),
    }),
    {
      status: "signed-in",
      user: {
        id: user.id,
        email: user.email,
      },
      profileBootstrap: { status: "not-required" },
    },
  );
});

test("sign-in has an explicit loading state", () => {
  assert.deepEqual(
    authReducer({ status: "signed-out" }, { type: "SIGN_IN_REQUESTED" }),
    { status: "signing-in" },
  );
});

test("sign-in success enters signed-in state", () => {
  assert.deepEqual(
    authReducer({ status: "signing-in" }, {
      type: "AUTHENTICATED",
      user: authenticatedUserFromSupabaseUser(user),
    }),
    {
      status: "signed-in",
      user: {
        id: user.id,
        email: user.email,
      },
      profileBootstrap: { status: "not-required" },
    },
  );
});

test("sign-in failure is readable and explicit", () => {
  assert.deepEqual(
    authReducer({ status: "signing-in" }, {
      type: "AUTH_FAILED",
      message: "Invalid login credentials",
    }),
    { status: "error", message: "Invalid login credentials" },
  );
});

test("sign-up starts in a separate loading state", () => {
  assert.deepEqual(
    authReducer({ status: "signed-out" }, { type: "SIGN_UP_REQUESTED" }),
    { status: "signing-up" },
  );
});

test("sign-up with immediate session can include profile display name", () => {
  assert.deepEqual(
    authReducer({ status: "signing-up" }, {
      type: "AUTHENTICATED",
      user: authenticatedUserFromSupabaseUser(user, "Study Student"),
    }),
    {
      status: "signed-in",
      user: {
        id: user.id,
        email: user.email,
        displayName: "Study Student",
      },
      profileBootstrap: { status: "pending" },
    },
  );
});

test("profile bootstrap failure cannot overwrite a valid authenticated session", () => {
  const authenticatedUser = authenticatedUserFromSupabaseUser(
    user,
    "Study Student",
  );
  const authenticated = authReducer(
    { status: "signing-in" },
    { type: "AUTHENTICATED", user: authenticatedUser },
  );
  const syncing = authReducer(authenticated, {
    type: "PROFILE_BOOTSTRAP_REQUESTED",
    userId: user.id,
  });
  const failed = authReducer(syncing, {
    type: "PROFILE_BOOTSTRAP_FAILED",
    userId: user.id,
    message: "Could not reach the StudyRoom server.",
  });

  assert.deepEqual(failed, {
    status: "signed-in",
    user: authenticatedUser,
    profileBootstrap: {
      status: "recoverable-error",
      message: "Could not reach the StudyRoom server.",
    },
  });
  assert.deepEqual(
    authReducer(failed, { type: "AUTHENTICATED", user: authenticatedUser }),
    failed,
  );
});

test("profile bootstrap failure can be retried without changing identity", () => {
  const authenticatedUser = authenticatedUserFromSupabaseUser(
    user,
    "Study Student",
  );
  const failed = {
    status: "signed-in",
    user: authenticatedUser,
    profileBootstrap: {
      status: "recoverable-error",
      message: "Could not reach the StudyRoom server.",
    },
  } as const;

  const pending = authReducer(failed, {
    type: "PROFILE_BOOTSTRAP_RETRY_REQUESTED",
    userId: user.id,
  });
  const syncing = authReducer(pending, {
    type: "PROFILE_BOOTSTRAP_REQUESTED",
    userId: user.id,
  });
  const ready = authReducer(syncing, {
    type: "PROFILE_BOOTSTRAP_SUCCEEDED",
    userId: user.id,
  });

  assert.deepEqual(ready, {
    status: "signed-in",
    user: authenticatedUser,
    profileBootstrap: { status: "ready" },
  });
});

test("sign-up requiring confirmation is explicit", () => {
  assert.deepEqual(
    authReducer({ status: "signing-up" }, {
      type: "CONFIRMATION_REQUIRED",
      email: user.email,
    }),
    { status: "confirmation-required", email: user.email },
  );
});

test("sign-out clears authenticated app state", () => {
  assert.deepEqual(
    authReducer({
      status: "signed-in",
      user: authenticatedUserFromSupabaseUser(user),
      profileBootstrap: { status: "not-required" },
    }, { type: "SIGNED_OUT" }),
    { status: "signed-out" },
  );
});

test("suspension is explicit and sign-out can clear it", () => {
  const authenticated = authReducer(
    { status: "signing-in" },
    { type: "AUTHENTICATED", user: authenticatedUserFromSupabaseUser(user) },
  );
  const suspended = authReducer(authenticated, {
    type: "ACCOUNT_SUSPENDED",
    message: "Your StudyRoom account is currently unavailable.",
  });
  const authenticatedUser =
    authenticated.status === "signed-in"
      ? authenticated.user
      : assert.fail("authentication should be signed in");
  assert.deepEqual(suspended, {
    status: "suspended",
    message: "Your StudyRoom account is currently unavailable.",
    user: authenticatedUser,
  });
  assert.deepEqual(authReducer(suspended, { type: "SIGNED_OUT" }), {
    status: "signed-out",
  });
});
