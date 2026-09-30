import { apiClient, type StudyRoomApiClient } from "./client";
import { MalformedResponseError } from "./errors";
import {
  isTopicForSubject,
  isUuidV4,
  isValidTotalMarks,
  type AdaptiveSubject,
  type AdaptiveTopic,
} from "../features/quiz/adaptiveQuiz";

export type SoloAttemptStatus =
  | "PREPARING" | "READY" | "IN_PROGRESS" | "AWAITING_MARKING"
  | "FINISHED" | "ABANDONED" | "FAILED";
export type SoloQuestionType = "MULTIPLE_CHOICE" | "NUMERICAL" | "WRITTEN";
export type SoloGradingStatus =
  | "SELF_CHECK_PENDING" | "PENDING" | "IN_PROGRESS"
  | "RETRYABLE" | "UNAVAILABLE" | "GRADED";
export type SoloMarkProvenance =
  | "DETERMINISTIC_OPTION" | "DETERMINISTIC_NUMERICAL"
  | "SELF_ASSESSED" | "AI_RUBRIC";

export type SoloQuestion = Readonly<{
  id: string;
  position: number;
  question_type: SoloQuestionType;
  max_marks: number;
  prompt: string;
  options: ReadonlyArray<Readonly<{ id: string; label: string }>>;
  original_extract: string | null;
}>;
export type SoloAnswer = Readonly<{
  question_id: string;
  selected_option_id: string | null;
  answer_text: string | null;
  accepted_at: string;
  grading_status: SoloGradingStatus;
  mark_provenance: SoloMarkProvenance;
  earned_marks: number | null;
  feedback: Readonly<Record<string, unknown>>;
}>;
export type SoloAttempt = Readonly<{
  id: string;
  request_id: string;
  status: SoloAttemptStatus;
  state_version: number;
  subject: AdaptiveSubject;
  topic: AdaptiveTopic;
  total_marks: number;
  current_question_position: number;
  created_at: string;
  started_at: string | null;
  terminal_at: string | null;
  questions: ReadonlyArray<SoloQuestion>;
  answers: ReadonlyArray<SoloAnswer>;
}>;
export type SoloSelfCheck = Readonly<{
  question_id: string;
  locked_answer: string;
  intended_answer: string;
  max_marks: number;
  criteria: ReadonlyArray<Readonly<{
    id: string;
    marks: number;
    marking_point: string;
    explanation: string;
  }>>;
}>;
export type SoloReview = Readonly<{
  attempt: SoloAttempt;
  questions: ReadonlyArray<Readonly<{
    question: SoloQuestion;
    answer: SoloAnswer;
    correct_option_id: string | null;
    intended_answer: string;
  }>>;
}>;
export type SoloCreateInput = Readonly<{
  request_id: string;
  subject: AdaptiveSubject;
  topic: AdaptiveTopic;
  total_marks: number;
}>;
export type SoloAnswerInput = Readonly<{
  question_id: string;
  selected_option_id?: string;
  text?: string;
}>;

const ATTEMPT_STATUSES: readonly string[] = [
  "PREPARING", "READY", "IN_PROGRESS", "AWAITING_MARKING", "FINISHED", "ABANDONED", "FAILED",
];
const QUESTION_TYPES: readonly string[] = ["MULTIPLE_CHOICE", "NUMERICAL", "WRITTEN"];
const GRADING_STATUSES: readonly string[] = [
  "SELF_CHECK_PENDING", "PENDING", "IN_PROGRESS", "RETRYABLE", "UNAVAILABLE", "GRADED",
];
const MARK_PROVENANCE: readonly string[] = [
  "DETERMINISTIC_OPTION", "DETERMINISTIC_NUMERICAL", "SELF_ASSESSED", "AI_RUBRIC",
];

function malformed(): never {
  throw new MalformedResponseError("The StudyRoom server returned an invalid solo quiz response.");
}

function object(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return malformed();
  const record = value as Record<string, unknown>;
  if (
    Object.keys(record).length !== keys.length ||
    keys.some((key) => !Object.prototype.hasOwnProperty.call(record, key)) ||
    Object.keys(record).some((key) => !keys.includes(key))
  ) return malformed();
  return record;
}

function text(value: unknown, maxLength = 4_000): string {
  if (typeof value !== "string" || value.length > maxLength) return malformed();
  return value;
}

function uuid(value: unknown): string {
  const parsed = text(value, 36);
  if (!isUuidV4(parsed)) return malformed();
  return parsed;
}

function instant(value: unknown): string {
  const parsed = text(value, 40);
  if (!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(parsed) || Number.isNaN(Date.parse(parsed))) {
    return malformed();
  }
  return parsed;
}

function optionalText(value: unknown, maxLength = 4_000): string | null {
  return value === null ? null : text(value, maxLength);
}

