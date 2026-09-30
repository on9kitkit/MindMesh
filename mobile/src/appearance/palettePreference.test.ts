import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import React, { createElement, type ReactElement } from "react";

import {
  PALETTE_LOAD_ERROR,
  PALETTE_SAVE_ERROR,
  PALETTE_STORAGE_KEY,
  PalettePreferenceController,
  isThemePalette,
  parseStoredThemePalette,
} from "./palettePreference";
import type { AppearanceStorage } from "./appearancePreference";
import {
  THEME_PALETTES,
  themeForPaletteAndScheme,
  type ThemePalette,
} from "../theme";
import type { StudioThemeContextValue } from "./StudioThemeContext";

type ModuleLoader = (request: string, parent: unknown, isMain: boolean) => unknown;

async function loadThemeContext() {
  (globalThis as typeof globalThis & { React?: typeof React }).React = React;
  const moduleRequire = createRequire(import.meta.url);
  const moduleApi = moduleRequire("node:module") as { _load: ModuleLoader };
  const originalLoad = moduleApi._load;
  moduleApi._load = (request, parent, isMain) => {
    if (request === "react-native") {
      return { useColorScheme: () => "light" };
    }
    return originalLoad(request, parent, isMain);
  };
  return import("./StudioThemeContext");
}

type ReactDOMServer = {
  renderToStaticMarkup: (element: ReactElement) => string;
};
const nodeRequire = createRequire(import.meta.url);
const reactDomServer: ReactDOMServer = nodeRequire("react-dom/server");
const renderToStaticMarkup = reactDomServer.renderToStaticMarkup;
// Deterministic turn drain for testing asynchronous SecureStore queue serialization.
function tick(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}

test("palette storage accepts only the isolated theme enum", () => {
  assert.equal(PALETTE_STORAGE_KEY, "studyroom.appearance.palette.v1");
  assert.equal(parseStoredThemePalette("wood"), "wood");
  assert.equal(parseStoredThemePalette("glass"), "glass");
  assert.equal(parseStoredThemePalette("paper"), "paper");
  assert.equal(parseStoredThemePalette("studio"), "studio");
  assert.equal(parseStoredThemePalette("unknown"), "studio");
  assert.equal(parseStoredThemePalette(null), "studio");
  assert.equal(isThemePalette("wood"), true);
  assert.equal(isThemePalette("glass"), true);
  assert.equal(isThemePalette("paper"), true);
  assert.equal(isThemePalette("studio"), true);
  assert.equal(isThemePalette("dark"), false);
  assert.equal(isThemePalette(""), false);
  assert.equal(isThemePalette(null), false);
  assert.equal(isThemePalette(undefined), false);
});

test("stored preference hydrates after a Studio first paint", async () => {
  const storage: AppearanceStorage = {
    getItem: async () => "wood",
    setItem: async () => undefined,
  };
  const controller = new PalettePreferenceController(storage);

  assert.deepEqual(controller.getSnapshot(), {
    palette: "studio",
    hydrated: false,
    error: undefined,
  });
  await controller.hydrate();
  assert.deepEqual(controller.getSnapshot(), {
    palette: "wood",
    hydrated: true,
    error: undefined,
  });
});

test("a user choice wins over a late hydration result", async () => {
  let resolveRead: ((value: string | null) => void) | undefined;
  const read = new Promise<string | null>((resolve) => {
    resolveRead = resolve;
  });
  const writes: string[] = [];
  const storage: AppearanceStorage = {
    getItem: async () => read,
    setItem: async (_key, value) => {
      writes.push(value);
    },
  };
  const controller = new PalettePreferenceController(storage);
  const hydration = controller.hydrate();
  controller.select("wood");
  resolveRead?.("glass");
  await hydration;
  await tick();

  assert.equal(controller.getSnapshot().palette, "wood");
  assert.deepEqual(writes, ["wood"]);
});

test("a late successful read cannot clear a newer save failure", async () => {
  let resolveRead: ((value: string | null) => void) | undefined;
  const read = new Promise<string | null>((resolve) => {
    resolveRead = resolve;
  });
  const storage: AppearanceStorage = {
    getItem: async () => read,
    setItem: async () => {
      throw new Error("synthetic write failure");
    },
  };
  const controller = new PalettePreferenceController(storage);
  const hydration = controller.hydrate();
  controller.select("wood");
  await tick();
  assert.equal(controller.getSnapshot().error, PALETTE_SAVE_ERROR);

  resolveRead?.("glass");
  await hydration;
  assert.equal(controller.getSnapshot().palette, "wood");
  assert.equal(controller.getSnapshot().error, PALETTE_SAVE_ERROR);
});

