import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import React, { type ReactNode } from "react";

import { PET_IDS, getPetCopy } from "./petPresentation";
import { THEME_PALETTES } from "../../theme";

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
  accessibilityLabel?: string;
  accessibilityHint?: string;
  accessibilityRole?: string;
  accessibilityLiveRegion?: string;
  importantForAccessibility?: string;
  onPress?: () => void;
  [key: string]: unknown;
};

type Capture = { tag: string; props: NativeProps };
const captures: Capture[] = [];
let motionStarts = 0;
let motionQueries = 0;

function host(tag: "div" | "span" | "button") {
  return function NativeHost(props: NativeProps) {
    captures.push({ tag, props });
    const attributes: Record<string, string> = {};
    if (props.testID) attributes["data-testid"] = props.testID;
    if (props.accessibilityLabel) attributes["aria-label"] = props.accessibilityLabel;
    if (props.accessibilityRole) attributes.role = props.accessibilityRole;
    if (props.accessibilityLiveRegion) {
      attributes["aria-live"] = props.accessibilityLiveRegion;
    }
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
    isReduceMotionEnabled: () => {
      motionQueries += 1;
      return Promise.resolve(true);
    },
    addEventListener: () => ({ remove: () => undefined }),
  },
  Animated: {
    Value: MockAnimatedValue,
    View: host("div"),
    sequence: () => ({
      start: () => {
        motionStarts += 1;
      },
      stop: () => undefined,
    }),
    timing: () => ({ start: () => undefined, stop: () => undefined }),
  },
  Pressable: host("button"),
  StyleSheet: {
    create: <T extends Record<string, unknown>>(styles: T): T => styles,
  },
  Text: host("span"),
  View: host("div"),
};

const originalLoad = moduleApi._load;
moduleApi._load = (request: string, parent: unknown, isMain: boolean) =>
  request === "react-native" ? nativeShim : originalLoad(request, parent, isMain);
const { PetCompanion } = moduleRequire("./PetCompanion") as typeof import("./PetCompanion");
moduleApi._load = originalLoad;

function flattenStyle(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) {
    return Object.assign({}, ...style.map(flattenStyle));
  }
  return typeof style === "object" && style !== null
    ? (style as Record<string, unknown>)
    : {};
}

function captured(testID: string): Capture {
  const found = captures.find((item) => item.props.testID === testID);
  assert.ok(found, `Missing ${testID}`);
  return found;
}

test("all three pets render native shapes and accessible text in every native palette", () => {
  for (const [palette, themes] of Object.entries(THEME_PALETTES)) {
    for (const [scheme, theme] of Object.entries(themes)) {
      for (const petId of PET_IDS) {
        captures.length = 0;
        const testID = `${palette}-${scheme}-${petId}`;
        const html = renderToStaticMarkup(
          React.createElement(PetCompanion, {
            petId,
            theme,
            occasion: "result",
            animationVariant: "animation.earned_celebration",
            testID,
          }),
        );
        const copy = getPetCopy(petId);
        assert.ok(html.includes(copy.name));
        assert.ok(html.includes(copy.finishLine));
        assert.ok(html.includes(copy.earnedAction));

        const card = captured(testID);
        assert.equal(flattenStyle(card.props.style).backgroundColor, theme.colors.surface);
        const art = captured(`${testID}-art`);
        assert.equal(flattenStyle(art.props.style).backgroundColor, theme.colors.surfaceElevated);
        assert.equal(art.props.importantForAccessibility, "no-hide-descendants");

        const button = captured(`${testID}-tap`);
        assert.equal(button.tag, "button");
        assert.equal(button.props.accessibilityRole, "button");
        assert.equal(button.props.accessibilityLabel, `Interact with ${copy.name}`);
        assert.equal(button.props.accessibilityHint, `Show ${copy.name}'s reaction`);
        assert.ok(Number(flattenStyle(button.props.style).minWidth) >= 44);
        assert.ok(Number(flattenStyle(button.props.style).minHeight) >= 44);
        assert.equal(captured(`${testID}-message`).props.accessibilityLiveRegion, "polite");

        const shapeName =
          petId === "pet.owl"
            ? "owl-body"
            : petId === "pet.tortoise"
              ? "tortoise-shell"
              : "fox-head";
        captured(`${testID}-${shapeName}`);
        assert.equal(captures.some((item) => item.props.testID === `${testID}-scarf-band`), false);
      }
    }
  }
});

test("confirmed scarf is a static native shape on every pet in all eight palettes", () => {
  motionStarts = 0;
  motionQueries = 0;
  for (const [palette, themes] of Object.entries(THEME_PALETTES)) {
    for (const [scheme, theme] of Object.entries(themes)) {
      for (const petId of PET_IDS) {
        captures.length = 0;
        const testID = `${palette}-${scheme}-${petId}-scarf`;
        const html = renderToStaticMarkup(
          React.createElement(PetCompanion, {
            petId,
            theme,
            equippedScarf: true,
            animationsEnabled: false,
            testID,
          }),
        );
        assert.ok(html.includes("Wearing study scarf"));
        assert.ok(html.includes(getPetCopy(petId).idleLine));
        assert.equal(flattenStyle(captured(`${testID}-scarf-band`).props.style).backgroundColor, theme.colors.primary);
        assert.equal(flattenStyle(captured(`${testID}-scarf-tail`).props.style).backgroundColor, theme.colors.primary);
        assert.equal(flattenStyle(captured(`${testID}-scarf-knot`).props.style).backgroundColor, theme.colors.onPrimary);
        assert.equal(
          flattenStyle(captured(`${testID}-scarf-label`).props.style).color,
          theme.colors.mutedText,
        );
      }
    }
  }
  assert.equal(motionStarts, 0);
  assert.equal(motionQueries, 0);
});

test("initial home render is still and does not query motion settings during render", () => {
  captures.length = 0;
  motionQueries = 0;
  motionStarts = 0;
  const html = renderToStaticMarkup(
    React.createElement(PetCompanion, {
      petId: "pet.owl",
      theme: THEME_PALETTES.studio.light,
      animationsEnabled: false,
      testID: "quiet-owl",
    }),
  );
  assert.ok(html.includes("Owl is ready to explore."));
  assert.ok(!html.includes("Owl lifts its wings in celebration."));
  assert.equal(motionQueries, 0);
  assert.equal(motionStarts, 0);
  assert.equal(typeof captured("quiet-owl-tap").props.onPress, "function");
});
