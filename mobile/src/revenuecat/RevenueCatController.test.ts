import assert from "node:assert/strict";
import test from "node:test";

import type { RevenueCatConfigurationResult } from "./config";
import { RevenueCatController } from "./RevenueCatController";
import {
  adapterFailureCodeFromError,
  formatSubscriptionPeriod,
  revenueCatErrorIsCancellation,
} from "./state";
import {
  revenueCatReadyData,
  type RevenueCatAdapter,
  type RevenueCatCustomerInfo,
  type RevenueCatOfferings,
  type RevenueCatPaywallResult,
  type RevenueCatPlatformCapability,
  type RevenueCatState,
} from "./types";

const USER_A = "11111111-1111-4111-8111-111111111111";
const USER_B = "22222222-2222-4222-8222-222222222222";
const TEST_STORE_KEY = ["test", "fixture", "public", "key"].join("_");

const configuration: RevenueCatConfigurationResult = {
  status: "configured",
  configuration: {
    mode: "test",
    apiKey: TEST_STORE_KEY,
    entitlementId: "pro",
    offeringId: "default",
  },
};

const nativeCapability: RevenueCatPlatformCapability = {
  status: "native-purchase-supported",
  platform: "ios",
};

function entitlement(
  identifier: string,
  isActive: boolean,
  expirationDate: string | null = "2026-09-01T12:00:00Z",
) {
  return {
    identifier,
    isActive,
    expirationDate,
    willRenew: true,
    isSandbox: true,
  };
}

function customerInfo(
  activeIdentifiers: readonly string[] = [],
  inactiveIdentifiers: readonly string[] = [],
): RevenueCatCustomerInfo {
  const active = Object.fromEntries(
    activeIdentifiers.map((identifier) => [
      identifier,
      entitlement(identifier, true),
    ]),
  );
  const all = {
    ...active,
    ...Object.fromEntries(
      inactiveIdentifiers.map((identifier) => [
        identifier,
        entitlement(identifier, false, "2026-01-01T00:00:00Z"),
      ]),
    ),
  };
  return {
    entitlements: { active, all },
    managementUrl: activeIdentifiers.length > 0 ? "https://store.example/manage" : null,
  };
}

function availableOfferings(): RevenueCatOfferings {
  return {
    currentOfferingId: "default",
    offerings: [
      {
        identifier: "default",
        packages: [
          {
            identifier: "$rc_monthly",
            productIdentifier: "studyroom_monthly",
            title: "StudyRoom Pro Monthly",
            description: "Monthly access",
            price: "£3.99",
            period: "P1M",
          },
        ],
      },
    ],
  };
}

type AsyncHandler<TArguments extends readonly unknown[], TResult> = (
  ...arguments_: TArguments
) => Promise<TResult>;

class FakeRevenueCatAdapter implements RevenueCatAdapter {
  readonly configureCalls: string[] = [];
  readonly logInCalls: string[] = [];
  logOutCalls = 0;
  customerInfoCalls = 0;
  offeringsCalls = 0;
  paywallCalls = 0;
  restoreCalls = 0;
  listenerRegistrations = 0;
  currentUserId: string | null = null;
  currentCustomerInfo = customerInfo();
  currentOfferings = availableOfferings();
  readonly customersByUserId = new Map<string, RevenueCatCustomerInfo>();
  configureError: unknown = null;
  offeringsError: unknown = null;
  loginHandler: AsyncHandler<[string], RevenueCatCustomerInfo> | null = null;
  customerInfoHandler: AsyncHandler<[], RevenueCatCustomerInfo> | null = null;
  paywallHandler: AsyncHandler<[string], RevenueCatPaywallResult> | null = null;
  restoreHandler: AsyncHandler<[], RevenueCatCustomerInfo> | null = null;
  private readonly customerInfoListeners = new Set<
    (info: RevenueCatCustomerInfo) => void
  >();

  constructor(
    readonly capability: RevenueCatPlatformCapability = nativeCapability,
  ) {}

  async configure(apiKey: string): Promise<void> {
    this.configureCalls.push(apiKey);
    if (this.configureError !== null) {
      throw this.configureError;
    }
  }

