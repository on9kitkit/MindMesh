import {
  awardedMarksTotal,
  InvalidGradingFeedbackError,
  looksLikeEnrichedFeedback,
  parseEnrichedWrittenFeedback,
  type EnrichedWrittenFeedback,
} from "../feedback/gradingFeedback";
import { parseNumericalFeedback } from "../feedback/numericalFeedback";

export const REALTIME_PROTOCOL_VERSION = 2 as const;

declare const canonicalUuidBrand: unique symbol;
declare const zonedIsoTimestampBrand: unique symbol;

export type CanonicalUuid = string & {
  readonly [canonicalUuidBrand]: "CanonicalUuid";
};

export type ZonedIsoTimestamp = string & {
  readonly [zonedIsoTimestampBrand]: "ZonedIsoTimestamp";
};

export type ViewerRole = "host" | "member";
export type SessionStatus =
  | "QUESTION_OPEN"
  | "QUESTION_GRADING"
  | "QUESTION_REVEAL"
  | "FINISHED";

export type QuizMode = "LEGACY_PHYSICS" | "ADAPTIVE";
export type AdaptiveQuestionType =
  | "MULTIPLE_CHOICE"
  | "NUMERICAL"
  | "WRITTEN";
export type GradingStatus =
  | "PENDING"
  | "IN_PROGRESS"
  | "GRADED"
  | "RETRYABLE"
  | "UNAVAILABLE";

export type RoomStateParticipant = {
  user_id: CanonicalUuid;
  display_name: string;
  role: ViewerRole;
  ready: boolean;
  online: boolean;
};

export type QuizPreparationStatus =
  | "GENERATING"
  | "READY"
  | "FAILED"
  | "CONSUMED"
  | "SUPERSEDED";

export type RoomStatePayload = {
  room_id: CanonicalUuid;
  name: string;
  join_code: string;
  maximum_members: number;
  viewer_role: ViewerRole;
  participants: RoomStateParticipant[];
  viewer_ready: boolean;
  quiz_mode: QuizMode;
  education_level: string | null;
  quiz_subject: string | null;
  quiz_topic: string | null;
  target_total_marks: number | null;
  active_preparation_status: QuizPreparationStatus | null;
  active_preparation_version: number | null;
  active_preparation_error_category: string | null;
};

export type QuestionOptionPayload = {
  id: string;
  label: string;
};

export type OpenQuestionPayload = {
  session_question_id: CanonicalUuid;
  prompt: string;
  options: QuestionOptionPayload[];
  question_number: number;
  total_questions: number;
  closes_at: ZonedIsoTimestamp;
  server_time: ZonedIsoTimestamp;
  question_type: AdaptiveQuestionType;
  max_marks: number;
  original_extract: string | null;
};

export type RevealedQuestionPayload = OpenQuestionPayload & {
  correct_option_id: string | null;
  worked_explanation: string;
};

export type OpenViewerSubmissionPayload = {
  session_question_id: CanonicalUuid;
  selected_option_id: string | null;
  answer_text: string | null;
  grading_status: GradingStatus;
};

export type RevealedViewerSubmissionPayload = {
  session_question_id: CanonicalUuid;
  selected_option_id: string | null;
  answer_text: string | null;
  is_correct: boolean | null;
  points: number | null;
  earned_marks: number | null;
  max_marks: number;
  grading_status: GradingStatus;
  feedback: Record<string, unknown>;
  awarded_criterion_ids: string[];
};

export type LeaderboardEntryPayload = {
  user_id: CanonicalUuid;
  display_name: string;
  total_points: number;
  correct_answers: number;
  rank: number;
  earned_marks: number;
  total_available_marks: number;
};

type SnapshotBase = {
  server_time: ZonedIsoTimestamp;
  room_state: RoomStatePayload;
  total_question_count: number;
  leaderboard: LeaderboardEntryPayload[];
  quiz_mode: QuizMode;
  total_available_marks: number;
  grading_retry_needed: boolean;
};

export type LobbyStateSnapshotPayload = SnapshotBase & {
  session_id: null;
  viewer_participated: false;
  state_version: 0;
  status: null;
  current_question_number: null;
  question: null;
  closes_at: null;
  reveal_ends_at: null;
  viewer_submission: null;
  finished_at: null;
};

export type OpenStateSnapshotPayload = SnapshotBase & {
  session_id: CanonicalUuid;
  viewer_participated: true;
  state_version: number;
  status: "QUESTION_OPEN";
  current_question_number: number;
  question: OpenQuestionPayload;
  closes_at: ZonedIsoTimestamp;
  reveal_ends_at: null;
  viewer_submission: OpenViewerSubmissionPayload | null;
  finished_at: null;
};

export type GradingStateSnapshotPayload = SnapshotBase & {
  session_id: CanonicalUuid;
  viewer_participated: true;
  state_version: number;
  status: "QUESTION_GRADING";
  current_question_number: number;
  question: OpenQuestionPayload;
  closes_at: ZonedIsoTimestamp;
  reveal_ends_at: null;
  viewer_submission: OpenViewerSubmissionPayload | null;
  finished_at: null;
};

