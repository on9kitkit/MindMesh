import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  resolveThemeScheme,
  studioDarkTheme,
  studioLightTheme,
  themeForMode,
} from "../theme";
import {
  studioButtonPresentation,
  studioChoicePresentation,
} from "./studioPresentation";

const mobileDirectory = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../..",
);

function source(relativePath: string): string {
  return readFileSync(join(mobileDirectory, relativePath), "utf8");
}

function channel(value: number): number {
  const normalized = value / 255;
  return normalized <= 0.03928
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const red = Number.parseInt(hex.slice(1, 3), 16);
  const green = Number.parseInt(hex.slice(3, 5), 16);
  const blue = Number.parseInt(hex.slice(5, 7), 16);
  return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue);
}

function contrast(first: string, second: string): number {
  const firstLuminance = luminance(first);
  const secondLuminance = luminance(second);
  const lighter = Math.max(firstLuminance, secondLuminance);
  const darker = Math.min(firstLuminance, secondLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

test("Studio mode resolves explicit and system schemes without persistence", () => {
  assert.equal(resolveThemeScheme("light", "dark"), "light");
  assert.equal(resolveThemeScheme("dark", "light"), "dark");
  assert.equal(resolveThemeScheme("system", "dark"), "dark");
  assert.equal(resolveThemeScheme("system", "light"), "light");
  assert.equal(resolveThemeScheme("system", null), "light");
  assert.equal(themeForMode("system", "dark"), studioDarkTheme);
  assert.equal(themeForMode("system", undefined), studioLightTheme);
});

test("both Studio palettes expose readable text and semantic state colors", () => {
  for (const theme of [studioLightTheme, studioDarkTheme]) {
    assert.ok(contrast(theme.colors.text, theme.colors.background) >= 7);
    assert.ok(contrast(theme.colors.mutedText, theme.colors.background) >= 4.5);
    assert.ok(contrast(theme.colors.onPrimary, theme.colors.primary) >= 4.5);
    assert.ok(theme.radii.lg > theme.radii.md);
    assert.ok(theme.spacing.xxl > theme.spacing.xl);
    assert.ok(theme.typography.title.lineHeight >= theme.typography.title.fontSize);
  }
  assert.notEqual(studioLightTheme.colors.background, studioDarkTheme.colors.background);
  assert.notEqual(studioLightTheme.colors.surface, studioDarkTheme.colors.surface);
});

test("native control presentation keeps disabled/selected states and touch targets", () => {
  for (const theme of [studioLightTheme, studioDarkTheme]) {
    const activeButton = studioButtonPresentation(theme, "primary", false);
    const disabledButton = studioButtonPresentation(theme, "primary", true);
    assert.equal(activeButton.button.minHeight, 48);
    assert.equal(disabledButton.button.opacity, 0.55);
    assert.equal(activeButton.button.backgroundColor, theme.colors.primary);
    assert.equal(activeButton.button.paddingVertical, theme.spacing.sm);
    assert.equal(activeButton.label.color, theme.colors.onPrimary);

    const selected = studioChoicePresentation(theme, true, false);
    const disabled = studioChoicePresentation(theme, false, true);
    assert.equal(selected.row.minHeight, 64);
    assert.equal(selected.row.borderColor, theme.colors.primary);
    assert.equal(disabled.row.opacity, 0.55);
    assert.equal(disabled.row.borderColor, theme.colors.border);
  }
});

test("real Studio primitives retain native ergonomics and accessibility contracts", () => {
  const primitives = source("src/components/studio/StudioPrimitives.tsx");
  const presentation = source("src/appearance/studioPresentation.ts");
  assert.match(primitives, /SafeAreaView/);
  assert.match(primitives, /keyboardShouldPersistTaps="handled"/);
  assert.match(primitives, /behavior=\{Platform\.OS === "ios" \? "padding"/);
  assert.match(primitives, /accessibilityRole="button"/);
  assert.match(primitives, /accessibilityRole="radio"/);
  assert.match(primitives, /accessibilityState=\{\{ disabled \}\}/);
  assert.match(primitives, /accessibilityState=\{\{ disabled: !editable \}\}/);
  assert.match(primitives, /accessibilityState=\{\{ checked: selected, disabled \}\}/);
  assert.match(presentation, /minHeight: 48/);
  assert.match(presentation, /minHeight: 64/);
  assert.match(primitives, /maxWidth: 720/);
});

test("Studio adoption is opt-in and real routes retain authority boundaries", () => {
  const layout = source("app/_layout.tsx");
  const home = source("app/index.tsx");
  const signIn = source("app/sign-in.tsx");
  const waitingRoom = source("app/waiting-room.tsx");
  const playerRow = source("src/components/PlayerRow.tsx");
  assert.ok(layout.indexOf("<AuthProvider>") < layout.indexOf("<RevenueCatProvider>"));
  assert.ok(layout.indexOf("<RevenueCatProvider>") < layout.indexOf("<SessionProvider>"));
  assert.ok(layout.indexOf("<SessionProvider>") < layout.indexOf("<SessionRouteCoordinator />"));
  assert.match(layout, /<StudioThemeProvider preferenceEnabled=\{appearanceEnabled\}>/);
  assert.match(
    layout,
    /pathname === "\/" \|\| pathname === "\/sign-in" \|\| pathname === "\/waiting-room"/,
  );
  assert.match(layout, /StatusBar style=\{theme\.scheme === "dark" \? "light" : "dark"\}/);
  assert.match(layout, /appearanceEnabled\s*\?\s*theme\.colors\.background\s*:\s*colors\.background/);
  assert.match(home, /requestCreateRoom/);
  assert.match(home, /requestJoinRoomByCode/);
  assert.match(home, /HomeRoomRequestCoordinator/);
  assert.match(home, /<StudioChoiceRow/);
  assert.match(home, /<StudioAppearanceSelector \/>/);
  assert.match(signIn, /useAuth/);
  assert.match(signIn, /<StudioAppearanceSelector \/>/);
  assert.match(signIn, /void signIn\(normalizedEmail, password\)/);
  assert.match(signIn, /void signOut\(\)/);
  assert.match(waitingRoom, /<StudioScreen>/);
  assert.match(waitingRoom, /<StudioCard/);
  assert.match(waitingRoom, /<StudioButton/);
  assert.match(waitingRoom, /<StudioPlayerRow/);
  assert.match(waitingRoom, /useSession/);
  assert.match(waitingRoom, /startSession\(\)/);
  assert.match(waitingRoom, /Alert\.alert/);
  assert.match(waitingRoom, /accessibilityLiveRegion="polite"/);
  assert.doesNotMatch(
    waitingRoom,
    /from "\.\.\/src\/components\/(AppButton|Card|Screen)"/,
  );
  assert.doesNotMatch(waitingRoom, /<PlayerRow\b/);
  assert.match(playerRow, /export function StudioPlayerRow/);
  assert.match(playerRow, /useStudioTheme/);
  assert.match(playerRow, /accessibilityLabel=\{`Report/);
  assert.match(playerRow, /accessibilityRole="button"/);
  assert.match(playerRow, /minHeight: 44/);
  for (const route of [home, signIn]) {
    assert.doesNotMatch(route, /AdaptivePreviewProvider|adaptivePreviewModel/);
    assert.doesNotMatch(route, /new WebSocket|fetch\(/);
  }
  assert.match(source("src/theme.ts"), /legacy exports/);
});
