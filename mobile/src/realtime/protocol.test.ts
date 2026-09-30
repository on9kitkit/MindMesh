import assert from "node:assert/strict";
import test from "node:test";

import {
  RealtimeProtocolError,
  UnsupportedProtocolVersionError,
  parseServerEvent,
} from "./protocol";

const ROOM_ID = "11111111-1111-4111-8111-111111111111";
const SESSION_ID = "22222222-2222-4222-8222-222222222222";
const QUESTION_ID = "33333333-3333-4333-8333-333333333333";
const MEMBER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SERVER_TIME = "2030-01-01T12:00:00Z";
const CLOSES_AT = "2030-01-01T12:00:20+00:00";
const REVEAL_ENDS_AT = "2030-01-01T12:00:23.500000Z";

const roomState = {
  room_id: ROOM_ID,
  name: "Physics Sprint",
  join_code: "PHYS42",
  maximum_members: 8,
  viewer_role: "host",
  participants: [
    {
      user_id: ROOM_ID,
      display_name: "Room Owner",
      role: "host",
      ready: false,
      online: true,
    },
    {
      user_id: MEMBER_ID,
      display_name: "Second User",
      role: "member",
      ready: false,
      online: true,
    },
  ],
  viewer_ready: false,
  quiz_mode: "LEGACY_PHYSICS",
  education_level: null,
  quiz_subject: null,
  quiz_topic: null,
  target_total_marks: null,
  active_preparation_status: null,
  active_preparation_version: null,
  active_preparation_error_category: null,
};

const openQuestion = {
  session_question_id: QUESTION_ID,
  prompt: "What is the SI unit of force?",
  options: [
    { id: "joule", label: "Joule" },
    { id: "newton", label: "Newton" },
  ],
  question_number: 1,
  total_questions: 5,
  closes_at: CLOSES_AT,
  server_time: SERVER_TIME,
  question_type: "MULTIPLE_CHOICE",
  max_marks: 1,
  original_extract: null,
};

const revealedQuestion = {
  ...openQuestion,
  correct_option_id: "newton",
  worked_explanation: "Force is measured in newtons.",
};

const leaderboard = [
  {
    user_id: ROOM_ID,
    display_name: "Room Owner",
    total_points: 100,
    correct_answers: 1,
    rank: 1,
    earned_marks: 1,
    total_available_marks: 5,
  },
  {
    user_id: MEMBER_ID,
    display_name: "Second User",
    total_points: 0,
    correct_answers: 0,
    rank: 2,
    earned_marks: 0,
    total_available_marks: 5,
  },
];

const openSnapshot = {
  server_time: SERVER_TIME,
  room_state: roomState,
  session_id: SESSION_ID,
  viewer_participated: true,
  state_version: 1,
  status: "QUESTION_OPEN",
  current_question_number: 1,
  total_question_count: 5,
  question: openQuestion,
  closes_at: CLOSES_AT,
  reveal_ends_at: null,
  viewer_submission: {
    session_question_id: QUESTION_ID,
    selected_option_id: "newton",
    answer_text: null,
    grading_status: "GRADED",
  },
  leaderboard,
  finished_at: null,
  quiz_mode: "LEGACY_PHYSICS",
  total_available_marks: 5,
  grading_retry_needed: false,
};

const revealSnapshot = {
  ...openSnapshot,
  state_version: 2,
  status: "QUESTION_REVEAL",
  question: revealedQuestion,
  reveal_ends_at: REVEAL_ENDS_AT,
  viewer_submission: {
    session_question_id: QUESTION_ID,
    selected_option_id: "newton",
    answer_text: null,
    is_correct: true,
    points: 100,
    earned_marks: 1,
    max_marks: 1,
    grading_status: "GRADED",
    feedback: {},
    awarded_criterion_ids: [],
  },
};

const finishedSnapshot = {
  ...revealSnapshot,
  state_version: 10,
  status: "FINISHED",
  reveal_ends_at: null,
  finished_at: "2030-01-01T12:02:00Z",
};