export type RevealStateSnapshotPayload = SnapshotBase & {
  session_id: CanonicalUuid;
  viewer_participated: true;
  state_version: number;
  status: "QUESTION_REVEAL";
  current_question_number: number;
  question: RevealedQuestionPayload;
  closes_at: ZonedIsoTimestamp;
  reveal_ends_at: ZonedIsoTimestamp;
  viewer_submission: RevealedViewerSubmissionPayload | null;
  finished_at: null;
};

export type FinishedStateSnapshotPayload = SnapshotBase & {
  session_id: CanonicalUuid;
  viewer_participated: true;
  state_version: number;
  status: "FINISHED";
  current_question_number: number;
  question: RevealedQuestionPayload;
  closes_at: ZonedIsoTimestamp;
  reveal_ends_at: null;
  viewer_submission: RevealedViewerSubmissionPayload | null;
  finished_at: ZonedIsoTimestamp;
};

export type StateSnapshotPayload =
  | LobbyStateSnapshotPayload
  | OpenStateSnapshotPayload
  | GradingStateSnapshotPayload
  | RevealStateSnapshotPayload
  | FinishedStateSnapshotPayload;

export type ConnectedEvent = {
  protocol_version: 2;
  type: "CONNECTED";
  payload: { server_time: ZonedIsoTimestamp };
};

export type RoomStateEvent = {
  protocol_version: 2;
  type: "ROOM_STATE";
  payload: RoomStatePayload;
};

export type StateSnapshotEvent = {
  protocol_version: 2;
  type: "STATE_SNAPSHOT";
  payload: StateSnapshotPayload;
};

export type SessionStartedEvent = {
  protocol_version: 2;
  type: "SESSION_STARTED";
  payload: {
    session_id: CanonicalUuid;
    state_version: number;
  };
};

export type QuestionOpenedEvent = {
  protocol_version: 2;
  type: "QUESTION_OPENED";
  payload: {
    session_id: CanonicalUuid;
    state_version: number;
    question: OpenQuestionPayload;
  };
};

export type AnswerAcceptedEvent = {
  protocol_version: 2;
  type: "ANSWER_ACCEPTED";
  payload: {
    session_id: CanonicalUuid;
    state_version: number;
    session_question_id: CanonicalUuid;
    selected_option_id: string | null;
    answer_text: string | null;
    grading_status: GradingStatus;
    accepted_at: ZonedIsoTimestamp;
  };
};

export type QuestionRevealedEvent = {
  protocol_version: 2;
  type: "QUESTION_REVEALED";
  payload: {
    session_id: CanonicalUuid;
    state_version: number;
    question: RevealedQuestionPayload;
    viewer_submission: RevealedViewerSubmissionPayload | null;
    leaderboard: LeaderboardEntryPayload[];
  };
};

export type SessionFinishedEvent = {
  protocol_version: 2;
  type: "SESSION_FINISHED";
  payload: {
    session_id: CanonicalUuid;
    state_version: number;
    leaderboard: LeaderboardEntryPayload[];
    finished_at: ZonedIsoTimestamp;
  };
};

export type ErrorEvent = {
  protocol_version: 2;
  type: "ERROR";
  payload: {
    code: string;
    message: string;
  };
};

export type ServerEvent =
  | ConnectedEvent
  | RoomStateEvent
  | StateSnapshotEvent
  | SessionStartedEvent
  | QuestionOpenedEvent
  | AnswerAcceptedEvent
  | QuestionRevealedEvent
  | SessionFinishedEvent
  | ErrorEvent;

export type AuthoritativeSessionStateEvent =
  | StateSnapshotEvent
  | SessionStartedEvent
  | QuestionOpenedEvent
  | QuestionRevealedEvent
  | SessionFinishedEvent;

export type RealtimeProtocolErrorCode = "malformed_json" | "invalid_event";

export class RealtimeProtocolError extends Error {
  readonly code: RealtimeProtocolErrorCode;

  constructor(code: RealtimeProtocolErrorCode, message: string) {
    super(message);
    this.name = "RealtimeProtocolError";
    this.code = code;
  }
}

export class UnsupportedProtocolVersionError extends Error {
  readonly code = "unsupported_protocol_version" as const;

  constructor() {
    super("The server uses an unsupported realtime protocol version.");
    this.name = "UnsupportedProtocolVersionError";
  }
}

type JsonObject = Record<string, unknown>;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TIMESTAMP_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/;
const JOIN_CODE_PATTERN = /^[A-Z2-9]{6}$/;

function invalidEvent(context: string): never {
  throw new RealtimeProtocolError(
    "invalid_event",
    `The server returned an invalid realtime ${context}.`,
  );
}

function expectExactObject(
  value: unknown,
  keys: readonly string[],
  context: string,
): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return invalidEvent(context);
  }

  const record = value as JsonObject;
  const actualKeys = Object.keys(record);
  if (
    actualKeys.length !== keys.length ||
    actualKeys.some((key) => !keys.includes(key))
  ) {
    return invalidEvent(context);
  }
  return record;
}

