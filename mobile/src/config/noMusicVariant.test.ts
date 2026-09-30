import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const mobileRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

test("the rights-safe handoff has no statically required music or playback UI", () => {
  const layout = readFileSync(resolve(mobileRoot, "app/_layout.tsx"), "utf8");
  const appConfig = readFileSync(resolve(mobileRoot, "app.json"), "utf8");
  const packageManifest = readFileSync(resolve(mobileRoot, "package.json"), "utf8");
  const packageLock = readFileSync(resolve(mobileRoot, "package-lock.json"), "utf8");

  assert.doesNotMatch(layout, /RouteMusic|ThemeMusic/);
  assert.doesNotMatch(appConfig, /expo-audio/);
  assert.doesNotMatch(packageManifest, /expo-audio|musicPolicy\.test/);
  assert.doesNotMatch(packageLock, /node_modules\/expo-audio/);
  assert.equal(existsSync(resolve(mobileRoot, "src/music")), false);
  assert.equal(existsSync(resolve(mobileRoot, "assets/music")), false);
});
