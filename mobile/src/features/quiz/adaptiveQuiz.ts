export const ADAPTIVE_EDUCATION_LEVEL = "GCSE" as const;
export const ADAPTIVE_QUIZ_MODE = "ADAPTIVE" as const;
export const LEGACY_QUIZ_MODE = "LEGACY_PHYSICS" as const;

export const MIN_TOTAL_MARKS = 5 as const;
export const MAX_TOTAL_MARKS = 40 as const;
export const DEFAULT_TOTAL_MARKS = 20 as const;

export const MIN_QUESTION_MARKS = 1 as const;
export const MAX_QUESTION_MARKS = 6 as const;
export const MAX_WRITTEN_ANSWER_LENGTH = 1000 as const;
export const MAX_NUMERICAL_ANSWER_LENGTH = 64 as const;

export type AdaptiveSubject =
  | "physics"
  | "mathematics"
  | "biology"
  | "chemistry"
  | "english_language"
  | "english_literature";

export type AdaptiveTopic =
  | "energy"
  | "electricity"
  | "forces"
  | "number"
  | "algebra"
  | "geometry"
  | "cells"
  | "organisation"
  | "ecology"
  | "atomic_structure"
  | "bonding"
  | "chemical_reactions"
  | "reading_comprehension"
  | "language_analysis"
  | "writing_techniques"
  | "literary_devices"
  | "character_and_theme"
  | "poetry_analysis";

export type AdaptiveSubjectInfo = {
  id: AdaptiveSubject;
  label: string;
  topics: ReadonlyArray<{ id: AdaptiveTopic; label: string }>;
};

export const ADAPTIVE_SUBJECTS: ReadonlyArray<AdaptiveSubjectInfo> = [
  {
    id: "physics",
    label: "Physics",
    topics: [
      { id: "energy", label: "Energy" },
      { id: "electricity", label: "Electricity" },
      { id: "forces", label: "Forces" },
    ],
  },
  {
    id: "mathematics",
    label: "Mathematics",
    topics: [
      { id: "number", label: "Number" },
      { id: "algebra", label: "Algebra" },
      { id: "geometry", label: "Geometry" },
    ],
  },
  {
    id: "biology",
    label: "Biology",
    topics: [
      { id: "cells", label: "Cells" },
      { id: "organisation", label: "Organisation" },
      { id: "ecology", label: "Ecology" },
    ],
  },
  {
    id: "chemistry",
    label: "Chemistry",
    topics: [
      { id: "atomic_structure", label: "Atomic structure" },
      { id: "bonding", label: "Bonding" },
      { id: "chemical_reactions", label: "Chemical reactions" },
    ],
  },
  {
    id: "english_language",
    label: "English Language",
    topics: [
      { id: "reading_comprehension", label: "Reading comprehension" },
      { id: "language_analysis", label: "Language analysis" },
      { id: "writing_techniques", label: "Writing techniques" },
    ],
  },
  {
    id: "english_literature",
    label: "English Literature",
    topics: [
      { id: "literary_devices", label: "Literary devices" },
      { id: "character_and_theme", label: "Character and theme" },
      { id: "poetry_analysis", label: "Poetry analysis" },
    ],
  },
];

const TOPIC_TO_SUBJECT = new Map<AdaptiveTopic, AdaptiveSubject>();
for (const subject of ADAPTIVE_SUBJECTS) {
  for (const topic of subject.topics) {
    TOPIC_TO_SUBJECT.set(topic.id, subject.id);
  }
}

export function isAdaptiveSubject(value: string): value is AdaptiveSubject {
  return ADAPTIVE_SUBJECTS.some((subject) => subject.id === value);
}

export function isAdaptiveTopic(value: string): value is AdaptiveTopic {
  return TOPIC_TO_SUBJECT.has(value as AdaptiveTopic);
}

export function isTopicForSubject(
  subject: string,
  topic: string,
): boolean {
  if (!isAdaptiveSubject(subject) || !isAdaptiveTopic(topic)) {
    return false;
  }
  return TOPIC_TO_SUBJECT.get(topic) === subject;
}

export function getSubjectLabel(subject: string): string | null {
  return (
    ADAPTIVE_SUBJECTS.find((entry) => entry.id === subject)?.label ?? null
  );
}

export function getTopicLabel(topic: string): string | null {
  for (const subject of ADAPTIVE_SUBJECTS) {
    const match = subject.topics.find((entry) => entry.id === topic);
    if (match !== undefined) {
      return match.label;
    }
  }
  return null;
}