function expectNonEmptyString(
  value: unknown,
  context: string,
  maximumLength?: number,
): string {
  if (
    typeof value !== "string" ||
    value.trim().length === 0 ||
    (maximumLength !== undefined && value.length > maximumLength)
  ) {
    return invalidEvent(context);
  }
  return value;
}

function expectBoolean(value: unknown, context: string): boolean {
  if (typeof value !== "boolean") {
    return invalidEvent(context);
  }
  return value;
}

function expectInteger(
  value: unknown,
  context: string,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    !Number.isSafeInteger(value) ||
    value < minimum ||
    value > maximum
  ) {
    return invalidEvent(context);
  }
  return value;
}

export function parseCanonicalUuid(
  value: unknown,
  context = "UUID",
): CanonicalUuid {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    return invalidEvent(context);
  }
  return value as CanonicalUuid;
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year: number, month: number): number {
  const days = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return days[month - 1] ?? 0;
}

function parseZonedTimestamp(
  value: unknown,
  context: string,
): ZonedIsoTimestamp {
  if (typeof value !== "string") {
    return invalidEvent(context);
  }
  const match = TIMESTAMP_PATTERN.exec(value);
  if (match === null) {
    return invalidEvent(context);
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const offsetHour = match[8] === undefined ? 0 : Number(match[8]);
  const offsetMinute = match[9] === undefined ? 0 : Number(match[9]);
  if (
    year < 1 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > daysInMonth(year, month) ||
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    offsetHour > 23 ||
    offsetMinute > 59 ||
    !Number.isFinite(Date.parse(value))
  ) {
    return invalidEvent(context);
  }
  return value as ZonedIsoTimestamp;
}

function parseViewerRole(value: unknown, context: string): ViewerRole {
  if (value !== "host" && value !== "member") {
    return invalidEvent(context);
  }
  return value;
}

function parseSessionStatus(value: unknown): SessionStatus {
  if (
    value !== "QUESTION_OPEN" &&
    value !== "QUESTION_GRADING" &&
    value !== "QUESTION_REVEAL" &&
    value !== "FINISHED"
  ) {
    return invalidEvent("session status");
  }
  return value;
}

function parseQuizMode(value: unknown, context: string): QuizMode {
  if (value !== "LEGACY_PHYSICS" && value !== "ADAPTIVE") {
    return invalidEvent(context);
  }
  return value;
}

function parseQuestionType(
  value: unknown,
  context: string,
): AdaptiveQuestionType {
  if (
    value !== "MULTIPLE_CHOICE" &&
    value !== "NUMERICAL" &&
    value !== "WRITTEN"
  ) {
    return invalidEvent(context);
  }
  return value;
}

function parseGradingStatus(value: unknown, context: string): GradingStatus {
  if (
    value !== "PENDING" &&
    value !== "IN_PROGRESS" &&
    value !== "GRADED" &&
    value !== "RETRYABLE" &&
    value !== "UNAVAILABLE"
  ) {
    return invalidEvent(context);
  }
  return value;
}

function parsePreparationStatus(
  value: unknown,
  context: string,
): QuizPreparationStatus | null {
  if (value === null) {
    return null;
  }
  if (
    value !== "GENERATING" &&
    value !== "READY" &&
    value !== "FAILED" &&
    value !== "CONSUMED" &&
    value !== "SUPERSEDED"
  ) {
    return invalidEvent(context);
  }
  return value;
}

function parseNullableString(
  value: unknown,
  context: string,
  maximumLength?: number,
): string | null {
  if (value === null) {
    return null;
  }
  return expectNonEmptyString(value, context, maximumLength);
}

function parseNullableInteger(
  value: unknown,
  context: string,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): number | null {
  if (value === null) {
    return null;
  }
  return expectInteger(value, context, minimum, maximum);
}

function parseArray<T>(
  value: unknown,
  parser: (entry: unknown, index: number) => T,
  context: string,
): T[] {
  if (!Array.isArray(value)) {
    return invalidEvent(context);
  }
  return value.map(parser);
}

function parseRoomStateParticipant(
  value: unknown,
  index: number,
): RoomStateParticipant {
  const context = `room participant at index ${index}`;
  const record = expectExactObject(
    value,
    ["user_id", "display_name", "role", "ready", "online"],
    context,
  );
  return {
    user_id: parseCanonicalUuid(record.user_id, `${context} user ID`),
    display_name: expectNonEmptyString(record.display_name, `${context} display name`, 40),
    role: parseViewerRole(record.role, `${context} role`),
    ready: expectBoolean(record.ready, `${context} readiness`),
    online: expectBoolean(record.online, `${context} presence`),
  };
}

function parseRoomState(value: unknown): RoomStatePayload {
  const record = expectExactObject(
    value,
    [
      "room_id",
      "name",
      "join_code",
      "maximum_members",
      "viewer_role",
      "participants",
      "viewer_ready",
      "quiz_mode",
      "education_level",
      "quiz_subject",
      "quiz_topic",
      "target_total_marks",
      "active_preparation_status",
      "active_preparation_version",
      "active_preparation_error_category",
    ],
    "room state",
  );
  const joinCode = expectNonEmptyString(record.join_code, "room join code");
  if (!JOIN_CODE_PATTERN.test(joinCode)) {
    return invalidEvent("room join code");
  }
  const participants = parseArray(
    record.participants,
    parseRoomStateParticipant,
    "room participants",
  );
  if (participants.length === 0) {
    return invalidEvent("room participants");
  }
  return {
    room_id: parseCanonicalUuid(record.room_id, "room ID"),
    name: expectNonEmptyString(record.name, "room name", 60),
    join_code: joinCode,
    maximum_members: expectInteger(record.maximum_members, "room capacity", 2, 20),
    viewer_role: parseViewerRole(record.viewer_role, "viewer role"),
    participants,
    viewer_ready: expectBoolean(record.viewer_ready, "viewer readiness"),
    quiz_mode: parseQuizMode(record.quiz_mode, "room quiz mode"),
    education_level: parseNullableString(
      record.education_level,
      "room education level",
      16,
    ),
    quiz_subject: parseNullableString(record.quiz_subject, "room quiz subject", 32),
    quiz_topic: parseNullableString(record.quiz_topic, "room quiz topic", 40),
    target_total_marks: parseNullableInteger(
      record.target_total_marks,
      "room target total marks",
      5,
      40,
    ),
    active_preparation_status: parsePreparationStatus(
      record.active_preparation_status,
      "room preparation status",
    ),
    active_preparation_version: parseNullableInteger(
      record.active_preparation_version,
      "room preparation version",
      1,
    ),
    active_preparation_error_category: parseNullableString(
      record.active_preparation_error_category,
      "room preparation error category",
      64,
    ),
  };
}

function parseQuestionOption(
  value: unknown,
  index: number,
): QuestionOptionPayload {
  const context = `question option at index ${index}`;
  const record = expectExactObject(value, ["id", "label"], context);
  return {
    id: expectNonEmptyString(record.id, `${context} ID`, 64),
    label: expectNonEmptyString(record.label, `${context} label`),
  };
}

function parseQuestionCommon(
  value: unknown,
  revealed: boolean,
): OpenQuestionPayload | RevealedQuestionPayload {
  const context = revealed ? "revealed question" : "open question";
  const keys = [
    "session_question_id",
    "prompt",
    "options",
    "question_number",
    "total_questions",
    "closes_at",
    "server_time",
    "question_type",
    "max_marks",
    "original_extract",
  ];
  if (revealed) {
    keys.push("correct_option_id", "worked_explanation");
  }
  const record = expectExactObject(value, keys, context);
  const options = parseArray(record.options, parseQuestionOption, `${context} options`);
  if (new Set(options.map((option) => option.id)).size !== options.length) {
    return invalidEvent(`${context} duplicate options`);
  }
  const questionType = parseQuestionType(
    record.question_type,
    `${context} type`,
  );
  if (questionType === "MULTIPLE_CHOICE") {
    if (options.length < 2 || options.length > 6 || record.max_marks !== 1) {
      return invalidEvent(`${context} options`);
    }
  } else if (options.length !== 0) {
    return invalidEvent(`${context} options`);
  }
  const questionNumber = expectInteger(record.question_number, `${context} number`, 1);
  const totalQuestions = expectInteger(record.total_questions, `${context} total`, 1);
  if (questionNumber > totalQuestions) {
    return invalidEvent(`${context} number`);
  }
  const common: OpenQuestionPayload = {
    session_question_id: parseCanonicalUuid(
      record.session_question_id,
      `${context} ID`,
    ),
    prompt: expectNonEmptyString(record.prompt, `${context} prompt`),
    options,
    question_number: questionNumber,
    total_questions: totalQuestions,
    closes_at: parseZonedTimestamp(record.closes_at, `${context} close time`),
    server_time: parseZonedTimestamp(record.server_time, `${context} server time`),
    question_type: questionType,
    max_marks: expectInteger(record.max_marks, `${context} max marks`, 1, 6),
    original_extract:
      record.original_extract === null
        ? null
        : expectNonEmptyString(
            record.original_extract,
            `${context} original extract`,
          ),
  };
  if (!revealed) {
    return common;
  }
  if (questionType === "MULTIPLE_CHOICE"
    ? !options.some((option) => option.id === record.correct_option_id)
    : record.correct_option_id !== null) {
    return invalidEvent(`${context} correct option`);
  }
  return {
    ...common,
    correct_option_id:
      record.correct_option_id === null
        ? null
        : expectNonEmptyString(
            record.correct_option_id,
            "revealed correct option ID",
            64,
          ),
    worked_explanation:
      typeof record.worked_explanation === "string"
        ? record.worked_explanation
        : invalidEvent("revealed worked explanation"),
  };
}

function parseOpenQuestion(value: unknown): OpenQuestionPayload {
  return parseQuestionCommon(value, false) as OpenQuestionPayload;
}

function parseRevealedQuestion(value: unknown): RevealedQuestionPayload {
  return parseQuestionCommon(value, true) as RevealedQuestionPayload;
}

function parseOptionalOptionId(
  value: unknown,
  context: string,
): string | null {
  if (value === null) {
    return null;
  }
  return expectNonEmptyString(value, context, 64);
}

function parseOptionalAnswerText(
  value: unknown,
  context: string,
): string | null {
  if (value === null) {
    return null;
  }
  if (typeof value !== "string" || value.length > 1000) {
    return invalidEvent(context);
  }
  return value;
}

function parseOpenViewerSubmission(
  value: unknown,
): OpenViewerSubmissionPayload {
  const record = expectExactObject(
    value,
    [
      "session_question_id",
      "selected_option_id",
      "answer_text",
      "grading_status",
    ],
    "open viewer submission",
  );
  const selectedOptionId = parseOptionalOptionId(
    record.selected_option_id,
    "open viewer selected option ID",
  );
  const answerText = parseOptionalAnswerText(
    record.answer_text,
    "open viewer answer text",
  );
  if (selectedOptionId === null && answerText === null) {
    return invalidEvent("open viewer submission answer");
  }
  if (selectedOptionId !== null && answerText !== null) {
    return invalidEvent("open viewer submission answer");
  }
  return {
    session_question_id: parseCanonicalUuid(
      record.session_question_id,
      "open viewer submission question ID",
    ),
    selected_option_id: selectedOptionId,
    answer_text: answerText,
    grading_status: parseGradingStatus(
      record.grading_status,
      "open viewer submission grading status",
    ),
  };
}

function parseFeedbackRecord(value: unknown, context: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return invalidEvent(context);
  }
  return value as Record<string, unknown>;
}

