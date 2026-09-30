import {
  parseCanonicalUuid,
  parseServerEvent,
  type CanonicalUuid,
  type LeaderboardEntryPayload,
  type RoomStatePayload,
  type StateSnapshotPayload,
} from "../../realtime/protocol";

export const ROOM_ID = parseCanonicalUuid(
  "11111111-1111-4111-8111-111111111111",
);
export const OTHER_ROOM_ID = parseCanonicalUuid(
  "11111111-1111-4111-8111-222222222222",
);
export const SESSION_ID = parseCanonicalUuid(
  "22222222-2222-4222-8222-222222222222",
);
export const NEW_SESSION_ID = parseCanonicalUuid(
  "22222222-2222-4222-8222-333333333333",
);
export const QUESTION_ID = parseCanonicalUuid(
  "33333333-3333-4333-8333-333333333333",
);
export const NEXT_QUESTION_ID = parseCanonicalUuid(
  "33333333-3333-4333-8333-444444444444",
);
export const MEMBER_ID = parseCanonicalUuid(
  "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
);
export const SERVER_TIME = "2030-01-01T12:00:00Z";
export const CLOSES_AT = "2030-01-01T12:00:20Z";
export const REVEAL_ENDS_AT = "2030-01-01T12:00:23Z";

function event(type: string, payload: unknown): string {
  return JSON.stringify({ protocol_version: 2, type, payload });
}

export type FixtureQuizSettings = {
  quizMode?: "LEGACY_PHYSICS" | "ADAPTIVE";
  educationLevel?: string | null;
  quizSubject?: string | null;
  quizTopic?: string | null;
  targetTotalMarks?: number | null;
  preparationStatus?:
    | "GENERATING"
    | "READY"
    | "FAILED"
    | "CONSUMED"
    | "SUPERSEDED"
    | null;
  preparationVersion?: number | null;
  preparationErrorCategory?: string | null;
};

export function makeRoomState(
  options: {
    viewerReady?: boolean;
    viewerRole?: "host" | "member";
    memberName?: string;
    includeMember?: boolean;
  } & FixtureQuizSettings = {},
): RoomStatePayload {
  const participants = [
    {
      user_id: ROOM_ID,
      display_name: "Room Owner",
      role: "host",
      ready: true,
      online: true,
    },
  ];
  if (options.includeMember ?? true) {
    participants.push({
      user_id: MEMBER_ID,
      display_name: options.memberName ?? "Second User",
      role: "member",
      ready: options.viewerReady ?? false,
      online: true,
    });
  }
  const parsed = parseServerEvent(
    event("ROOM_STATE", {
      room_id: ROOM_ID,
      name:
        (options.quizMode ?? "LEGACY_PHYSICS") === "ADAPTIVE"
          ? "GCSE Physics"
          : "Physics Sprint",
      join_code: "PHYS42",
      maximum_members: 8,
      viewer_role: options.viewerRole ?? "host",
      participants,
      viewer_ready: options.viewerReady ?? false,
      quiz_mode: options.quizMode ?? "LEGACY_PHYSICS",
      education_level: options.educationLevel ?? null,
      quiz_subject: options.quizSubject ?? null,
      quiz_topic: options.quizTopic ?? null,
      target_total_marks: options.targetTotalMarks ?? null,
      active_preparation_status: options.preparationStatus ?? null,
      active_preparation_version: options.preparationVersion ?? null,
      active_preparation_error_category:
        options.preparationErrorCategory ?? null,
    }),
  );
  if (parsed.type !== "ROOM_STATE") {
    throw new Error("Expected a room-state fixture.");
  }
  return parsed.payload;
}

export function makeAdaptiveRoomState(
  options: {
    viewerReady?: boolean;
    viewerRole?: "host" | "member";
    memberReady?: boolean;
    preparationStatus?:
      | "GENERATING"
      | "READY"
      | "FAILED"
      | "CONSUMED"
      | "SUPERSEDED"
      | null;
    preparationVersion?: number | null;
    preparationErrorCategory?: string | null;
  } = {},
): RoomStatePayload {
  const participants = [
    {
      user_id: ROOM_ID,
      display_name: "Room Owner",
      role: "host",
      ready: true,
      online: true,
    },
    {
      user_id: MEMBER_ID,
      display_name: "Second User",
      role: "member",
      ready: options.memberReady ?? options.viewerReady ?? false,
      online: true,
    },
  ];
  const parsed = parseServerEvent(
    event("ROOM_STATE", {
      room_id: ROOM_ID,
      name: "GCSE Physics",
      join_code: "PHYS42",
      maximum_members: 8,
      viewer_role: options.viewerRole ?? "host",
      participants,
      viewer_ready: options.viewerReady ?? false,
      quiz_mode: "ADAPTIVE",
      education_level: "GCSE",
      quiz_subject: "physics",
      quiz_topic: "energy",
      target_total_marks: 20,
      active_preparation_status: options.preparationStatus ?? null,
      active_preparation_version: options.preparationVersion ?? null,
      active_preparation_error_category:
        options.preparationErrorCategory ?? null,
    }),
  );
  if (parsed.type !== "ROOM_STATE") {
    throw new Error("Expected an adaptive room-state fixture.");
  }
  return parsed.payload;
}