  async logIn(appUserId: string): Promise<RevenueCatCustomerInfo> {
    this.logInCalls.push(appUserId);
    const info = this.loginHandler
      ? await this.loginHandler(appUserId)
      : (this.customersByUserId.get(appUserId) ?? this.currentCustomerInfo);
    this.currentUserId = appUserId;
    return info;
  }

  async logOut(): Promise<RevenueCatCustomerInfo> {
    this.logOutCalls += 1;
    this.currentUserId = null;
    return customerInfo();
  }

  async getCustomerInfo(): Promise<RevenueCatCustomerInfo> {
    this.customerInfoCalls += 1;
    if (this.customerInfoHandler) {
      return this.customerInfoHandler();
    }
    return (
      (this.currentUserId
        ? this.customersByUserId.get(this.currentUserId)
        : undefined) ?? this.currentCustomerInfo
    );
  }

  async getOfferings(): Promise<RevenueCatOfferings> {
    this.offeringsCalls += 1;
    if (this.offeringsError !== null) {
      throw this.offeringsError;
    }
    return this.currentOfferings;
  }

  async presentPaywall(offeringId: string): Promise<RevenueCatPaywallResult> {
    this.paywallCalls += 1;
    return this.paywallHandler
      ? this.paywallHandler(offeringId)
      : { status: "cancelled" };
  }

  async restorePurchases(): Promise<RevenueCatCustomerInfo> {
    this.restoreCalls += 1;
    return this.restoreHandler
      ? this.restoreHandler()
      : this.currentCustomerInfo;
  }

  async addCustomerInfoUpdateListener(
    listener: (info: RevenueCatCustomerInfo) => void,
  ): Promise<() => void> {
    this.listenerRegistrations += 1;
    this.customerInfoListeners.add(listener);
    return () => this.customerInfoListeners.delete(listener);
  }

  emitCustomerInfo(info: RevenueCatCustomerInfo): void {
    this.currentCustomerInfo = info;
    if (this.currentUserId !== null) {
      this.customersByUserId.set(this.currentUserId, info);
    }
    for (const listener of this.customerInfoListeners) {
      listener(info);
    }
  }
}

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

function nextTurn(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}

async function signedInController(
  adapter: FakeRevenueCatAdapter,
  userId = USER_A,
): Promise<RevenueCatController> {
  const controller = new RevenueCatController({ adapter, configuration });
  void controller.setAuthenticated(userId);
  await controller.initialize();
  return controller;
}

function readyData(state: RevenueCatState) {
  const data = revenueCatReadyData(state);
  if (data === null) {
    throw new Error(`Expected RevenueCat data in state ${state.status}.`);
  }
  return data;
}

test("missing configuration produces a safe unavailable state", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const controller = new RevenueCatController({
    adapter,
    configuration: {
      status: "unavailable",
      message: "The RevenueCat Test Store public SDK key is not configured.",
    },
  });
  await controller.initialize();
  assert.equal(controller.getState().status, "unavailable");
  assert.equal(adapter.configureCalls.length, 0);
});

test("SDK configuration and listener registration happen exactly once", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const controller = new RevenueCatController({ adapter, configuration });
  await Promise.all([
    controller.initialize(),
    controller.initialize(),
    controller.initialize(),
  ]);
  assert.equal(adapter.configureCalls.length, 1);
  assert.equal(adapter.listenerRegistrations, 1);
});

test("SDK configuration failures never expose the API key", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.configureError = new Error(`Rejected ${TEST_STORE_KEY}`);
  const controller = new RevenueCatController({ adapter, configuration });
  await controller.initialize();
  const state = controller.getState();
  assert.equal(state.status, "unavailable");
  if (state.status === "unavailable") {
    assert.equal(state.message.includes(TEST_STORE_KEY), false);
  }
});

test("a signed-out app configures without logging in a customer", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const controller = new RevenueCatController({ adapter, configuration });
  await controller.initialize();
  assert.equal(controller.getState().status, "signed-out");
  assert.deepEqual(adapter.logInCalls, []);
});

