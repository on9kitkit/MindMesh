import assert from "node:assert/strict";
import test from "node:test";
import { mindMeshProductCopy } from "./brandCopy";

test("legacy subscription display copy uses MindMesh without changing identifiers", () => {
  assert.equal(mindMeshProductCopy("StudyRoom Pro"), "MindMesh Pro");
  assert.equal(mindMeshProductCopy("STUDYROOM PRO"), "MINDMESH PRO");
  assert.equal(mindMeshProductCopy("studyroom pro monthly"), "MindMesh pro monthly");
  assert.equal(mindMeshProductCopy("studyroom_monthly"), "studyroom_monthly");
  assert.equal(mindMeshProductCopy("Your study room"), "Your study room");
});

import {
  resolveRevenueCatConfiguration,
  type RevenueCatEnvironment,
} from "./config";

const TEST_STORE_KEY = ["test", "fixture", "public", "key"].join("_");

const completeEnvironment: RevenueCatEnvironment = {
  EXPO_PUBLIC_REVENUECAT_TEST_API_KEY: TEST_STORE_KEY,
  EXPO_PUBLIC_REVENUECAT_ENTITLEMENT_ID: "pro",
  EXPO_PUBLIC_REVENUECAT_OFFERING_ID: "default",
  EXPO_PUBLIC_REVENUECAT_MODE: "test",
};

test("every RevenueCat environment value is required", () => {
  for (const name of Object.keys(
    completeEnvironment,
  ) as Array<keyof RevenueCatEnvironment>) {
    const result = resolveRevenueCatConfiguration({
      ...completeEnvironment,
      [name]: " ",
    });
    assert.equal(result.status, "unavailable", `${name} must be required`);
  }
});

test("missing Test Store key returns a safe unavailable result", () => {
  const result = resolveRevenueCatConfiguration({
    ...completeEnvironment,
    EXPO_PUBLIC_REVENUECAT_TEST_API_KEY: undefined,
  });
  assert.deepEqual(result, {
    status: "unavailable",
    message: "The RevenueCat Test Store public SDK key is not configured.",
  });
});

test("test mode accepts a Test Store key without defaulting identifiers", () => {
  const result = resolveRevenueCatConfiguration(completeEnvironment);
  assert.deepEqual(result, {
    status: "configured",
    configuration: {
      mode: "test",
      apiKey: TEST_STORE_KEY,
      entitlementId: "pro",
      offeringId: "default",
    },
  });
});

test("production mode rejects a Test Store key", () => {
  const result = resolveRevenueCatConfiguration({
    ...completeEnvironment,
    EXPO_PUBLIC_REVENUECAT_MODE: "production",
  });
  assert.equal(result.status, "unavailable");
  if (result.status === "unavailable") {
    assert.match(result.message, /cannot be used in production mode/);
  }
});

test("test mode rejects a key that is not from Test Store", () => {
  const result = resolveRevenueCatConfiguration({
    ...completeEnvironment,
    EXPO_PUBLIC_REVENUECAT_TEST_API_KEY: "public-platform-key",
  });
  assert.equal(result.status, "unavailable");
});

test("configuration errors never include the API key", () => {
  const result = resolveRevenueCatConfiguration({
    ...completeEnvironment,
    EXPO_PUBLIC_REVENUECAT_MODE: "production",
  });
  assert.equal(JSON.stringify(result).includes(TEST_STORE_KEY), false);
});