function wire(type: string, payload: unknown): Record<string, unknown> {
  return { protocol_version: 2, type, payload };
}

function parse(value: unknown) {
  return parseServerEvent(JSON.stringify(value));
}

function assertInvalid(value: unknown): void {
  assert.throws(
    () => parse(value),
    (error: unknown) => {
      assert.ok(error instanceof RealtimeProtocolError);
      assert.equal(error.code, "invalid_event");
      return true;
    },
  );
}

test("parses every protocol-v1 server event", () => {
  const events = [
    wire("CONNECTED", { server_time: SERVER_TIME }),
    wire("ROOM_STATE", roomState),
    wire("STATE_SNAPSHOT", openSnapshot),
    wire("SESSION_STARTED", {
      session_id: SESSION_ID,
      state_version: 1,
    }),
    wire("QUESTION_OPENED", {
      session_id: SESSION_ID,
      state_version: 1,
      question: openQuestion,
    }),
    wire("ANSWER_ACCEPTED", {
      session_id: SESSION_ID,
      state_version: 1,
      session_question_id: QUESTION_ID,
      selected_option_id: "newton",
      answer_text: null,
      grading_status: "GRADED",
      accepted_at: SERVER_TIME,
    }),
    wire("QUESTION_REVEALED", {
      session_id: SESSION_ID,
      state_version: 2,
      question: revealedQuestion,
      viewer_submission: {
        session_question_id: QUESTION_ID,
        selected_option_id: "newton",
        answer_text: null,
        is_correct: true,
        points: 100,
        earned_marks: 1,
        max_marks: 1,
        grading_status: "GRADED",
        feedback: {},
        awarded_criterion_ids: [],
      },
      leaderboard,
    }),
    wire("SESSION_FINISHED", {
      session_id: SESSION_ID,
      state_version: 10,
      leaderboard,
      finished_at: "2030-01-01T12:02:00Z",
    }),
    wire("ERROR", {
      code: "future_backend_error_code",
      message: "The command could not be completed.",
    }),
  ];

  assert.deepEqual(
    events.map((event) => parse(event).type),
    [
      "CONNECTED",
      "ROOM_STATE",
      "STATE_SNAPSHOT",
      "SESSION_STARTED",
      "QUESTION_OPENED",
      "ANSWER_ACCEPTED",
      "QUESTION_REVEALED",
      "SESSION_FINISHED",
      "ERROR",
    ],
  );
});

test("parses lobby, reveal, and finished snapshot variants", () => {
  const lobby = parse(
    wire("STATE_SNAPSHOT", {
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
      quiz_mode: "LEGACY_PHYSICS",
      total_available_marks: 5,
      grading_retry_needed: false,
    }),
  );
  const reveal = parse(wire("STATE_SNAPSHOT", revealSnapshot));
  const finished = parse(wire("STATE_SNAPSHOT", finishedSnapshot));

  assert.equal(lobby.type, "STATE_SNAPSHOT");
  assert.equal(lobby.payload.viewer_participated, false);
  assert.equal(reveal.type, "STATE_SNAPSHOT");
  assert.equal(reveal.payload.status, "QUESTION_REVEAL");
  assert.equal(finished.type, "STATE_SNAPSHOT");
  assert.equal(finished.payload.status, "FINISHED");
  assert.equal(finished.payload.viewer_participated, true);
});

test("malformed JSON produces a typed protocol error", () => {
  assert.throws(
    () => parseServerEvent("{"),
    (error: unknown) => {
      assert.ok(error instanceof RealtimeProtocolError);
      assert.equal(error.code, "malformed_json");
      return true;
    },
  );
});

test("unsupported protocol versions produce an incompatibility error", () => {
  for (const protocolVersion of [1, 3]) {
    assert.throws(
      () =>
        parse({
          protocol_version: protocolVersion,
          type: "CONNECTED",
          payload: {},
        }),
      (error: unknown) => error instanceof UnsupportedProtocolVersionError,
    );
  }
});