export function parseViewerFeedbackSummary(
  feedback: Record<string, unknown>,
): string | null {
  const summary = feedback.summary;
  return typeof summary === "string" && summary.length > 0 ? summary : null;
}

function sameStringSet(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false;
  }
  const remaining = new Set(left);
  for (const entry of right) {
    if (!remaining.delete(entry)) {
      return false;
    }
  }
  return remaining.size === 0;
}

function parseRevealedViewerSubmission(
  value: unknown,
  questionType: AdaptiveQuestionType,
  questionMaxMarks: number,
): RevealedViewerSubmissionPayload {
  const record = expectExactObject(
    value,
    [
      "session_question_id",
      "selected_option_id",
      "answer_text",
      "is_correct",
      "points",
      "earned_marks",
      "max_marks",
      "grading_status",
      "feedback",
      "awarded_criterion_ids",
    ],
    "revealed viewer submission",
  );
  const context = "revealed viewer submission";
  if (record.is_correct !== null && typeof record.is_correct !== "boolean") {
    return invalidEvent(`${context} correctness`);
  }
  if (
    record.points !== null &&
    (typeof record.points !== "number" ||
      !Number.isSafeInteger(record.points) ||
      record.points < 0)
  ) {
    return invalidEvent(`${context} points`);
  }
  if (
    record.earned_marks !== null &&
    (typeof record.earned_marks !== "number" ||
      !Number.isSafeInteger(record.earned_marks) ||
      record.earned_marks < 0)
  ) {
    return invalidEvent(`${context} earned marks`);
  }
  if (!Array.isArray(record.awarded_criterion_ids)) {
    return invalidEvent(`${context} awarded criteria`);
  }
  const awardedCriterionIds: string[] = [];
  for (const entry of record.awarded_criterion_ids) {
    if (typeof entry !== "string" || entry.length === 0) {
      return invalidEvent(`${context} awarded criteria`);
    }
    awardedCriterionIds.push(entry);
  }
  const feedback = parseFeedbackRecord(
    record.feedback,
    "revealed viewer submission feedback",
  );
  const gradingStatus = parseGradingStatus(
    record.grading_status,
    "revealed viewer submission grading status",
  );
  const maxMarks = expectInteger(
    record.max_marks,
    "revealed viewer submission max marks",
    1,
    6,
  );
  // Written marking feedback is server-derived and only exists post-grade:
  // a GRADED written outcome must carry the exact enriched shape whose
  // awarded marks sum to the earned marks and whose awarded IDs exactly
  // match, while any non-graded written outcome must carry no feedback.
  // Numerical outcomes use their own producer shape below; MCQ stays empty.
  let enriched: EnrichedWrittenFeedback | null = null;
  if (Object.keys(feedback).length > 0 && questionType !== "NUMERICAL") {
    if (questionType !== "WRITTEN" || gradingStatus !== "GRADED") {
      return invalidEvent(`${context} feedback before grading completed`);
    }
    try {
      enriched = parseEnrichedWrittenFeedback(feedback);
    } catch (error: unknown) {
      if (error instanceof InvalidGradingFeedbackError) {
        return invalidEvent(`${context} written feedback`);
      }
      throw error;
    }
  }
  if (questionType !== "WRITTEN" && looksLikeEnrichedFeedback(feedback)) {
    return invalidEvent(`${context} misattributed written feedback`);
  }
  const earnedMarks =
    record.earned_marks === null
      ? null
      : typeof record.earned_marks === "number" &&
          Number.isSafeInteger(record.earned_marks) &&
          record.earned_marks >= 0
        ? record.earned_marks
        : invalidEvent(`${context} earned marks`);
  if (questionType === "NUMERICAL") {
    if (gradingStatus !== "GRADED" || earnedMarks === null || maxMarks !== questionMaxMarks ||
        record.is_correct !== (earnedMarks === maxMarks) || awardedCriterionIds.length !== 0 ||
        record.selected_option_id !== null || typeof record.answer_text !== "string") {
      return invalidEvent(`${context} numerical coherence`);
    }
    try {
      parseNumericalFeedback(feedback, earnedMarks, maxMarks);
    } catch (error: unknown) {
      if (error instanceof InvalidGradingFeedbackError) return invalidEvent(`${context} numerical feedback`);
      throw error;
    }
  }
  if (questionType === "WRITTEN" && gradingStatus === "GRADED") {
    if (
      enriched === null ||
      earnedMarks === null ||
      maxMarks !== questionMaxMarks ||
      awardedMarksTotal(enriched) !== earnedMarks ||
      !sameStringSet(
        awardedCriterionIds,
        enriched.awarded.map((point) => point.id),
      )
    ) {
      return invalidEvent(`${context} graded written coherence`);
    }
  }
  return {
    session_question_id: parseCanonicalUuid(
      record.session_question_id,
      "revealed viewer submission question ID",
    ),
    selected_option_id: parseOptionalOptionId(
      record.selected_option_id,
      "revealed viewer selected option ID",
    ),
    answer_text: parseOptionalAnswerText(
      record.answer_text,
      "revealed viewer answer text",
    ),
    is_correct: record.is_correct as boolean | null,
    points: record.points as number | null,
    earned_marks: earnedMarks,
    max_marks: maxMarks,
    grading_status: gradingStatus,
    feedback,
    awarded_criterion_ids: awardedCriterionIds,
  };
}