function openQuestion(
  sessionQuestionId: CanonicalUuid,
  questionNumber = 1,
  overrides: {
    questionType?: "MULTIPLE_CHOICE" | "NUMERICAL" | "WRITTEN";
    maxMarks?: number;
    options?: Array<{ id: string; label: string }>;
    originalExtract?: string | null;
  } = {},
) {
  const questionType = overrides.questionType ?? "MULTIPLE_CHOICE";
  return {
    session_question_id: sessionQuestionId,
    prompt: "What is the SI unit of force?",
    options:
      overrides.options ??
      (questionType === "MULTIPLE_CHOICE"
        ? [
            { id: "joule", label: "Joule" },
            { id: "newton", label: "Newton" },
          ]
        : []),
    question_number: questionNumber,
    total_questions: 5,
    closes_at: CLOSES_AT,
    server_time: SERVER_TIME,
    question_type: questionType,
    max_marks: overrides.maxMarks ?? 1,
    original_extract: overrides.originalExtract ?? null,
  };
}

function parseSnapshot(payload: unknown): StateSnapshotPayload {
  const parsed = parseServerEvent(event("STATE_SNAPSHOT", payload));
  if (parsed.type !== "STATE_SNAPSHOT") {
    throw new Error("Expected a snapshot fixture.");
  }
  return parsed.payload;
}

export function makeLobbySnapshot(
  roomState = makeRoomState(),
  options: { gradingRetryNeeded?: boolean } = {},
): StateSnapshotPayload {
  return parseSnapshot({
    server_time: SERVER_TIME,
    room_state: roomState,
    session_id: null,
    viewer_participated: false,
    state_version: 0,
    status: null,
    current_question_number: null,
    total_question_count: 5,
    question: null,
    closes_at: null,
    reveal_ends_at: null,
    viewer_submission: null,
    leaderboard: [],
    finished_at: null,
    quiz_mode: roomState.quiz_mode,
    total_available_marks: 5,
    grading_retry_needed: options.gradingRetryNeeded ?? false,
  });
}

export function makeOpenSnapshot(
  options: {
    sessionId?: CanonicalUuid;
    stateVersion?: number;
    questionId?: CanonicalUuid;
    questionNumber?: number;
    selectedOptionId?: string | null;
    answerText?: string | null;
    gradingStatus?:
      | "PENDING"
      | "IN_PROGRESS"
      | "GRADED"
      | "RETRYABLE"
      | "UNAVAILABLE";
    roomState?: RoomStatePayload;
    questionType?: "MULTIPLE_CHOICE" | "NUMERICAL" | "WRITTEN";
    maxMarks?: number;
    originalExtract?: string | null;
    totalAvailableMarks?: number;
    gradingRetryNeeded?: boolean;
  } = {},
): StateSnapshotPayload {
  const questionId = options.questionId ?? QUESTION_ID;
  const question = openQuestion(questionId, options.questionNumber, {
    questionType: options.questionType,
    maxMarks: options.maxMarks,
    originalExtract: options.originalExtract,
  });
  const hasSubmission =
    options.selectedOptionId != null || options.answerText != null;
  const roomState = options.roomState ?? makeRoomState();
  return parseSnapshot({
    server_time: SERVER_TIME,
    room_state: roomState,
    session_id: options.sessionId ?? SESSION_ID,
    viewer_participated: true,
    state_version: options.stateVersion ?? 1,
    status: "QUESTION_OPEN",
    current_question_number: options.questionNumber ?? 1,
    total_question_count: 5,
    question,
    closes_at: CLOSES_AT,
    reveal_ends_at: null,
    viewer_submission: !hasSubmission
      ? null
      : {
          session_question_id: questionId,
          selected_option_id: options.selectedOptionId ?? null,
          answer_text: options.answerText ?? null,
          grading_status: options.gradingStatus ?? "GRADED",
        },
    leaderboard: [],
    finished_at: null,
    quiz_mode: roomState.quiz_mode,
    total_available_marks: options.totalAvailableMarks ?? 5,
    grading_retry_needed: options.gradingRetryNeeded ?? false,
  });
}

