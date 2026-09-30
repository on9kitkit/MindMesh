import assert from "node:assert/strict";
import test from "node:test";

import {
  APPEARANCE_LOAD_ERROR,
  APPEARANCE_SAVE_ERROR,
  APPEARANCE_STORAGE_KEY,
  AppearancePreferenceController,
  type AppearanceStorage,
  parseStoredThemeMode,
} from "./appearancePreference";

function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

test("appearance storage accepts only the isolated theme enum", () => {
  assert.equal(APPEARANCE_STORAGE_KEY, "studyroom.appearance.mode.v1");
  assert.equal(parseStoredThemeMode("dark"), "dark");
  assert.equal(parseStoredThemeMode("system"), "system");
  assert.equal(parseStoredThemeMode("unknown"), "light");
  assert.equal(parseStoredThemeMode(null), "light");
});

test("stored preference hydrates after a Light first paint", async () => {
  const storage: AppearanceStorage = {
    getItem: async () => "dark",
    setItem: async () => undefined,
  };
  const controller = new AppearancePreferenceController(storage);

  assert.deepEqual(controller.getSnapshot(), {
    mode: "light",
    hydrated: false,
    error: undefined,
  });
  await controller.hydrate();
  assert.deepEqual(controller.getSnapshot(), {
    mode: "dark",
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
  const controller = new AppearancePreferenceController(storage);
  const hydration = controller.hydrate();
  controller.select("dark");
  resolveRead?.("light");
  await hydration;
  await tick();

  assert.equal(controller.getSnapshot().mode, "dark");
  assert.deepEqual(writes, ["dark"]);
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
  const controller = new AppearancePreferenceController(storage);
  const hydration = controller.hydrate();
  controller.select("dark");
  await tick();
  assert.equal(controller.getSnapshot().error, APPEARANCE_SAVE_ERROR);

  resolveRead?.("light");
  await hydration;
  assert.equal(controller.getSnapshot().mode, "dark");
  assert.equal(controller.getSnapshot().error, APPEARANCE_SAVE_ERROR);
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
  const controller = new AppearancePreferenceController(storage);
  const hydration = controller.hydrate();
  controller.select("dark");
  await tick();
  assert.equal(controller.getSnapshot().error, undefined);

  rejectRead?.(new Error("synthetic read failure"));
  await hydration;
  assert.equal(controller.getSnapshot().mode, "dark");
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
  const controller = new AppearancePreferenceController(storage);
  const initial = controller.hydrate();
  reads[0].reject(new Error("initial read failure"));
  await initial;
  assert.equal(controller.getSnapshot().error, APPEARANCE_LOAD_ERROR);

  controller.retry();
  controller.retry();
  assert.equal(reads.length, 2);
  reads[1].reject(new Error("retry read failure"));
  await tick();
  assert.equal(controller.getSnapshot().error, APPEARANCE_LOAD_ERROR);

  controller.retry();
  assert.equal(reads.length, 3);
  reads[2].resolve("system");
  await tick();
  assert.equal(controller.getSnapshot().mode, "system");
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
    const controller = new AppearancePreferenceController(storage);
    const initial = controller.hydrate();
    reads[0].reject(new Error("initial read failure"));
    await initial;
    assert.equal(controller.getSnapshot().error, APPEARANCE_LOAD_ERROR);

    controller.retry();
    assert.equal(reads.length, 2);
    controller.select("dark");
    await tick();
    assert.equal(writes, 1);
    assert.equal(controller.getSnapshot().mode, "dark");
    assert.equal(controller.getSnapshot().error, APPEARANCE_SAVE_ERROR);

    if (outcome === "resolve") {
      reads[1].resolve("light");
    } else {
      reads[1].reject(new Error("late retry read failure"));
    }
    await tick();
    assert.equal(controller.getSnapshot().mode, "dark");
    assert.equal(controller.getSnapshot().error, APPEARANCE_SAVE_ERROR);
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
      if (value === "dark") {
        await firstWrite;
      }
    },
  };
  const controller = new AppearancePreferenceController(storage);
  controller.select("dark");
  controller.select("system");
  await tick();
  assert.deepEqual(writes, ["dark"]);

  releaseFirst?.();
  await tick();
  await tick();
  assert.deepEqual(writes, ["dark", "system"]);
  assert.equal(controller.getSnapshot().mode, "system");
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
  const controller = new AppearancePreferenceController(storage);
  controller.select("dark");
  await tick();
  assert.equal(controller.getSnapshot().mode, "dark");
  assert.equal(controller.getSnapshot().error, APPEARANCE_SAVE_ERROR);

  fail = false;
  controller.retry();
  await tick();
  assert.equal(controller.getSnapshot().mode, "dark");
  assert.equal(controller.getSnapshot().error, undefined);
  assert.deepEqual(writes, ["dark", "dark"]);
});

test("read failure is recoverable without replacing the Light default", async () => {
  let fail = true;
  const storage: AppearanceStorage = {
    getItem: async () => {
      if (fail) {
        throw new Error("synthetic read failure");
      }
      return "system";
    },
    setItem: async () => undefined,
  };
  const controller = new AppearancePreferenceController(storage);
  await controller.hydrate();
  assert.equal(controller.getSnapshot().mode, "light");
  assert.equal(controller.getSnapshot().error, APPEARANCE_LOAD_ERROR);

  fail = false;
  controller.retry();
  await tick();
  assert.equal(controller.getSnapshot().mode, "system");
  assert.equal(controller.getSnapshot().error, undefined);
});