test("rejects unknown event types and unknown top-level fields", () => {
  assertInvalid(wire("FUTURE_EVENT", {}));
  assertInvalid({
    ...wire("CONNECTED", { server_time: SERVER_TIME }),
    trace_id: "not-in-protocol-v2",
  });
});

test("keeps error codes open-ended but rejects empty values", () => {
  const parsed = parse(
    wire("ERROR", {
      code: "new_safe_backend_code",
      message: "A safe message.",
    }),
  );
  assert.equal(parsed.type, "ERROR");
  assert.equal(parsed.payload.code, "new_safe_backend_code");

  assertInvalid(wire("ERROR", { code: "  ", message: "A safe message." }));
});

test("rejects unknown nested fields recursively", () => {
  assertInvalid(
    wire("ROOM_STATE", {
      ...roomState,
      participants: [
        {
          ...roomState.participants[0],
          selected_option_id: "newton",
        },
      ],
    }),
  );
});

test("rejects invalid UUIDs, timestamps, roles, and statuses", () => {
  assertInvalid(
    wire("SESSION_STARTED", {
      session_id: "NOT-A-CANONICAL-UUID",
      state_version: 1,
    }),
  );
  assertInvalid(wire("CONNECTED", { server_time: "2030-01-01T12:00:00" }));
  assertInvalid(wire("ROOM_STATE", { ...roomState, viewer_role: "owner" }));
  assertInvalid(
    wire("STATE_SNAPSHOT", { ...openSnapshot, status: "WAITING" }),
  );
});

test("rejects room capacity above the absolute server maximum", () => {
  const largeRoom = parse(
    wire("ROOM_STATE", { ...roomState, maximum_members: 20 }),
  );
  assert.equal(largeRoom.type, "ROOM_STATE");
  assert.equal(largeRoom.payload.maximum_members, 20);
  assertInvalid(
    wire("ROOM_STATE", { ...roomState, maximum_members: 21 }),
  );
});

test("rejects invalid leaderboard entries and question options", () => {
  assertInvalid(
    wire("SESSION_FINISHED", {
      session_id: SESSION_ID,
      state_version: 10,
      leaderboard: [{ ...leaderboard[0], rank: 0 }],
      finished_at: SERVER_TIME,
    }),
  );
  assertInvalid(
    wire("QUESTION_OPENED", {
      session_id: SESSION_ID,
      state_version: 1,
      question: {
        ...openQuestion,
        options: [{ id: "newton", label: 42 }, openQuestion.options[0]],
      },
    }),
  );
});

test("rejects a correct answer in an open question", () => {
  assertInvalid(
    wire("QUESTION_OPENED", {
      session_id: SESSION_ID,
      state_version: 1,
      question: { ...openQuestion, correct_option_id: "newton" },
    }),
  );
});

test("rejects correctness and points in an open viewer submission", () => {
  assertInvalid(
    wire("STATE_SNAPSHOT", {
      ...openSnapshot,
      viewer_submission: {
        ...openSnapshot.viewer_submission,
        is_correct: true,
      },
    }),
  );
  assertInvalid(
    wire("STATE_SNAPSHOT", {
      ...openSnapshot,
      viewer_submission: {
        ...openSnapshot.viewer_submission,
        points: 100,
      },
    }),
  );
});

test("rejects another user's selected answer in open state", () => {
  assertInvalid(
    wire("STATE_SNAPSHOT", {
      ...openSnapshot,
      other_submissions: [
        { user_id: MEMBER_ID, selected_option_id: "joule" },
      ],
    }),
  );
});

test("accepts only the viewer-private result after reveal", () => {
  const parsed = parse(
    wire("QUESTION_REVEALED", {
      session_id: SESSION_ID,
      state_version: 2,
      question: revealedQuestion,
      viewer_submission: revealSnapshot.viewer_submission,
      leaderboard,
    }),
  );

  assert.equal(parsed.type, "QUESTION_REVEALED");
  assert.equal(parsed.payload.viewer_submission?.is_correct, true);
  assert.equal(parsed.payload.viewer_submission?.points, 100);
  assert.equal(
    Object.hasOwn(parsed.payload.leaderboard[1] ?? {}, "selected_option_id"),
    false,
  );
});

