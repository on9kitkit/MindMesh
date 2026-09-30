import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_THEME_PALETTE,
  THEME_PALETTE_INFO,
  THEME_PALETTES,
  type ThemePalette,
  type ThemeScheme,
  type ThemeTokens,
} from "./../theme";

function channel(value: number): number {
  const normalized = value / 255;
  return normalized <= 0.03928
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const parsed = hex.replace("#", "");
  const r = parseInt(parsed.slice(0, 2), 16);
  const g = parseInt(parsed.slice(2, 4), 16);
  const b = parseInt(parsed.slice(4, 6), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(first: string, second: string): number {
  const firstLuminance = luminance(first);
  const secondLuminance = luminance(second);
  const lighter = Math.max(firstLuminance, secondLuminance);
  const darker = Math.min(firstLuminance, secondLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

const PALETTES: ReadonlyArray<ThemePalette> = ["studio", "wood", "glass", "paper"];
const SCHEMES: ReadonlyArray<ThemeScheme> = ["light", "dark"];

test("all four theme palettes export valid ThemeTokens schemas without missing keys", () => {
  assert.equal(DEFAULT_THEME_PALETTE, "studio");

  for (const palette of PALETTES) {
    const info = THEME_PALETTE_INFO[palette];
    assert.ok(info, `Palette info missing for ${palette}`);
    assert.ok(info.name.length > 0, `Palette name missing for ${palette}`);
    assert.ok(info.description.length > 0, `Palette description missing for ${palette}`);

    for (const scheme of SCHEMES) {
      const theme = THEME_PALETTES[palette][scheme];
      assert.ok(theme, `Theme missing for ${palette} ${scheme}`);
      assert.equal(theme.scheme, scheme);

      // Verify all 17 required ThemeColors keys are present with valid hex values
      const requiredColorKeys: Array<keyof ThemeTokens["colors"]> = [
        "background",
        "surface",
        "surfaceElevated",
        "input",
        "text",
        "mutedText",
        "border",
        "primary",
        "primaryPressed",
        "primarySoft",
        "primaryDisabled",
        "onPrimary",
        "selectedBackground",
        "success",
        "successBackground",
        "error",
        "errorBackground",
      ];

      for (const key of requiredColorKeys) {
        const val = theme.colors[key];
        assert.ok(
          typeof val === "string" && /^#[0-9A-Fa-f]{6}$/.test(val),
          `${palette} ${scheme} colors.${key} must be valid 6-char hex, got "${val}"`,
        );
      }

      // Verify radii
      assert.ok(theme.radii.sm > 0);
      assert.ok(theme.radii.md > theme.radii.sm);
      assert.ok(theme.radii.lg > theme.radii.md);
      assert.equal(theme.radii.pill, 999);

      // Verify spacing
      assert.ok(theme.spacing.xxl > theme.spacing.xl);
      assert.ok(theme.spacing.xl > theme.spacing.lg);
      assert.ok(theme.spacing.lg > theme.spacing.md);
      assert.ok(theme.spacing.md > theme.spacing.sm);
      assert.ok(theme.spacing.sm > theme.spacing.xs);

      // Verify typography
      assert.ok(theme.typography.title.fontSize > theme.typography.heading.fontSize);
      assert.ok(theme.typography.heading.fontSize > theme.typography.body.fontSize);
      assert.ok(theme.typography.title.lineHeight >= theme.typography.title.fontSize);
    }
  }
});

test("all four theme palettes meet WCAG text readability requirements in both schemes", () => {
  for (const palette of PALETTES) {
    for (const scheme of SCHEMES) {
      const { colors } = THEME_PALETTES[palette][scheme];

      // Primary text on canvas and card surface: AAA >= 7.0:1
      const textOnBg = contrast(colors.text, colors.background);
      assert.ok(
        textOnBg >= 7.0,
        `${palette} ${scheme} text on background must meet >= 7.0:1 (got ${textOnBg.toFixed(2)})`,
      );

      const textOnSurface = contrast(colors.text, colors.surface);
      assert.ok(
        textOnSurface >= 7.0,
        `${palette} ${scheme} text on surface must meet >= 7.0:1 (got ${textOnSurface.toFixed(2)})`,
      );

      // Text on elevated diagram canvas: AA >= 4.5:1
      const textOnElevated = contrast(colors.text, colors.surfaceElevated);
      assert.ok(
        textOnElevated >= 4.5,
        `${palette} ${scheme} text on surfaceElevated must meet >= 4.5:1 (got ${textOnElevated.toFixed(2)})`,
      );

      // Muted text on canvas and card surface: AA >= 4.5:1
      const mutedOnBg = contrast(colors.mutedText, colors.background);
      assert.ok(
        mutedOnBg >= 4.5,
        `${palette} ${scheme} mutedText on background must meet >= 4.5:1 (got ${mutedOnBg.toFixed(2)})`,
      );

      const mutedOnSurface = contrast(colors.mutedText, colors.surface);
      assert.ok(
        mutedOnSurface >= 4.5,
        `${palette} ${scheme} mutedText on surface must meet >= 4.5:1 (got ${mutedOnSurface.toFixed(2)})`,
      );

      // Release-gate assertion: mutedText on surfaceElevated must meet AA >= 4.5:1 across all 8 combinations
      const mutedOnElevated = contrast(colors.mutedText, colors.surfaceElevated);
      assert.ok(
        mutedOnElevated >= 4.5,
        `${palette} ${scheme} mutedText on surfaceElevated must meet >= 4.5:1 (got ${mutedOnElevated.toFixed(2)})`,
      );
    }
  }
});

test("all four theme palettes satisfy button and interactive element contrast in both schemes", () => {
  for (const palette of PALETTES) {
    for (const scheme of SCHEMES) {
      const { colors } = THEME_PALETTES[palette][scheme];

      // Primary button label on primary button fill: AA >= 4.5:1
      const onPrimaryOnPrimary = contrast(colors.onPrimary, colors.primary);
      assert.ok(
        onPrimaryOnPrimary >= 4.5,
        `${palette} ${scheme} onPrimary on primary must meet >= 4.5:1 (got ${onPrimaryOnPrimary.toFixed(2)})`,
      );

      // Destructive button label on error fill: AA >= 4.5:1
      const onPrimaryOnError = contrast(colors.onPrimary, colors.error);
      assert.ok(
        onPrimaryOnError >= 4.5,
        `${palette} ${scheme} onPrimary on error must meet >= 4.5:1 (got ${onPrimaryOnError.toFixed(2)})`,
      );

      // Secondary button label (colors.text) on surface: AAA >= 7.0:1
      const secondaryLabel = contrast(colors.text, colors.surface);
      assert.ok(
        secondaryLabel >= 7.0,
        `${palette} ${scheme} secondary button label must meet >= 7.0:1 (got ${secondaryLabel.toFixed(2)})`,
      );

      // Primary accent on soft background (concept badge & active toggles): AA >= 4.5:1
      // CRITICAL GATE: Prevents dark-mode badge washout failure
      const primaryOnSoft = contrast(colors.primary, colors.primarySoft);
      assert.ok(
        primaryOnSoft >= 4.5,
        `${palette} ${scheme} primary on primarySoft must meet >= 4.5:1 (got ${primaryOnSoft.toFixed(2)})`,
      );

      // Selected choice row background contrast with primary text: AA >= 4.5:1
      const textOnSelected = contrast(colors.text, colors.selectedBackground);
      assert.ok(
        textOnSelected >= 4.5,
        `${palette} ${scheme} text on selectedBackground must meet >= 4.5:1 (got ${textOnSelected.toFixed(2)})`,
      );
    }
  }
});

test("all four theme palettes satisfy semantic alert and status contrast in both schemes", () => {
  for (const palette of PALETTES) {
    for (const scheme of SCHEMES) {
      const { colors } = THEME_PALETTES[palette][scheme];

      // Success text on success background: AA >= 4.5:1
      const successOnBg = contrast(colors.success, colors.successBackground);
      assert.ok(
        successOnBg >= 4.5,
        `${palette} ${scheme} success on successBackground must meet >= 4.5:1 (got ${successOnBg.toFixed(2)})`,
      );

      // Error text on error background: AA >= 4.5:1
      const errorOnBg = contrast(colors.error, colors.errorBackground);
      assert.ok(
        errorOnBg >= 4.5,
        `${palette} ${scheme} error on errorBackground must meet >= 4.5:1 (got ${errorOnBg.toFixed(2)})`,
      );

      // Error text on surface (inline form field errors): AA >= 4.5:1
      const errorOnSurface = contrast(colors.error, colors.surface);
      assert.ok(
        errorOnSurface >= 4.5,
        `${palette} ${scheme} error on surface must meet >= 4.5:1 (got ${errorOnSurface.toFixed(2)})`,
      );
    }
  }
});
