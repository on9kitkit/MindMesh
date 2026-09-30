import assert from "node:assert/strict";
import test from "node:test";

import { BackendApiError, NetworkApiError } from "../../api/errors";
import {
  ACCOUNT_DELETION_CONFIRMATION,
  AccountDeletionController,
  type AccountDeletionDependencies,
} from "./accountDeletion";

const deletedResponse = {
  status: "account_deleted" as const,
  local_deletion_complete: true as const,
  provider_cleanup_pending: false,
};

function dependencies(
  overrides: Partial<AccountDeletionDependencies> = {},
): AccountDeletionDependencies {
  return {
    deleteAccount: async () => deletedResponse,
    reauthenticate: async () => undefined,
    completeLocalCleanup: async () => undefined,
    ...overrides,
  };
}

function readyController(
  overrides: Partial<AccountDeletionDependencies> = {},
): AccountDeletionController {
  const controller = new AccountDeletionController(dependencies(overrides));
  controller.start();
  controller.setConfirmation(ACCOUNT_DELETION_CONFIRMATION);
  return controller;
}

test("confirmation must be exactly DELETE before any request is sent", async () => {
  let deleteCalls = 0;
  const controller = new AccountDeletionController(
    dependencies({
      deleteAccount: async () => {
        deleteCalls += 1;
        return deletedResponse;
      },
    }),
  );
  controller.start();
  controller.setConfirmation("delete");

  await controller.submit();

  assert.equal(deleteCalls, 0);
  assert.deepEqual(controller.getState(), {
    status: "confirming",
    confirmation: "delete",
    errorMessage: "Type DELETE exactly to confirm account deletion.",
  });
});

test("duplicate taps do not duplicate the deletion request", async () => {
  let deleteCalls = 0;
  let resolveDelete: ((value: typeof deletedResponse) => void) | undefined;
  const pendingDelete = new Promise<typeof deletedResponse>((resolve) => {
    resolveDelete = resolve;
  });
  const controller = readyController({
    deleteAccount: async () => {
      deleteCalls += 1;
      return pendingDelete;
    },
  });

  const first = controller.submit();
  const second = controller.submit();
  assert.equal(deleteCalls, 1);
  assert.equal(controller.getState().status, "deleting");

  resolveDelete?.(deletedResponse);
  await Promise.all([first, second]);
  assert.equal(controller.getState().status, "deleted");
});

test("recent authentication requires one password reauthentication and one retry", async () => {
  let deleteCalls = 0;
  const passwords: string[] = [];
  const controller = readyController({
    deleteAccount: async () => {
      deleteCalls += 1;
      if (deleteCalls === 1) {
        throw new BackendApiError(
          "recent_authentication_required",
          "Recent authentication is required.",
          401,
        );
      }
      return deletedResponse;
    },
    reauthenticate: async (password) => {
      passwords.push(password);
    },
  });

  await controller.submit();
  assert.equal(controller.getState().status, "reauth_required");
  await controller.submitPassword("not-stored-in-state");

  assert.deepEqual(passwords, ["not-stored-in-state"]);
  assert.equal(deleteCalls, 2);
  assert.equal(controller.getState().status, "deleted");
  assert.equal(JSON.stringify(controller.getState()).includes("not-stored"), false);
});

test("wrong password is recoverable without attempting deletion", async () => {
  let deleteCalls = 0;
  const controller = readyController({
    deleteAccount: async () => {
      deleteCalls += 1;
      throw new BackendApiError(
        "recent_authentication_required",
        "Recent authentication is required.",
        401,
      );
    },
    reauthenticate: async () => {
      throw new Error("invalid credentials");
    },
  });

  await controller.submit();
  await controller.submitPassword("wrong-password");

  const state = controller.getState();
  assert.equal(deleteCalls, 1);
  assert.equal(state.status, "reauth_required");
  assert.equal(state.errorMessage, "The password could not be confirmed. Check it and try again.");
  assert.equal(JSON.stringify(state).includes("wrong-password"), false);
});

test("active quiz blocking is shown as a recoverable server decision", async () => {
  const controller = readyController({
    deleteAccount: async () =>
      Promise.reject(
        new BackendApiError(
          "account_deletion_blocked_active_quiz",
          "An active quiz blocks deletion.",
          409,
        ),
      ),
  });

  await controller.submit();

  assert.deepEqual(controller.getState(), {
    status: "error",
    confirmation: "DELETE",
    message:
      "You cannot delete your account while a quiz is in progress. Finish or leave the active quiz first.",
    retryable: true,
    retriedAfterReauthentication: false,
  });
});

test("a lost response followed by account_deleted is treated as successful deletion", async () => {
  let deleteCalls = 0;
  let cleanupCalls = 0;
  const controller = readyController({
    deleteAccount: async () => {
      deleteCalls += 1;
      if (deleteCalls === 1) {
        throw new NetworkApiError();
      }
      throw new BackendApiError(
        "account_deleted",
        "The account has already been deleted.",
        403,
      );
    },
    completeLocalCleanup: async () => {
      cleanupCalls += 1;
    },
  });

  await controller.submit();
  assert.equal(controller.getState().status, "error");
  await controller.submit();

  assert.equal(controller.getState().status, "deleted");
  assert.equal(cleanupCalls, 1);
});

test("cleanup failure cannot turn a confirmed local deletion into a failure", async () => {
  const controller = readyController({
    completeLocalCleanup: async () => {
      throw new Error("local cleanup unavailable");
    },
  });

  await controller.submit();
  await new Promise<void>((resolve) => setImmediate(resolve));

  assert.equal(controller.getState().status, "deleted");
});