test("finished state cannot claim a non-participating viewer", () => {
  assertInvalid(
    wire("STATE_SNAPSHOT", {
      ...finishedSnapshot,
      viewer_participated: false,
    }),
  );
});

test("parses the QUESTION_GRADING state with the viewer's own pending answer", () => {
  const parsed = parse(
    wire("STATE_SNAPSHOT", {
      ...openSnapshot,
      state_version: 3,
      status: "QUESTION_GRADING",
      viewer_submission: {
        session_question_id: QUESTION_ID,
        selected_option_id: null,
        answer_text: "Heat flows from hot to cold.",
        grading_status: "PENDING",
      },
    }),
  );
  assert.equal(parsed.type, "STATE_SNAPSHOT");
  assert.equal(parsed.payload.status, "QUESTION_GRADING");
  if (parsed.type !== "STATE_SNAPSHOT" || parsed.payload.status !== "QUESTION_GRADING") {
    throw new Error("Expected a grading snapshot.");
  }
  assert.equal(
    parsed.payload.viewer_submission?.answer_text,
    "Heat flows from hot to cold.",
  );
  assert.equal(parsed.payload.viewer_submission?.grading_status, "PENDING");
  assert.equal(parsed.payload.reveal_ends_at, null);
  assert.equal(parsed.payload.finished_at, null);
});

test("parses adaptive room settings and preparation gating fields", () => {
  const parsed = parse(
    wire("ROOM_STATE", {
      ...roomState,
      name: "GCSE Physics",
      quiz_mode: "ADAPTIVE",
      education_level: "GCSE",
      quiz_subject: "physics",
      quiz_topic: "energy",
      target_total_marks: 20,
      active_preparation_status: "READY",
      active_preparation_version: 2,
    }),
  );
  assert.equal(parsed.type, "ROOM_STATE");
  if (parsed.type !== "ROOM_STATE") {
    throw new Error("Expected a room-state event.");
  }
  assert.equal(parsed.payload.quiz_mode, "ADAPTIVE");
  assert.equal(parsed.payload.quiz_subject, "physics");
  assert.equal(parsed.payload.quiz_topic, "energy");
  assert.equal(parsed.payload.target_total_marks, 20);
  assert.equal(parsed.payload.active_preparation_status, "READY");
  assert.equal(parsed.payload.active_preparation_version, 2);

  assertInvalid(
    wire("ROOM_STATE", { ...roomState, quiz_mode: "ARCADE" }),
  );
  assertInvalid(
    wire("ROOM_STATE", {
      ...roomState,
      quiz_mode: "ADAPTIVE",
      target_total_marks: 41,
    }),
  );
  assertInvalid(
    wire("ROOM_STATE", {
      ...roomState,
      active_preparation_status: "DREAMING",
    }),
  );
});

test("parses typed written questions with extracts and no options", () => {
  const written = {
    ...openQuestion,
    prompt: "Explain conduction.",
    options: [],
    question_type: "WRITTEN",
    max_marks: 4,
    original_extract: null,
  };
  const parsed = parse(
    wire("QUESTION_OPENED", {
      session_id: SESSION_ID,
      state_version: 1,
      question: written,
    }),
  );
  assert.equal(parsed.type, "QUESTION_OPENED");
  if (parsed.type !== "QUESTION_OPENED") {
    throw new Error("Expected a question-opened event.");
  }
  assert.equal(parsed.payload.question.question_type, "WRITTEN");
  assert.equal(parsed.payload.question.max_marks, 4);
  assert.deepEqual(parsed.payload.question.options, []);

  assertInvalid(
    wire("QUESTION_OPENED", {
      session_id: SESSION_ID,
      state_version: 1,
      question: { ...written, options: openQuestion.options },
    }),
  );
  assertInvalid(
    wire("QUESTION_OPENED", {
      session_id: SESSION_ID,
      state_version: 1,
      question: { ...openQuestion, question_type: "ESSAY" },
    }),
  );
  assertInvalid(
    wire("QUESTION_OPENED", {
      session_id: SESSION_ID,
      state_version: 1,
      question: { ...openQuestion, max_marks: 7 },
    }),
  );
});

