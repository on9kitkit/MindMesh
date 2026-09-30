import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import React from "react";
import type { ReactElement, ReactNode } from "react";

const moduleRequire = createRequire(import.meta.url);
const moduleApi = moduleRequire("node:module") as {
  _load: (request: string, parent: unknown, isMain: boolean) => unknown;
};

const serverModule = moduleRequire("react-dom/server") as {
  renderToStaticMarkup: (element: ReactElement) => string;
};
const renderToStaticMarkup = serverModule.renderToStaticMarkup;

type NativeProps = {
  accessibilityLabel?: unknown;
  accessibilityRole?: unknown;
  accessibilityState?: { checked?: boolean; disabled?: boolean };
  children?: ReactNode;
  onPress?: () => void;
  style?: unknown;
  testID?: string;
  [key: string]: unknown;
};

type CapturedCall = {
  tag: string;
  props: NativeProps;
};

const capturedCalls: CapturedCall[] = [];

function host(tag: string) {
  return function HostComponent({ children, ...props }: NativeProps) {
    capturedCalls.push({ tag, props });
    const htmlProps: Record<string, unknown> = {};
    if (typeof props.testID === "string") {
      htmlProps["data-testid"] = props.testID;
    }
    if (typeof props.accessibilityLabel === "string") {
      htmlProps["aria-label"] = props.accessibilityLabel;
    }
    if (typeof props.accessibilityRole === "string") {
      htmlProps.role = props.accessibilityRole;
    }
    if (props.accessibilityState?.checked !== undefined) {
      htmlProps["aria-checked"] = props.accessibilityState.checked;
    }
    if (props.accessibilityState?.disabled !== undefined) {
      htmlProps.disabled = props.accessibilityState.disabled;
    }
    return React.createElement(tag, htmlProps, children);
  };
}

const originalLoad = moduleApi._load;
const nativeShim = {
  KeyboardAvoidingView: host("div"),
  Platform: { OS: "ios" },
  Pressable: host("button"),
  ScrollView: host("div"),
  StyleSheet: {
    create: <T extends Record<string, unknown>>(styles: T): T => styles,
  },
  Text: host("span"),
  TextInput: host("input"),
  View: host("div"),
  useColorScheme: (): "light" => "light",
};

moduleApi._load = (request: string, parent: unknown, isMain: boolean) => {
  if (request === "react-native") {
    return nativeShim;
  }
  if (request === "react-native-safe-area-context") {
    return { SafeAreaView: host("div") };
  }
  return originalLoad(request, parent, isMain);
};

(globalThis as typeof globalThis & { React?: typeof React }).React = React;

// Import component and context under test after native shim is wired
import type { ThemePalette } from "../theme";

const themeModule = moduleRequire("../theme") as typeof import("../theme");
const { THEME_PALETTE_INFO } = themeModule;

const contextModule = moduleRequire("./StudioThemeContext") as typeof import("./StudioThemeContext");
const selectorModule = moduleRequire("./AppearanceSelector") as typeof import("./AppearanceSelector");
const { StudioAppearanceSelector } = selectorModule;

test("StudioAppearanceSelector renders collapsed state with both mode and palette controls", () => {
  capturedCalls.length = 0;
  const html = renderToStaticMarkup(
    React.createElement(
      contextModule.StudioThemeProvider,
      { mode: "light" },
      React.createElement(StudioAppearanceSelector),
    ),
  );

  // Exact strings required by studioComponents.test.tsx and design spec
  assert.match(html, /Appearance/);
  assert.match(html, /Choose appearance: Light/);
  assert.match(html, /Choose theme: Studio/);
  assert.match(html, /not linked to your account/);
  assert.match(html, /Changes apply immediately; this setting is device-local\./);
  assert.doesNotMatch(html, /Using Light while this device preference loads\./);
});

test("StudioAppearanceSelector palette metadata matches THEME_PALETTE_INFO", () => {
  const palettes: ThemePalette[] = ["studio", "wood", "glass", "paper"];

  for (const pal of palettes) {
    const info = THEME_PALETTE_INFO[pal];
    assert.ok(info.name.length > 0);
    assert.ok(info.description.length > 0);
  }
  assert.equal(THEME_PALETTE_INFO.studio.name, "Studio");
  assert.equal(THEME_PALETTE_INFO.wood.name, "Wood");
  assert.equal(THEME_PALETTE_INFO.glass.name, "Glass");
  assert.equal(THEME_PALETTE_INFO.paper.name, "Paper");
});

test("StudioAppearanceSelector accessibility contracts are preserved", () => {
  capturedCalls.length = 0;
  renderToStaticMarkup(
    React.createElement(
      contextModule.StudioThemeProvider,
      { mode: "light" },
      React.createElement(StudioAppearanceSelector),
    ),
  );

  // Buttons rendered must have valid accessibility labels and role="button"
  const buttonCalls = capturedCalls.filter((c) => c.tag === "button");
  assert.ok(buttonCalls.length >= 2, "Expected at least mode and palette toggle buttons");

  const modeBtn = buttonCalls.find((c) =>
    String(c.props.accessibilityLabel).includes("Choose appearance: Light"),
  );
  assert.ok(modeBtn, "Expected mode button with accessibilityLabel matching its label");
  assert.equal(modeBtn.props.accessibilityRole, "button");

  const themeBtn = buttonCalls.find((c) =>
    String(c.props.accessibilityLabel).includes("Choose theme: Studio"),
  );
  assert.ok(themeBtn, "Expected theme button with accessibilityLabel matching its label");
  assert.equal(themeBtn.props.accessibilityRole, "button");
});

test("StudioAppearanceSelector supports storage initialization for mode and palette", async () => {
  const mockStorage = {
    getItem: async () => "dark",
    setItem: async () => undefined,
  };

  const html = renderToStaticMarkup(
    React.createElement(
      contextModule.StudioThemeProvider,
      {
        storage: mockStorage,
        palette: "wood",
      },
      React.createElement(StudioAppearanceSelector),
    ),
  );

  assert.match(html, /Appearance/);
  assert.match(html, /Choose appearance/);
  assert.match(html, /Choose theme/);
});
test("StudioAppearanceSelector mode options use palette-neutral descriptions", () => {
  const fs = moduleRequire("node:fs") as typeof import("node:fs");
  const path = moduleRequire("node:path") as typeof import("node:path");
  const selectorSource = fs.readFileSync(
    path.resolve(import.meta.dirname, "AppearanceSelector.tsx"),
    "utf8",
  );
  assert.match(selectorSource, /description:\s*"A bright appearance\."/);
  assert.match(selectorSource, /description:\s*"A focused dark appearance\."/);
  assert.doesNotMatch(selectorSource, /A bright Studio palette/);
  assert.doesNotMatch(selectorSource, /A focused dark Studio palette/);
});
