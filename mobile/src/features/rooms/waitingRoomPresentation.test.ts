import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  CommandRejectedError,
  RealtimeAuthenticationError,
  RealtimeConnectionLimitError,
  RealtimeRoomError,
  ReconnectExhaustedError,
} from "../../realtime/errors";
import {
  parseServerEvent,
  type RoomStatePayload,
} from "../../realtime/protocol";
import { getSessionErrorMessage } from "../session/sessionErrorMessages";
import {
  initialSessionState,
  sessionReducer,
  type SessionState,
} from "../session/sessionState";
import {
  makeAdaptiveRoomState,
  makeLobbySnapshot,
  makeFinishedSnapshot,
  makeOpenSnapshot,
  MEMBER_ID,
  ROOM_ID,
} from "../session/sessionTestFixtures";
import {
  buildAdaptiveRoomSummary,
  buildWaitingRoomPresentation,
  derivePreparationControl,
  deriveReadinessControl,
  deriveRoomLifecycleControl,
  getConnectionLabel,
  getStartEligibilityMessage,
  selectStartEligibility,
  waitingRoomRouteMatches,
} from "./waitingRoomPresentation";

type RoomOptions = {
  viewerRole?: "host" | "member";
  viewerReady?: boolean;
  memberReady?: boolean;
  memberOnline?: boolean;
  memberName?: string;
  includeMember?: boolean;
};

function roomState(options: RoomOptions = {}): RoomStatePayload {
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
      ready: options.memberReady ?? options.viewerReady ?? false,
      online: options.memberOnline ?? true,
    });
  }
  const event = parseServerEvent(
    JSON.stringify({
      protocol_version: 2,
      type: "ROOM_STATE",
      payload: {
        room_id: ROOM_ID,
        name: "Physics Sprint",
        join_code: "PHYS42",
        maximum_members: 8,
        viewer_role: options.viewerRole ?? "host",
        participants,
        viewer_ready: options.viewerReady ?? false,
        quiz_mode: "LEGACY_PHYSICS",
        education_level: null,
        quiz_subject: null,
        quiz_topic: null,
        target_total_marks: null,
        active_preparation_status: null,
        active_preparation_version: null,
        active_preparation_error_category: null,
      },
    }),
  );
  if (event.type !== "ROOM_STATE") {
    throw new Error("Expected a ROOM_STATE fixture.");
  }
  return event.payload;
}

function establishedState(
  authoritativeRoomState = roomState(),
  activeSession = false,
): SessionState {
  const snapshot = activeSession
    ? makeOpenSnapshot({ roomState: authoritativeRoomState })
    : makeLobbySnapshot(authoritativeRoomState);
  let state = sessionReducer(initialSessionState, {
    type: "ROOM_SELECTED",
    roomId: ROOM_ID,
    generation: 1,
  });
  state = sessionReducer(state, {
    type: "CONNECTED_RECEIVED",
    generation: 1,
    serverTime: snapshot.server_time,
  });
  return sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: 1,
    snapshot,
    source: "new-socket",
  });
}

test("room name, join code, capacity, and participants come from ROOM_STATE", () => {
  const presentation = buildWaitingRoomPresentation(establishedState());
  assert.ok(presentation !== null);
  assert.deepEqual(
    {
      name: presentation.name,
      joinCode: presentation.joinCode,
      participantCount: presentation.participantCount,
      maximumMembers: presentation.maximumMembers,
      viewerRole: presentation.viewerRole,
    },
    {
      name: "Physics Sprint",
      joinCode: "PHYS42",
      participantCount: 2,
      maximumMembers: 8,
      viewerRole: "host",
    },
  );
});

