import {
  awardedMarksTotal,
  InvalidGradingFeedbackError,
  parseEnrichedWrittenFeedback,
} from "../feedback/gradingFeedback";
import { MalformedResponseError } from "./errors";
import { parseNumericalFeedback } from "../feedback/numericalFeedback";

export type QuizSettingsInput = {
  mode: "adaptive";
  level: "gcse";
  subject: string;
  topic: string;
  total_marks: number;
};

export type CreateRoomInput = {
  name: string;
  maximum_members: number;
  quiz_settings?: QuizSettingsInput;
};

export type QuizMode = "LEGACY_PHYSICS" | "ADAPTIVE";

export type RoomResponse = {
  id: string;
  name: string;
  join_code: string;
  maximum_members: number;
  member_count: number;
  quiz_mode: QuizMode;
  education_level: string | null;
  quiz_subject: string | null;
  quiz_topic: string | null;
  target_total_marks: number | null;
};

export type QuizPreparationStatus =
  | "GENERATING"
  | "READY"
  | "FAILED"
  | "CONSUMED"
  | "SUPERSEDED";

export type QuizPreparationResponse = {
  id: string;
  room_id: string;
  request_id: string;
  status: QuizPreparationStatus;
  state_version: number;
  error_category: string | null;
};

export type ReviewQuestionOption = {
  id: string;
  label: string;
};

export type ReviewQuestionItem = {
  session_question_id: string;
  position: number;
  question_type: string;
  prompt: string;
  max_marks: number;
  options: ReviewQuestionOption[];
  correct_option_id: string | null;
  worked_explanation: string;
  original_extract: string | null;
  selected_option_id: string | null;
  answer_text: string | null;
  earned_marks: number;
  feedback: Record<string, unknown>;
  awarded_criterion_ids: string[];
};

export type SessionReviewResponse = {
  session_id: string;
  room_id: string;
  viewer_user_id: string;
  total_earned_marks: number;
  total_available_marks: number;
  questions: ReviewQuestionItem[];
};

export type SubmitChoiceInput = {
  type: "choice";
  option_id: string;
};

export type SubmitTextInput = {
  type: "text";
  text: string;
};

export type SubmitAnswerInput = SubmitChoiceInput | SubmitTextInput;

export type RoomMemberResponse = {
  user_id: string;
  display_name: string;
  room_id: string;
};

export type JoinByCodeResponse = {
  room: RoomResponse;
  member: RoomMemberResponse;
};

export type RoomMemberListItem = {
  user_id: string;
  display_name: string;
};

export type RoomMembersResponse = {
  room_id: string;
  members: RoomMemberListItem[];
  member_count: number;
  maximum_members: number;
};

export type ProfileResponse = {
  id: string;
  display_name: string;
};

export type AccountDeletionResponse = {
  status: "account_deleted";
  local_deletion_complete: true;
  provider_cleanup_pending: boolean;
};

export type SafetyReportReason =
  | "inappropriate_display_name"
  | "disruptive_room_behaviour"
  | "other_safety_concern";

export type SafetyReportInput = {
  reported_user_id: string;
  room_id: string;
  reason: SafetyReportReason;
  details?: string;
};

export type SafetyReportResponse = {
  status: "report_received";
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isRoomCapacity(value: unknown): value is number {
  return (
    isFiniteNumber(value) &&
    Number.isInteger(value) &&
    value >= 2 &&
    value <= 20
  );
}

function malformedResponse(resource: string): MalformedResponseError {
  return new MalformedResponseError(
    `The StudyRoom server returned an invalid ${resource} response.`,
  );
}

const QUIZ_MODES: ReadonlySet<string> = new Set([
  "LEGACY_PHYSICS",
  "ADAPTIVE",
]);

const QUIZ_PREPARATION_STATUSES: ReadonlySet<string> = new Set([
  "GENERATING",
  "READY",
  "FAILED",
  "CONSUMED",
  "SUPERSEDED",
]);

function isQuizMode(value: unknown): value is QuizMode {
  return typeof value === "string" && QUIZ_MODES.has(value);
}

function isNullableNonEmptyString(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value);
}

function isNullableTotalMarks(value: unknown): value is number | null {
  return (
    value === null ||
    (isFiniteNumber(value) &&
      Number.isInteger(value) &&
      value >= 5 &&
      value <= 40)
  );
}