test("the authenticated UUID is the RevenueCat App User ID", async () => {
  const adapter = new FakeRevenueCatAdapter();
  await signedInController(adapter);
  assert.deepEqual(adapter.logInCalls, [USER_A]);
});

test("repeated auth events do not reconfigure or relogin", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const controller = await signedInController(adapter);
  await controller.setAuthenticated(USER_A);
  await controller.setAuthenticated(USER_A);
  assert.equal(adapter.configureCalls.length, 1);
  assert.deepEqual(adapter.logInCalls, [USER_A]);
});

test("identity switch logs into the new UUID and clears prior Pro immediately", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.customersByUserId.set(USER_A, customerInfo(["pro"]));
  adapter.customersByUserId.set(USER_B, customerInfo());
  const controller = await signedInController(adapter, USER_A);
  assert.equal(readyData(controller.getState()).isPro, true);

  const switching = controller.setAuthenticated(USER_B);
  assert.deepEqual(controller.getState(), {
    status: "loading-customer",
    capability: nativeCapability,
    appUserId: USER_B,
  });
  await switching;
  assert.deepEqual(adapter.logInCalls, [USER_A, USER_B]);
  assert.equal(readyData(controller.getState()).isPro, false);
});

test("stale prior login completion cannot publish the old customer", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const firstLogin = deferred<RevenueCatCustomerInfo>();
  adapter.customersByUserId.set(USER_B, customerInfo());
  adapter.loginHandler = async (userId) =>
    userId === USER_A ? firstLogin.promise : customerInfo();
  const controller = new RevenueCatController({ adapter, configuration });
  const publishedReadyUsers: string[] = [];
  controller.subscribe(() => {
    const data = revenueCatReadyData(controller.getState());
    if (controller.getState().status === "ready" && data !== null) {
      publishedReadyUsers.push(data.appUserId);
    }
  });
  void controller.setAuthenticated(USER_A);
  const initializing = controller.initialize();
  await nextTurn();
  assert.deepEqual(adapter.logInCalls, [USER_A]);

  const switching = controller.setAuthenticated(USER_B);
  firstLogin.resolve(customerInfo(["pro"]));
  await Promise.all([initializing, switching]);
  assert.equal(publishedReadyUsers.includes(USER_A), false);
  assert.deepEqual(adapter.logInCalls, [USER_A, USER_B]);
  assert.equal(readyData(controller.getState()).appUserId, USER_B);
});

test("sign-out logs RevenueCat out and clears Pro state", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.currentCustomerInfo = customerInfo(["pro"]);
  const controller = await signedInController(adapter);
  assert.equal(readyData(controller.getState()).isPro, true);
  const signingOut = controller.setSignedOut();
  assert.equal(controller.getState().status, "signed-out");
  assert.equal(revenueCatReadyData(controller.getState()), null);
  await signingOut;
  assert.equal(adapter.logOutCalls, 1);
});

test("no active entitlement means Free", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const controller = await signedInController(adapter);
  assert.equal(readyData(controller.getState()).isPro, false);
});

test("an active pro entitlement means Pro", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.currentCustomerInfo = customerInfo(["pro"]);
  const controller = await signedInController(adapter);
  assert.equal(readyData(controller.getState()).isPro, true);
});

test("an inactive pro entitlement remains Free", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.currentCustomerInfo = customerInfo([], ["pro"]);
  const controller = await signedInController(adapter);
  assert.equal(readyData(controller.getState()).isPro, false);
});

test("an unrelated active entitlement does not grant Pro", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.currentCustomerInfo = customerInfo(["another-entitlement"]);
  const controller = await signedInController(adapter);
  assert.equal(readyData(controller.getState()).isPro, false);
});

test("CustomerInfo listener activation and expiry update Pro", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const controller = await signedInController(adapter);
  adapter.emitCustomerInfo(customerInfo(["pro"]));
  assert.equal(readyData(controller.getState()).isPro, true);
  adapter.emitCustomerInfo(customerInfo([], ["pro"]));
  assert.equal(readyData(controller.getState()).isPro, false);
});