function optionalInstant(value: unknown): string | null {
  return value === null ? null : instant(value);
}

function number(value: unknown, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) {
    return malformed();
  }
  return value;
}

function choice<T extends string>(value: unknown, options: readonly string[]): T {
  if (typeof value !== "string" || !options.includes(value)) return malformed();
  return value as T;
}

function array(value: unknown, maxLength: number): unknown[] {
  if (!Array.isArray(value) || value.length > maxLength) return malformed();
  return value;
}

export function parseSoloQuestion(value: unknown): SoloQuestion {
  const row = object(value, [
    "id", "position", "question_type", "max_marks", "prompt", "options", "original_extract",
  ]);
  const questionType = choice<SoloQuestionType>(row.question_type, QUESTION_TYPES);
  const maxMarks = number(row.max_marks, 1, 6);
  const options = array(row.options, 8).map((entry) => {
    const option = object(entry, ["id", "label"]);
    return { id: text(option.id, 64), label: text(option.label, 1_000) };
  });
  if ((questionType === "MULTIPLE_CHOICE") !== (options.length > 0)) return malformed();
  return {
    id: uuid(row.id), position: number(row.position, 0, 39),
    question_type: questionType, max_marks: maxMarks,
    prompt: text(row.prompt), options,
    original_extract: optionalText(row.original_extract),
  };
}

export function parseSoloAnswer(value: unknown): SoloAnswer {
  const row = object(value, [
    "question_id", "selected_option_id", "answer_text", "accepted_at",
    "grading_status", "mark_provenance", "earned_marks", "feedback",
  ]);
  const status = choice<SoloGradingStatus>(row.grading_status, GRADING_STATUSES);
  const earnedMarks = row.earned_marks === null ? null : number(row.earned_marks, 0, 6);
  if ((status === "GRADED") !== (earnedMarks !== null)) return malformed();
  const selectedOptionId = optionalText(row.selected_option_id, 64);
  const answerText = optionalText(row.answer_text, 1_000);
  if ((selectedOptionId === null) === (answerText === null)) return malformed();
  if (row.feedback === null || typeof row.feedback !== "object" || Array.isArray(row.feedback)) {
    return malformed();
  }
  return {
    question_id: uuid(row.question_id), selected_option_id: selectedOptionId,
    answer_text: answerText, accepted_at: instant(row.accepted_at),
    grading_status: status,
    mark_provenance: choice<SoloMarkProvenance>(row.mark_provenance, MARK_PROVENANCE),
    earned_marks: earnedMarks, feedback: row.feedback as Record<string, unknown>,
  };
}

export function parseSoloAttempt(value: unknown): SoloAttempt {
  const row = object(value, [
    "id", "request_id", "status", "state_version", "subject", "topic", "total_marks",
    "current_question_position", "created_at", "started_at", "terminal_at", "questions", "answers",
  ]);
  if (
    typeof row.subject !== "string" || typeof row.topic !== "string" ||
    !isTopicForSubject(row.subject, row.topic)
  ) return malformed();
  const status = choice<SoloAttemptStatus>(row.status, ATTEMPT_STATUSES);
  const questions = array(row.questions, 40).map(parseSoloQuestion);
  const answers = array(row.answers, 40).map(parseSoloAnswer);
  const position = number(row.current_question_position, 0, 40);
  if (
    position > questions.length && questions.length > 0 ||
    new Set(questions.map((question) => question.id)).size !== questions.length ||
    questions.some((question, index) => question.position !== index) ||
    new Set(answers.map((answer) => answer.question_id)).size !== answers.length ||
    answers.some((answer) => !questions.some((question) => question.id === answer.question_id)) ||
    (["PREPARING", "READY", "FAILED", "ABANDONED"] as readonly string[]).includes(status) && questions.length > 0 && status !== "ABANDONED"
  ) return malformed();
  const totalMarks = number(row.total_marks, 5, 40);
  if (questions.length > 0 && questions.reduce((sum, question) => sum + question.max_marks, 0) !== totalMarks) {
    return malformed();
  }
  return {
    id: uuid(row.id), request_id: uuid(row.request_id), status,
    state_version: number(row.state_version, 1, Number.MAX_SAFE_INTEGER),
    subject: row.subject as AdaptiveSubject, topic: row.topic as AdaptiveTopic,
    total_marks: totalMarks, current_question_position: position,
    created_at: instant(row.created_at), started_at: optionalInstant(row.started_at),
    terminal_at: optionalInstant(row.terminal_at), questions, answers,
  };
}