export function parseRoomResponse(value: unknown): RoomResponse {
  if (!isRecord(value)) {
    throw malformedResponse("room");
  }

  if (
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.name) ||
    !isNonEmptyString(value.join_code) ||
    !isRoomCapacity(value.maximum_members) ||
    !isFiniteNumber(value.member_count)
  ) {
    throw malformedResponse("room");
  }

  // Adaptive room settings are validated strictly when present and default
  // to the legacy Physics Sprint shape when absent.
  const quizMode: QuizMode =
    value.quiz_mode === undefined
      ? "LEGACY_PHYSICS"
      : isQuizMode(value.quiz_mode)
        ? value.quiz_mode
        : (() => {
            throw malformedResponse("room");
          })();
  if (
    (value.education_level !== undefined &&
      !isNullableNonEmptyString(value.education_level)) ||
    (value.quiz_subject !== undefined &&
      !isNullableNonEmptyString(value.quiz_subject)) ||
    (value.quiz_topic !== undefined &&
      !isNullableNonEmptyString(value.quiz_topic)) ||
    (value.target_total_marks !== undefined &&
      !isNullableTotalMarks(value.target_total_marks))
  ) {
    throw malformedResponse("room");
  }
  const educationLevel =
    value.education_level === undefined
      ? null
      : (value.education_level as string | null);
  const quizSubject =
    value.quiz_subject === undefined
      ? null
      : (value.quiz_subject as string | null);
  const quizTopic =
    value.quiz_topic === undefined
      ? null
      : (value.quiz_topic as string | null);
  const targetTotalMarks =
    value.target_total_marks === undefined
      ? null
      : (value.target_total_marks as number | null);

  return {
    id: value.id,
    name: value.name,
    join_code: value.join_code,
    maximum_members: value.maximum_members,
    member_count: value.member_count,
    quiz_mode: quizMode,
    education_level: educationLevel,
    quiz_subject: quizSubject,
    quiz_topic: quizTopic,
    target_total_marks: targetTotalMarks,
  };
}

function isPreparationStatus(
  value: unknown,
): value is QuizPreparationStatus {
  return (
    typeof value === "string" && QUIZ_PREPARATION_STATUSES.has(value)
  );
}

export function parseQuizPreparationResponse(
  value: unknown,
): QuizPreparationResponse {
  if (!isRecord(value)) {
    throw malformedResponse("quiz preparation");
  }
  if (
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.room_id) ||
    !isNonEmptyString(value.request_id) ||
    !isPreparationStatus(value.status) ||
    !isFiniteNumber(value.state_version) ||
    !Number.isInteger(value.state_version) ||
    value.state_version < 1 ||
    (value.error_category !== null &&
      value.error_category !== undefined &&
      !isNonEmptyString(value.error_category))
  ) {
    throw malformedResponse("quiz preparation");
  }
  return {
    id: value.id,
    room_id: value.room_id,
    request_id: value.request_id,
    status: value.status,
    state_version: value.state_version,
    error_category:
      value.error_category === undefined
        ? null
        : (value.error_category as string | null),
  };
}

const REVIEW_QUESTION_TYPES: ReadonlySet<string> = new Set([
  "MULTIPLE_CHOICE",
  "NUMERICAL",
  "WRITTEN",
]);

const REVIEW_OPTION_KEYS = ["id", "label"] as const;

const REVIEW_QUESTION_KEYS = [
  "session_question_id",
  "position",
  "question_type",
  "prompt",
  "max_marks",
  "options",
  "correct_option_id",
  "worked_explanation",
  "original_extract",
  "selected_option_id",
  "answer_text",
  "earned_marks",
  "feedback",
  "awarded_criterion_ids",
] as const;

const SESSION_REVIEW_KEYS = [
  "session_id",
  "room_id",
  "viewer_user_id",
  "total_earned_marks",
  "total_available_marks",
  "questions",
] as const;

function hasExactReviewKeys(
  value: Record<string, unknown>,
  keys: ReadonlyArray<string>,
): boolean {
  const actual = Object.keys(value);
  return (
    actual.length === keys.length && actual.every((key) => keys.includes(key))
  );
}

function parseReviewOption(value: unknown): ReviewQuestionOption {
  if (
    !isRecord(value) ||
    !hasExactReviewKeys(value, REVIEW_OPTION_KEYS) ||
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.label)
  ) {
    throw malformedResponse("session review");
  }
  return { id: value.id, label: value.label };
}

const CANONICAL_UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function isCanonicalUuid(value: unknown): value is string {
  return typeof value === "string" && CANONICAL_UUID_PATTERN.test(value);
}

