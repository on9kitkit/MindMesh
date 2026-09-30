import { apiClient, type StudyRoomApiClient } from "./client";
import { MalformedResponseError } from "./errors";
import {
  isTopicForSubject,
  type AdaptiveSubject,
  type AdaptiveTopic,
} from "../features/quiz/adaptiveQuiz";

export type LearningEvidenceStatus =
  | "no_data"
  | "insufficient_evidence"
  | "observed";

export type LearningTopicKey = {
  subject: AdaptiveSubject;
  topic: AdaptiveTopic;
};

export type LearningTopicSummary = LearningTopicKey & {
  evidence_status: LearningEvidenceStatus;
  finished_session_count: number;
  presented_question_count: number;
  answered_attempt_count: number;
  graded_attempt_count: number;
  ungraded_attempt_count: number;
  unanswered_question_count: number;
  distinct_question_count: number;
  repeat_attempt_count: number;
  earned_marks: number;
  possible_marks: number;
  accuracy_on_graded_answers_percent: number | null;
  full_credit_attempt_count: number;
  partial_credit_attempt_count: number;
  zero_credit_attempt_count: number;
};

export type LearningSummaryResponse = {
  status: LearningEvidenceStatus;
  session_window: {
    limit: 100;
    included: number;
    truncated: boolean;
  };
  topics: LearningTopicSummary[];
  strongest_topics: LearningTopicKey[];
  weakest_topics: LearningTopicKey[];
};

const SUMMARY_KEYS = [
  "status",
  "session_window",
  "topics",
  "strongest_topics",
  "weakest_topics",
] as const;
const WINDOW_KEYS = ["limit", "included", "truncated"] as const;
const TOPIC_KEY_FIELDS = ["subject", "topic"] as const;
const TOPIC_KEYS = [
  ...TOPIC_KEY_FIELDS,
  "evidence_status",
  "finished_session_count",
  "presented_question_count",
  "answered_attempt_count",
  "graded_attempt_count",
  "ungraded_attempt_count",
  "unanswered_question_count",
  "distinct_question_count",
  "repeat_attempt_count",
  "earned_marks",
  "possible_marks",
  "accuracy_on_graded_answers_percent",
  "full_credit_attempt_count",
  "partial_credit_attempt_count",
  "zero_credit_attempt_count",
] as const;
const COUNT_FIELDS = [
  "finished_session_count",
  "presented_question_count",
  "answered_attempt_count",
  "graded_attempt_count",
  "ungraded_attempt_count",
  "unanswered_question_count",
  "distinct_question_count",
  "repeat_attempt_count",
  "earned_marks",
  "possible_marks",
  "full_credit_attempt_count",
  "partial_credit_attempt_count",
  "zero_credit_attempt_count",
] as const;

function malformed(): never {
  throw new MalformedResponseError(
    "The StudyRoom server returned an invalid learning summary response.",
  );
}

function exactObject(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return malformed();
  }
  const record = value as Record<string, unknown>;
  const actualKeys = Object.keys(record);
  if (
    actualKeys.length !== keys.length ||
    actualKeys.some((key) => !keys.includes(key)) ||
    keys.some((key) => !Object.prototype.hasOwnProperty.call(record, key))
  ) {
    return malformed();
  }
  return record;
}

function count(value: unknown, max: number): number {
  if (!Number.isSafeInteger(value) || typeof value !== "number" || value < 0 || value > max) {
    return malformed();
  }
  return value;
}

function evidenceStatus(value: unknown): LearningEvidenceStatus {
  if (
    value !== "no_data" &&
    value !== "insufficient_evidence" &&
    value !== "observed"
  ) {
    return malformed();
  }
  return value;
}

function topicKey(value: unknown): LearningTopicKey {
  const record = exactObject(value, TOPIC_KEY_FIELDS);
  if (
    typeof record.subject !== "string" ||
    typeof record.topic !== "string" ||
    !isTopicForSubject(record.subject, record.topic)
  ) {
    return malformed();
  }
  return {
    subject: record.subject as AdaptiveSubject,
    topic: record.topic as AdaptiveTopic,
  };
}

