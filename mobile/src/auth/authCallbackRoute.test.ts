import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  authCallbackUrlFromRouteParams,
  processAuthCallbackRoute,
} from "./authCallbackRoute";

const mobileDirectory = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../..",
);

test("callback route converts Expo params into the stable native callback URL", () => {
  assert.equal(
    authCallbackUrlFromRouteParams({
      code: "authorization-code",
      type: "signup",
    }),
    "studyroom-preview://auth/callback?code=authorization-code",
  );
});

test("callback route delegates to the centralized callback processor", async () => {
  let receivedUrl: string | undefined;

  await processAuthCallbackRoute({ code: "authorization-code" }, async (url) => {
    receivedUrl = url;
  });

  assert.equal(
    receivedUrl,
    "studyroom-preview://auth/callback?code=authorization-code",
  );
});

test("callback route source does not implement a second exchange path", () => {
  const routeSource = readFileSync(
    join(mobileDirectory, "app/auth/callback.tsx"),
    "utf8",
  );

  assert.match(routeSource, /processAuthCallbackRoute\(params, processAuthCallback\)/);
  assert.equal(routeSource.includes("exchangeCodeForSession"), false);
});
