import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import React, { type ReactNode } from "react";

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
  accessibilityLabel?: unknown;
  accessibilityRole?: unknown;
  accessibilityLiveRegion?: unknown;
  children?: ReactNode;
  onPress?: () => void;
  style?: unknown;
  testID?: string;
  [key: string]: unknown;
};

function host(tag: string) {
  return function HostComponent(props: NativeProps) {
    return React.createElement(tag, {
      ...props,
      "data-testid": props.testID,
    });
  };
}

const originalLoad = moduleApi._load;
const nativeShim = {
  PanResponder: {
    create: (config: { onStartShouldSetPanResponder?: () => boolean }) => ({
      panHandlers: {
        onTouchStart: config.onStartShouldSetPanResponder,
      },
    }),
  },
  Pressable: host("button"),
  StyleSheet: {
    create: <T extends Record<string, unknown>>(styles: T): T => styles,
  },
  Text: host("span"),
  View: host("div"),
};

moduleApi._load = (request: string, parent: unknown, isMain: boolean) => {
  if (request === "react-native") {
    return nativeShim;
  }
  return originalLoad(request, parent, isMain);
};

const { VisualLearningCard } = moduleRequire("./VisualLearningCard") as typeof import("./VisualLearningCard");
const { GEOMETRY_PYRAMID_3D, FORCES_VECTOR_2D } = moduleRequire("./curatedRegistry") as typeof import("./curatedRegistry");
const { THEME_PALETTES } = moduleRequire("../../theme") as typeof import("../../theme");

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

const PALETTES = ["studio", "wood", "glass", "paper"] as const;
const SCHEMES = ["light", "dark"] as const;

test("3D pyramid primitives meet >= 3.0:1 graphical contrast against surfaceElevated across all four palettes", () => {
  for (const palette of PALETTES) {
    for (const scheme of SCHEMES) {
      const theme = THEME_PALETTES[palette][scheme];
      const canvas = theme.colors.surfaceElevated;

      // 1. Apex and base vertices against canvas
      for (const vertex of GEOMETRY_PYRAMID_3D.vertices) {
        const vertexColor = theme.colors[vertex.colorToken];
        const cr = contrast(vertexColor, canvas);
        assert.ok(
          cr >= 3.0,
          `${palette} ${scheme} 3D vertex ${vertex.id} (${vertex.colorToken}) contrast against surfaceElevated must be >= 3.0:1 (got ${cr.toFixed(2)})`,
        );
      }

      // 2. Base perimeter edges and slant edges against canvas
      for (const edge of GEOMETRY_PYRAMID_3D.edges) {
        const edgeColor = theme.colors[edge.colorToken];
        const cr = contrast(edgeColor, canvas);
        assert.ok(
          cr >= 3.0,
          `${palette} ${scheme} 3D edge ${edge.id} (${edge.colorToken}) contrast against surfaceElevated must be >= 3.0:1 (got ${cr.toFixed(2)})`,
        );
      }
    }
  }
});

test("2D forces diagram vectors meet >= 3.0:1 graphical contrast against surfaceElevated across all four palettes", () => {
  for (const palette of PALETTES) {
    for (const scheme of SCHEMES) {
      const theme = THEME_PALETTES[palette][scheme];
      const canvas = theme.colors.surfaceElevated;

      // 1. Force vectors (thrust, friction, normal, weight) against canvas
      for (const vec of FORCES_VECTOR_2D.vectors) {
        const vecColor = theme.colors[vec.colorToken];
        const cr = contrast(vecColor, canvas);
        assert.ok(
          cr >= 3.0,
          `${palette} ${scheme} 2D vector ${vec.id} (${vec.colorToken}) contrast against surfaceElevated must be >= 3.0:1 (got ${cr.toFixed(2)})`,
        );
      }

      // 2. Net resultant force badge foreground against canvas
      if (FORCES_VECTOR_2D.resultant) {
        const resultantColor = theme.colors[FORCES_VECTOR_2D.resultant.colorToken];
        const cr = contrast(resultantColor, canvas);
        assert.ok(
          cr >= 3.0,
          `${palette} ${scheme} 2D resultant (${FORCES_VECTOR_2D.resultant.colorToken}) contrast against surfaceElevated must be >= 3.0:1 (got ${cr.toFixed(2)})`,
        );
      }
    }
  }
});

test("diagram labels and tabular text maintain readable contrast across all four palettes", () => {
  for (const palette of PALETTES) {
    for (const scheme of SCHEMES) {
      const { colors } = THEME_PALETTES[palette][scheme];

      // Primary text on surfaceElevated (vertex labels, vector titles): AA >= 4.5:1
      const textOnCanvas = contrast(colors.text, colors.surfaceElevated);
      assert.ok(
        textOnCanvas >= 4.5,
        `${palette} ${scheme} text on surfaceElevated must meet >= 4.5:1 (got ${textOnCanvas.toFixed(2)})`,
      );

      // Muted description on surface (fallback table cells): AA >= 4.5:1
      const mutedOnTable = contrast(colors.mutedText, colors.surface);
      assert.ok(
        mutedOnTable >= 4.5,
        `${palette} ${scheme} table cell mutedText on surface must meet >= 4.5:1 (got ${mutedOnTable.toFixed(2)})`,
      );

      // Primary button label in table toggle on primarySoft: AA >= 4.5:1
      const toggleContrast = contrast(colors.primary, colors.primarySoft);
      assert.ok(
        toggleContrast >= 4.5,
        `${palette} ${scheme} table toggle button text contrast must meet >= 4.5:1 (got ${toggleContrast.toFixed(2)})`,
      );
    }
  }
});

test("VisualLearningCard renders all four palettes in both schemes cleanly upon answer reveal", () => {
  for (const palette of PALETTES) {
    for (const scheme of SCHEMES) {
      const theme = THEME_PALETTES[palette][scheme];

      // Render 3D geometry pyramid
      const markup3D = renderToStaticMarkup(
        React.createElement(VisualLearningCard, {
          subject: "mathematics",
          topic: "geometry",
          isRevealed: true,
          theme,
          testID: `test-${palette}-${scheme}-3d`,
        }),
      );
      assert.match(markup3D, /Square-Based Pyramid/);
      assert.match(markup3D, /Topic Concept Illustration/);
      assert.match(markup3D, /Rotate Left/);

      // Render 2D forces diagram
      const markup2D = renderToStaticMarkup(
        React.createElement(VisualLearningCard, {
          subject: "physics",
          topic: "forces",
          isRevealed: true,
          theme,
          testID: `test-${palette}-${scheme}-2d`,
        }),
      );
      assert.match(markup2D, /Forces on a Surface/);
      assert.match(markup2D, /Forward Thrust/);
      assert.match(markup2D, /View Forces Table/);
    }
  }
});
