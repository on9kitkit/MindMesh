import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import React, { type ReactNode } from "react";

import { THEME_PALETTES } from "../../theme";
import type { PetAccountState } from "../../api/learningCompanions";
import type { PetGalleryState } from "./petGalleryPresentation";
import type { PetsRouteApi, PetsScreenProps } from "../../../app/pets";

const moduleRequire = createRequire(import.meta.url);
const moduleApi = moduleRequire("node:module") as {
  _load: (request: string, parent: unknown, isMain: boolean) => unknown;
};
const renderToStaticMarkup = (
  moduleRequire("react-dom/server") as {
    renderToStaticMarkup: (element: React.ReactElement) => string;
  }
).renderToStaticMarkup;

type NativeProps = {
  children?: ReactNode;
  style?: unknown;
  testID?: string;
  disabled?: boolean;
  accessibilityRole?: string;
  accessibilityLabel?: string;
  onPress?: () => void;
  [key: string]: unknown;
};
type Capture = { tag: "div" | "span" | "button"; props: NativeProps };
const captures: Capture[] = [];
function host(tag: Capture["tag"]) {
  return function NativeHost(props: NativeProps) {
    captures.push({ tag, props });
    const attributes: Record<string, string> = {};
    if (props.testID) attributes["data-testid"] = props.testID;
    if (props.accessibilityLabel) attributes["aria-label"] = props.accessibilityLabel;
    if (props.accessibilityRole) attributes.role = props.accessibilityRole;
    return React.createElement(tag, attributes, props.children);
  };
}
class MockAnimatedValue {
  constructor(_initial: number) {}
  interpolate(config: { outputRange: ReadonlyArray<unknown> }) {
    return config.outputRange[1];
  }
  setValue(_value: number) {}
  stopAnimation() {}
}
const nativeShim = {
  AccessibilityInfo: {
    isReduceMotionEnabled: () => Promise.resolve(true),
    addEventListener: () => ({ remove: () => undefined }),
  },
  Animated: {
    Value: MockAnimatedValue,
    View: host("div"),
    sequence: () => ({ start: () => undefined, stop: () => undefined }),
    timing: () => ({ start: () => undefined, stop: () => undefined }),
  },
  Pressable: host("button"),
  StyleSheet: { create: <T extends Record<string, unknown>>(styles: T): T => styles },
  Text: host("span"),
  View: host("div"),
};
let sessionReader: () => Promise<{
  data: { session: { user: { id: string }; access_token: string } | null };
  error: null;
}> = async () => ({ data: { session: null }, error: null });
const originalLoad = moduleApi._load;
moduleApi._load = (request: string, parent: unknown, isMain: boolean) => {
  if (request === "react-native") return nativeShim;
  if (request === "expo-router") return { router: { replace: () => undefined } };
  if (request === "../src/auth/AuthContext") return { useAuth: () => ({}) };
  if (request === "../src/revenuecat/RevenueCatContext") return { useRevenueCat: () => ({}) };
  if (request === "../src/appearance/StudioThemeContext") return {
    useStudioTheme: () => THEME_PALETTES.studio.light,
  };
  if (request === "../src/appearance/appearancePreference") return {
    secureAppearanceStorage: {
      getItem: async () => null, setItem: async () => undefined,
    },
  };
  if (request === "../src/auth/supabase") return {
    getSupabaseClient: () => ({ auth: { getSession: sessionReader } }),
  };
  if (request === "../src/components/studio/StudioPrimitives") return {
    StudioScreen: host("div"),
    StudioText: host("span"),
    StudioButton: ({ label, onPress, disabled }: {
      label: string; onPress: () => void; disabled?: boolean;
    }) => React.createElement(host("button"), {
      accessibilityLabel: label, accessibilityRole: "button", disabled, onPress,
    }, label),
  };
  return originalLoad(request, parent, isMain);
};
const routeModule = moduleRequire("../../../app/pets") as typeof import("../../../app/pets");
moduleApi._load = originalLoad;

const catalog = [
  { id: "pet.owl", kind: "pet", coin_price: 120 },
  { id: "pet.tortoise", kind: "pet", coin_price: 120 },
  { id: "pet.fox", kind: "pet", coin_price: 120 },
  { id: "cosmetic.study_scarf", kind: "cosmetic", coin_price: 40 },
  { id: "animation.earned_celebration", kind: "animation", coin_price: 80 },
] as const;