export function makeGradingSnapshot(
  options: {
    sessionId?: CanonicalUuid;
    stateVersion?: number;
    questionId?: CanonicalUuid;
    selectedOptionId?: string | null;
    answerText?: string | null;
    gradingStatus?:
      | "PENDING"
      | "IN_PROGRESS"
      | "GRADED"
      | "RETRYABLE"
      | "UNAVAILABLE";
    roomState?: RoomStatePayload;
    questionType?: "MULTIPLE_CHOICE" | "NUMERICAL" | "WRITTEN";
    maxMarks?: number;
    totalAvailableMarks?: number;
    gradingRetryNeeded?: boolean;
  } = {},
): StateSnapshotPayload {
  const open = makeOpenSnapshot({
    ...options,
    selectedOptionId:
      options.selectedOptionId === undefined
        ? "newton"
        : options.selectedOptionId,
  });
  if (open.status !== "QUESTION_OPEN") {
    throw new Error("Expected an open fixture.");
  }
  return parseSnapshot({
    ...open,
    status: "QUESTION_GRADING",
    state_version: options.stateVersion ?? 2,
  });
}

export function makeRevealSnapshot(
  options: {
    sessionId?: CanonicalUuid;
    stateVersion?: number;
    questionId?: CanonicalUuid;
    selectedOptionId?: string | null;
    answerText?: string | null;
    earnedMarks?: number | null;
    maxMarks?: number;
    questionType?: "MULTIPLE_CHOICE" | "NUMERICAL" | "WRITTEN";
    gradingStatus?:
      | "PENDING"
      | "IN_PROGRESS"
      | "GRADED"
      | "RETRYABLE"
      | "UNAVAILABLE";
    feedback?: Record<string, unknown>;
    awardedCriterionIds?: string[];
    roomState?: RoomStatePayload;
    totalAvailableMarks?: number;
    gradingRetryNeeded?: boolean;
  } = {},
): StateSnapshotPayload {
  const questionId = options.questionId ?? QUESTION_ID;
  const questionType = options.questionType ?? "MULTIPLE_CHOICE";
  const maxMarks = options.maxMarks ?? 1;
  const selectedOptionId =
    options.selectedOptionId === undefined && options.answerText === undefined
      ? questionType === "MULTIPLE_CHOICE"
        ? "newton"
        : null
      : (options.selectedOptionId ?? null);
  const answerText = options.answerText ?? null;
  const hasSubmission = selectedOptionId !== null || answerText !== null;
  const earnedMarks =
    options.earnedMarks !== undefined
      ? options.earnedMarks
      : selectedOptionId === "newton" && questionType === "MULTIPLE_CHOICE"
        ? maxMarks
        : 0;
  const roomState = options.roomState ?? makeRoomState();
  return parseSnapshot({
    server_time: SERVER_TIME,
    room_state: roomState,
    session_id: options.sessionId ?? SESSION_ID,
    viewer_participated: true,
    state_version: options.stateVersion ?? 2,
    status: "QUESTION_REVEAL",
    current_question_number: 1,
    total_question_count: 5,
    question: {
      ...openQuestion(questionId, 1, {
        questionType,
        maxMarks,
      }),
      correct_option_id:
        questionType === "MULTIPLE_CHOICE" ? "newton" : null,
      worked_explanation: "Force is measured in newtons.",
    },
    closes_at: CLOSES_AT,
    reveal_ends_at: REVEAL_ENDS_AT,
    viewer_submission: !hasSubmission
      ? null
      : {
          session_question_id: questionId,
          selected_option_id: selectedOptionId,
          answer_text: answerText,
          is_correct: earnedMarks === maxMarks,
          points: earnedMarks === maxMarks ? 100 : 0,
          earned_marks: earnedMarks,
          max_marks: maxMarks,
          grading_status: options.gradingStatus ?? "GRADED",
          feedback: options.feedback ?? {},
          awarded_criterion_ids: options.awardedCriterionIds ?? [],
        },
    leaderboard: [
      {
        user_id: ROOM_ID,
        display_name: "Room Owner",
        total_points: 100,
        correct_answers: 1,
        rank: 1,
        earned_marks: maxMarks,
        total_available_marks: options.totalAvailableMarks ?? 5,
      },
    ],
    finished_at: null,
    quiz_mode: roomState.quiz_mode,
    total_available_marks: options.totalAvailableMarks ?? 5,
    grading_retry_needed: options.gradingRetryNeeded ?? false,
  });
}

export function makeFinishedSnapshot(
  options: {
    sessionId?: CanonicalUuid;
    stateVersion?: number;
    leaderboard?: LeaderboardEntryPayload[];
  } = {},
): StateSnapshotPayload {
  const reveal = makeRevealSnapshot({
    sessionId: options.sessionId,
    stateVersion: options.stateVersion ?? 10,
  });
  if (reveal.status !== "QUESTION_REVEAL") {
    throw new Error("Expected a reveal fixture.");
  }
  return parseSnapshot({
    ...reveal,
    status: "FINISHED",
    state_version: options.stateVersion ?? 10,
    reveal_ends_at: null,
    leaderboard: options.leaderboard ?? reveal.leaderboard,
    finished_at: "2030-01-01T12:02:00Z",
  });
}

export function serverEventFrame(type: string, payload: unknown): string {
  return event(type, payload);
}