test("parses text answer acknowledgements with grading state", () => {
  const parsed = parse(
    wire("ANSWER_ACCEPTED", {
      session_id: SESSION_ID,
      state_version: 1,
      session_question_id: QUESTION_ID,
      selected_option_id: null,
      answer_text: "42",
      grading_status: "PENDING",
      accepted_at: SERVER_TIME,
    }),
  );
  assert.equal(parsed.type, "ANSWER_ACCEPTED");
  if (parsed.type !== "ANSWER_ACCEPTED") {
    throw new Error("Expected an acknowledgement.");
  }
  assert.equal(parsed.payload.answer_text, "42");
  assert.equal(parsed.payload.grading_status, "PENDING");

  assertInvalid(
    wire("ANSWER_ACCEPTED", {
      session_id: SESSION_ID,
      state_version: 1,
      session_question_id: QUESTION_ID,
      selected_option_id: "newton",
      answer_text: "Newton",
      grading_status: "GRADED",
      accepted_at: SERVER_TIME,
    }),
  );
  assertInvalid(
    wire("ANSWER_ACCEPTED", {
      session_id: SESSION_ID,
      state_version: 1,
      session_question_id: QUESTION_ID,
      selected_option_id: null,
      answer_text: null,
      grading_status: "GRADED",
      accepted_at: SERVER_TIME,
    }),
  );
});

test("parses adaptive reveal with raw marks, feedback, and criteria", () => {
  const parsed = parse(
    wire("QUESTION_REVEALED", {
      session_id: SESSION_ID,
      state_version: 2,
      question: {
        ...openQuestion,
        options: [],
        question_type: "WRITTEN",
        max_marks: 4,
        correct_option_id: null,
        worked_explanation: "Conduction needs particles.",
      },
      viewer_submission: {
        session_question_id: QUESTION_ID,
        selected_option_id: null,
        answer_text: "Particles vibrate.",
        is_correct: false,
        points: 0,
        earned_marks: 2,
        max_marks: 4,
        grading_status: "GRADED",
        feedback: enrichedFeedback,
        awarded_criterion_ids: ["c1"],
      },
      leaderboard,
    }),
  );
  assert.equal(parsed.type, "QUESTION_REVEALED");
  if (parsed.type !== "QUESTION_REVEALED") {
    throw new Error("Expected a reveal.");
  }
  assert.equal(parsed.payload.question.correct_option_id, null);
  assert.equal(
    parsed.payload.question.worked_explanation,
    "Conduction needs particles.",
  );
  assert.equal(parsed.payload.viewer_submission?.earned_marks, 2);
  assert.deepEqual(parsed.payload.viewer_submission?.awarded_criterion_ids, [
    "c1",
  ]);
});

test("rejects legacy v1 frames missing strict v2 fields", () => {
  const { quiz_mode, ...legacyRoomState } = roomState;
  assertInvalid(wire("ROOM_STATE", legacyRoomState));
  const { question_type, ...legacyQuestion } = openQuestion;
  assertInvalid(
    wire("QUESTION_OPENED", {
      session_id: SESSION_ID,
      state_version: 1,
      question: legacyQuestion,
    }),
  );
  assertInvalid(
    wire("STATE_SNAPSHOT", {
      ...openSnapshot,
      viewer_submission: {
        session_question_id: QUESTION_ID,
        selected_option_id: "newton",
      },
    }),
  );
});