test("a new ROOM_STATE fully replaces previous participant presentation", () => {
  let state = establishedState(roomState({ memberName: "Previous Name" }));
  state = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: 1,
    roomState: roomState({ memberName: "Current Name", memberOnline: false }),
  });
  const presentation = buildWaitingRoomPresentation(state);
  assert.ok(presentation !== null);
  assert.deepEqual(
    presentation.participants.map((participant) => participant.display_name),
    ["Room Owner", "Current Name"],
  );
  assert.equal(
    presentation.participants.some(
      (participant) => participant.display_name === "Previous Name",
    ),
    false,
  );
});

test("participant roles, host readiness, and presence are explicit", () => {
  const presentation = buildWaitingRoomPresentation(
    establishedState(roomState({ memberReady: true, memberOnline: false })),
  );
  assert.ok(presentation !== null);
  assert.deepEqual(
    presentation.participants.map((participant) => ({
      role: participant.roleLabel,
      readiness: participant.readinessLabel,
      presence: participant.presenceLabel,
    })),
    [
      { role: "Host", readiness: "Ready automatically", presence: "Online" },
      { role: "Member", readiness: "Ready", presence: "Offline" },
    ],
  );
});

test("member readiness sends an explicit desired state", () => {
  const notReady = establishedState(
    roomState({ viewerRole: "member", viewerReady: false }),
  );
  assert.deepEqual(deriveReadinessControl(notReady), {
    status: "available",
    desiredReady: true,
    label: "I'm ready",
  });

  const ready = establishedState(
    roomState({ viewerRole: "member", viewerReady: true }),
  );
  assert.deepEqual(deriveReadinessControl(ready), {
    status: "available",
    desiredReady: false,
    label: "I'm not ready",
  });
});

test("readiness remains pending until authoritative ROOM_STATE confirms it", () => {
  let state = establishedState(
    roomState({ viewerRole: "member", viewerReady: false }),
  );
  state = sessionReducer(state, {
    type: "READY_COMMAND_STARTED",
    generation: 1,
    ready: true,
  });
  assert.deepEqual(deriveReadinessControl(state), {
    status: "pending",
    desiredReady: true,
    label: "Setting ready...",
  });
  assert.equal(state.roomState?.viewer_ready, false);

  state = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: 1,
    roomState: roomState({ viewerRole: "member", viewerReady: true }),
  });
  assert.equal(state.pendingCommand, null);
  assert.deepEqual(deriveReadinessControl(state), {
    status: "available",
    desiredReady: false,
    label: "I'm not ready",
  });
});

test("host readiness is implicit and never exposes a member toggle", () => {
  assert.deepEqual(deriveReadinessControl(establishedState()), {
    status: "host",
  });
});

test("member sees Leave Room while host sees Close Room", () => {
  assert.deepEqual(
    deriveRoomLifecycleControl(
      establishedState(roomState({ viewerRole: "member" })),
    ),
    {
      kind: "leave",
      label: "Leave Room",
      disabled: false,
      message: "Leaving returns you Home. Completed quiz results remain saved.",
    },
  );
  assert.deepEqual(deriveRoomLifecycleControl(establishedState()), {
    kind: "close",
    label: "Close Room",
    disabled: false,
    message:
      "Closing the room removes every current member. Completed quiz results will remain saved.",
  });
});

test("lifecycle controls disable during active quiz, disconnect, and pending exit", () => {
  const active = deriveRoomLifecycleControl(
    establishedState(roomState({ viewerRole: "member" }), true),
  );
  assert.equal(active?.disabled, true);
  assert.equal(
    active?.message,
    "Finish the current quiz before leaving the room.",
  );

  let disconnected = establishedState();
  disconnected = sessionReducer(disconnected, {
    type: "SOCKET_INVALIDATED",
    generation: 2,
  });
  assert.equal(deriveRoomLifecycleControl(disconnected)?.disabled, true);

  let pending = establishedState(roomState({ viewerRole: "member" }));
  pending = sessionReducer(pending, {
    type: "ROOM_EXIT_STARTED",
    generation: 1,
    kind: "leave",
  });
  assert.deepEqual(deriveRoomLifecycleControl(pending), {
    kind: "leave",
    label: "Leaving Room...",
    disabled: true,
    message: "Leaving room…",
  });
  assert.equal(deriveReadinessControl(pending).status, "disabled");

  let pendingClose = establishedState(roomState({ memberReady: true }));
  pendingClose = sessionReducer(pendingClose, {
    type: "ROOM_EXIT_STARTED",
    generation: 1,
    kind: "close",
  });
  assert.equal(selectStartEligibility(pendingClose).eligible, false);
  assert.equal(selectStartEligibility(pendingClose).noCommandPending, false);
});

