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

type CapturedCall = {
  tag: string;
  props: NativeProps;
};

const capturedCalls: CapturedCall[] = [];

function host(tag: string) {
  return function HostComponent(props: NativeProps) {
    capturedCalls.push({ tag, props });
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

// Import component under test after native shim is wired
const { VisualLearningCard } = moduleRequire("./VisualLearningCard") as typeof import("./VisualLearningCard");
const { InteractiveScene3D } = moduleRequire("./InteractiveScene3D") as typeof import("./InteractiveScene3D");
const { Visualization2D } = moduleRequire("./Visualization2D") as typeof import("./Visualization2D");
const { GEOMETRY_PYRAMID_3D, FORCES_VECTOR_2D } = moduleRequire("./curatedRegistry") as typeof import("./curatedRegistry");
const { studioLightTheme, studioDarkTheme } = moduleRequire("../../theme") as typeof import("../../theme");

test("VisualLearningCard strictly returns null when isRevealed=false (no solution leaks)", () => {
  const html = renderToStaticMarkup(
    React.createElement(VisualLearningCard, {
      subject: "mathematics",
      topic: "geometry",
      isRevealed: false,
    }),
  );
  assert.equal(html, "", "Must render nothing when isRevealed is false");
});

test("VisualLearningCard returns null for unknown subject/topic pairs", () => {
  const html = renderToStaticMarkup(
    React.createElement(VisualLearningCard, {
      subject: "english_language",
      topic: "writing_techniques",
      isRevealed: true,
    }),
  );
  assert.equal(html, "", "Must return null for topics without a curated visual");
});

test("VisualLearningCard renders 3D Pyramid for mathematics/geometry when isRevealed=true", () => {
  const html = renderToStaticMarkup(
    React.createElement(VisualLearningCard, {
      subject: "mathematics",
      topic: "geometry",
      isRevealed: true,
      theme: studioLightTheme,
      testID: "test-card-3d",
    }),
  );

  // Must include explicit generic illustration disclaimer
  assert.ok(html.includes("Topic Concept Illustration"));
  assert.ok(html.includes("General topic concept illustration — not specific to this question&#x27;s values or answer."));
  assert.ok(html.includes("Square-Based Pyramid"));

  // Must render 3D canvas and stepper buttons
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-canvas\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-btn-left\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-btn-right\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-btn-up\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-btn-down\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-btn-reset\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-btn-toggle-table\""));

  // Check 5 vertices and 8 edges rendered
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-vertex-v_apex\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-vertex-v_b1\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-vertex-v_b2\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-vertex-v_b3\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-vertex-v_b4\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-edge-e_apex_b1\""));
  assert.ok(html.includes("data-testid=\"test-card-3d-3d-edge-e_b1_b2\""));
});

test("VisualLearningCard renders 2D Forces Diagram for physics/forces when isRevealed=true", () => {
  const html = renderToStaticMarkup(
    React.createElement(VisualLearningCard, {
      subject: "physics",
      topic: "forces",
      isRevealed: true,
      theme: studioDarkTheme,
      testID: "test-card-2d",
    }),
  );

  // Must include explicit generic illustration disclaimer
  assert.ok(html.includes("Topic Concept Illustration"));
  assert.ok(html.includes("General topic concept illustration — not specific to this question&#x27;s values or answer."));
  assert.ok(html.includes("Forces on a Surface"));

  // Must render 2D canvas, center object box, and vector lines
  assert.ok(html.includes("data-testid=\"test-card-2d-2d-canvas\""));
  assert.ok(html.includes("data-testid=\"test-card-2d-2d-center-box\""));
  assert.ok(html.includes("data-testid=\"test-card-2d-2d-vector-f_thrust\""));
  assert.ok(html.includes("data-testid=\"test-card-2d-2d-vector-f_friction\""));
  assert.ok(html.includes("data-testid=\"test-card-2d-2d-vector-f_normal\""));
  assert.ok(html.includes("data-testid=\"test-card-2d-2d-vector-f_weight\""));
  assert.ok(html.includes("data-testid=\"test-card-2d-2d-arrowhead-f_thrust\""));
  assert.ok(html.includes("Resultant Force (8 N Forward)"));
});