function parseNullable<T>(
  value: unknown,
  parser: (entry: unknown) => T,
): T | null {
  return value === null ? null : parser(value);
}

function parseLeaderboardEntry(
  value: unknown,
  index: number,
): LeaderboardEntryPayload {
  const context = `leaderboard entry at index ${index}`;
  const record = expectExactObject(
    value,
    [
      "user_id",
      "display_name",
      "total_points",
      "correct_answers",
      "rank",
      "earned_marks",
      "total_available_marks",
    ],
    context,
  );
  return {
    user_id: parseCanonicalUuid(record.user_id, `${context} user ID`),
    display_name: expectNonEmptyString(record.display_name, `${context} display name`, 40),
    total_points: expectInteger(record.total_points, `${context} points`, 0),
    correct_answers: expectInteger(
      record.correct_answers,
      `${context} correct answer count`,
      0,
    ),
    rank: expectInteger(record.rank, `${context} rank`, 1),
    earned_marks: expectInteger(record.earned_marks, `${context} earned marks`, 0),
    total_available_marks: expectInteger(
      record.total_available_marks,
      `${context} total available marks`,
      0,
    ),
  };
}

function parseLeaderboard(value: unknown): LeaderboardEntryPayload[] {
  return parseArray(value, parseLeaderboardEntry, "leaderboard");
}