test("start eligibility requires host, two participants, member readiness, lobby, and connection", () => {
  const eligible = selectStartEligibility(
    establishedState(roomState({ memberReady: true })),
  );
  assert.equal(eligible.eligible, true);
  assert.equal(
    getStartEligibilityMessage(eligible),
    "Everyone is ready. You can start the quiz.",
  );

  assert.equal(
    selectStartEligibility(
      establishedState(roomState({ includeMember: false })),
    ).eligible,
    false,
  );
  assert.equal(
    selectStartEligibility(establishedState(roomState({ memberReady: false })))
      .eligible,
    false,
  );
  assert.equal(
    selectStartEligibility(
      establishedState(
        roomState({ viewerRole: "member", viewerReady: true, memberReady: true }),
      ),
    ).eligible,
    false,
  );
  assert.equal(
    selectStartEligibility(
      establishedState(roomState({ memberReady: true }), true),
    ).eligible,
    false,
  );
});

test("pending commands and disconnected state synchronously disable Start", () => {
  let state = establishedState(roomState({ memberReady: true }));
  state = sessionReducer(state, {
    type: "START_COMMAND_STARTED",
    generation: 1,
    previousSessionId: null,
  });
  assert.equal(selectStartEligibility(state).eligible, false);
  assert.equal(selectStartEligibility(state).noCommandPending, false);

  const disconnected = sessionReducer(
    establishedState(roomState({ memberReady: true })),
    { type: "SOCKET_INVALIDATED", generation: 2 },
  );
  assert.equal(selectStartEligibility(disconnected).eligible, false);
  assert.equal(
    selectStartEligibility(disconnected).connectionEstablished,
    false,
  );
});

test("reconnecting retains room data and disables readiness", () => {
  const established = establishedState(
    roomState({ viewerRole: "member", viewerReady: false }),
  );
  const reconnecting = sessionReducer(established, {
    type: "SOCKET_INVALIDATED",
    generation: 2,
  });
  assert.equal(reconnecting.phase, "reconnecting");
  assert.ok(buildWaitingRoomPresentation(reconnecting) !== null);
  assert.deepEqual(deriveReadinessControl(reconnecting), {
    status: "disabled",
    label: "Readiness unavailable while reconnecting",
  });
  assert.equal(getConnectionLabel(reconnecting), "Reconnecting…");
});

test("active authoritative sessions disable lobby actions without local quiz state", () => {
  const state = establishedState(
    roomState({ viewerRole: "member", viewerReady: true }),
    true,
  );
  assert.equal(state.snapshot?.status, "QUESTION_OPEN");
  assert.equal(deriveReadinessControl(state).status, "disabled");
  assert.equal(selectStartEligibility(state).hasNoActiveSession, false);
});

test("dismissing finished Results restores lobby readiness and rematch eligibility", () => {
  let state = establishedState(roomState({ memberReady: false }), true);
  state = sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: 1,
    snapshot: makeFinishedSnapshot(),
    source: "requested",
  });
  assert.equal(state.phase, "finished");
  state = sessionReducer(state, { type: "DISMISS_FINISHED_SESSION" });
  assert.equal(state.phase, "waiting");
  assert.equal(selectStartEligibility(state).eligible, false);

  state = sessionReducer(state, {
    type: "ROOM_STATE_RECEIVED",
    generation: 1,
    roomState: roomState({ memberReady: true }),
  });
  assert.equal(selectStartEligibility(state).eligible, true);
});