function account(overrides: Partial<PetAccountState> = {}): PetAccountState {
  return {
    catalog,
    owned_item_ids: ["pet.owl"],
    starter_pet_id: "pet.owl",
    equipment: { pet_id: "pet.owl", cosmetic_id: null, animation_id: null },
    balance: 120,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function fakeApi(load: () => Promise<PetAccountState>): PetsRouteApi {
  return {
    load,
    chooseStarter: async () => ({}),
    purchase: async () => ({}),
    equip: async () => ({}),
    createPurchaseRequestId: () => "11111111-1111-4111-8111-111111111111",
  };
}

test("owner key requires signed-in bootstrap and separates session revisions", () => {
  const signedIn = {
    status: "signed-in" as const,
    user: { id: "user-A", email: null },
    profileBootstrap: { status: "ready" as const },
  };
  assert.equal(routeModule.petsOwnerKey(signedIn, 1), "user-A:1");
  assert.equal(routeModule.petsOwnerKey(signedIn, 2), "user-A:2");
  assert.equal(routeModule.petsOwnerKey({ ...signedIn, profileBootstrap: { status: "pending" } }, 1), null);
  assert.equal(routeModule.petsOwnerKey({ status: "signed-out" }, 1), null);
});

test("late user-A load cannot publish into user-B gallery", async () => {
  const first = deferred<PetAccountState>();
  const second = deferred<PetAccountState>();
  let calls = 0;
  let owner = "user-A:1";
  const controller = new routeModule.PetsRouteController(fakeApi(() => {
    calls += 1;
    return calls === 1 ? first.promise : second.promise;
  }), () => owner);
  const oldLoad = controller.setOwner(owner);
  assert.equal(controller.getSnapshot().status, "loading");
  owner = "user-B:2";
  const newLoad = controller.setOwner(owner);
  first.resolve(account({ balance: 999 }));
  await oldLoad;
  assert.equal(routeModule.visiblePetsGalleryState(owner, controller.getSnapshot()).status, "loading");
  second.resolve(account({ balance: 0, owned_item_ids: [], starter_pet_id: null, equipment: null }));
  await newLoad;
  const visible = routeModule.visiblePetsGalleryState(owner, controller.getSnapshot());
  assert.equal(visible.status, "ready");
  if (visible.status === "ready") assert.equal(visible.snapshot.balance, 0);
  assert.equal(routeModule.visiblePetsGalleryState("user-A:1", controller.getSnapshot()).status, "loading");
  controller.dispose();
});

test("purchase stays pending until a second confirmed GET and blocks duplicate taps", async () => {
  const mutation = deferred<unknown>();
  const refreshed = deferred<PetAccountState>();
  let loads = 0;
  let purchases = 0;
  let requestIds = 0;
  const api = fakeApi(() => {
    loads += 1;
    return loads === 1 ? Promise.resolve(account()) : refreshed.promise;
  });
  api.purchase = async (itemId, requestId) => {
    assert.equal(itemId, "pet.fox");
    assert.equal(requestId, "11111111-1111-4111-8111-111111111111");
    purchases += 1;
    return mutation.promise;
  };
  api.createPurchaseRequestId = () => {
    requestIds += 1;
    return "11111111-1111-4111-8111-111111111111";
  };
  const controller = new routeModule.PetsRouteController(api, () => "user-A:1");
  await controller.setOwner("user-A:1");
  const request = controller.requestPurchase("pet.fox");
  assert.equal(controller.getSnapshot().status, "ready");
  const pending = routeModule.visiblePetsGalleryState("user-A:1", controller.getSnapshot());
  assert.equal(pending.status, "ready");
  if (pending.status === "ready") {
    assert.equal(pending.snapshot.balance, 120);
    assert.deepEqual(pending.snapshot.ownedPetIds, ["pet.owl"]);
    assert.deepEqual(pending.pending, { kind: "purchase", itemId: "pet.fox" });
  }
  await controller.requestPurchase("pet.fox");
  assert.equal(purchases, 1);
  assert.equal(requestIds, 1);
  mutation.resolve({});
  await Promise.resolve();
  const stillPending = routeModule.visiblePetsGalleryState("user-A:1", controller.getSnapshot());
  assert.equal(stillPending.status, "ready");
  if (stillPending.status === "ready") assert.equal(stillPending.pending?.kind, "purchase");
  refreshed.resolve(account({ balance: 0, owned_item_ids: ["pet.owl", "pet.fox"] }));
  await request;
  const confirmed = routeModule.visiblePetsGalleryState("user-A:1", controller.getSnapshot());
  assert.equal(confirmed.status, "ready");
  if (confirmed.status === "ready") {
    assert.equal(confirmed.snapshot.balance, 0);
    assert.deepEqual(confirmed.snapshot.ownedPetIds, ["pet.owl", "pet.fox"]);
    assert.equal(confirmed.pending, null);
  }
  controller.dispose();
});

test("unconfirmed mutation refresh failure hides old wallet and offers retry", async () => {
  let loads = 0;
  const api = fakeApi(async () => {
    loads += 1;
    if (loads === 1) return account();
    throw new Error("synthetic refresh failure");
  });
  const controller = new routeModule.PetsRouteController(api, () => "user-A:1");
  await controller.setOwner("user-A:1");
  await controller.requestPurchase("pet.fox");
  const visible = routeModule.visiblePetsGalleryState("user-A:1", controller.getSnapshot());
  assert.equal(visible.status, "error");
  if (visible.status === "error") assert.match(visible.message, /could not be confirmed/);
  controller.dispose();
});

test("equipment writes preserve confirmed slots and Pro remains presentation only", async () => {
  let confirmed = account({
    owned_item_ids: [
      "pet.owl", "pet.fox", "cosmetic.study_scarf", "animation.earned_celebration",
    ],
    equipment: {
      pet_id: "pet.owl",
      cosmetic_id: "cosmetic.study_scarf",
      animation_id: "animation.earned_celebration",
    },
  });
  const equips: Array<NonNullable<PetAccountState["equipment"]>> = [];
  const api = fakeApi(async () => confirmed);
  api.equip = async (input) => {
    equips.push(input);
    confirmed = { ...confirmed, equipment: input };
    return input;
  };
  const controller = new routeModule.PetsRouteController(api, () => "user-A:1");
  await controller.setOwner("user-A:1");
  controller.selectPro("unknown");
  assert.equal(routeModule.selectedPetAnimation(controller.getSnapshot()), "animation.earned_celebration");
  controller.selectPro("active");
  assert.equal(routeModule.selectedPetAnimation(controller.getSnapshot()), "animation.pro_flourish");
  assert.equal(equips.length, 0);

  await controller.requestEquipPet("pet.fox");
  assert.deepEqual(equips[0], {
    pet_id: "pet.fox", cosmetic_id: "cosmetic.study_scarf",
    animation_id: "animation.earned_celebration",
  });
  await controller.requestEarnedAnimation("basic");
  assert.deepEqual(equips[1], {
    pet_id: "pet.fox", cosmetic_id: "cosmetic.study_scarf", animation_id: null,
  });
  assert.equal(routeModule.selectedPetAnimation(controller.getSnapshot()), "basic");
  await controller.requestScarfEquipped(false);
  assert.deepEqual(equips[2], {
    pet_id: "pet.fox", cosmetic_id: null, animation_id: null,
  });
  controller.dispose();
});

test("owner-bound API refuses a replacement account token before transport", async () => {
  let owner = "user-A:1";
  const session = deferred<{
    data: { session: { user: { id: string }; access_token: string } | null };
    error: null;
  }>();
  sessionReader = () => session.promise;
  const api = routeModule.createOwnerBoundPetsApi(() => owner);
  let fetches = 0;
  const priorFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    fetches += 1;
    throw new Error("must not fetch");
  };
  try {
    const load = api.load();
    owner = "user-B:2";
    session.resolve({ data: {
      session: { user: { id: "user-B" }, access_token: "synthetic-B" },
    }, error: null });
    await assert.rejects(load);
    assert.equal(fetches, 0);
  } finally {
    globalThis.fetch = priorFetch;
  }
});

test("owner-bound API sends only the current account token to /me/pets", async () => {
  sessionReader = async () => ({ data: {
    session: { user: { id: "user-A" }, access_token: "synthetic-A" },
  }, error: null });
  const api = routeModule.createOwnerBoundPetsApi(() => "user-A:1");
  const priorFetch = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async (input, init) => {
    requests += 1;
    assert.ok(String(input).endsWith("/me/pets"));
    assert.equal(new Headers(init?.headers).get("Authorization"), "Bearer synthetic-A");
    return new Response(JSON.stringify(account()), { status: 200 });
  };
  try {
    assert.equal((await api.load()).balance, 120);
    assert.equal(requests, 1);
  } finally {
    globalThis.fetch = priorFetch;
  }
});

test("only fresh owner-matched native ready Pro enables the visual variant", () => {
  const native = { status: "native-purchase-supported" as const, platform: "ios" as const };
  const data = {
    appUserId: "user-A", isPro: true, entitlementIdentifier: "pro",
    expirationDate: null, willRenew: null, managementUrl: null, isSandbox: null,
    offering: null, offeringStatus: "missing" as const,
  };
  const ready = { status: "ready" as const, capability: native, data, notice: null };
  assert.equal(routeModule.petProAvailability("user-A", ready), "active");
  assert.equal(routeModule.petProAvailability("user-B", ready), "unknown");
  assert.equal(routeModule.petProAvailability("user-A", {
    ...ready, data: { ...data, isPro: false },
  }), "inactive");
  assert.equal(routeModule.petProAvailability("user-A", {
    ...ready, data: { ...data, expirationDate: "2026-01-01T00:00:00Z" },
  }, Date.parse("2026-09-27T00:00:00Z")), "inactive");
  assert.equal(routeModule.petProAvailability("user-A", {
    ...ready, data: { ...data, expirationDate: "invalid" },
  }), "unknown");
  assert.equal(routeModule.petProAvailability("user-A", {
    status: "recoverable-error", capability: native, appUserId: "user-A",
    data, code: "network-failure", message: "synthetic",
  }), "unknown");
});

test("themed pets screen renders explicit wait, loading and confirmed gallery", () => {
  let mutations = 0;
  const base: PetsScreenProps = {
    theme: THEME_PALETTES.studio.light,
    galleryState: { status: "loading" },
    proAvailability: "unknown",
    selectedAnimationVariant: "basic",
    animationsEnabled: false,
    motionPreferenceError: null,
    waitingMessage: null,
    onRetry: () => undefined,
    onRequestStarterClaim: () => { mutations += 1; },
    onRequestPurchase: () => { mutations += 1; },
    onRequestEquipPet: () => { mutations += 1; },
    onRequestScarfEquipped: () => { mutations += 1; },
    onRequestAnimationVariant: () => { mutations += 1; },
    onRequestAnimationsEnabled: () => { mutations += 1; },
    onReturnHome: () => undefined,
  };
  const waiting = renderToStaticMarkup(React.createElement(routeModule.PetsScreen, {
    ...base, waitingMessage: "Returning to sign in…",
  }));
  assert.ok(waiting.includes("Returning to sign in"));
  assert.ok(!waiting.includes("Confirmed balance"));
  const loading = renderToStaticMarkup(React.createElement(routeModule.PetsScreen, base));
  assert.ok(loading.includes("Loading your confirmed pets"));
  const state: PetGalleryState = {
    status: "ready",
    snapshot: {
      balance: 0, ownedPetIds: [], equippedPetId: null,
      ownedCosmeticIds: [], scarfEquipped: false,
      starterClaimAvailable: true,
      catalogPrices: {
        "pet.owl": 120, "pet.tortoise": 120, "pet.fox": 120,
        "cosmetic.study_scarf": 40, "animation.earned_celebration": 80,
      },
    },
    pending: null,
    operationError: null,
  };
  for (const themes of Object.values(THEME_PALETTES)) {
    for (const theme of Object.values(themes)) {
      captures.length = 0;
      const html = renderToStaticMarkup(React.createElement(routeModule.PetsScreen, {
        ...base, theme, galleryState: state,
      }));
      assert.ok(html.includes("Confirmed balance: 0 coins"));
      assert.ok(html.includes("free starter"));
      const gallery = captures.find((item) => item.props.testID === "pet-gallery");
      assert.ok(gallery);
      assert.equal((gallery.props.style as Array<{ backgroundColor?: string }>)[1]?.backgroundColor, theme.colors.background);
    }
  }
  assert.equal(mutations, 0);
});
