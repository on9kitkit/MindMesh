import assert from "node:assert/strict";
import test from "node:test";

import { validateDisplayName } from "./displayNamePolicy";

test("display names normalize NFKC and whitespace", () => {
  assert.deepEqual(validateDisplayName("  Ｓtudent\u00a0  "), {
    valid: true,
    value: "Student",
  });
  assert.equal(validateDisplayName("Ångström 学生").valid, true);
});

test("display names reject reserved, dangerous, and bounded names", () => {
  for (const value of [
    "StudyRoom",
    "Official Tutor",
    "official_staff",
    "Student\u200bName",
    "a".repeat(41),
  ]) {
    assert.equal(validateDisplayName(value).valid, false);
  }
});

test("prohibited matching does not reject ordinary containing words", () => {
  assert.equal(validateDisplayName("Officially Curious").valid, true);
  assert.equal(validateDisplayName("Stafford Student").valid, true);
});
