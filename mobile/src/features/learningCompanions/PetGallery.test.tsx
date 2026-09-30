import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import React, { type ReactNode } from "react";

import { THEME_PALETTES } from "../../theme";
import {
  EARNED_CELEBRATION_ID,
  STUDY_SCARF_ID,
  type ConfirmedPetGallery,
  type PetGalleryState,
} from "./petGalleryPresentation";
import type { PetGalleryProps } from "./PetGallery";

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
  accessibilityLabel?: string;
  accessibilityRole?: string;
  accessibilityState?: { disabled?: boolean };
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

const originalLoad = moduleApi._load;
moduleApi._load = (request: string, parent: unknown, isMain: boolean) =>
  request === "react-native" ? nativeShim : originalLoad(request, parent, isMain);
const { PetGallery } = moduleRequire("./PetGallery") as typeof import("./PetGallery");
moduleApi._load = originalLoad;

const catalogPrices = {
  "pet.owl": 120,
  "pet.tortoise": 120,
  "pet.fox": 120,
  [STUDY_SCARF_ID]: 40,
  [EARNED_CELEBRATION_ID]: 80,
} as const;

function confirmed(overrides: Partial<ConfirmedPetGallery> = {}): ConfirmedPetGallery {
  return {
    balance: 0,
    ownedPetIds: [],
    equippedPetId: null,
    ownedCosmeticIds: [],
    scarfEquipped: false,
    starterClaimAvailable: true,
    catalogPrices,
    ...overrides,
  };
}

function ready(
  snapshot: ConfirmedPetGallery,
  overrides: Partial<Extract<PetGalleryState, { status: "ready" }>> = {},
): PetGalleryState {
  return { status: "ready", snapshot, pending: null, operationError: null, ...overrides };
}

function render(state: PetGalleryState, overrides: Partial<PetGalleryProps> = {}): string {
  captures.length = 0;
  const props: PetGalleryProps = {
    theme: THEME_PALETTES.studio.light,
    state,
    proAvailability: "unknown",
    selectedAnimationVariant: "basic",
    animationsEnabled: false,
    onRequestStarterClaim: () => undefined,
    onRequestPurchase: () => undefined,
    onRequestEquipPet: () => undefined,
    onRequestScarfEquipped: () => undefined,
    onRequestAnimationVariant: () => undefined,
    onRequestAnimationsEnabled: () => undefined,
    ...overrides,
  };
  return renderToStaticMarkup(React.createElement(PetGallery, props));
}

function captured(testID: string): Capture {
  const found = captures.find((entry) => entry.props.testID === testID);
  assert.ok(found, `Missing ${testID}`);
  return found;
}

function flattenStyle(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) return Object.assign({}, ...style.map(flattenStyle));
  return style !== null && typeof style === "object"
    ? style as Record<string, unknown>
    : {};
}

test("loading and error states never invent a balance or ownership", () => {
  const loading = render({ status: "loading" });
  assert.ok(loading.includes("Loading your confirmed pets and coin balance"));
  assert.equal(captures.some((entry) => entry.props.testID === "pet-gallery-balance"), false);

  const error = render({ status: "error", message: "Could not load companions" }, {
    onRetryLoad: () => undefined,
  });
  assert.ok(error.includes("Could not load companions"));
  assert.equal(captured("pet-gallery-retry").props.accessibilityRole, "button");
  assert.equal(captures.some((entry) => entry.props.testID === "pet-gallery-balance"), false);
});

test("zero balance shows one free starter choice and blocks paid items", () => {
  const html = render(ready(confirmed()));
  assert.ok(html.includes("Confirmed balance: 0 coins"));
  assert.ok(html.includes("Owl preview only. Choose a starter below"));
  for (const petId of ["pet.owl", "pet.tortoise", "pet.fox"]) {
    const offer = captured(`pet-gallery-offer-${petId}`);
    assert.equal(offer.props.disabled, false);
    assert.ok(offer.props.accessibilityLabel?.includes("free starter"));
  }
  assert.equal(captured(`pet-gallery-offer-${STUDY_SCARF_ID}`).props.disabled, true);
  assert.equal(captured(`pet-gallery-offer-${EARNED_CELEBRATION_ID}`).props.disabled, true);
  assert.ok(html.includes("Need 40 more coins for Study scarf"));
  assert.ok(html.includes("Need 80 more coins for Earned celebration"));
  assert.equal(captures.some((entry) => entry.props.testID === "pet-gallery-review"), false);
});

test("owned pet remains owned and insufficient balance disables the next pet", () => {
  const html = render(ready(confirmed({
    balance: 40,
    ownedPetIds: ["pet.owl"],
    equippedPetId: "pet.owl",
    starterClaimAvailable: false,
  })));
  assert.ok(html.includes("Owl is equipped."));
  assert.ok(html.includes("Need 80 more coins for Fox"));
  assert.equal(captured("pet-gallery-offer-pet.fox").props.disabled, true);
  assert.equal(captured(`pet-gallery-offer-${STUDY_SCARF_ID}`).props.disabled, false);
  assert.equal(captured(`pet-gallery-offer-${EARNED_CELEBRATION_ID}`).props.disabled, true);
  assert.equal(captured("pet-gallery-equip-pet.owl").props.disabled, true);
});