export function isValidTotalMarks(value: number): boolean {
  return (
    Number.isSafeInteger(value) &&
    value >= MIN_TOTAL_MARKS &&
    value <= MAX_TOTAL_MARKS
  );
}

export function clampTotalMarks(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_TOTAL_MARKS;
  }
  const floored = Math.floor(value);
  if (floored < MIN_TOTAL_MARKS) {
    return MIN_TOTAL_MARKS;
  }
  if (floored > MAX_TOTAL_MARKS) {
    return MAX_TOTAL_MARKS;
  }
  return floored;
}

export function getTotalMarksValidationMessage(value: number): string | null {
  if (!Number.isSafeInteger(value)) {
    return `Total marks must be a whole number between ${MIN_TOTAL_MARKS} and ${MAX_TOTAL_MARKS}.`;
  }
  if (value < MIN_TOTAL_MARKS || value > MAX_TOTAL_MARKS) {
    return `Total marks must be between ${MIN_TOTAL_MARKS} and ${MAX_TOTAL_MARKS}.`;
  }
  return null;
}

export type AdaptiveQuizSelection = {
  subject: AdaptiveSubject;
  topic: AdaptiveTopic;
  totalMarks: number;
};

export function getAdaptiveSelectionValidationMessage(
  selection: AdaptiveQuizSelection,
): string | null {
  if (!isTopicForSubject(selection.subject, selection.topic)) {
    return "Choose a valid topic for the selected subject.";
  }
  return getTotalMarksValidationMessage(selection.totalMarks);
}

export function isAdaptiveSelectionValid(
  selection: AdaptiveQuizSelection,
): boolean {
  return getAdaptiveSelectionValidationMessage(selection) === null;
}

/**
 * Totally ordered mark display derived from server-confirmed values only.
 * This helper never infers, estimates, or rounds a mark.
 */
export function formatEarnedMarks(
  earnedMarks: number | null,
  maxMarks: number,
): string {
  if (earnedMarks === null) {
    return `0/${maxMarks} marks pending`;
  }
  return `${earnedMarks}/${maxMarks} marks`;
}

export function openDurationSecondsForMarks(maxMarks: number): number {
  const bounded = Math.min(
    MAX_QUESTION_MARKS,
    Math.max(MIN_QUESTION_MARKS, Math.floor(maxMarks)),
  );
  return 30 * bounded;
}

export function revealDurationSecondsForMarks(maxMarks: number): number {
  const bounded = Math.min(
    MAX_QUESTION_MARKS,
    Math.max(MIN_QUESTION_MARKS, Math.floor(maxMarks)),
  );
  return 15 + 5 * bounded;
}

const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export function isUuidV4(value: string): boolean {
  return UUID_V4_PATTERN.test(value);
}

/**
 * Generate one idempotency key for an explicit host preparation request.
 * The server treats retries with the same request ID as the same request.
 */
export function createPreparationRequestId(
  random: () => number = Math.random,
): string {
  const bytes = Array.from({ length: 16 }, () =>
    Math.floor(random() * 256),
  );
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.map((byte) => byte.toString(16).padStart(2, "0"));
  return (
    `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-` +
    `${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-` +
    `${hex.slice(10, 16).join("")}`
  );
}

export type AdaptiveQuestionType =
  | "MULTIPLE_CHOICE"
  | "NUMERICAL"
  | "WRITTEN";

export function isAdaptiveQuestionType(
  value: string,
): value is AdaptiveQuestionType {
  return (
    value === "MULTIPLE_CHOICE" ||
    value === "NUMERICAL" ||
    value === "WRITTEN"
  );
}

export type GradingStatus =
  | "PENDING"
  | "IN_PROGRESS"
  | "GRADED"
  | "RETRYABLE"
  | "UNAVAILABLE";

export function isGradingStatus(value: string): value is GradingStatus {
  return (
    value === "PENDING" ||
    value === "IN_PROGRESS" ||
    value === "GRADED" ||
    value === "RETRYABLE" ||
    value === "UNAVAILABLE"
  );
}

export function getGradingStatusLabel(status: GradingStatus): string {
  switch (status) {
    case "GRADED":
      return "Marked";
    case "PENDING":
    case "IN_PROGRESS":
      return "Marking in progress";
    case "RETRYABLE":
      return "Marking delayed — retrying automatically";
    case "UNAVAILABLE":
      return "Marking unavailable";
  }
}