test("rejects repaired-backend frames missing the Repair2 fields", () => {
  const { active_preparation_error_category, ...roomWithoutCategory } =
    roomState;
  assertInvalid(wire("ROOM_STATE", roomWithoutCategory));
  const { grading_retry_needed, ...snapshotWithoutRetry } = openSnapshot;
  assertInvalid(wire("STATE_SNAPSHOT", snapshotWithoutRetry));
  assertInvalid(
    wire("STATE_SNAPSHOT", {
      ...openSnapshot,
      grading_retry_needed: "no",
    }),
  );
  assertInvalid(
    wire("ROOM_STATE", {
      ...roomState,
      active_preparation_error_category: "",
    }),
  );
});

test("parses durable FAILED preparation with its error category", () => {
  const parsed = parse(
    wire("ROOM_STATE", {
      ...roomState,
      name: "GCSE Physics",
      quiz_mode: "ADAPTIVE",
      education_level: "GCSE",
      quiz_subject: "physics",
      quiz_topic: "energy",
      target_total_marks: 20,
      active_preparation_status: "FAILED",
      active_preparation_version: 2,
      active_preparation_error_category: "generation_failed",
    }),
  );
  assert.equal(parsed.type, "ROOM_STATE");
  if (parsed.type !== "ROOM_STATE") {
    throw new Error("Expected a room-state event.");
  }
  assert.equal(parsed.payload.active_preparation_status, "FAILED");
  assert.equal(
    parsed.payload.active_preparation_error_category,
    "generation_failed",
  );
});

test("parses the aggregate grading retry signal", () => {
  const parsed = parse(
    wire("STATE_SNAPSHOT", {
      ...openSnapshot,
      status: "QUESTION_GRADING",
      grading_retry_needed: true,
    }),
  );
  assert.equal(parsed.type, "STATE_SNAPSHOT");
  if (
    parsed.type !== "STATE_SNAPSHOT" ||
    parsed.payload.status !== "QUESTION_GRADING"
  ) {
    throw new Error("Expected a grading snapshot.");
  }
  assert.equal(parsed.payload.grading_retry_needed, true);
});

const enrichedFeedback = {
  summary: "Good start; mention conduction.",
  awarded: [{ id: "c1", marks: 2, explanation: "Named heat flow." }],
  missing: [{ id: "c2", marks: 2, explanation: "Explain particle role." }],
  awarded_count: 1,
  total_criteria: 2,
};

function writtenRevealSubmission(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    session_question_id: QUESTION_ID,
    selected_option_id: null,
    answer_text: "Particles vibrate.",
    is_correct: false,
    points: 0,
    earned_marks: 2,
    max_marks: 4,
    grading_status: "GRADED",
    feedback: enrichedFeedback,
    awarded_criterion_ids: ["c1"],
    ...overrides,
  };
}

function writtenRevealQuestion(): Record<string, unknown> {
  return {
    ...openQuestion,
    options: [],
    question_type: "WRITTEN",
    max_marks: 4,
    correct_option_id: null,
    worked_explanation: "Conduction needs particles.",
  };
}

function revealedFrame(
  question: Record<string, unknown>,
  viewerSubmission: Record<string, unknown> | null,
): Record<string, unknown> {
  return wire("QUESTION_REVEALED", {
    session_id: SESSION_ID,
    state_version: 2,
    question,
    viewer_submission: viewerSubmission,
    leaderboard,
  });
}

test("question types enforce unique options, one-mark MCQ and correct-option membership", () => {
  for (const question of [
    { ...openQuestion, max_marks: 2 },
    { ...openQuestion, options: [openQuestion.options[0], openQuestion.options[0]] },
    { ...openQuestion, question_type: "NUMERICAL" },
    { ...openQuestion, question_type: "WRITTEN" },
  ]) {
    assertInvalid(wire("STATE_SNAPSHOT", { ...openSnapshot, question }));
    assertInvalid(revealedFrame({ ...question, correct_option_id: "newton", worked_explanation: "Example" }, null));
  }
  for (const correct_option_id of [null, "missing"]) {
    assertInvalid(revealedFrame({ ...revealedQuestion, correct_option_id }, null));
  }
  for (const question_type of ["NUMERICAL", "WRITTEN"]) {
    assertInvalid(revealedFrame({ ...revealedQuestion, question_type, options: [] }, null));
    assert.equal(parse(wire("STATE_SNAPSHOT", { ...openSnapshot,
      question: { ...openQuestion, question_type, options: [], max_marks: 3 }, viewer_submission: null })).type, "STATE_SNAPSHOT");
  }
});