test("pending wallet request blocks duplicate purchase and equip dispatch", () => {
  let purchases = 0;
  let equips = 0;
  const html = render(ready(confirmed({
    balance: 120,
    ownedPetIds: ["pet.owl", "pet.tortoise"],
    equippedPetId: "pet.owl",
    starterClaimAvailable: false,
  }), {
    pending: { kind: "purchase", itemId: "pet.fox" },
  }), {
    onRequestPurchase: () => { purchases += 1; },
    onRequestEquipPet: () => { equips += 1; },
  });
  assert.ok(html.includes("Request pending"));
  const purchase = captured("pet-gallery-offer-pet.fox").props;
  const equip = captured("pet-gallery-equip-pet.tortoise").props;
  assert.equal(purchase.disabled, true);
  assert.equal(equip.disabled, true);
  assert.equal(purchase.accessibilityState?.disabled, true);
  purchase.onPress?.();
  equip.onPress?.();
  assert.equal(purchases, 0);
  assert.equal(equips, 0);
});

test("server operation error is visible without a fabricated balance change", () => {
  const html = render(ready(confirmed({
    balance: 120,
    ownedPetIds: ["pet.owl"],
    starterClaimAvailable: false,
  }), { operationError: "Purchase could not be confirmed" }));
  assert.ok(html.includes("Purchase could not be confirmed"));
  assert.ok(html.includes("Confirmed balance: 120 coins"));
  assert.equal(captured("pet-gallery-operation-error").props.accessibilityRole, "alert");
  assert.equal(captured("pet-gallery-offer-pet.fox").props.disabled, false);
});

test("unknown Pro pauses flourish while permanent earned items remain visible", () => {
  const html = render(ready(confirmed({
    balance: 0,
    ownedPetIds: ["pet.fox"],
    equippedPetId: "pet.fox",
    ownedCosmeticIds: [STUDY_SCARF_ID, EARNED_CELEBRATION_ID],
    scarfEquipped: true,
    starterClaimAvailable: false,
  })), { selectedAnimationVariant: "animation.pro_flourish" });
  assert.ok(html.includes("Fox is equipped."));
  assert.ok(html.includes("Study scarf is equipped."));
  assert.ok(html.includes("Wearing study scarf"));
  assert.ok(html.includes("Owned permanently"));
  assert.ok(html.includes("Pro flourish is paused"));
  assert.equal(captured("pet-gallery-select-pro").props.disabled, true);
  assert.equal(captured("pet-gallery-select-earned").props.disabled, false);
  assert.equal(captured("pet-gallery-equip-scarf").props.disabled, false);
  captured("pet-gallery-preview-scarf-band");
  assert.equal(captured("pet-gallery-preview-tap").props.accessibilityLabel, "Interact with Fox");
});

test("scarf art requires both confirmed ownership and equipment on the previewed pet", () => {
  const ownedPet = {
    ownedPetIds: ["pet.fox"] as const,
    equippedPetId: "pet.fox" as const,
    starterClaimAvailable: false,
    scarfEquipped: true,
  };
  render(ready(confirmed(ownedPet)));
  assert.equal(captures.some((entry) => entry.props.testID === "pet-gallery-preview-scarf-band"), false);
  assert.equal(captures.some((entry) => entry.props.testID === "pet-gallery-scarf-status"), false);

  const invalidEquipment = confirmed({
    ...ownedPet,
    equippedPetId: "pet.owl",
    ownedCosmeticIds: [STUDY_SCARF_ID],
  });
  render(ready(invalidEquipment));
  assert.ok(captured("pet-gallery-preview-status"));
  assert.equal(captures.some((entry) => entry.props.testID === "pet-gallery-preview-scarf-band"), false);
  assert.equal(captured("pet-gallery-equip-scarf").props.disabled, true);
});

test("all eight theme combinations supply native tokens and accessible 44pt controls", () => {
  const snapshot = confirmed();
  for (const [palette, themes] of Object.entries(THEME_PALETTES)) {
    for (const [scheme, theme] of Object.entries(themes)) {
      render(ready(snapshot), { theme, testID: `${palette}-${scheme}-gallery` });
      const root = captured(`${palette}-${scheme}-gallery`);
      assert.equal(flattenStyle(root.props.style).backgroundColor, theme.colors.background);
      const owl = captured(`${palette}-${scheme}-gallery-item-pet.owl`);
      assert.equal(flattenStyle(owl.props.style).backgroundColor, theme.colors.surface);
      const buttons = captures.filter((entry) => entry.tag === "button");
      assert.ok(buttons.length >= 8);
      for (const button of buttons) {
        assert.equal(button.props.accessibilityRole, "button");
        assert.ok(button.props.accessibilityLabel);
        assert.ok(Number(flattenStyle(button.props.style).minHeight) >= 44);
      }
      assert.ok(captured(`${palette}-${scheme}-gallery-preview-message`));
    }
  }
});