const SNAPSHOT_KEYS = [
  "server_time",
  "room_state",
  "session_id",
  "viewer_participated",
  "state_version",
  "status",
  "current_question_number",
  "total_question_count",
  "question",
  "closes_at",
  "reveal_ends_at",
  "viewer_submission",
  "leaderboard",
  "finished_at",
  "quiz_mode",
  "total_available_marks",
  "grading_retry_needed",
] as const;

function expectNull(value: unknown, context: string): null {
  if (value !== null) {
    return invalidEvent(context);
  }
  return null;
}

function validateQuestionCoordinates(
  currentQuestionNumber: number,
  totalQuestionCount: number,
  question: OpenQuestionPayload | RevealedQuestionPayload,
): void {
  if (
    currentQuestionNumber !== question.question_number ||
    totalQuestionCount !== question.total_questions
  ) {
    invalidEvent("snapshot question coordinates");
  }
}

function parseStateSnapshot(value: unknown): StateSnapshotPayload {
  const record = expectExactObject(value, SNAPSHOT_KEYS, "state snapshot");
  const serverTime = parseZonedTimestamp(record.server_time, "snapshot server time");
  const roomState = parseRoomState(record.room_state);
  const viewerParticipated = expectBoolean(
    record.viewer_participated,
    "viewer participation",
  );
  const leaderboard = parseLeaderboard(record.leaderboard);

  const quizMode = parseQuizMode(record.quiz_mode, "snapshot quiz mode");
  const totalAvailableMarks = expectInteger(
    record.total_available_marks,
    "snapshot total available marks",
    0,
  );
  const gradingRetryNeeded = expectBoolean(
    record.grading_retry_needed,
    "snapshot grading retry signal",
  );
  if (roomState.quiz_mode !== quizMode) {
    return invalidEvent("snapshot quiz mode");
  }

  if (record.session_id === null) {
    if (viewerParticipated || leaderboard.length !== 0) {
      return invalidEvent("lobby snapshot");
    }
    expectNull(record.status, "lobby session status");
    expectNull(record.current_question_number, "lobby question number");
    expectNull(record.question, "lobby question");
    expectNull(record.closes_at, "lobby close time");
    expectNull(record.reveal_ends_at, "lobby reveal end time");
    expectNull(record.viewer_submission, "lobby viewer submission");
    expectNull(record.finished_at, "lobby finish time");
    const stateVersion = expectInteger(record.state_version, "lobby state version", 0, 0);
    return {
      server_time: serverTime,
      room_state: roomState,
      session_id: null,
      viewer_participated: false,
      state_version: stateVersion as 0,
      status: null,
      current_question_number: null,
      total_question_count: expectInteger(
        record.total_question_count,
        "lobby question count",
        0,
      ),
      question: null,
      closes_at: null,
      reveal_ends_at: null,
      viewer_submission: null,
      leaderboard,
      finished_at: null,
      quiz_mode: quizMode,
      total_available_marks: totalAvailableMarks,
      grading_retry_needed: gradingRetryNeeded,
    };
  }

  if (!viewerParticipated) {
    return invalidEvent("session viewer participation");
  }
  const sessionId = parseCanonicalUuid(record.session_id, "snapshot session ID");
  const stateVersion = expectInteger(record.state_version, "snapshot state version", 1);
  const status = parseSessionStatus(record.status);
  const currentQuestionNumber = expectInteger(
    record.current_question_number,
    "snapshot current question number",
    1,
  );
  const totalQuestionCount = expectInteger(
    record.total_question_count,
    "snapshot question count",
    1,
  );

  if (status === "QUESTION_OPEN" || status === "QUESTION_GRADING") {
    const question = parseOpenQuestion(record.question);
    validateQuestionCoordinates(currentQuestionNumber, totalQuestionCount, question);
    const context = status === "QUESTION_OPEN" ? "open" : "grading";
    expectNull(record.reveal_ends_at, `${context} snapshot reveal end time`);
    expectNull(record.finished_at, `${context} snapshot finish time`);
    const shared = {
      server_time: serverTime,
      room_state: roomState,
      session_id: sessionId,
      viewer_participated: true as const,
      state_version: stateVersion,
      current_question_number: currentQuestionNumber,
      total_question_count: totalQuestionCount,
      question,
      closes_at: parseZonedTimestamp(
        record.closes_at,
        `${context} snapshot close time`,
      ),
      reveal_ends_at: null as null,
      viewer_submission: parseNullable(
        record.viewer_submission,
        parseOpenViewerSubmission,
      ),
      leaderboard,
      finished_at: null as null,
      quiz_mode: quizMode,
      total_available_marks: totalAvailableMarks,
      grading_retry_needed: gradingRetryNeeded,
    };
    if (status === "QUESTION_OPEN") {
      const openSnapshot: OpenStateSnapshotPayload = {
        ...shared,
        status,
      };
      return openSnapshot;
    }
    const gradingSnapshot: GradingStateSnapshotPayload = {
      ...shared,
      status,
    };
    return gradingSnapshot;
  }

  const question = parseRevealedQuestion(record.question);
  validateQuestionCoordinates(currentQuestionNumber, totalQuestionCount, question);
  const common = {
    server_time: serverTime,
    room_state: roomState,
    session_id: sessionId,
    viewer_participated: true as const,
    state_version: stateVersion,
    current_question_number: currentQuestionNumber,
    total_question_count: totalQuestionCount,
    question,
    closes_at: parseZonedTimestamp(record.closes_at, "snapshot close time"),
    viewer_submission: parseNullable(record.viewer_submission, (entry) =>
      parseRevealedViewerSubmission(
        entry,
        question.question_type,
        question.max_marks,
      ),
    ),
    leaderboard,
    quiz_mode: quizMode,
    total_available_marks: totalAvailableMarks,
    grading_retry_needed: gradingRetryNeeded,
  };
  if (status === "QUESTION_REVEAL") {
    expectNull(record.finished_at, "reveal snapshot finish time");
    return {
      ...common,
      status,
      reveal_ends_at: parseZonedTimestamp(
        record.reveal_ends_at,
        "reveal snapshot end time",
      ),
      finished_at: null,
    };
  }
  expectNull(record.reveal_ends_at, "finished snapshot reveal end time");
  return {
    ...common,
    status,
    reveal_ends_at: null,
    finished_at: parseZonedTimestamp(record.finished_at, "snapshot finish time"),
  };
}