function topicSummary(value: unknown, included: number): LearningTopicSummary {
  const record = exactObject(value, TOPIC_KEYS);
  const key = topicKey({ subject: record.subject, topic: record.topic });
  const counts: Record<(typeof COUNT_FIELDS)[number], number> = {
    finished_session_count: 0,
    presented_question_count: 0,
    answered_attempt_count: 0,
    graded_attempt_count: 0,
    ungraded_attempt_count: 0,
    unanswered_question_count: 0,
    distinct_question_count: 0,
    repeat_attempt_count: 0,
    earned_marks: 0,
    possible_marks: 0,
    full_credit_attempt_count: 0,
    partial_credit_attempt_count: 0,
    zero_credit_attempt_count: 0,
  };
  for (const field of COUNT_FIELDS) {
    counts[field] = count(
      record[field],
      field === "earned_marks" || field === "possible_marks" ? 24_000 : 4_000,
    );
  }
  if (
    counts.finished_session_count > included ||
    counts.answered_attempt_count !==
      counts.graded_attempt_count + counts.ungraded_attempt_count ||
    counts.presented_question_count !==
      counts.answered_attempt_count + counts.unanswered_question_count ||
    counts.graded_attempt_count !==
      counts.full_credit_attempt_count +
        counts.partial_credit_attempt_count +
        counts.zero_credit_attempt_count ||
    counts.repeat_attempt_count !==
      counts.graded_attempt_count - counts.distinct_question_count ||
    (counts.presented_question_count > 0 && counts.finished_session_count === 0) ||
    counts.presented_question_count > counts.finished_session_count * 40 ||
    counts.possible_marks < counts.graded_attempt_count ||
    counts.possible_marks > counts.graded_attempt_count * 6 ||
    counts.earned_marks > counts.possible_marks ||
    (counts.graded_attempt_count === 0) !== (counts.possible_marks === 0)
  ) {
    return malformed();
  }

  const accuracy = record.accuracy_on_graded_answers_percent;
  if (counts.possible_marks === 0) {
    if (accuracy !== null) return malformed();
  } else if (
    typeof accuracy !== "number" ||
    !Number.isFinite(accuracy) ||
    accuracy < 0 ||
    accuracy > 100 ||
    Math.abs(accuracy * 10 - Math.round(accuracy * 10)) > 1e-8 ||
    Math.abs(accuracy - (counts.earned_marks / counts.possible_marks) * 100) > 0.051
  ) {
    return malformed();
  }
  const status = evidenceStatus(record.evidence_status);
  if (
    (status === "no_data") !== (counts.graded_attempt_count === 0) ||
    (status === "observed" &&
      (counts.distinct_question_count < 5 || counts.finished_session_count < 2)) ||
    (status === "insufficient_evidence" &&
      counts.distinct_question_count >= 5 && counts.finished_session_count >= 2)
  ) {
    return malformed();
  }
  return {
    ...key,
    evidence_status: status,
    ...counts,
    accuracy_on_graded_answers_percent: accuracy as number | null,
  };
}

function parseKeys(value: unknown, rows: LearningTopicSummary[]): LearningTopicKey[] {
  if (!Array.isArray(value) || value.length > 18) return malformed();
  const existing = new Set(
    rows.filter((row) => row.evidence_status === "observed").map(
      (row) => `${row.subject}/${row.topic}`,
    ),
  );
  const parsed = value.map(topicKey);
  const seen = new Set<string>();
  for (const key of parsed) {
    const joined = `${key.subject}/${key.topic}`;
    if (!existing.has(joined) || seen.has(joined)) return malformed();
    seen.add(joined);
  }
  return parsed;
}

function validateComparisons(
  topics: LearningTopicSummary[],
  strongest: LearningTopicKey[],
  weakest: LearningTopicKey[],
): void {
  const expectedStrong = new Set<string>();
  const expectedWeak = new Set<string>();
  const subjects = new Set(topics.map((topic) => topic.subject));
  for (const subject of subjects) {
    const rows = topics.filter(
      (topic) => topic.subject === subject && topic.evidence_status === "observed",
    );
    if (rows.length < 2) continue;
    for (const row of rows) {
      if (
        rows.every(
          (other) =>
            row.earned_marks * other.possible_marks >=
            other.earned_marks * row.possible_marks,
        )
      ) {
        expectedStrong.add(`${row.subject}/${row.topic}`);
      }
      if (
        rows.every(
          (other) =>
            row.earned_marks * other.possible_marks <=
            other.earned_marks * row.possible_marks,
        )
      ) {
        expectedWeak.add(`${row.subject}/${row.topic}`);
      }
    }
  }
  const actualStrong = new Set(strongest.map((key) => `${key.subject}/${key.topic}`));
  const actualWeak = new Set(weakest.map((key) => `${key.subject}/${key.topic}`));
  if (
    actualStrong.size !== expectedStrong.size ||
    actualWeak.size !== expectedWeak.size ||
    [...expectedStrong].some((key) => !actualStrong.has(key)) ||
    [...expectedWeak].some((key) => !actualWeak.has(key))
  ) {
    malformed();
  }
}

/** Strict viewer-only parser; it never passes unknown server fields to the UI. */
export function parseLearningSummaryResponse(value: unknown): LearningSummaryResponse {
  const record = exactObject(value, SUMMARY_KEYS);
  const window = exactObject(record.session_window, WINDOW_KEYS);
  if (window.limit !== 100 || typeof window.truncated !== "boolean") {
    return malformed();
  }
  const included = count(window.included, 100);
  if (!Array.isArray(record.topics) || record.topics.length > 18) {
    return malformed();
  }
  const topics = record.topics.map((topic) => topicSummary(topic, included));
  const seen = new Set<string>();
  for (const topic of topics) {
    const key = `${topic.subject}/${topic.topic}`;
    if (seen.has(key)) return malformed();
    seen.add(key);
  }
  if (
    topics.reduce((sum, topic) => sum + topic.presented_question_count, 0) > 4_000 ||
    topics.reduce((sum, topic) => sum + topic.finished_session_count, 0) !== included
  ) {
    return malformed();
  }
  const status = evidenceStatus(record.status);
  const gradedCount = topics.reduce((sum, topic) => sum + topic.graded_attempt_count, 0);
  const hasObserved = topics.some((topic) => topic.evidence_status === "observed");
  if (
    (status === "no_data") !== (gradedCount === 0) ||
    (status === "observed") !== hasObserved
  ) {
    return malformed();
  }
  const strongest = parseKeys(record.strongest_topics, topics);
  const weakest = parseKeys(record.weakest_topics, topics);
  validateComparisons(topics, strongest, weakest);
  return {
    status,
    session_window: { limit: 100, included, truncated: window.truncated },
    topics,
    strongest_topics: strongest,
    weakest_topics: weakest,
  };
}

export async function getLearningSummary(
  client: StudyRoomApiClient = apiClient,
): Promise<LearningSummaryResponse> {
  const response = await client.requestJson("/me/learning-summary");
  return parseLearningSummaryResponse(response);
}