test("a late failed read cannot clear a newer successful save", async () => {
  let rejectRead: ((reason?: unknown) => void) | undefined;
  const read = new Promise<string | null>((_resolve, reject) => {
    rejectRead = reject;
  });
  const storage: AppearanceStorage = {
    getItem: async () => read,
    setItem: async () => undefined,
  };
  const controller = new PalettePreferenceController(storage);
  const hydration = controller.hydrate();
  controller.select("wood");
  await tick();
  assert.equal(controller.getSnapshot().error, undefined);

  rejectRead?.(new Error("synthetic read failure"));
  await hydration;
  assert.equal(controller.getSnapshot().palette, "wood");
  assert.equal(controller.getSnapshot().error, undefined);
});

test("manual load retry is single-flight and remains retryable", async () => {
  const reads: Array<{
    resolve: (value: string | null) => void;
    reject: (reason?: unknown) => void;
  }> = [];
  let writes = 0;
  const storage: AppearanceStorage = {
    getItem: async () =>
      new Promise<string | null>((resolve, reject) => {
        reads.push({ resolve, reject });
      }),
    setItem: async () => {
      writes += 1;
      throw new Error("load retry must not write");
    },
  };
  const controller = new PalettePreferenceController(storage);
  const initial = controller.hydrate();
  reads[0].reject(new Error("initial read failure"));
  await initial;
  assert.equal(controller.getSnapshot().error, PALETTE_LOAD_ERROR);

  controller.retry();
  controller.retry();
  assert.equal(reads.length, 2);
  reads[1].reject(new Error("retry read failure"));
  await tick();
  assert.equal(controller.getSnapshot().error, PALETTE_LOAD_ERROR);

  controller.retry();
  assert.equal(reads.length, 3);
  reads[2].resolve("paper");
  await tick();
  assert.equal(controller.getSnapshot().palette, "paper");
  assert.equal(controller.getSnapshot().error, undefined);
  assert.equal(writes, 0);
});

test("a late manual retry read cannot replace a newer save error", async () => {
  for (const outcome of ["resolve", "reject"] as const) {
    const reads: Array<{
      resolve: (value: string | null) => void;
      reject: (reason?: unknown) => void;
    }> = [];
    let writes = 0;
    const storage: AppearanceStorage = {
      getItem: async () =>
        new Promise<string | null>((resolve, reject) => {
          reads.push({ resolve, reject });
        }),
      setItem: async () => {
        writes += 1;
        throw new Error("synthetic save failure");
      },
    };
    const controller = new PalettePreferenceController(storage);
    const initial = controller.hydrate();
    reads[0].reject(new Error("initial read failure"));
    await initial;
    assert.equal(controller.getSnapshot().error, PALETTE_LOAD_ERROR);

    controller.retry();
    assert.equal(reads.length, 2);
    controller.select("glass");
    await tick();
    assert.equal(writes, 1);
    assert.equal(controller.getSnapshot().palette, "glass");
    assert.equal(controller.getSnapshot().error, PALETTE_SAVE_ERROR);

    if (outcome === "resolve") {
      reads[1].resolve("wood");
    } else {
      reads[1].reject(new Error("late retry read failure"));
    }
    await tick();
    assert.equal(controller.getSnapshot().palette, "glass");
    assert.equal(controller.getSnapshot().error, PALETTE_SAVE_ERROR);
  }
});

test("rapid choices serialize and persist the latest value", async () => {
  const writes: string[] = [];
  let releaseFirst: (() => void) | undefined;
  const firstWrite = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });
  const storage: AppearanceStorage = {
    getItem: async () => null,
    setItem: async (_key, value) => {
      writes.push(value);
      if (value === "wood") {
        await firstWrite;
      }
    },
  };
  const controller = new PalettePreferenceController(storage);
  controller.select("wood");
  controller.select("glass");
  await tick();
  assert.deepEqual(writes, ["wood"]);

  releaseFirst?.();
  await tick();
  await tick();
  assert.deepEqual(writes, ["wood", "glass"]);
  assert.equal(controller.getSnapshot().palette, "glass");
});
test("storage failure retains the visible choice and supports manual retry", async () => {
  let fail = true;
  const writes: string[] = [];
  const storage: AppearanceStorage = {
    getItem: async () => null,
    setItem: async (_key, value) => {
      writes.push(value);
      if (fail) {
        throw new Error("synthetic storage failure");
      }
    },
  };
  const controller = new PalettePreferenceController(storage);
  controller.select("wood");
  await tick();
  assert.equal(controller.getSnapshot().palette, "wood");
  assert.equal(controller.getSnapshot().error, PALETTE_SAVE_ERROR);

  fail = false;
  controller.retry();
  await tick();
  assert.equal(controller.getSnapshot().palette, "wood");
  assert.equal(controller.getSnapshot().error, undefined);
  assert.deepEqual(writes, ["wood", "wood"]);
});