const numericalQuestion = { ...revealedQuestion, question_type: "NUMERICAL", options: [],
  correct_option_id: null, max_marks: 3 };

function numericalFrames(feedback: unknown, earned: number, overrides: Record<string, unknown> = {}) {
  const submission = { ...revealSnapshot.viewer_submission, selected_option_id: null,
    answer_text: "12 N", points: earned, earned_marks: earned, max_marks: 3,
    is_correct: earned === 3, feedback, ...overrides };
  return [revealedFrame(numericalQuestion, submission),
    wire("STATE_SNAPSHOT", { ...revealSnapshot, question: numericalQuestion, viewer_submission: submission })];
}

test("producer numerical full, partial, zero and unparseable feedback survives reveal and reconnect", () => {
  for (const [earned, feedback] of [
    [3, { value_awarded: true, unit_awarded: true, earned_marks: 3, max_marks: 3 }],
    [2, { value_awarded: true, unit_awarded: false, earned_marks: 2, max_marks: 3 }],
    [0, { value_awarded: false, unit_awarded: true, earned_marks: 0, max_marks: 3 }],
    [0, { value_awarded: false, unit_awarded: false, explanation: "Could not parse a valid number from the answer." }],
    [0, { value_awarded: false, unit_awarded: false, explanation: "Could not compare the answer value safely." }],
  ] as const) {
    for (const frame of numericalFrames(feedback, earned)) assert.doesNotThrow(() => parse(frame));
  }
});

test("numerical feedback rejects malformed producer records and outer grade mismatches on both transports", () => {
  const normal = { value_awarded: true, unit_awarded: false, earned_marks: 2, max_marks: 3 };
  for (const feedback of [{}, { ...normal, extra: true }, { ...normal, value_awarded: 1 },
    { ...normal, unit_awarded: "false" }, { ...normal, earned_marks: 1 },
    { ...normal, earned_marks: "2" }, { ...normal, max_marks: 4 },
    { value_awarded: false, unit_awarded: false, explanation: " " },
    { value_awarded: true, unit_awarded: false, explanation: "Invalid" },
    { value_awarded: false, unit_awarded: false, explanation: "Invalid", extra: true }]) {
    for (const frame of numericalFrames(feedback, 2)) assertInvalid(frame);
  }
  for (const overrides of [{ grading_status: "PENDING" }, { earned_marks: null },
    { earned_marks: 4 }, { max_marks: 2 }, { is_correct: true },
    { awarded_criterion_ids: ["c1"] }, { answer_text: null }, { selected_option_id: "a" }]) {
    for (const frame of numericalFrames(normal, 2, overrides)) assertInvalid(frame);
  }
  for (const feedback of [
    { value_awarded: false, unit_awarded: false, explanation: " " },
    { value_awarded: true, unit_awarded: false, explanation: "Invalid number" },
    { value_awarded: false, unit_awarded: true, explanation: "Invalid number" },
    { value_awarded: false, unit_awarded: false, explanation: 1 },
    { value_awarded: false, unit_awarded: false, explanation: "Invalid number", extra: true },
  ]) {
    for (const frame of numericalFrames(feedback, 0)) assertInvalid(frame);
  }
});