function parseSessionReference(value: unknown): SessionStartedEvent["payload"] {
  const record = expectExactObject(
    value,
    ["session_id", "state_version"],
    "session reference",
  );
  return {
    session_id: parseCanonicalUuid(record.session_id, "session ID"),
    state_version: expectInteger(record.state_version, "session state version", 1),
  };
}

function parseQuestionOpened(value: unknown): QuestionOpenedEvent["payload"] {
  const record = expectExactObject(
    value,
    ["session_id", "state_version", "question"],
    "question-opened payload",
  );
  return {
    session_id: parseCanonicalUuid(record.session_id, "opened session ID"),
    state_version: expectInteger(record.state_version, "opened state version", 1),
    question: parseOpenQuestion(record.question),
  };
}

function parseAnswerAccepted(value: unknown): AnswerAcceptedEvent["payload"] {
  const record = expectExactObject(
    value,
    [
      "session_id",
      "state_version",
      "session_question_id",
      "selected_option_id",
      "answer_text",
      "grading_status",
      "accepted_at",
    ],
    "answer acknowledgement",
  );
  const selectedOptionId = parseOptionalOptionId(
    record.selected_option_id,
    "accepted option ID",
  );
  const answerText = parseOptionalAnswerText(
    record.answer_text,
    "accepted answer text",
  );
  if (selectedOptionId === null && answerText === null) {
    return invalidEvent("answer acknowledgement answer");
  }
  if (selectedOptionId !== null && answerText !== null) {
    return invalidEvent("answer acknowledgement answer");
  }
  return {
    session_id: parseCanonicalUuid(record.session_id, "answer session ID"),
    state_version: expectInteger(record.state_version, "answer state version", 1),
    session_question_id: parseCanonicalUuid(
      record.session_question_id,
      "answered question ID",
    ),
    selected_option_id: selectedOptionId,
    answer_text: answerText,
    grading_status: parseGradingStatus(
      record.grading_status,
      "answer acknowledgement grading status",
    ),
    accepted_at: parseZonedTimestamp(record.accepted_at, "answer acceptance time"),
  };
}

