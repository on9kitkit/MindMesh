import assert from "node:assert/strict";
import test from "node:test";

import {
  ADAPTIVE_SUBJECTS,
  clampTotalMarks,
  createPreparationRequestId,
  DEFAULT_TOTAL_MARKS,
  formatEarnedMarks,
  getAdaptiveSelectionValidationMessage,
  getSubjectLabel,
  getTopicLabel,
  getTotalMarksValidationMessage,
  isAdaptiveSelectionValid,
  isAdaptiveSubject,
  isAdaptiveTopic,
  isTopicForSubject,
  isUuidV4,
  MAX_TOTAL_MARKS,
  MIN_TOTAL_MARKS,
  openDurationSecondsForMarks,
  revealDurationSecondsForMarks,
} from "./adaptiveQuiz";

test("catalogue contains six subjects with three snake_case topics each", () => {
  assert.equal(ADAPTIVE_SUBJECTS.length, 6);
  const subjectIds = ADAPTIVE_SUBJECTS.map((subject) => subject.id);
  assert.deepEqual(subjectIds, [
    "physics",
    "mathematics",
    "biology",
    "chemistry",
    "english_language",
    "english_literature",
  ]);
  for (const subject of ADAPTIVE_SUBJECTS) {
    assert.equal(subject.topics.length, 3);
    for (const topic of subject.topics) {
      assert.match(topic.id, /^[a-z]+(_[a-z]+)*$/);
      assert.ok(!topic.id.includes(" "));
    }
  }
  assert.equal(ADAPTIVE_SUBJECTS.flatMap((s) => s.topics).length, 18);
});

test("catalogue rejects space-separated legacy identifiers", () => {
  assert.equal(isAdaptiveSubject("english language"), false);
  assert.equal(isAdaptiveTopic("atomic structure"), false);
  assert.equal(isAdaptiveTopic("chemical reactions"), false);
  assert.equal(isAdaptiveTopic("reading comprehension"), false);
  assert.equal(isTopicForSubject("chemistry", "atomic structure"), false);
});

test("catalogue accepts the locked snake_case identifiers", () => {
  assert.equal(isTopicForSubject("physics", "energy"), true);
  assert.equal(isTopicForSubject("physics", "electricity"), true);
  assert.equal(isTopicForSubject("physics", "forces"), true);
  assert.equal(isTopicForSubject("mathematics", "number"), true);
  assert.equal(isTopicForSubject("mathematics", "algebra"), true);
  assert.equal(isTopicForSubject("mathematics", "geometry"), true);
  assert.equal(isTopicForSubject("biology", "cells"), true);
  assert.equal(isTopicForSubject("biology", "organisation"), true);
  assert.equal(isTopicForSubject("biology", "ecology"), true);
  assert.equal(isTopicForSubject("chemistry", "atomic_structure"), true);
  assert.equal(isTopicForSubject("chemistry", "bonding"), true);
  assert.equal(isTopicForSubject("chemistry", "chemical_reactions"), true);
  assert.equal(
    isTopicForSubject("english_language", "reading_comprehension"),
    true,
  );
  assert.equal(isTopicForSubject("english_language", "language_analysis"), true);
  assert.equal(
    isTopicForSubject("english_language", "writing_techniques"),
    true,
  );
  assert.equal(
    isTopicForSubject("english_literature", "literary_devices"),
    true,
  );
  assert.equal(
    isTopicForSubject("english_literature", "character_and_theme"),
    true,
  );
  assert.equal(isTopicForSubject("english_literature", "poetry_analysis"), true);
  assert.equal(isTopicForSubject("physics", "algebra"), false);
});

test("friendly labels render separately from identifiers", () => {
  assert.equal(getSubjectLabel("english_language"), "English Language");
  assert.equal(getSubjectLabel("english_literature"), "English Literature");
  assert.equal(getTopicLabel("atomic_structure"), "Atomic structure");
  assert.equal(getTopicLabel("character_and_theme"), "Character and theme");
  assert.equal(getTopicLabel("reading_comprehension"), "Reading comprehension");
  assert.equal(getSubjectLabel("unknown"), null);
  assert.equal(getTopicLabel("unknown"), null);
});

test("total mark budget validates the 5–40 range with default 20", () => {
  assert.equal(MIN_TOTAL_MARKS, 5);
  assert.equal(MAX_TOTAL_MARKS, 40);
  assert.equal(DEFAULT_TOTAL_MARKS, 20);
  assert.equal(getTotalMarksValidationMessage(20), null);
  assert.equal(getTotalMarksValidationMessage(5), null);
  assert.equal(getTotalMarksValidationMessage(40), null);
  assert.ok(getTotalMarksValidationMessage(4) !== null);
  assert.ok(getTotalMarksValidationMessage(41) !== null);
  assert.ok(getTotalMarksValidationMessage(20.5) !== null);
  assert.equal(clampTotalMarks(4), 5);
  assert.equal(clampTotalMarks(41), 40);
  assert.equal(clampTotalMarks(20.9), 20);
});

test("adaptive selection validation requires a matching topic and budget", () => {
  assert.equal(
    getAdaptiveSelectionValidationMessage({
      subject: "physics",
      topic: "energy",
      totalMarks: 20,
    }),
    null,
  );
  assert.equal(
    isAdaptiveSelectionValid({
      subject: "physics",
      topic: "energy",
      totalMarks: 20,
    }),
    true,
  );
  assert.ok(
    getAdaptiveSelectionValidationMessage({
      subject: "physics",
      topic: "algebra",
      totalMarks: 20,
    }) !== null,
  );
  assert.ok(
    getAdaptiveSelectionValidationMessage({
      subject: "physics",
      topic: "energy",
      totalMarks: 4,
    }) !== null,
  );
});

test("mark display never infers a mark", () => {
  assert.equal(formatEarnedMarks(3, 4), "3/4 marks");
  assert.equal(formatEarnedMarks(0, 1), "0/1 marks");
  assert.equal(formatEarnedMarks(null, 4), "0/4 marks pending");
});

test("adaptive timing helpers follow the locked policy", () => {
  assert.equal(openDurationSecondsForMarks(1), 30);
  assert.equal(openDurationSecondsForMarks(6), 180);
  assert.equal(revealDurationSecondsForMarks(1), 20);
  assert.equal(revealDurationSecondsForMarks(6), 45);
});

test("preparation request IDs are UUID v4 idempotency keys", () => {
  let seed = 0.123456789;
  const deterministic = () => {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };
  const first = createPreparationRequestId(deterministic);
  const second = createPreparationRequestId(deterministic);
  assert.equal(isUuidV4(first), true);
  assert.equal(isUuidV4(second), true);
  assert.notEqual(first, second);
});