export function parseSoloSelfCheck(value: unknown): SoloSelfCheck {
  const row = object(value, [
    "question_id", "locked_answer", "intended_answer", "max_marks", "criteria",
  ]);
  const maxMarks = number(row.max_marks, 1, 4);
  const criteria = array(row.criteria, 4).map((entry) => {
    const criterion = object(entry, ["id", "marks", "marking_point", "explanation"]);
    return {
      id: text(criterion.id, 64), marks: number(criterion.marks, 1, 4),
      marking_point: text(criterion.marking_point),
      explanation: text(criterion.explanation),
    };
  });
  if (
    criteria.length === 0 ||
    new Set(criteria.map((criterion) => criterion.id)).size !== criteria.length ||
    criteria.reduce((sum, criterion) => sum + criterion.marks, 0) !== maxMarks
  ) return malformed();
  return {
    question_id: uuid(row.question_id), locked_answer: text(row.locked_answer, 1_000),
    intended_answer: text(row.intended_answer), max_marks: maxMarks, criteria,
  };
}

export function parseSoloReview(value: unknown): SoloReview {
  const row = object(value, ["attempt", "questions"]);
  const attempt = parseSoloAttempt(row.attempt);
  if (attempt.status !== "FINISHED") return malformed();
  const questions = array(row.questions, 40).map((entry) => {
    const item = object(entry, ["question", "answer", "correct_option_id", "intended_answer"]);
    return {
      question: parseSoloQuestion(item.question), answer: parseSoloAnswer(item.answer),
      correct_option_id: optionalText(item.correct_option_id, 64),
      intended_answer: text(item.intended_answer),
    };
  });
  if (
    questions.length !== attempt.questions.length ||
    questions.some((item, index) =>
      item.question.id !== attempt.questions[index]?.id ||
      item.answer.question_id !== item.question.id ||
      !attempt.answers.some((answer) => answer.question_id === item.question.id)
    )
  ) return malformed();
  return { attempt, questions };
}

function attemptPath(attemptId: string): string {
  return `/me/solo-attempts/${encodeURIComponent(attemptId)}`;
}

export async function getActiveSoloAttempt(client: StudyRoomApiClient = apiClient): Promise<SoloAttempt | null> {
  const response = await client.requestJson("/me/solo-attempts/active");
  return response === null ? null : parseSoloAttempt(response);
}

export async function getSoloAttempt(attemptId: string, client: StudyRoomApiClient = apiClient): Promise<SoloAttempt> {
  return parseSoloAttempt(await client.requestJson(attemptPath(attemptId)));
}

export async function createSoloAttempt(input: SoloCreateInput, client: StudyRoomApiClient = apiClient): Promise<SoloAttempt> {
  if (!isUuidV4(input.request_id) || !isTopicForSubject(input.subject, input.topic) || !isValidTotalMarks(input.total_marks)) {
    throw new Error("Invalid solo quiz selection.");
  }
  return parseSoloAttempt(await client.requestJson("/me/solo-attempts", {
    method: "POST", body: input, timeoutMs: 15_000,
  }));
}

export async function startSoloAttempt(attemptId: string, client: StudyRoomApiClient = apiClient): Promise<SoloAttempt> {
  return parseSoloAttempt(await client.requestJson(`${attemptPath(attemptId)}/start`, { method: "POST" }));
}

export async function submitSoloAnswer(attemptId: string, input: SoloAnswerInput, client: StudyRoomApiClient = apiClient): Promise<SoloAnswer> {
  return parseSoloAnswer(await client.requestJson(`${attemptPath(attemptId)}/answers`, { method: "POST", body: input }));
}

export async function getSoloSelfCheck(attemptId: string, questionId: string, client: StudyRoomApiClient = apiClient): Promise<SoloSelfCheck> {
  return parseSoloSelfCheck(await client.requestJson(`${attemptPath(attemptId)}/questions/${encodeURIComponent(questionId)}/self-check`));
}

export async function finalizeSoloSelfCheck(attemptId: string, questionId: string, selectedCriterionIds: readonly string[], client: StudyRoomApiClient = apiClient): Promise<SoloAnswer> {
  return parseSoloAnswer(await client.requestJson(`${attemptPath(attemptId)}/questions/${encodeURIComponent(questionId)}/self-check`, {
    method: "POST", body: { selected_criterion_ids: selectedCriterionIds },
  }));
}

export async function retrySoloMarking(attemptId: string, client: StudyRoomApiClient = apiClient): Promise<number> {
  const response = object(await client.requestJson(`${attemptPath(attemptId)}/retry-marking`, { method: "POST" }), ["queued_answers"]);
  return number(response.queued_answers, 0, 40);
}

export async function abandonSoloAttempt(attemptId: string, client: StudyRoomApiClient = apiClient): Promise<SoloAttempt> {
  return parseSoloAttempt(await client.requestJson(`${attemptPath(attemptId)}/abandon`, { method: "POST" }));
}

export async function getSoloReview(attemptId: string, client: StudyRoomApiClient = apiClient): Promise<SoloReview> {
  return parseSoloReview(await client.requestJson(`${attemptPath(attemptId)}/review`));
}