function parseReviewQuestion(value: unknown): ReviewQuestionItem {
  if (!isRecord(value) || !hasExactReviewKeys(value, REVIEW_QUESTION_KEYS)) {
    throw malformedResponse("session review");
  }
  if (
    !isCanonicalUuid(value.session_question_id) ||
    !isFiniteNumber(value.position) ||
    !Number.isInteger(value.position) ||
    value.position < 0 ||
    typeof value.question_type !== "string" ||
    !REVIEW_QUESTION_TYPES.has(value.question_type) ||
    !isNonEmptyString(value.prompt) ||
    !isFiniteNumber(value.max_marks) ||
    !Number.isInteger(value.max_marks) ||
    value.max_marks < 1 ||
    value.max_marks > 6 ||
    !Array.isArray(value.options) ||
    (value.correct_option_id !== null &&
      !isNonEmptyString(value.correct_option_id)) ||
    typeof value.worked_explanation !== "string" ||
    (value.original_extract !== null &&
      !isNonEmptyString(value.original_extract)) ||
    (value.selected_option_id !== null &&
      !isNonEmptyString(value.selected_option_id)) ||
    (value.answer_text !== null && typeof value.answer_text !== "string") ||
    (typeof value.answer_text === "string" &&
      value.answer_text.length > 1000) ||
    !isFiniteNumber(value.earned_marks) ||
    !Number.isInteger(value.earned_marks) ||
    value.earned_marks < 0 ||
    typeof value.feedback !== "object" ||
    value.feedback === null ||
    Array.isArray(value.feedback) ||
    !Array.isArray(value.awarded_criterion_ids) ||
    !value.awarded_criterion_ids.every(
      (entry): entry is string => isNonEmptyString(entry),
    )
  ) {
    throw malformedResponse("session review");
  }
  if (value.earned_marks > value.max_marks) {
    throw malformedResponse("session review");
  }
  const options = value.options.map(parseReviewOption);
  if (new Set(options.map((option) => option.id)).size !== options.length) {
    throw malformedResponse("session review");
  }
  // Question-type consistency mirrors the realtime contract: multiple
  // choice carries 2-6 options and a matching correct option, while typed
  // questions carry no options and no correct option.
  if (value.question_type === "MULTIPLE_CHOICE") {
    if (
      options.length < 2 ||
      value.max_marks !== 1 ||
      options.length > 6 ||
      value.correct_option_id === null ||
      !options.some((option) => option.id === value.correct_option_id)
    ) {
      throw malformedResponse("session review");
    }
  } else if (
    options.length !== 0 ||
    value.correct_option_id !== null
  ) {
    throw malformedResponse("session review");
  }
  const feedback = value.feedback as Record<string, unknown>;
  // Written marking feedback is server-derived and only exists post-grade:
  // a non-empty written record must match the exact enriched shape, its
  // awarded marks must sum exactly to the earned marks, and its awarded IDs
  // must exactly match. An empty written record is legitimate only without
  // an earned grade (unanswered or ungraded), never as a graded outcome.
  // Deterministic and legacy outcomes keep their own small records; an
  // enriched-shaped record on them is misattributed and rejected.
  if (value.question_type === "WRITTEN") {
    if (Object.keys(feedback).length === 0) {
      if (value.earned_marks !== 0) {
        throw malformedResponse("session review");
      }
    } else {
      try {
        const enriched = parseEnrichedWrittenFeedback(feedback);
        if (
          enriched === null ||
          awardedMarksTotal(enriched) !== value.earned_marks
        ) {
          throw malformedResponse("session review");
        }
        const awardedIds = new Set(enriched.awarded.map((point) => point.id));
        if (
          awardedIds.size !== value.awarded_criterion_ids.length ||
          !value.awarded_criterion_ids.every((id: string) => awardedIds.has(id))
        ) {
          throw malformedResponse("session review");
        }
      } catch (error: unknown) {
        if (error instanceof InvalidGradingFeedbackError) {
          throw malformedResponse("session review");
        }
        throw error;
      }
    }
  } else if (value.question_type === "NUMERICAL") {
    if (value.selected_option_id !== null || value.awarded_criterion_ids.length !== 0) {
      throw malformedResponse("session review");
    }
    if (value.answer_text === null) {
      if (value.earned_marks !== 0 || Object.keys(feedback).length !== 0) throw malformedResponse("session review");
    } else {
      try {
        parseNumericalFeedback(feedback, value.earned_marks, value.max_marks);
      } catch (error: unknown) {
        if (error instanceof InvalidGradingFeedbackError) throw malformedResponse("session review");
        throw error;
      }
    }
  } else if (Object.keys(feedback).length !== 0 || value.awarded_criterion_ids.length !== 0) {
    throw malformedResponse("session review");
  }
  return {
    session_question_id: value.session_question_id,
    position: value.position,
    question_type: value.question_type,
    prompt: value.prompt,
    max_marks: value.max_marks,
    options,
    correct_option_id: value.correct_option_id,
    worked_explanation: value.worked_explanation,
    original_extract: value.original_extract,
    selected_option_id: value.selected_option_id,
    answer_text: value.answer_text,
    earned_marks: value.earned_marks,
    feedback,
    awarded_criterion_ids: [...value.awarded_criterion_ids],
  };
}

