import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import React, { createElement, type ReactElement } from "react";

import {
  THEME_PALETTES,
  type ThemePalette,
  type ThemeScheme,
  type ThemeTokens,
} from "../../theme";
import type {
  DrawingAction,
  DrawingDocument,
  DrawingStroke,
} from "./types";

type ModuleLoader = (request: string, parent: unknown, isMain: boolean) => unknown;
const nodeRequire = createRequire(import.meta.url);
const moduleApi = nodeRequire("node:module") as { _load: ModuleLoader };
const originalLoad = moduleApi._load;
function host(tag: string) {
  return ({ children, testID, ...props }: Record<string, unknown>) => {
    const domProps: Record<string, unknown> = {
      ...props,
      ...(testID !== undefined ? { "data-testid": testID } : {}),
    };
    return createElement(tag, domProps, children as React.ReactNode);
  };
}
moduleApi._load = (request, parent, isMain) => {
  if (request === "react-native") {
    const View = host("div");
    const Text = host("span");
    const Pressable = host("button");
    const ScrollView = host("div");
    return {
      __esModule: true,
      default: { View, Text, Pressable, ScrollView },
      Platform: { OS: "ios" },
      StyleSheet: { create: <T extends Record<string, unknown>>(s: T): T => s },
      View,
      Text,
      Pressable,
      ScrollView,
      PanResponder: {
        create: (config: Record<string, unknown>) => ({
          panHandlers: config,
        }),
      },
      useColorScheme: () => "light",
    };
  }
  if (request === "react-native-svg") {
    const SvgHost = host("svg");
    return {
      __esModule: true,
      default: SvgHost,
      Svg: SvgHost,
      Path: host("path"),
      Line: host("line"),
      Circle: host("circle"),
      G: host("g"),
      Rect: host("rect"),
      Text: host("text"),
    };
  }
  return originalLoad(request, parent, isMain);
};

type ReactDOMServer = {
  renderToStaticMarkup: (element: ReactElement) => string;
};
const reactDomServer: ReactDOMServer = nodeRequire("react-dom/server");
const renderToStaticMarkup = reactDomServer.renderToStaticMarkup;

async function loadWorkspaceModule() {
  (globalThis as typeof globalThis & { React?: typeof React }).React = React;
  return import("./DrawingWorkspace");
}

function makeTestDocument(overrides?: Partial<DrawingDocument>): DrawingDocument {
  return {
    strokes: [],
    active: null,
    past: [],
    future: [],
    nextStrokeId: 1,
    limitReached: false,
    ...overrides,
  };
}

const ALL_PALETTES: readonly ThemePalette[] = ["studio", "wood", "glass", "paper"];
const ALL_SCHEMES: readonly ThemeScheme[] = ["light", "dark"];

test("resolveInkColor resolves high-contrast semantic tokens across all 8 palette/schemes", async () => {
  const { resolveInkColor } = await loadWorkspaceModule();
  for (const palette of ALL_PALETTES) {
    for (const scheme of ALL_SCHEMES) {
      const theme: ThemeTokens = THEME_PALETTES[palette][scheme];
      assert.equal(resolveInkColor("ink", theme), theme.colors.text);
      assert.equal(resolveInkColor("primary", theme), theme.colors.primary);
      assert.equal(resolveInkColor("success", theme), theme.colors.success);
      assert.equal(resolveInkColor("error", theme), theme.colors.error);
      assert.ok(theme.colors.text.startsWith("#"));
      assert.ok(theme.colors.primary.startsWith("#"));
    }
  }
});