test("foreground-style refresh reloads CustomerInfo and entitlement state", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const controller = await signedInController(adapter);
  adapter.currentCustomerInfo = customerInfo(["pro"]);
  await controller.refreshCustomerInfo();
  assert.equal(readyData(controller.getState()).isPro, true);
  assert.equal(adapter.customerInfoCalls, 2);
});

test("the configured default offering and store metadata load", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const controller = await signedInController(adapter);
  const data = readyData(controller.getState());
  assert.equal(data.offering?.identifier, "default");
  assert.deepEqual(data.offering?.packages[0], {
    identifier: "$rc_monthly",
    productIdentifier: "studyroom_monthly",
    title: "StudyRoom Pro Monthly",
    description: "Monthly access",
    price: "£3.99",
    period: "P1M",
  });
  assert.equal(formatSubscriptionPeriod(data.offering?.packages[0]?.period ?? null), "1 month");
});

test("missing configured offering is readable and not fabricated", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.currentOfferings = {
    currentOfferingId: "another",
    offerings: [{ identifier: "another", packages: [] }],
  };
  const controller = await signedInController(adapter);
  const data = readyData(controller.getState());
  assert.equal(data.offering, null);
  assert.equal(data.offeringStatus, "missing");
});

test("an offering with no packages is an explicit empty state", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.currentOfferings = {
    currentOfferingId: "default",
    offerings: [{ identifier: "default", packages: [] }],
  };
  const controller = await signedInController(adapter);
  assert.equal(readyData(controller.getState()).offeringStatus, "empty");
  assert.deepEqual(await controller.presentPaywall(), { status: "failed" });
  assert.equal(adapter.paywallCalls, 0);
});

test("offering network failure preserves entitlement data as recoverable", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.currentCustomerInfo = customerInfo(["pro"]);
  adapter.offeringsError = { code: "10" };
  const controller = await signedInController(adapter);
  const state = controller.getState();
  assert.equal(state.status, "recoverable-error");
  assert.equal(readyData(state).isPro, true);
  assert.equal(readyData(state).offeringStatus, "load-failed");
});

test("purchase success grants Pro only after refreshed CustomerInfo confirms it", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.paywallHandler = async () => {
    adapter.currentCustomerInfo = customerInfo(["pro"]);
    return { status: "purchased" };
  };
  const controller = await signedInController(adapter);
  const result = await controller.presentPaywall();
  assert.deepEqual(result, { status: "completed", isPro: true });
  assert.equal(readyData(controller.getState()).isPro, true);
});

test("paywall purchase result without active entitlement remains Free", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.paywallHandler = async () => ({ status: "purchased" });
  const controller = await signedInController(adapter);
  const result = await controller.presentPaywall();
  assert.deepEqual(result, { status: "failed" });
  assert.equal(controller.getState().status, "recoverable-error");
  assert.equal(readyData(controller.getState()).isPro, false);
});

test("paywall dismissal and user cancellation are neutral", async () => {
  for (const result of [
    { status: "not-presented" },
    { status: "cancelled" },
  ] as const) {
    const adapter = new FakeRevenueCatAdapter();
    adapter.paywallHandler = async () => result;
    const controller = await signedInController(adapter);
    assert.deepEqual(await controller.presentPaywall(), { status: "cancelled" });
    const state = controller.getState();
    assert.equal(state.status, "ready");
    assert.equal(readyData(state).isPro, false);
  }
});

test("purchase pending stays Free until CustomerInfo changes", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.paywallHandler = async () => ({ status: "pending" });
  const controller = await signedInController(adapter);
  assert.deepEqual(await controller.presentPaywall(), { status: "pending" });
  assert.equal(readyData(controller.getState()).isPro, false);
});

test("RevenueCat cancellation and pending errors are classified safely", () => {
  assert.equal(revenueCatErrorIsCancellation({ code: "1" }), true);
  assert.equal(adapterFailureCodeFromError({ code: "20" }), "purchase-pending");
  assert.equal(adapterFailureCodeFromError({ code: "10" }), "network-failure");
  assert.equal(adapterFailureCodeFromError({ code: "42" }), "purchase-failed");
});