test("graded written reveal requires full mark coherence", () => {
  const parsed = parse(revealedFrame(writtenRevealQuestion(), writtenRevealSubmission()));
  assert.equal(parsed.type, "QUESTION_REVEALED");
  if (parsed.type !== "QUESTION_REVEALED") {
    throw new Error("Expected a reveal.");
  }
  assert.equal(parsed.payload.viewer_submission?.earned_marks, 2);
  assert.deepEqual(parsed.payload.viewer_submission?.awarded_criterion_ids, [
    "c1",
  ]);

  const question = writtenRevealQuestion();
  const coherenceMutations: Record<string, unknown>[] = [
    // Grade without feedback is malformed: feedback only exists post-grade
    // and a graded written outcome must carry it.
    writtenRevealSubmission({ feedback: {} }),
    // Earned marks must be present once graded.
    writtenRevealSubmission({ earned_marks: null }),
    // Submission marks must match the question marks.
    writtenRevealSubmission({ max_marks: 3 }),
    // Awarded point marks must sum exactly to the earned marks.
    writtenRevealSubmission({
      feedback: {
        ...enrichedFeedback,
        awarded: [{ id: "c1", marks: 1, explanation: "Named heat flow." }],
      },
    }),
    // Awarded criterion IDs must exactly match the awarded points.
    writtenRevealSubmission({ awarded_criterion_ids: [] }),
    writtenRevealSubmission({ awarded_criterion_ids: ["c1", "c2"] }),
    writtenRevealSubmission({ awarded_criterion_ids: ["c9"] }),
  ];
  for (const mutation of coherenceMutations) {
    assertInvalid(revealedFrame(question, mutation));
  }
  // Submission marks must agree with the authoritative question marks.
  assertInvalid(
    revealedFrame(question, writtenRevealSubmission({ max_marks: 3 })),
  );
});

test("non-written reveal rejects misattributed enriched feedback", () => {
  assertInvalid(
    revealedFrame(revealedQuestion, {
      session_question_id: QUESTION_ID,
      selected_option_id: "newton",
      answer_text: null,
      is_correct: true,
      points: 100,
      earned_marks: 1,
      max_marks: 1,
      grading_status: "GRADED",
      feedback: enrichedFeedback,
      awarded_criterion_ids: [],
    }),
  );
});

test("parses enriched written feedback only for graded post-reveal outcomes", () => {
  const writtenReveal = {
    ...openQuestion,
    options: [],
    question_type: "WRITTEN",
    max_marks: 4,
    correct_option_id: null,
    worked_explanation: "Conduction needs particles.",
  };
  const parsed = parse(
    wire("QUESTION_REVEALED", {
      session_id: SESSION_ID,
      state_version: 2,
      question: writtenReveal,
      viewer_submission: {
        session_question_id: QUESTION_ID,
        selected_option_id: null,
        answer_text: "Particles vibrate.",
        is_correct: false,
        points: 0,
        earned_marks: 2,
        max_marks: 4,
        grading_status: "GRADED",
        feedback: enrichedFeedback,
        awarded_criterion_ids: ["c1"],
      },
      leaderboard,
    }),
  );
  assert.equal(parsed.type, "QUESTION_REVEALED");

  assertInvalid(
    wire("QUESTION_REVEALED", {
      session_id: SESSION_ID,
      state_version: 2,
      question: writtenReveal,
      viewer_submission: {
        session_question_id: QUESTION_ID,
        selected_option_id: null,
        answer_text: "Particles vibrate.",
        is_correct: false,
        points: 0,
        earned_marks: 2,
        max_marks: 4,
        grading_status: "GRADED",
        feedback: { summary: "x", awarded: [], missing: "no" },
        awarded_criterion_ids: ["c1"],
      },
      leaderboard,
    }),
  );
  assertInvalid(
    wire("QUESTION_REVEALED", {
      session_id: SESSION_ID,
      state_version: 2,
      question: writtenReveal,
      viewer_submission: {
        session_question_id: QUESTION_ID,
        selected_option_id: null,
        answer_text: "Particles vibrate.",
        is_correct: null,
        points: null,
        earned_marks: null,
        max_marks: 4,
        grading_status: "PENDING",
        feedback: enrichedFeedback,
        awarded_criterion_ids: [],
      },
      leaderboard,
    }),
  );
});