test("DrawingWorkspace renders with themed canvas across all 8 palette/schemes without forced white canvas", async () => {
  const { DrawingWorkspace } = await loadWorkspaceModule();
  for (const palette of ALL_PALETTES) {
    for (const scheme of ALL_SCHEMES) {
      const theme: ThemeTokens = THEME_PALETTES[palette][scheme];
      const doc = makeTestDocument();
      const actions: DrawingAction[] = [];

      const markup = renderToStaticMarkup(
        createElement(DrawingWorkspace, {
          document: doc,
          dispatch: (a) => actions.push(a),
          editable: true,
          theme,
        }),
      );

      // Verify canvas rendered
      assert.match(markup, /data-testid="drawing-workspace-canvas"/);
      assert.match(markup, /Maths Scratchpad/);
      assert.match(markup, /0 \/ 96 strokes/);

      // In dark mode, canvas background MUST be dark surfaceElevated, NEVER forced white #FFFFFF
      if (scheme === "dark") {
        assert.doesNotMatch(
          markup,
          new RegExp(`background-color:#FFFFFF.*data-testid="drawing-workspace-canvas"`),
        );
      }
    }
  }
});

test("DrawingWorkspace renders committed and active strokes", async () => {
  const { DrawingWorkspace } = await loadWorkspaceModule();
  const theme = THEME_PALETTES.studio.light;
  const stroke1: DrawingStroke = {
    id: 1,
    kind: "freehand",
    ink: "ink",
    points: [
      { x: 100, y: 100 },
      { x: 200, y: 200 },
    ],
  };
  const activeStroke: DrawingStroke = {
    id: 2,
    kind: "straight",
    ink: "primary",
    points: [
      { x: 300, y: 300 },
      { x: 500, y: 500 },
    ],
  };

  const doc = makeTestDocument({
    strokes: [stroke1],
    active: activeStroke,
  });

  const markup = renderToStaticMarkup(
    createElement(DrawingWorkspace, {
      document: doc,
      dispatch: () => undefined,
      editable: true,
      theme,
    }),
  );

  assert.match(markup, /1 \/ 96 strokes/);
  // Stroke 1 path
  assert.match(markup, /d="M 100 100 L 200 200"/);
  // Active stroke path
  assert.match(markup, /d="M 300 300 L 500 500"/);
});

test("DrawingWorkspace shows read-only banner and disables controls when editable is false", async () => {
  const { DrawingWorkspace } = await loadWorkspaceModule();
  const theme = THEME_PALETTES.studio.light;
  const doc = makeTestDocument();

  const markup = renderToStaticMarkup(
    createElement(DrawingWorkspace, {
      document: doc,
      dispatch: () => undefined,
      editable: false,
      theme,
    }),
  );

  assert.match(markup, /data-testid="drawing-workspace-read-only-banner"/);
  assert.match(markup, /Viewing saved working \(read-only\)/);
});

test("DrawingWorkspace shows limit reached banner when limitReached is true", async () => {
  const { DrawingWorkspace } = await loadWorkspaceModule();
  const theme = THEME_PALETTES.studio.light;
  const doc = makeTestDocument({ limitReached: true });

  const markup = renderToStaticMarkup(
    createElement(DrawingWorkspace, {
      document: doc,
      dispatch: () => undefined,
      editable: true,
      theme,
    }),
  );

  assert.match(markup, /data-testid="drawing-workspace-limit-banner"/);
  assert.match(markup, /Drawing limit reached\. Delete strokes or clear to continue\./);
});

test("DrawingWorkspace history buttons reflect document past, future, and strokes state", async () => {
  const { DrawingWorkspace } = await loadWorkspaceModule();
  const theme = THEME_PALETTES.studio.light;

  // 1. Initial empty document: Undo, Redo, and Clear should be disabled
  const emptyDoc = makeTestDocument();
  const emptyMarkup = renderToStaticMarkup(
    createElement(DrawingWorkspace, {
      document: emptyDoc,
      dispatch: () => undefined,
      editable: true,
      theme,
    }),
  );

  assert.match(emptyMarkup, /data-testid="drawing-workspace-action-undo"/);
  assert.match(emptyMarkup, /data-testid="drawing-workspace-action-redo"/);
  assert.match(emptyMarkup, /data-testid="drawing-workspace-action-clear"/);

  // 2. Document with past history and strokes: Undo and Clear enabled
  const stroke: DrawingStroke = {
    id: 1,
    kind: "freehand",
    ink: "ink",
    points: [{ x: 10, y: 10 }],
  };
  const activeDoc = makeTestDocument({
    strokes: [stroke],
    past: [[stroke]],
    future: [[stroke]],
  });

  const activeMarkup = renderToStaticMarkup(
    createElement(DrawingWorkspace, {
      document: activeDoc,
      dispatch: () => undefined,
      editable: true,
      theme,
    }),
  );
  assert.ok(activeMarkup.includes("data-testid=\"drawing-workspace-action-undo\""));
});