test("purchase failure is readable and recoverable", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.paywallHandler = async () => ({
    status: "failed",
    code: "store-unavailable",
  });
  const controller = await signedInController(adapter);
  assert.deepEqual(await controller.presentPaywall(), { status: "failed" });
  const state = controller.getState();
  assert.equal(state.status, "recoverable-error");
  if (state.status === "recoverable-error") {
    assert.equal(state.code, "store-unavailable");
    assert.match(state.message, /store is unavailable/i);
  }
});

test("duplicate purchase taps are blocked", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const paywall = deferred<RevenueCatPaywallResult>();
  adapter.paywallHandler = async () => paywall.promise;
  const controller = await signedInController(adapter);
  const first = controller.presentPaywall();
  const second = await controller.presentPaywall();
  assert.equal(second.status, "blocked");
  assert.equal(adapter.paywallCalls, 1);
  paywall.resolve({ status: "cancelled" });
  await first;
});

test("explicit restore activates Pro when CustomerInfo confirms it", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.restoreHandler = async () => customerInfo(["pro"]);
  const controller = await signedInController(adapter);
  const result = await controller.restorePurchases();
  assert.deepEqual(result, { status: "completed", isPro: true });
  assert.equal(readyData(controller.getState()).isPro, true);
});

test("duplicate restore taps coalesce into one SDK operation", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const restore = deferred<RevenueCatCustomerInfo>();
  adapter.restoreHandler = async () => restore.promise;
  const controller = await signedInController(adapter);
  const first = controller.restorePurchases();
  const second = controller.restorePurchases();
  assert.strictEqual(first, second);
  assert.equal(adapter.restoreCalls, 1);
  restore.resolve(customerInfo());
  await first;
});

test("restore with no entitlement remains Free with a neutral result", async () => {
  const adapter = new FakeRevenueCatAdapter();
  const controller = await signedInController(adapter);
  const result = await controller.restorePurchases();
  assert.deepEqual(result, { status: "completed", isPro: false });
  const state = controller.getState();
  assert.equal(state.status, "ready");
  if (state.status === "ready") {
    assert.match(state.notice?.message ?? "", /No StudyRoom Pro purchase/);
  }
});

test("restore failure is recoverable without exposing SDK details", async () => {
  const adapter = new FakeRevenueCatAdapter();
  adapter.restoreHandler = async () => {
    throw { code: "10", message: "unsafe internal detail" };
  };
  const controller = await signedInController(adapter);
  assert.deepEqual(await controller.restorePurchases(), { status: "failed" });
  const state = controller.getState();
  assert.equal(state.status, "recoverable-error");
  if (state.status === "recoverable-error") {
    assert.equal(state.message.includes("unsafe internal detail"), false);
    assert.equal(state.code, "network-failure");
  }
});

test("Expo Go preview initializes but cannot invoke purchase or restore", async () => {
  const adapter = new FakeRevenueCatAdapter({
    status: "preview-only",
    platform: "ios",
    message: "Expo Go is preview-only.",
  });
  const controller = await signedInController(adapter);
  assert.equal(controller.getState().status, "ready");
  assert.equal(adapter.configureCalls.length, 1);
  assert.deepEqual(adapter.logInCalls, [USER_A]);
  assert.equal((await controller.presentPaywall()).status, "blocked");
  assert.equal((await controller.restorePurchases()).status, "blocked");
  assert.equal(adapter.paywallCalls, 0);
  assert.equal(adapter.restoreCalls, 0);
});

test("Web fallback never invokes RevenueCat native methods", async () => {
  const adapter = new FakeRevenueCatAdapter({
    status: "unsupported-with-current-web-configuration",
    platform: "web",
    message: "Use a native development build.",
  });
  const controller = new RevenueCatController({ adapter, configuration });
  void controller.setAuthenticated(USER_A);
  await controller.initialize();
  assert.equal(controller.getState().status, "unavailable");
  assert.equal(adapter.configureCalls.length, 0);
  assert.equal(adapter.logInCalls.length, 0);
  assert.equal((await controller.presentPaywall()).status, "blocked");
  assert.equal((await controller.restorePurchases()).status, "blocked");
  assert.equal(adapter.paywallCalls, 0);
  assert.equal(adapter.restoreCalls, 0);
});