test("fatal room loss and mismatched IDs leave Waiting Room safely", () => {
  const connected = establishedState();
  assert.equal(waitingRoomRouteMatches(ROOM_ID, connected), true);
  assert.equal(waitingRoomRouteMatches("different-room", connected), false);
  const lost = sessionReducer(connected, {
    type: "FATAL_FAILURE",
    generation: 1,
    error: new RealtimeRoomError(undefined, "not_room_member"),
    clearRoom: true,
  });
  assert.equal(lost.roomId, null);
  assert.equal(waitingRoomRouteMatches(ROOM_ID, lost), false);
});

test("required realtime failures have concise user-facing messages", () => {
  const cases = [
    [new ReconnectExhaustedError(), "The room connection could not be restored automatically."],
    [new RealtimeAuthenticationError(), "Your session has expired. Please sign in again."],
    [new RealtimeRoomError(undefined, "not_room_member"), "You are no longer a member of this room."],
    [new RealtimeConnectionLimitError(), "The realtime connection limit has been reached."],
    [new CommandRejectedError("rate_limited", "server detail"), "Too many requests. Please wait a moment and try again."],
    [new CommandRejectedError("session_already_active", "server detail"), "This quiz has already started."],
    [new CommandRejectedError("room_owner_required", "server detail"), "Only the room host can start the quiz."],
    [new CommandRejectedError("participants_not_ready", "server detail"), "Every non-host member must be ready before the quiz starts."],
    [new CommandRejectedError("insufficient_participants", "server detail"), "At least two participants are required to start the quiz."],
    [new CommandRejectedError("answer_too_late", "server detail"), "The answer window has closed."],
    [new CommandRejectedError("answer_already_submitted", "server detail"), "Your answer is already recorded."],
    [new CommandRejectedError("stale_session_question", "server detail"), "The quiz has moved to another question."],
    [new CommandRejectedError("question_not_open", "server detail"), "This question is not open for answers."],
    [new CommandRejectedError("invalid_option", "server detail"), "That answer option is no longer available."],
    [new CommandRejectedError("session_not_active", "server detail"), "The quiz session is no longer active."],
    [new CommandRejectedError("internal_error", "server detail"), "The StudyRoom server could not complete that request."],
  ] as const;
  for (const [error, expected] of cases) {
    assert.equal(getSessionErrorMessage(error), expected);
  }
});

