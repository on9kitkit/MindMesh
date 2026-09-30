import assert from "node:assert/strict";
import test from "node:test";

import { resolveSupportContact, supportMailto } from "./support";

test("support contact accepts a configured email without inventing a default", () => {
  const contact = resolveSupportContact(" help@example.test ");
  assert.deepEqual(contact, {
    status: "configured",
    email: "help@example.test",
  });
  assert.equal(supportMailto(contact), "mailto:help@example.test");
});

test("the approved public support contact is a valid build configuration", () => {
  const contact = resolveSupportContact("studyroom.support@proton.me");
  assert.deepEqual(contact, {
    status: "configured",
    email: "studyroom.support@proton.me",
  });
  assert.equal(supportMailto(contact), "mailto:studyroom.support@proton.me");
});

test("missing and malformed support contacts fail safely", () => {
  assert.deepEqual(resolveSupportContact(undefined), { status: "unavailable" });
  assert.deepEqual(resolveSupportContact("not-an-email"), {
    status: "unavailable",
  });
  assert.equal(supportMailto({ status: "unavailable" }), null);
});