function parseQuestionRevealed(value: unknown): QuestionRevealedEvent["payload"] {
  const record = expectExactObject(
    value,
    ["session_id", "state_version", "question", "viewer_submission", "leaderboard"],
    "question-revealed payload",
  );
  const question = parseRevealedQuestion(record.question);
  return {
    session_id: parseCanonicalUuid(record.session_id, "revealed session ID"),
    state_version: expectInteger(record.state_version, "revealed state version", 1),
    question,
    viewer_submission: parseNullable(record.viewer_submission, (entry) =>
      parseRevealedViewerSubmission(
        entry,
        question.question_type,
        question.max_marks,
      ),
    ),
    leaderboard: parseLeaderboard(record.leaderboard),
  };
}

function parseSessionFinished(value: unknown): SessionFinishedEvent["payload"] {
  const record = expectExactObject(
    value,
    ["session_id", "state_version", "leaderboard", "finished_at"],
    "session-finished payload",
  );
  return {
    session_id: parseCanonicalUuid(record.session_id, "finished session ID"),
    state_version: expectInteger(record.state_version, "finished state version", 1),
    leaderboard: parseLeaderboard(record.leaderboard),
    finished_at: parseZonedTimestamp(record.finished_at, "session finish time"),
  };
}

function parseErrorPayload(value: unknown): ErrorEvent["payload"] {
  const record = expectExactObject(value, ["code", "message"], "error payload");
  return {
    code: expectNonEmptyString(record.code, "error code"),
    message: expectNonEmptyString(record.message, "error message"),
  };
}

export function parseServerEvent(message: string): ServerEvent {
  let value: unknown;
  try {
    value = JSON.parse(message) as unknown;
  } catch {
    throw new RealtimeProtocolError(
      "malformed_json",
      "The server returned malformed realtime JSON.",
    );
  }

  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return invalidEvent("event");
  }
  const untrusted = value as JsonObject;
  if (untrusted.protocol_version !== REALTIME_PROTOCOL_VERSION) {
    throw new UnsupportedProtocolVersionError();
  }
  const record = expectExactObject(
    value,
    ["protocol_version", "type", "payload"],
    "event",
  );

  switch (record.type) {
    case "CONNECTED": {
      const payload = expectExactObject(
        record.payload,
        ["server_time"],
        "connected payload",
      );
      return {
        protocol_version: 2,
        type: "CONNECTED",
        payload: {
          server_time: parseZonedTimestamp(payload.server_time, "connected server time"),
        },
      };
    }
    case "ROOM_STATE":
      return {
        protocol_version: 2,
        type: "ROOM_STATE",
        payload: parseRoomState(record.payload),
      };
    case "STATE_SNAPSHOT":
      return {
        protocol_version: 2,
        type: "STATE_SNAPSHOT",
        payload: parseStateSnapshot(record.payload),
      };
    case "SESSION_STARTED":
      return {
        protocol_version: 2,
        type: "SESSION_STARTED",
        payload: parseSessionReference(record.payload),
      };
    case "QUESTION_OPENED":
      return {
        protocol_version: 2,
        type: "QUESTION_OPENED",
        payload: parseQuestionOpened(record.payload),
      };
    case "ANSWER_ACCEPTED":
      return {
        protocol_version: 2,
        type: "ANSWER_ACCEPTED",
        payload: parseAnswerAccepted(record.payload),
      };
    case "QUESTION_REVEALED":
      return {
        protocol_version: 2,
        type: "QUESTION_REVEALED",
        payload: parseQuestionRevealed(record.payload),
      };
    case "SESSION_FINISHED":
      return {
        protocol_version: 2,
        type: "SESSION_FINISHED",
        payload: parseSessionFinished(record.payload),
      };
    case "ERROR":
      return {
        protocol_version: 2,
        type: "ERROR",
        payload: parseErrorPayload(record.payload),
      };
    default:
      return invalidEvent("event type");
  }
}