function adaptiveEstablishedState(
  options: {
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
): SessionState {
  const roomStateValue = makeAdaptiveRoomState({
    viewerRole: options.viewerRole,
    memberReady: options.memberReady,
    preparationStatus: options.preparationStatus ?? null,
    preparationVersion: options.preparationVersion ?? null,
    preparationErrorCategory: options.preparationErrorCategory ?? null,
  });
  const snapshot = makeLobbySnapshot(roomStateValue);
  let state = sessionReducer(initialSessionState, {
    type: "ROOM_SELECTED",
    roomId: ROOM_ID,
    generation: 1,
  });
  state = sessionReducer(state, {
    type: "CONNECTED_RECEIVED",
    generation: 1,
    serverTime: snapshot.server_time,
  });
  return sessionReducer(state, {
    type: "SNAPSHOT_RECEIVED",
    generation: 1,
    snapshot,
    source: "new-socket",
  });
}

test("adaptive rooms expose the immutable subject, topic, and mark budget", () => {
  const presentation = buildWaitingRoomPresentation(
    adaptiveEstablishedState({ preparationStatus: "READY", preparationVersion: 2 }),
  );
  assert.ok(presentation !== null);
  assert.equal(presentation.quizMode, "ADAPTIVE");
  assert.deepEqual(presentation.adaptiveSummary, {
    educationLevel: "GCSE",
    subject: "physics",
    topic: "energy",
    subjectLabel: "Physics",
    topicLabel: "Energy",
    targetTotalMarks: 20,
  });
  assert.equal(presentation.preparationStatus, "READY");
  assert.equal(presentation.preparationVersion, 2);
  assert.deepEqual(buildAdaptiveRoomSummary(adaptiveEstablishedState()), {
    educationLevel: "GCSE",
    subject: "physics",
    topic: "energy",
    subjectLabel: "Physics",
    topicLabel: "Energy",
    targetTotalMarks: 20,
  });
});

test("legacy rooms carry no adaptive summary and no preparation control", () => {
  const presentation = buildWaitingRoomPresentation(establishedState());
  assert.ok(presentation !== null);
  assert.equal(presentation.quizMode, "LEGACY_PHYSICS");
  assert.equal(presentation.adaptiveSummary, null);
  assert.deepEqual(derivePreparationControl(establishedState()), {
    status: "legacy",
  });
});

test("preparation control gates Generate on host, lobby, and connection", () => {
  assert.deepEqual(
    derivePreparationControl(adaptiveEstablishedState()),
    { status: "generate-available", label: "Generate Quiz" },
  );
  assert.deepEqual(
    derivePreparationControl(
      adaptiveEstablishedState({
        preparationStatus: "GENERATING",
        preparationVersion: 1,
      }),
    ),
    { status: "generating", label: "Generating quiz..." },
  );
  assert.deepEqual(
    derivePreparationControl(
      adaptiveEstablishedState({
        preparationStatus: "READY",
        preparationVersion: 2,
      }),
    ),
    { status: "ready", label: "Quiz ready" },
  );
  assert.deepEqual(
    derivePreparationControl(adaptiveEstablishedState({ viewerRole: "member" })),
    {
      status: "waiting-host",
      label: "Waiting for the host to generate the quiz.",
    },
  );
});

test("failed preparation exposes an explicit host retry", () => {
  let state = adaptiveEstablishedState();
  state = sessionReducer(state, {
    type: "COMMAND_REJECTED",
    generation: 1,
    error: new CommandRejectedError("preparation_failed", "server detail"),
  });
  assert.deepEqual(derivePreparationControl(state), {
    status: "failed",
    label: "Quiz generation failed.",
    canRetry: true,
  });
  assert.equal(
    getSessionErrorMessage(state.lastError),
    "Quiz generation failed. Please try generating again.",
  );

  let unavailable = adaptiveEstablishedState();
  unavailable = sessionReducer(unavailable, {
    type: "COMMAND_REJECTED",
    generation: 1,
    error: new CommandRejectedError(
      "ai_generation_unavailable",
      "server detail",
    ),
  });
  const control = derivePreparationControl(unavailable);
  assert.equal(control.status, "failed");
  assert.equal(
    getSessionErrorMessage(unavailable.lastError),
    "AI quiz generation is currently unavailable. Please try again later.",
  );
});

test("durable FAILED preparation drives retry without transient errors", () => {
  const failed = adaptiveEstablishedState({
    preparationStatus: "FAILED",
    preparationVersion: 2,
    preparationErrorCategory: "generation_failed",
  });
  assert.deepEqual(derivePreparationControl(failed), {
    status: "failed",
    label: "Quiz generation failed.",
    canRetry: true,
  });

  const unavailable = adaptiveEstablishedState({
    preparationStatus: "FAILED",
    preparationVersion: 2,
    preparationErrorCategory: "ai_generation_unavailable",
  });
  assert.deepEqual(derivePreparationControl(unavailable), {
    status: "failed",
    label: "AI quiz generation is currently unavailable.",
    canRetry: true,
  });

  const memberFailed = adaptiveEstablishedState({
    viewerRole: "member",
    preparationStatus: "FAILED",
    preparationVersion: 2,
    preparationErrorCategory: "generation_failed",
  });
  const memberControl = derivePreparationControl(memberFailed);
  assert.equal(memberControl.status, "failed");
  if (memberControl.status !== "failed") {
    throw new Error("Expected a failed preparation control.");
  }
  assert.equal(memberControl.canRetry, false);

  const gated = selectStartEligibility(failed);
  assert.equal(gated.quizContentReady, false);
  assert.equal(gated.eligible, false);
});

test("a fresh retry request uses a new UUID; transport fallback replays the same one", () => {
  // Documented contract (route behavior): every explicit host Generate/Retry
  // tap mints a fresh idempotency key via createPreparationRequestId, while
  // the realtime-unavailable HTTP fallback replays the identical request ID
  // so the server treats it as the same request instead of a conflict.
  const source = readFileSync(
    resolve(
      dirname(fileURLToPath(import.meta.url)),
      "../../../app/waiting-room.tsx",
    ),
    "utf8",
  );
  assert.match(source, /createPreparationRequestId\(\)/);
  assert.match(
    source,
    /requestPrepareQuiz\(roomId, requestId\)/,
  );
  assert.match(source, /prepareQuiz\(requestId\)/);
  assert.match(source, /setHttpPreparationPending\(true\)/);
  assert.match(source, /finally\(\(\) => setHttpPreparationPending\(false\)\)/);
});

test("HTTP preparation keeps generation disabled while pending and reconnecting", () => {
  let state = adaptiveEstablishedState({ memberReady: true });
  assert.equal(derivePreparationControl(state, true).status, "generate-pending");
  state = { ...state, connectionStage: "connecting" };
  assert.equal(derivePreparationControl(state, true).status, "generate-pending");
  assert.equal(derivePreparationControl(state, false).status, "waiting-host");
  assert.equal(selectStartEligibility(state).eligible, false);
});

test("adaptive start requires READY preparation content", () => {
  const generating = selectStartEligibility(
    adaptiveEstablishedState({
      memberReady: true,
      preparationStatus: "GENERATING",
      preparationVersion: 1,
    }),
  );
  assert.equal(generating.quizContentReady, false);
  assert.equal(generating.eligible, false);
  assert.equal(
    getStartEligibilityMessage(generating),
    "Generate the quiz and wait for it to be ready.",
  );

  const unprepared = selectStartEligibility(
    adaptiveEstablishedState({ memberReady: true }),
  );
  assert.equal(unprepared.quizContentReady, false);
  assert.equal(unprepared.eligible, false);

  const ready = selectStartEligibility(
    adaptiveEstablishedState({
      memberReady: true,
      preparationStatus: "READY",
      preparationVersion: 2,
    }),
  );
  assert.equal(ready.quizContentReady, true);
  assert.equal(ready.eligible, true);
});

test("production Waiting Room starts only through SessionProvider authority", () => {
  const source = readFileSync(
    resolve(
      dirname(fileURLToPath(import.meta.url)),
      "../../../app/waiting-room.tsx",
    ),
    "utf8",
  );
  for (const forbidden of [
    "waitingRoomFlow",
    "useQuizFlow",
    "START_QUIZ",
    "START_SESSION",
    "getRoom(",
    "getRoomMembers(",
    "mockData",
    "Alex",
    "Sam",
    'router.replace("/quiz")',
  ]) {
    assert.equal(
      source.includes(forbidden),
      false,
      `Waiting Room must not contain ${forbidden}`,
    );
  }
  assert.equal(source.includes("useSession"), true);
  assert.equal(source.includes("startSession()"), true);
  assert.equal(source.includes('router.replace("/quiz")'), false);
  assert.match(source, /StudioScreen/);
  assert.match(source, /StudioCard/);
  assert.match(source, /StudioButton/);
  assert.match(source, /StudioPlayerRow/);
  assert.match(source, /Alert\.alert/);
  assert.match(source, /accessibilityLiveRegion="polite"/);
  assert.match(source, /accessibilityRole="alert"/);
  assert.match(source, /onReport/);
  assert.doesNotMatch(
    source,
    /from "\.\.\/src\/components\/(AppButton|Card|Screen)"/,
  );
  assert.doesNotMatch(source, /<PlayerRow\b/);
});