test("read failure is recoverable without replacing the Studio default", async () => {
  let fail = true;
  const storage: AppearanceStorage = {
    getItem: async () => {
      if (fail) {
        throw new Error("synthetic read failure");
      }
      return "paper";
    },
    setItem: async () => undefined,
  };
  const controller = new PalettePreferenceController(storage);
  await controller.hydrate();
  assert.equal(controller.getSnapshot().palette, "studio");
  assert.equal(controller.getSnapshot().error, PALETTE_LOAD_ERROR);

  fail = false;
  controller.retry();
  await tick();
  assert.equal(controller.getSnapshot().palette, "paper");
  assert.equal(controller.getSnapshot().error, undefined);
});

test("invalid palette selection is ignored gracefully", () => {
  const storage: AppearanceStorage = {
    getItem: async () => null,
    setItem: async () => undefined,
  };
  const controller = new PalettePreferenceController(storage);
  controller.select("invalid-palette" as unknown as ThemePalette);
  assert.equal(controller.getSnapshot().palette, "studio");
});

test("themeForPaletteAndScheme resolves all 4 palettes across light and dark", () => {
  for (const palette of ["studio", "wood", "glass", "paper"] as const) {
    for (const scheme of ["light", "dark"] as const) {
      const tokens = themeForPaletteAndScheme(palette, scheme);
      assert.equal(tokens.scheme, scheme);
      assert.equal(tokens, THEME_PALETTES[palette][scheme]);
      assert.ok(tokens.colors.primary.length > 0);
      assert.ok(tokens.colors.background.length > 0);
      assert.ok(tokens.colors.surface.length > 0);
      assert.ok(tokens.radii.lg > 0);
      assert.ok(tokens.spacing.md > 0);
    }
  }
});


test("StudioThemeProvider defaults to Studio palette and exposes context API", async () => {
  const { StudioThemeProvider, useStudioTheme } = await loadThemeContext();
  let capturedTheme: StudioThemeContextValue | undefined;
  function Probe() {
    capturedTheme = useStudioTheme();
    return createElement("span", null, capturedTheme.palette);
  }

  const storage: AppearanceStorage = {
    getItem: async () => null,
    setItem: async () => undefined,
  };

  renderToStaticMarkup(
    createElement(
      StudioThemeProvider,
      { storage, mode: "light" },
      createElement(Probe),
    ),
  );

  assert.ok(capturedTheme);
  assert.equal(capturedTheme.palette, "studio");
  assert.equal(capturedTheme.selectedPalette, "studio");
  assert.equal(capturedTheme.mode, "light");
  assert.equal(capturedTheme.selectedMode, "light");
  assert.equal(typeof capturedTheme.setPalette, "function");
  assert.equal(typeof capturedTheme.retryPaletteSave, "function");
  assert.equal(typeof capturedTheme.setMode, "function");
  assert.equal(typeof capturedTheme.retryModeSave, "function");
});

test("StudioThemeProvider deterministic palette override bypasses preference and applies tokens", async () => {
  const { StudioThemeProvider, useStudioTheme } = await loadThemeContext();
  for (const palette of ["wood", "glass", "paper"] as const) {
    let capturedTheme: StudioThemeContextValue | undefined;
    function Probe() {
      capturedTheme = useStudioTheme();
      return createElement("span", null, capturedTheme.palette);
    }

    renderToStaticMarkup(
      createElement(
        StudioThemeProvider,
        { palette, mode: "light" },
        createElement(Probe),
      ),
    );

    assert.ok(capturedTheme);
    assert.equal(capturedTheme.palette, palette);
    assert.equal(
      capturedTheme.colors.background,
      THEME_PALETTES[palette].light.colors.background,
    );
    assert.equal(
      capturedTheme.colors.primary,
      THEME_PALETTES[palette].light.colors.primary,
    );
  }
});

test("StudioThemeProvider with preferenceEnabled=false uses Studio without storage read", async () => {
  const { StudioThemeProvider, useStudioTheme } = await loadThemeContext();
  let readCalls = 0;
  const storage: AppearanceStorage = {
    getItem: async () => {
      readCalls += 1;
      return "wood";
    },
    setItem: async () => undefined,
  };

  let capturedTheme: StudioThemeContextValue | undefined;
  function Probe() {
    capturedTheme = useStudioTheme();
    return createElement("span", null, capturedTheme.palette);
  }

  renderToStaticMarkup(
    createElement(
      StudioThemeProvider,
      { preferenceEnabled: false, storage },
      createElement(Probe),
    ),
  );

  await tick();
  assert.ok(capturedTheme);
  assert.equal(capturedTheme.palette, "studio");
  assert.equal(capturedTheme.mode, "light");
  assert.equal(readCalls, 0);
});
