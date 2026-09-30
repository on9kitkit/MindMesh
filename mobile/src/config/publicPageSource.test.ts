import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const mobileDirectory = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../..",
);

function source(relativePath: string): string {
  return readFileSync(join(mobileDirectory, relativePath), "utf8");
}

test("canonical source contains the approved factual publication contract", () => {
  const page = source("../docs/public-pages/studyroom-policy-support.html");
  const normalizedPage = page.replace(/\s+/g, " ");

  for (const statement of [
    "studyroom.support@proton.me",
    "StudyRoom project owner",
    "within 3 working days",
    "Public HTTPS publication is pending",
    "Account &amp; settings",
    "external deletion-request entry",
    "does <strong>not</strong> cancel an Apple or Google subscription",
    "retention and purge automation are not yet configured",
    "local emergency services",
    "application code does not currently collect or store",
    "does not persist an entered password",
    "usage-telemetry analytics",
    "their own still-retained finished adaptive GCSE sessions",
    "accuracy on graded answers",
    "not a guarantee of zero provider retention",
  ]) {
    assert.ok(
      normalizedPage.includes(statement),
      `missing canonical statement: ${statement}`,
    );
  }
});

test("canonical source does not claim a production URL", () => {
  const page = source("../docs/public-pages/studyroom-policy-support.html");
  assert.doesNotMatch(page, /https?:\/\//i);
  assert.doesNotMatch(page, /href="https?:/i);
});

test("in-app mirrors preserve the canonical deletion and subscription boundaries", () => {
  const privacy = source("app/privacy.tsx");
  const support = source("app/support.tsx");
  const account = source("app/account.tsx");
  const environmentExample = source("../mobile/.env.example");

  assert.match(environmentExample, /EXPO_PUBLIC_SUPPORT_EMAIL=studyroom\.support@proton\.me/);
  assert.match(support, /resolveSupportContact\(\)/);
  assert.match(support, /contact\.email/);
  assert.match(privacy, /Current\s+retention periods are not yet automated/);
  assert.match(support, /local emergency services/);
  assert.match(account, /does\s+not\s+cancel the store subscription/);
  for (const route of [privacy, support, account]) {
    assert.doesNotMatch(route, /https?:\/\//i);
  }
});