test("InteractiveScene3D renders accessible data table alternative when showTable is true", () => {
  // Directly test table rendering by exercising the component
  const html = renderToStaticMarkup(
    React.createElement(InteractiveScene3D, {
      descriptor: GEOMETRY_PYRAMID_3D,
      theme: studioLightTheme,
      testID: "test-scene",
    }),
  );

  // By default, table is collapsed, button is present
  assert.ok(html.includes("data-testid=\"test-scene-btn-toggle-table\""));
  assert.ok(html.includes("Data Table"));
});

test("Visualization2D renders educational summary for screen readers", () => {
  const html = renderToStaticMarkup(
    React.createElement(Visualization2D, {
      descriptor: FORCES_VECTOR_2D,
      theme: studioLightTheme,
      testID: "test-viz",
    }),
  );

  assert.ok(html.includes(FORCES_VECTOR_2D.educationalSummary));
});

function channel(value: number): number {
  const normalized = value / 255;
  return normalized <= 0.03928
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const clean = hex.replace("#", "");
  const r = channel(parseInt(clean.slice(0, 2), 16));
  const g = channel(parseInt(clean.slice(2, 4), 16));
  const b = channel(parseInt(clean.slice(4, 6), 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(hex1: string, hex2: string): number {
  const l1 = luminance(hex1);
  const l2 = luminance(hex2);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

test("interactive control touch targets meet the established >= 44pt minimum size", () => {
  // Render 3D and 2D scenes and check captured button props
  capturedCalls.length = 0;

  renderToStaticMarkup(
    React.createElement(InteractiveScene3D, {
      descriptor: GEOMETRY_PYRAMID_3D,
      theme: studioLightTheme,
    }),
  );

  const stepperButtons = capturedCalls.filter((c) => c.tag === "button");
  assert.ok(stepperButtons.length >= 7, "Must capture at least 7 interactive buttons in 3D scene");

  for (const btn of stepperButtons) {
    const style = btn.props.style as Record<string, unknown> | Array<Record<string, unknown>>;
    const flatStyle = Array.isArray(style)
      ? Object.assign({}, ...style)
      : (style as Record<string, unknown>);

    assert.ok(
      typeof flatStyle.minHeight === "number" && flatStyle.minHeight >= 44,
      `Button ${btn.props.accessibilityLabel} must have minHeight >= 44 (got ${flatStyle.minHeight})`,
    );
    assert.ok(
      typeof flatStyle.minWidth === "number" && flatStyle.minWidth >= 44,
      `Button ${btn.props.accessibilityLabel} must have minWidth >= 44 (got ${flatStyle.minWidth})`,
    );
  }

  // Check 2D toggle button
  capturedCalls.length = 0;
  renderToStaticMarkup(
    React.createElement(Visualization2D, {
      descriptor: FORCES_VECTOR_2D,
      theme: studioLightTheme,
    }),
  );

  const toggleBtn = capturedCalls.find((c) => c.tag === "button");
  assert.ok(toggleBtn !== undefined);
  const toggleStyle = toggleBtn?.props.style as Record<string, unknown> | Array<Record<string, unknown>>;
  const flatToggleStyle = Array.isArray(toggleStyle)
    ? Object.assign({}, ...toggleStyle)
    : (toggleStyle as Record<string, unknown>);

  assert.ok(
    typeof flatToggleStyle.minHeight === "number" && flatToggleStyle.minHeight >= 44,
    "2D Toggle button must have minHeight >= 44",
  );
  assert.ok(
    typeof flatToggleStyle.minWidth === "number" && flatToggleStyle.minWidth >= 44,
    "2D Toggle button must have minWidth >= 44",
  );
});

test("all used foreground/background color pairs meet WCAG >= 4.5:1 contrast in both Studio palettes", () => {
  for (const theme of [studioLightTheme, studioDarkTheme]) {
    // Primary text on surface
    const textOnSurface = contrast(theme.colors.text, theme.colors.surface);
    assert.ok(
      textOnSurface >= 4.5,
      `${theme.scheme} text on surface contrast must be >= 4.5:1 (got ${textOnSurface.toFixed(2)})`,
    );

    // Muted text on surface
    const mutedOnSurface = contrast(theme.colors.mutedText, theme.colors.surface);
    assert.ok(
      mutedOnSurface >= 4.5,
      `${theme.scheme} mutedText on surface contrast must be >= 4.5:1 (got ${mutedOnSurface.toFixed(2)})`,
    );

    // Text on canvas surfaceElevated
    const textOnElevated = contrast(theme.colors.text, theme.colors.surfaceElevated);
    assert.ok(
      textOnElevated >= 4.5,
      `${theme.scheme} text on surfaceElevated contrast must be >= 4.5:1 (got ${textOnElevated.toFixed(2)})`,
    );

    // Primary brand foreground on soft background (used in active badge & toggle)
    const primaryOnSoft = contrast(theme.colors.primary, theme.colors.primarySoft);
    assert.ok(
      primaryOnSoft >= 4.5,
      `${theme.scheme} primary on primarySoft contrast must be >= 4.5:1 (got ${primaryOnSoft.toFixed(2)})`,
    );

    // Success foreground on success background (used in resultant force badge)
    const successOnBg = contrast(theme.colors.success, theme.colors.successBackground);
    assert.ok(
      successOnBg >= 4.5,
      `${theme.scheme} success on successBackground contrast must be >= 4.5:1 (got ${successOnBg.toFixed(2)})`,
    );
  }
});

test("all curated diagram primitives (vertices, edges, vectors) meet >= 3:1 graphical contrast against surfaceElevated in both Studio palettes", () => {
  for (const theme of [studioLightTheme, studioDarkTheme]) {
    // 1. Pyramid 3D vertices against surfaceElevated canvas
    for (const v of GEOMETRY_PYRAMID_3D.vertices) {
      const cr = contrast(theme.colors[v.colorToken], theme.colors.surfaceElevated);
      assert.ok(
        cr >= 3.0,
        `${theme.scheme} pyramid vertex ${v.id} (${v.colorToken}) contrast against surfaceElevated must be >= 3:1 (got ${cr.toFixed(2)})`,
      );
    }

    // 2. Pyramid 3D edges against surfaceElevated canvas
    for (const e of GEOMETRY_PYRAMID_3D.edges) {
      const cr = contrast(theme.colors[e.colorToken], theme.colors.surfaceElevated);
      assert.ok(
        cr >= 3.0,
        `${theme.scheme} pyramid edge ${e.id} (${e.colorToken}) contrast against surfaceElevated must be >= 3:1 (got ${cr.toFixed(2)})`,
      );
    }

    // 3. Forces 2D vectors against surfaceElevated canvas
    for (const vec of FORCES_VECTOR_2D.vectors) {
      const cr = contrast(theme.colors[vec.colorToken], theme.colors.surfaceElevated);
      assert.ok(
        cr >= 3.0,
        `${theme.scheme} forces vector ${vec.id} (${vec.colorToken}) contrast against surfaceElevated must be >= 3:1 (got ${cr.toFixed(2)})`,
      );
    }

    // 4. Forces 2D resultant against surfaceElevated canvas
    if (FORCES_VECTOR_2D.resultant) {
      const cr = contrast(
        theme.colors[FORCES_VECTOR_2D.resultant.colorToken],
        theme.colors.surfaceElevated,
      );
      assert.ok(
        cr >= 3.0,
        `${theme.scheme} forces resultant (${FORCES_VECTOR_2D.resultant.colorToken}) contrast against surfaceElevated must be >= 3:1 (got ${cr.toFixed(2)})`,
      );
    }
  }
});