export function parseSessionReviewResponse(
  value: unknown,
): SessionReviewResponse {
  if (!isRecord(value) || !hasExactReviewKeys(value, SESSION_REVIEW_KEYS)) {
    throw malformedResponse("session review");
  }
  if (
    !isCanonicalUuid(value.session_id) ||
    !isCanonicalUuid(value.room_id) ||
    !isCanonicalUuid(value.viewer_user_id) ||
    !isFiniteNumber(value.total_earned_marks) ||
    !Number.isInteger(value.total_earned_marks) ||
    value.total_earned_marks < 0 ||
    !isFiniteNumber(value.total_available_marks) ||
    !Number.isInteger(value.total_available_marks) ||
    value.total_available_marks < 1 ||
    !Array.isArray(value.questions) ||
    value.questions.length === 0
  ) {
    throw malformedResponse("session review");
  }
  if (value.total_earned_marks > value.total_available_marks) {
    throw malformedResponse("session review");
  }
  const questions = value.questions.map(parseReviewQuestion);
  // Structural invariants for the durable finished outcome: backend
  // positions are zero-based and strictly increasing, every question is
  // unique, and the server totals equal the per-question sums exactly.
  // Nothing is recomputed or trusted blindly here.
  const seenQuestionIds = new Set<string>();
  let availableSum = 0;
  let earnedSum = 0;
  for (let index = 0; index < questions.length; index += 1) {
    const question = questions[index];
    if (question === undefined) {
      throw malformedResponse("session review");
    }
    if (index > 0) {
      const previous = questions[index - 1];
      if (
        previous === undefined ||
        question.position <= previous.position
      ) {
        throw malformedResponse("session review");
      }
    }
    if (seenQuestionIds.has(question.session_question_id)) {
      throw malformedResponse("session review");
    }
    seenQuestionIds.add(question.session_question_id);
    availableSum += question.max_marks;
    earnedSum += question.earned_marks;
  }
  if (
    availableSum !== value.total_available_marks ||
    earnedSum !== value.total_earned_marks
  ) {
    throw malformedResponse("session review");
  }
  return {
    session_id: value.session_id,
    room_id: value.room_id,
    viewer_user_id: value.viewer_user_id,
    total_earned_marks: value.total_earned_marks,
    total_available_marks: value.total_available_marks,
    questions,
  };
}

function parseRoomMemberListItem(value: unknown): RoomMemberListItem {
  if (!isRecord(value)) {
    throw malformedResponse("member list");
  }

  if (!isNonEmptyString(value.user_id) || !isNonEmptyString(value.display_name)) {
    throw malformedResponse("member list");
  }

  return {
    user_id: value.user_id,
    display_name: value.display_name,
  };
}

export function parseRoomMemberResponse(value: unknown): RoomMemberResponse {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.user_id) ||
    !isNonEmptyString(value.display_name) ||
    !isNonEmptyString(value.room_id)
  ) {
    throw malformedResponse("member");
  }

  return {
    user_id: value.user_id,
    display_name: value.display_name,
    room_id: value.room_id,
  };
}

export function parseJoinByCodeResponse(value: unknown): JoinByCodeResponse {
  if (!isRecord(value)) {
    throw malformedResponse("join room");
  }

  return {
    room: parseRoomResponse(value.room),
    member: parseRoomMemberResponse(value.member),
  };
}

export function parseActiveRoomResponse(value: unknown): RoomResponse | null {
  return value === null ? null : parseRoomResponse(value);
}

export function parseRoomMembersResponse(value: unknown): RoomMembersResponse {
  if (!isRecord(value) || !Array.isArray(value.members)) {
    throw malformedResponse("members");
  }

  if (
    !isNonEmptyString(value.room_id) ||
    !isFiniteNumber(value.member_count) ||
    !isRoomCapacity(value.maximum_members)
  ) {
    throw malformedResponse("members");
  }

  return {
    room_id: value.room_id,
    members: value.members.map(parseRoomMemberListItem),
    member_count: value.member_count,
    maximum_members: value.maximum_members,
  };
}

export function parseProfileResponse(value: unknown): ProfileResponse {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.display_name)
  ) {
    throw malformedResponse("profile");
  }

  return {
    id: value.id,
    display_name: value.display_name,
  };
}

export function parseAccountDeletionResponse(
  value: unknown,
): AccountDeletionResponse {
  if (
    !isRecord(value) ||
    value.status !== "account_deleted" ||
    value.local_deletion_complete !== true ||
    typeof value.provider_cleanup_pending !== "boolean"
  ) {
    throw malformedResponse("account deletion");
  }

  return {
    status: "account_deleted",
    local_deletion_complete: true,
    provider_cleanup_pending: value.provider_cleanup_pending,
  };
}

export function parseSafetyReportResponse(
  value: unknown,
): SafetyReportResponse {
  if (!isRecord(value) || value.status !== "report_received") {
    throw malformedResponse("safety report");
  }

  return { status: "report_received" };
}