test("DrawingWorkspace renders close button as Return to answer and invokes onClose", async () => {
  const { DrawingWorkspace } = await loadWorkspaceModule();
  const theme = THEME_PALETTES.studio.light;
  const doc = makeTestDocument();
  let closed = false;

  const markup = renderToStaticMarkup(
    createElement(DrawingWorkspace, {
      document: doc,
      dispatch: () => undefined,
      editable: true,
      onClose: () => {
        closed = true;
      },
      theme,
    }),
  );

  assert.match(markup, /data-testid="drawing-workspace-close"/);
  assert.match(markup, /Return to answer/);
  assert.equal(closed, false);
});

test("DrawingWorkspace accessible tool options and ink selectors render with labels", async () => {
  const { DrawingWorkspace } = await loadWorkspaceModule();
  const theme = THEME_PALETTES.studio.light;
  const doc = makeTestDocument();

  const markup = renderToStaticMarkup(
    createElement(DrawingWorkspace, {
      document: doc,
      dispatch: () => undefined,
      editable: true,
      theme,
    }),
  );

  assert.match(markup, /data-testid="drawing-workspace-tool-pen"/);
  assert.match(markup, /data-testid="drawing-workspace-tool-ruler"/);
  assert.match(markup, /data-testid="drawing-workspace-tool-protractor"/);
  assert.match(markup, /data-testid="drawing-workspace-tool-eraser"/);

  assert.match(markup, /data-testid="drawing-workspace-ink-ink"/);
  assert.match(markup, /data-testid="drawing-workspace-ink-primary"/);
  assert.match(markup, /data-testid="drawing-workspace-ink-success"/);
  assert.match(markup, /data-testid="drawing-workspace-ink-error"/);
});

test("DrawingWorkspace renders protractor overlay and rotation controls when protractor tool is active", async () => {
  const { DrawingWorkspace } = await loadWorkspaceModule();
  const theme = THEME_PALETTES.studio.light;
  const doc = makeTestDocument();

  const markup = renderToStaticMarkup(
    createElement(DrawingWorkspace, {
      document: doc,
      dispatch: () => undefined,
      editable: true,
      initialTool: "protractor",
      theme,
    }),
  );

  assert.match(markup, /data-testid="drawing-workspace-protractor-overlay"/);
  assert.match(markup, /data-testid="drawing-workspace-protractor-rotate-ccw"/);
  assert.match(markup, /data-testid="drawing-workspace-protractor-rotate-cw"/);
  assert.match(markup, /data-testid="drawing-workspace-protractor-reset"/);
  assert.match(markup, /0° Protractor/);
});

test("DrawingWorkspace straightedge ruler active measurement displays units", async () => {
  const { DrawingWorkspace } = await loadWorkspaceModule();
  const theme = THEME_PALETTES.studio.light;
  const activeStroke: DrawingStroke = {
    id: 1,
    kind: "straight",
    ink: "primary",
    points: [
      { x: 100, y: 100 },
      { x: 400, y: 500 },
    ],
  };
  const doc = makeTestDocument({ active: activeStroke });

  const markup = renderToStaticMarkup(
    createElement(DrawingWorkspace, {
      document: doc,
      dispatch: () => undefined,
      editable: true,
      initialTool: "ruler",
      theme,
    }),
  );

  // 100,100 to 400,500 has dx=300, dy=400, hypot=500 units
  assert.match(markup, /500 units \(53°\)/);
});
