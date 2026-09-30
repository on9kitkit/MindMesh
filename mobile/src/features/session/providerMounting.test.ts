import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const appDirectory = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../app",
);
const rootLayoutSource = readFileSync(
  join(appDirectory, "_layout.tsx"),
  "utf8",
);

function occurrenceCount(source: string, value: string): number {
  return source.split(value).length - 1;
}

test("root mounts RevenueCat inside Auth and Session inside RevenueCat", () => {
  assert.equal(occurrenceCount(rootLayoutSource, "<RevenueCatProvider>"), 1);
  assert.equal(occurrenceCount(rootLayoutSource, "<SessionProvider>"), 1);
  assert.match(
    rootLayoutSource,
    /<AuthProvider>[\s\S]*<RevenueCatProvider>[\s\S]*<SessionProvider>[\s\S]*<SessionRouteCoordinator \/>[\s\S]*<Stack/,
  );
});

test("RevenueCatProvider keeps one controller across provider rerenders", () => {
  const revenueCatProviderSource = readFileSync(
    resolve(appDirectory, "../src/revenuecat/RevenueCatContext.tsx"),
    "utf8",
  );
  assert.match(
    revenueCatProviderSource,
    /const controllerRef = useRef<RevenueCatController \| null>\(null\)/,
  );
  assert.match(
    revenueCatProviderSource,
    /if \(controllerRef\.current === null\)[\s\S]*createProductionController\(\)/,
  );
  assert.match(
    revenueCatProviderSource,
    /useEffect\(\(\) => \{[\s\S]*controller\.initialize\(\)[\s\S]*\}, \[controller\]\)/,
  );
});

test("SessionProvider keeps one controller across route and provider rerenders", () => {
  const sessionProviderSource = readFileSync(
    resolve(appDirectory, "../src/features/session/SessionContext.tsx"),
    "utf8",
  );
  assert.match(
    sessionProviderSource,
    /const controllerRef = useRef<SessionController \| null>\(null\)/,
  );
  assert.match(
    sessionProviderSource,
    /if \(controllerRef\.current === null\)[\s\S]*createProductionSessionController\(\)/,
  );
  assert.equal(
    occurrenceCount(sessionProviderSource, "createProductionSessionController()"),
    2,
  );
});

test("one route coordinator is mounted and legacy quiz authority is absent", () => {
  assert.equal(occurrenceCount(rootLayoutSource, "<SessionRouteCoordinator />"), 1);
  assert.equal(rootLayoutSource.includes("QuizFlowProvider"), false);
});

test("no individual route mounts another SessionProvider", () => {
  const routeFiles = readdirSync(appDirectory).filter(
    (name) => name.endsWith(".tsx") && name !== "_layout.tsx",
  );
  for (const routeFile of routeFiles) {
    const source = readFileSync(join(appDirectory, routeFile), "utf8");
    assert.equal(
      source.includes("<SessionProvider>"),
      false,
      `${routeFile} must use the single root provider`,
    );
    assert.equal(
      source.includes("<RevenueCatProvider>"),
      false,
      `${routeFile} must use the single root RevenueCat provider`,
    );
  }
});
