import assert from "node:assert/strict";
import test from "node:test";

import type { HomeRoomRequestDependencies } from "../rooms/homeFlow";
import { HomeRoomRequestCoordinator } from "../rooms/homeFlow";
import { CommandUnavailableError } from "../../realtime/errors";
import { BackendApiError, NetworkApiError } from "../../api/errors";
import {
  FakeRealtimeTransport,
  FakeRealtimeTransportFactory,
  parseFrame,
} from "../../realtime/realtimeTestSupport";
import type { StateSnapshotPayload } from "../../realtime/protocol";
import {
  REALTIME_BOOTSTRAP_DEADLINE_MS,
  reconnectDelayMs,
  SessionController,
  type ScheduleTimeout,
} from "./sessionController";
import {
  makeAdaptiveRoomState,
  makeGradingSnapshot,
  makeLobbySnapshot,
  makeRoomState,
  makeFinishedSnapshot,
  NEW_SESSION_ID,
  makeOpenSnapshot,
  makeRevealSnapshot,
  OTHER_ROOM_ID,
  QUESTION_ID,
  ROOM_ID,
  SESSION_ID,
  serverEventFrame,
} from "./sessionTestFixtures";

type ScheduledTask = {
  callback: () => void;
  delayMs: number;
  cancelled: boolean;
};

const AUTHENTICATED_USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-111111111111";
const OTHER_AUTHENTICATED_USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-222222222222";

class FakeScheduler {
  readonly tasks: ScheduledTask[] = [];

  readonly schedule: ScheduleTimeout = (callback, delayMs) => {
    const task: ScheduledTask = { callback, delayMs, cancelled: false };
    this.tasks.push(task);
    return () => {
      task.cancelled = true;
    };
  };

  pending(): ScheduledTask[] {
    return this.tasks.filter((task) => !task.cancelled);
  }

  runNext(): void {
    const task = this.pending()[0];
    if (task === undefined) {
      throw new Error("No scheduled task is pending.");
    }
    task.cancelled = true;
    task.callback();
  }

  runAll(): void {
    while (this.pending().length > 0) {
      this.runNext();
    }
  }
}

class ControllerHarness {
  readonly factory = new FakeRealtimeTransportFactory();
  readonly scheduler = new FakeScheduler();
  readonly controller: SessionController;
  activeRoomId: string | null = ROOM_ID;
  recoveryFailure: Error | null = null;
  recoveryCalls = 0;
  refreshCalls = 0;
  authRecoveryCalls = 0;
  leaveCalls = 0;
  closeCalls = 0;
  accessTokenHandler: () => Promise<string | null> = async () =>
    "safe-test-token";
  refreshHandler: () => Promise<boolean> = async () => true;
  leaveHandler: () => Promise<void> = async () => undefined;
  closeHandler: () => Promise<void> = async () => undefined;

  constructor(random = 0.5) {
    this.controller = new SessionController({
      apiBaseUrl: "http://127.0.0.1:8000",
      getAccessToken: () => this.accessTokenHandler(),
      getActiveRoom: async () => {
        this.recoveryCalls += 1;
        if (this.recoveryFailure !== null) {
          throw this.recoveryFailure;
        }
        return this.activeRoomId === null ? null : { id: this.activeRoomId };
      },
      refreshAccessToken: async () => {
        this.refreshCalls += 1;
        return this.refreshHandler();
      },
      onAuthenticationFailure: async () => {
        this.authRecoveryCalls += 1;
      },
      leaveRoom: async () => {
        this.leaveCalls += 1;
        await this.leaveHandler();
      },
      closeRoom: async () => {
        this.closeCalls += 1;
        await this.closeHandler();
      },
      transportFactory: this.factory,
      scheduleTimeout: this.scheduler.schedule,
      random: () => random,
    });
  }
}

async function settleAsyncWork(): Promise<void> {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve();
  }
}

function establishSocket(
  socket: FakeRealtimeTransport,
  snapshot: StateSnapshotPayload,
): void {
  socket.open();
  socket.message(
    serverEventFrame("CONNECTED", {
      server_time: "2030-01-01T12:00:00Z",
    }),
  );
  socket.message(serverEventFrame("STATE_SNAPSHOT", snapshot));
}

async function recoverAndEstablish(
  harness: ControllerHarness,
  snapshot: StateSnapshotPayload,
): Promise<FakeRealtimeTransport> {
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  const socket = harness.factory.latest();
  establishSocket(socket, snapshot);
  return socket;
}

function commandFrameCount(
  socket: FakeRealtimeTransport,
  commandType: string,
): number {
  return socket.frames.filter(
    (frame) => parseFrame(frame).type === commandType,
  ).length;
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
} {
  let resolvePromise: ((value: T) => void) | undefined;
  let rejectPromise: ((error: unknown) => void) | undefined;
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return {
    promise,
    resolve(value) {
      resolvePromise?.(value);
    },
    reject(error) {
      rejectPromise?.(error);
    },
  };
}

test("signed-in recovery with no active room becomes idle without a socket", async () => {
  const harness = new ControllerHarness();
  harness.activeRoomId = null;
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  assert.equal(harness.controller.getState().phase, "idle");
  assert.equal(harness.factory.sockets.length, 0);
});

test("signed-in recovery with an active room connects and snapshots", async () => {
  const harness = new ControllerHarness();
  await recoverAndEstablish(harness, makeLobbySnapshot());
  assert.equal(harness.controller.getState().roomId, ROOM_ID);
  assert.equal(harness.controller.getState().phase, "waiting");
  assert.equal(harness.factory.sockets.length, 1);
});

test("successful HTTP join bootstraps realtime and accepts the first authoritative snapshot", async () => {
  const harness = new ControllerHarness();
  harness.activeRoomId = null;
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  assert.equal(harness.controller.getState().phase, "idle");

  const dependencies: HomeRoomRequestDependencies = {
    createRoom: async () => {
      throw new Error("Create is outside this join test.");
    },
    joinRoomByCode: async () => ({
      room: {
        id: ROOM_ID,
        name: "Physics Sprint",
        join_code: "PHYS42",
        maximum_members: 8,
        member_count: 2,
        quiz_mode: "LEGACY_PHYSICS",
        education_level: null,
        quiz_subject: null,
        quiz_topic: null,
        target_total_marks: null,
      },
      member: {
        user_id: AUTHENTICATED_USER_ID,
        display_name: "Second User",
        room_id: ROOM_ID,
      },
    }),
    selectRoom: (roomId) => harness.controller.selectRoom(roomId),
    recoverActiveRoom: () => harness.controller.recoverActiveRoom(),
    getSelectedRoomId: () => harness.controller.getState().roomId,
    resultIsCurrent: () => true,
  };

  assert.deepEqual(
    await new HomeRoomRequestCoordinator().joinRoom("PHYS42", dependencies),
    { status: "selected", roomId: ROOM_ID },
  );
  await settleAsyncWork();
  const socket = harness.factory.latest();
  establishSocket(
    socket,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );

  assert.equal(parseFrame(socket.frames[0] ?? "").type, "AUTHENTICATE");
  assert.equal(harness.controller.getState().phase, "waiting");
  assert.equal(harness.controller.getState().connectionStage, "established");
});

test("a silent post-join bootstrap is bounded and automatically replaced", async () => {
  const harness = new ControllerHarness();
  harness.activeRoomId = null;
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();

  harness.controller.selectRoom(ROOM_ID);
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, 1);
  assert.equal(harness.controller.getState().phase, "connecting");
  assert.equal(
    harness.scheduler.pending()[0]?.delayMs,
    REALTIME_BOOTSTRAP_DEADLINE_MS,
  );

  harness.scheduler.runNext();
  assert.equal(harness.controller.getState().phase, "reconnecting");
  assert.equal(harness.controller.getState().reconnectAttempt, 1);
  harness.scheduler.runNext();
  await settleAsyncWork();

  assert.equal(harness.factory.sockets.length, 2);
  establishSocket(
    harness.factory.latest(),
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  assert.equal(harness.controller.getState().phase, "waiting");
});

test("a stalled post-join access-token lookup cannot suppress the replacement generation", async () => {
  const harness = new ControllerHarness();
  const stalledToken = deferred<string | null>();
  let tokenRequest = 0;
  harness.accessTokenHandler = () => {
    tokenRequest += 1;
    return tokenRequest === 1
      ? stalledToken.promise
      : Promise.resolve("current-safe-test-token");
  };
  harness.activeRoomId = null;
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();

  harness.controller.selectRoom(ROOM_ID);
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, 0);
  assert.equal(
    harness.scheduler.pending()[0]?.delayMs,
    REALTIME_BOOTSTRAP_DEADLINE_MS,
  );

  harness.scheduler.runNext();
  harness.scheduler.runNext();
  await settleAsyncWork();
  const currentSocket = harness.factory.latest();

  stalledToken.resolve("stale-safe-test-token");
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, 1);
  assert.equal(harness.factory.latest(), currentSocket);
  assert.equal(currentSocket.closeCalls.length, 0);

  establishSocket(
    currentSocket,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  assert.equal(harness.controller.getState().phase, "waiting");
});

test("stale token work cannot suppress the current room generation", async () => {
  const harness = new ControllerHarness();
  const firstToken = deferred<string | null>();
  const currentToken = deferred<string | null>();
  let tokenRequest = 0;
  harness.accessTokenHandler = () => {
    tokenRequest += 1;
    return tokenRequest === 1 ? firstToken.promise : currentToken.promise;
  };
  harness.activeRoomId = null;
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();

  harness.controller.selectRoom(ROOM_ID);
  harness.controller.setAppState("background");
  harness.controller.setAppState("active");
  currentToken.resolve("current-safe-test-token");
  await settleAsyncWork();
  const currentSocket = harness.factory.latest();

  firstToken.resolve("stale-safe-test-token");
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, 1);
  assert.equal(harness.factory.latest(), currentSocket);
  assert.equal(currentSocket.closeCalls.length, 0);

  establishSocket(
    currentSocket,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  assert.equal(harness.controller.getState().phase, "waiting");
});

test("active-room recovery failure is explicit and Retry recovers", async () => {
  const harness = new ControllerHarness();
  harness.recoveryFailure = new Error("offline detail must not leak");
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  assert.equal(harness.controller.getState().phase, "recoverable-error");
  harness.recoveryFailure = null;
  harness.controller.retryConnection();
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, 1);
  assert.equal(harness.controller.getState().phase, "connecting");
});

test("one active room creates at most one socket", async () => {
  const harness = new ControllerHarness();
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  harness.controller.selectRoom(ROOM_ID);
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, 1);
});

test("ordinary authenticated rerenders do not repeat active-room recovery", async () => {
  const harness = new ControllerHarness();
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  assert.equal(harness.recoveryCalls, 1);
  assert.equal(harness.factory.sockets.length, 1);
});

test("a changed authenticated identity starts one fresh recovery lifecycle", async () => {
  const harness = new ControllerHarness();
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  const firstSocket = harness.factory.latest();
  harness.controller.setAuthenticated(0, OTHER_AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  assert.equal(harness.recoveryCalls, 2);
  assert.equal(firstSocket.closeCalls.length, 1);
  assert.equal(harness.factory.sockets.length, 2);
});

test("selecting a different room closes and rotates the socket", async () => {
  const harness = new ControllerHarness();
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  const first = harness.factory.latest();
  harness.controller.selectRoom(OTHER_ROOM_ID);
  await settleAsyncWork();
  assert.equal(first.closeCalls.length, 1);
  assert.equal(harness.factory.sockets.length, 2);
  assert.equal(harness.factory.latest().url.includes(OTHER_ROOM_ID), true);
});

test("background closes the socket without clearing the snapshot or room", async () => {
  const harness = new ControllerHarness();
  const snapshot = makeOpenSnapshot();
  const socket = await recoverAndEstablish(harness, snapshot);
  const appliedSnapshot = harness.controller.getState().snapshot;
  harness.controller.setAppState("background");
  assert.equal(socket.closeCalls.length, 1);
  assert.equal(harness.controller.getState().snapshot, appliedSnapshot);
  assert.equal(harness.controller.getState().roomId, ROOM_ID);
  assert.equal(harness.scheduler.pending().length, 0);
});

test("foreground reconnects with a fresh socket and requires a snapshot", async () => {
  const harness = new ControllerHarness();
  await recoverAndEstablish(harness, makeOpenSnapshot());
  harness.controller.setAppState("background");
  harness.controller.setAppState("active");
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, 2);
  assert.equal(harness.controller.getState().phase, "reconnecting");
  establishSocket(harness.factory.latest(), makeOpenSnapshot());
  assert.equal(harness.controller.getState().phase, "question-open");
});

test("TOKEN_REFRESHED auth revision rotates the socket generation", async () => {
  const harness = new ControllerHarness();
  const first = await recoverAndEstablish(harness, makeLobbySnapshot());
  harness.controller.setAuthenticated(1, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  assert.equal(first.closeCalls.length, 1);
  assert.equal(harness.factory.sockets.length, 2);
});

test("close 4401 performs only one refresh attempt for its generation", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(harness, makeLobbySnapshot());
  let resolveRefresh: ((value: boolean) => void) | undefined;
  harness.refreshHandler = () =>
    new Promise<boolean>((resolve) => {
      resolveRefresh = resolve;
    });
  socket.serverClose(4401);
  socket.serverClose(4401);
  await settleAsyncWork();
  assert.equal(harness.refreshCalls, 1);
  resolveRefresh?.(true);
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, 2);
});

test("a freshly rotated socket cannot create an authentication refresh loop", async () => {
  const harness = new ControllerHarness();
  const first = await recoverAndEstablish(harness, makeLobbySnapshot());
  first.serverClose(4401);
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, 2);
  harness.factory.latest().serverClose(4401);
  await settleAsyncWork();
  assert.equal(harness.refreshCalls, 1);
  assert.equal(harness.authRecoveryCalls, 1);
  assert.equal(harness.controller.getState().phase, "idle");
});

test("failed refresh after 4401 invokes auth recovery and signs out", async () => {
  const harness = new ControllerHarness();
  harness.refreshHandler = async () => false;
  const socket = await recoverAndEstablish(harness, makeLobbySnapshot());
  socket.serverClose(4401);
  await settleAsyncWork();
  assert.equal(harness.refreshCalls, 1);
  assert.equal(harness.authRecoveryCalls, 1);
  assert.equal(harness.controller.getState().phase, "idle");
  assert.equal(harness.controller.getState().roomId, null);
});

test("reconnect delays use 0.5/1/2/4/8 seconds with bounded jitter", () => {
  assert.deepEqual(
    [1, 2, 3, 4, 5].map((attempt) => reconnectDelayMs(attempt, 0.5)),
    [500, 1_000, 2_000, 4_000, 8_000],
  );
  assert.equal(reconnectDelayMs(1, 0), 400);
  assert.equal(reconnectDelayMs(1, 1), 600);
});

test("five failed automatic reconnects end in recoverable-error", async () => {
  const harness = new ControllerHarness();
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  for (let failure = 0; failure < 6; failure += 1) {
    harness.factory.latest().serverClose(1006);
    if (failure < 5) {
      assert.equal(harness.scheduler.pending().length, 1);
      harness.scheduler.runNext();
      await settleAsyncWork();
    }
  }
  assert.equal(harness.controller.getState().phase, "recoverable-error");
  assert.equal(
    harness.controller.getState().lastError?.kind,
    "reconnect-exhausted",
  );
  assert.equal(harness.scheduler.pending().length, 0);
  const exhaustedSocketCount = harness.factory.sockets.length;
  harness.controller.retryConnection();
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, exhaustedSocketCount + 1);
  assert.equal(harness.controller.getState().phase, "reconnecting");
});

test("an authenticated snapshot resets reconnect backoff", async () => {
  const harness = new ControllerHarness();
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  harness.factory.latest().serverClose(1006);
  harness.scheduler.runNext();
  await settleAsyncWork();
  const recovered = harness.factory.latest();
  establishSocket(recovered, makeLobbySnapshot());
  recovered.serverClose(1006);
  assert.equal(harness.controller.getState().reconnectAttempt, 1);
  assert.equal(harness.scheduler.pending()[0]?.delayMs, 500);
});

test("duplicate answer submission is blocked synchronously before send returns", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(harness, makeOpenSnapshot());
  let nestedError: unknown;
  socket.sendHook = (frame) => {
    if (parseFrame(frame).type === "SUBMIT_ANSWER") {
      try {
        harness.controller.submitAnswer(QUESTION_ID, "joule");
      } catch (error: unknown) {
        nestedError = error;
      }
    }
  };
  harness.controller.submitAnswer(QUESTION_ID, "newton");
  assert.ok(nestedError instanceof CommandUnavailableError);
  assert.equal(commandFrameCount(socket, "SUBMIT_ANSWER"), 1);
  assert.equal(harness.controller.getState().phase, "submitting");
  const submittedFrame = socket.frames
    .map(parseFrame)
    .find((frame) => frame.type === "SUBMIT_ANSWER");
  assert.deepEqual(submittedFrame?.payload, {
    session_question_id: QUESTION_ID,
    type: "choice",
    option_id: "newton",
  });
  assert.equal(JSON.stringify(submittedFrame).includes("correct"), false);
  assert.equal(JSON.stringify(submittedFrame).includes("points"), false);
});

test("a pending answer is cleared and never replayed after disconnect", async () => {
  const harness = new ControllerHarness();
  const first = await recoverAndEstablish(harness, makeOpenSnapshot());
  harness.controller.submitAnswer(QUESTION_ID, "newton");
  first.serverClose(1006);
  assert.equal(harness.controller.getState().pendingCommand, null);
  harness.scheduler.runNext();
  await settleAsyncWork();
  const second = harness.factory.latest();
  establishSocket(second, makeOpenSnapshot());
  assert.equal(commandFrameCount(second, "SUBMIT_ANSWER"), 0);
  assert.equal(harness.controller.getState().phase, "question-open");
});

test("equal-version reconnect snapshot restores a durable accepted submission", async () => {
  const harness = new ControllerHarness();
  const first = await recoverAndEstablish(harness, makeOpenSnapshot());
  harness.controller.submitAnswer(QUESTION_ID, "newton");
  first.serverClose(1006);
  harness.scheduler.runNext();
  await settleAsyncWork();
  establishSocket(
    harness.factory.latest(),
    makeOpenSnapshot({ selectedOptionId: "newton" }),
  );
  assert.equal(harness.controller.getState().phase, "submitted");
  assert.equal(
    harness.controller.getState().snapshot?.viewer_submission
      ?.selected_option_id,
    "newton",
  );
});

test("reconnect snapshot overrides a local acknowledgement without durable submission", async () => {
  const harness = new ControllerHarness();
  const first = await recoverAndEstablish(harness, makeOpenSnapshot());
  harness.controller.submitAnswer(QUESTION_ID, "newton");
  first.message(
    serverEventFrame("ANSWER_ACCEPTED", {
      session_id: harness.controller.getState().snapshot?.session_id,
      state_version: 1,
      session_question_id: QUESTION_ID,
      selected_option_id: "newton",
      answer_text: null,
      grading_status: "GRADED",
      accepted_at: "2030-01-01T12:00:05Z",
    }),
  );
  assert.equal(harness.controller.getState().phase, "submitted");
  first.serverClose(1006);
  harness.scheduler.runNext();
  await settleAsyncWork();
  establishSocket(harness.factory.latest(), makeOpenSnapshot());
  assert.equal(harness.controller.getState().acknowledgedAnswer, null);
  assert.equal(harness.controller.getState().phase, "question-open");
});

test("REQUEST_STATE calls are coalesced per socket generation", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(harness, makeLobbySnapshot());
  assert.deepEqual(harness.controller.requestState(), { status: "sent" });
  assert.deepEqual(harness.controller.requestState(), {
    status: "coalesced",
  });
  assert.equal(commandFrameCount(socket, "REQUEST_STATE"), 1);
});

test("readiness and host start commands are typed and synchronously guarded", async () => {
  const readyHarness = new ControllerHarness();
  const readySocket = await recoverAndEstablish(
    readyHarness,
    makeLobbySnapshot(),
  );
  assert.deepEqual(readyHarness.controller.setReady(true), { status: "sent" });
  assert.throws(
    () => readyHarness.controller.setReady(false),
    CommandUnavailableError,
  );
  assert.equal(commandFrameCount(readySocket, "SET_READY"), 1);

  const startHarness = new ControllerHarness();
  const startSocket = await recoverAndEstablish(
    startHarness,
    makeLobbySnapshot(),
  );
  assert.deepEqual(startHarness.controller.startSession(), { status: "sent" });
  assert.throws(
    () => startHarness.controller.startSession(),
    CommandUnavailableError,
  );
  assert.equal(commandFrameCount(startSocket, "START_SESSION"), 1);
});

test("matching ANSWER_ACCEPTED requests durable state without local scoring", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(harness, makeOpenSnapshot());
  harness.controller.submitAnswer(QUESTION_ID, "newton");
  socket.message(
    serverEventFrame("ANSWER_ACCEPTED", {
      session_id: harness.controller.getState().snapshot?.session_id,
      state_version: 1,
      session_question_id: QUESTION_ID,
      selected_option_id: "newton",
      answer_text: null,
      grading_status: "GRADED",
      accepted_at: "2030-01-01T12:00:05Z",
    }),
  );
  const acknowledgement = harness.controller.getState().acknowledgedAnswer;
  assert.equal(acknowledgement?.selectedOptionId, "newton");
  assert.equal(Object.hasOwn(acknowledgement ?? {}, "points"), false);
  assert.equal(commandFrameCount(socket, "REQUEST_STATE"), 1);
  assert.throws(
    () => harness.controller.submitAnswer(QUESTION_ID, "joule"),
    CommandUnavailableError,
  );
  assert.equal(commandFrameCount(socket, "SUBMIT_ANSWER"), 1);
});

test("host quiz preparation sends one strict PREPARE_QUIZ command", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(
    harness,
    makeLobbySnapshot(makeAdaptiveRoomState()),
  );
  const requestId = "44444444-4444-4444-8444-444444444444";
  assert.deepEqual(harness.controller.prepareQuiz(requestId), {
    status: "sent",
  });
  assert.throws(
    () => harness.controller.prepareQuiz(requestId),
    CommandUnavailableError,
  );
  assert.equal(commandFrameCount(socket, "PREPARE_QUIZ"), 1);
  const frame = socket.frames
    .map(parseFrame)
    .find((entry) => entry.type === "PREPARE_QUIZ");
  assert.deepEqual(frame?.payload, { request_id: requestId });
  assert.equal(
    JSON.stringify(frame).includes("correct_option_id"),
    false,
  );
});

test("quiz preparation is host-only, adaptive-only, and lobby-only", async () => {
  const memberHarness = new ControllerHarness();
  await recoverAndEstablish(
    memberHarness,
    makeLobbySnapshot(
      makeAdaptiveRoomState({ viewerRole: "member", viewerReady: true }),
    ),
  );
  assert.throws(
    () =>
      memberHarness.controller.prepareQuiz(
        "44444444-4444-4444-8444-444444444444",
      ),
    CommandUnavailableError,
  );

  const legacyHarness = new ControllerHarness();
  await recoverAndEstablish(legacyHarness, makeLobbySnapshot());
  assert.throws(
    () =>
      legacyHarness.controller.prepareQuiz(
        "44444444-4444-4444-8444-444444444444",
      ),
    CommandUnavailableError,
  );

  const activeHarness = new ControllerHarness();
  await recoverAndEstablish(activeHarness, makeOpenSnapshot());
  assert.throws(
    () =>
      activeHarness.controller.prepareQuiz(
        "44444444-4444-4444-8444-444444444444",
      ),
    CommandUnavailableError,
  );
});

test("host retry grading sends one bounded RETRY_GRADING command", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(
    harness,
    makeGradingSnapshot({ gradingStatus: "UNAVAILABLE" }),
  );
  assert.equal(harness.controller.getState().phase, "grading");
  assert.deepEqual(harness.controller.retryGrading(), { status: "sent" });
  assert.throws(
    () => harness.controller.retryGrading(),
    CommandUnavailableError,
  );
  assert.equal(commandFrameCount(socket, "RETRY_GRADING"), 1);

  const openHarness = new ControllerHarness();
  await recoverAndEstablish(openHarness, makeOpenSnapshot());
  assert.throws(
    () => openHarness.controller.retryGrading(),
    CommandUnavailableError,
  );
});

test("typed answers send strict text frames and reject option questions", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(
    harness,
    makeOpenSnapshot({ questionType: "WRITTEN", maxMarks: 4 }),
  );
  assert.deepEqual(
    harness.controller.submitTextAnswer(QUESTION_ID, "  Heat flows.  "),
    { status: "sent" },
  );
  const frame = socket.frames
    .map(parseFrame)
    .find((entry) => entry.type === "SUBMIT_ANSWER");
  assert.deepEqual(frame?.payload, {
    session_question_id: QUESTION_ID,
    type: "text",
    text: "Heat flows.",
  });
  assert.throws(
    () => harness.controller.submitAnswer(QUESTION_ID, "newton"),
    CommandUnavailableError,
  );
  assert.throws(
    () => harness.controller.submitTextAnswer(QUESTION_ID, "   "),
    CommandUnavailableError,
  );
  assert.throws(
    () => harness.controller.submitTextAnswer(QUESTION_ID, "x".repeat(1001)),
    CommandUnavailableError,
  );

  const choiceHarness = new ControllerHarness();
  await recoverAndEstablish(choiceHarness, makeOpenSnapshot());
  assert.throws(
    () => choiceHarness.controller.submitTextAnswer(QUESTION_ID, "Newton"),
    CommandUnavailableError,
  );
});

test("answer conflicts request fresh state and do not resend", async () => {
  for (const code of [
    "answer_too_late",
    "answer_already_submitted",
    "stale_session_question",
    "invalid_option",
    "question_not_open",
    "session_not_active",
  ]) {
    const harness = new ControllerHarness();
    const socket = await recoverAndEstablish(harness, makeOpenSnapshot());
    harness.controller.submitAnswer(QUESTION_ID, "newton");
    socket.message(
      serverEventFrame("ERROR", {
        code,
        message: "Safe server message",
      }),
    );
    assert.equal(harness.controller.getState().lastError?.code, code);
    assert.equal(harness.controller.getState().pendingCommand, null);
    assert.equal(commandFrameCount(socket, "SUBMIT_ANSWER"), 1);
    assert.equal(commandFrameCount(socket, "REQUEST_STATE"), 1);
  }
});

test("session-already-active start rejection repairs state without local navigation", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(harness, makeLobbySnapshot());
  harness.controller.startSession();
  socket.message(
    serverEventFrame("ERROR", {
      code: "session_already_active",
      message: "A session is already active.",
    }),
  );
  assert.equal(harness.controller.getState().phase, "waiting");
  assert.equal(harness.controller.getState().lastError?.code, "session_already_active");
  assert.equal(commandFrameCount(socket, "START_SESSION"), 1);
  assert.equal(commandFrameCount(socket, "REQUEST_STATE"), 1);
});

test("finished dismissal permits a guarded rematch and only a new session resolves it", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(harness, makeFinishedSnapshot());
  harness.controller.dismissFinishedSession();
  assert.equal(harness.controller.getState().phase, "waiting");
  harness.controller.startSession();
  assert.throws(() => harness.controller.startSession(), CommandUnavailableError);
  assert.equal(commandFrameCount(socket, "START_SESSION"), 1);

  socket.message(serverEventFrame("STATE_SNAPSHOT", makeFinishedSnapshot()));
  assert.equal(harness.controller.getState().pendingCommand?.kind, "start");
  socket.message(
    serverEventFrame(
      "STATE_SNAPSHOT",
      makeOpenSnapshot({ sessionId: NEW_SESSION_ID, stateVersion: 1 }),
    ),
  );
  assert.equal(harness.controller.getState().pendingCommand, null);
  assert.equal(harness.controller.getState().dismissedFinishedSessionId, null);
  assert.equal(harness.controller.getState().phase, "question-open");
});

test("an old socket generation cannot change route-driving session state", async () => {
  const harness = new ControllerHarness();
  const oldSocket = await recoverAndEstablish(harness, makeLobbySnapshot());
  harness.controller.selectRoom(OTHER_ROOM_ID);
  oldSocket.message(serverEventFrame("STATE_SNAPSHOT", makeFinishedSnapshot()));
  assert.equal(harness.controller.getState().roomId, OTHER_ROOM_ID);
  assert.equal(harness.controller.getState().snapshot, null);
  assert.notEqual(harness.controller.getState().phase, "finished");
});

test("transition hints coalesce into one REQUEST_STATE command", async () => {
  const harness = new ControllerHarness();
  const snapshot = makeOpenSnapshot();
  const socket = await recoverAndEstablish(harness, snapshot);
  socket.message(
    serverEventFrame("QUESTION_OPENED", {
      session_id: snapshot.session_id,
      state_version: 2,
      question: snapshot.question,
    }),
  );
  socket.message(
    serverEventFrame("SESSION_STARTED", {
      session_id: snapshot.session_id,
      state_version: 3,
    }),
  );
  assert.equal(commandFrameCount(socket, "REQUEST_STATE"), 1);
  assert.equal(
    harness.controller.getState().expectedSnapshot?.stateVersion,
    3,
  );
});

test("a final transition repairs an in-flight stale snapshot request", async () => {
  const harness = new ControllerHarness();
  const revealSnapshot = makeRevealSnapshot({ stateVersion: 8 });
  const socket = await recoverAndEstablish(harness, revealSnapshot);

  socket.message(
    serverEventFrame("QUESTION_REVEALED", {
      session_id: SESSION_ID,
      state_version: 9,
      question: revealSnapshot.question,
      viewer_submission: revealSnapshot.viewer_submission,
      leaderboard: revealSnapshot.leaderboard,
    }),
  );
  assert.equal(commandFrameCount(socket, "REQUEST_STATE"), 1);

  socket.message(
    serverEventFrame("SESSION_FINISHED", {
      session_id: SESSION_ID,
      state_version: 10,
      leaderboard: revealSnapshot.leaderboard,
      finished_at: "2030-01-01T12:02:00Z",
    }),
  );

  socket.message(serverEventFrame("STATE_SNAPSHOT", revealSnapshot));
  assert.equal(commandFrameCount(socket, "REQUEST_STATE"), 2);

  const finishedSnapshot = makeFinishedSnapshot({ stateVersion: 10 });
  socket.message(serverEventFrame("STATE_SNAPSHOT", finishedSnapshot));
  assert.equal(harness.controller.getState().phase, "finished");
  assert.equal(harness.controller.getState().snapshot?.status, "FINISHED");
});

test("duplicate FINISHED hints and reconnect preserve the finished snapshot", async () => {
  const harness = new ControllerHarness();
  const revealSnapshot = makeRevealSnapshot({ stateVersion: 8 });
  const socket = await recoverAndEstablish(harness, revealSnapshot);
  socket.message(
    serverEventFrame("SESSION_FINISHED", {
      session_id: SESSION_ID,
      state_version: 10,
      leaderboard: revealSnapshot.leaderboard,
      finished_at: "2030-01-01T12:02:00Z",
    }),
  );
  socket.message(
    serverEventFrame(
      "STATE_SNAPSHOT",
      makeFinishedSnapshot({ stateVersion: 10 }),
    ),
  );
  const requestCount = commandFrameCount(socket, "REQUEST_STATE");

  socket.message(
    serverEventFrame("SESSION_FINISHED", {
      session_id: SESSION_ID,
      state_version: 10,
      leaderboard: revealSnapshot.leaderboard,
      finished_at: "2030-01-01T12:02:00Z",
    }),
  );
  assert.equal(commandFrameCount(socket, "REQUEST_STATE"), requestCount);
  assert.equal(harness.controller.getState().phase, "finished");

  harness.controller.setAppState("background");
  harness.controller.setAppState("active");
  await settleAsyncWork();
  const reconnectedSocket = harness.factory.latest();
  establishSocket(reconnectedSocket, makeFinishedSnapshot({ stateVersion: 10 }));
  assert.equal(harness.controller.getState().phase, "finished");
  assert.equal(harness.controller.getState().snapshot?.status, "FINISHED");
});

test("fatal protocol and connection-limit closes never schedule retry", async () => {
  for (const closeCode of [4400, 4409]) {
    const harness = new ControllerHarness();
    const socket = await recoverAndEstablish(harness, makeLobbySnapshot());
    socket.serverClose(closeCode);
    assert.equal(harness.controller.getState().phase, "fatal-error");
    assert.equal(harness.scheduler.pending().length, 0);
  }
});

test("missing-room and membership closes clear room state without retry", async () => {
  for (const closeCode of [4403, 4404]) {
    const harness = new ControllerHarness();
    const socket = await recoverAndEstablish(harness, makeLobbySnapshot());
    socket.serverClose(closeCode);
    assert.equal(harness.controller.getState().phase, "fatal-error");
    assert.equal(harness.controller.getState().roomId, null);
    assert.equal(harness.controller.getState().snapshot, null);
    assert.equal(harness.scheduler.pending().length, 0);
  }
});

test("member leave and host close clear the room through typed HTTP commands", async () => {
  const memberHarness = new ControllerHarness();
  const memberSocket = await recoverAndEstablish(
    memberHarness,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  assert.deepEqual(await memberHarness.controller.leaveCurrentRoom(), {
    status: "completed",
  });
  assert.equal(memberHarness.leaveCalls, 1);
  assert.equal(memberHarness.closeCalls, 0);
  assert.equal(memberHarness.controller.getState().roomId, null);
  assert.equal(memberHarness.controller.getState().phase, "idle");
  assert.equal(memberSocket.closeCalls.length, 1);
  assert.equal(memberHarness.scheduler.pending().length, 0);

  const hostHarness = new ControllerHarness();
  const hostSocket = await recoverAndEstablish(
    hostHarness,
    makeLobbySnapshot(),
  );
  assert.deepEqual(await hostHarness.controller.closeCurrentRoom(), {
    status: "completed",
  });
  assert.equal(hostHarness.closeCalls, 1);
  assert.equal(hostHarness.leaveCalls, 0);
  assert.equal(hostHarness.controller.getState().roomId, null);
  assert.equal(hostSocket.closeCalls.length, 1);
  assert.equal(hostHarness.scheduler.pending().length, 0);
});

test("duplicate lifecycle taps share one in-flight HTTP request", async () => {
  const leaveHarness = new ControllerHarness();
  const pendingLeave = deferred<void>();
  leaveHarness.leaveHandler = () => pendingLeave.promise;
  await recoverAndEstablish(
    leaveHarness,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  const firstLeave = leaveHarness.controller.leaveCurrentRoom();
  const secondLeave = leaveHarness.controller.leaveCurrentRoom();
  assert.equal(firstLeave, secondLeave);
  assert.equal(leaveHarness.leaveCalls, 1);
  assert.equal(leaveHarness.controller.getState().pendingRoomExit, "leave");
  assert.throws(
    () => leaveHarness.controller.setReady(true),
    CommandUnavailableError,
  );
  pendingLeave.resolve(undefined);
  await Promise.all([firstLeave, secondLeave]);

  const closeHarness = new ControllerHarness();
  const pendingClose = deferred<void>();
  closeHarness.closeHandler = () => pendingClose.promise;
  await recoverAndEstablish(closeHarness, makeLobbySnapshot());
  const firstClose = closeHarness.controller.closeCurrentRoom();
  const secondClose = closeHarness.controller.closeCurrentRoom();
  assert.equal(firstClose, secondClose);
  assert.equal(closeHarness.closeCalls, 1);
  assert.equal(closeHarness.controller.getState().pendingRoomExit, "close");
  assert.throws(
    () => closeHarness.controller.startSession(),
    CommandUnavailableError,
  );
  pendingClose.resolve(undefined);
  await Promise.all([firstClose, secondClose]);
});

test("expected lifecycle socket closure never schedules reconnect", async () => {
  const harness = new ControllerHarness();
  const pendingLeave = deferred<void>();
  harness.leaveHandler = () => pendingLeave.promise;
  const socket = await recoverAndEstablish(
    harness,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  const leave = harness.controller.leaveCurrentRoom();

  socket.message(
    serverEventFrame("ERROR", {
      code: "room_left",
      message: "You left this room.",
    }),
  );
  socket.serverClose(4403, "room_left", true);

  assert.equal(harness.controller.getState().roomId, null);
  assert.equal(harness.scheduler.pending().length, 0);
  assert.equal(harness.factory.sockets.length, 1);
  pendingLeave.resolve(undefined);
  await leave;
  assert.equal(harness.factory.sockets.length, 1);
});

test("pending room exit suppresses every alternate socket-opening path", async () => {
  const harness = new ControllerHarness();
  const pendingLeave = deferred<void>();
  harness.leaveHandler = () => pendingLeave.promise;
  await recoverAndEstablish(
    harness,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  const leave = harness.controller.leaveCurrentRoom();

  harness.controller.setAuthenticated(1, AUTHENTICATED_USER_ID);
  harness.controller.retryConnection();
  harness.controller.setAppState("background");
  harness.controller.setAppState("active");
  await settleAsyncWork();

  assert.equal(harness.factory.sockets.length, 1);
  assert.equal(harness.scheduler.pending().length, 0);
  pendingLeave.resolve(undefined);
  await leave;
  assert.equal(harness.controller.getState().roomId, null);
});

test("failed leave reconnects only after an in-flight socket loss", async () => {
  const harness = new ControllerHarness();
  const pendingLeave = deferred<void>();
  harness.leaveHandler = () => pendingLeave.promise;
  const socket = await recoverAndEstablish(
    harness,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  const leave = harness.controller.leaveCurrentRoom();

  socket.serverClose(1006);
  assert.equal(harness.scheduler.pending().length, 0);
  assert.equal(harness.factory.sockets.length, 1);
  pendingLeave.reject(new NetworkApiError());
  await assert.rejects(leave);
  await settleAsyncWork();

  assert.equal(harness.controller.getState().roomId, ROOM_ID);
  assert.equal(harness.controller.getState().pendingRoomExit, null);
  assert.equal(harness.factory.sockets.length, 2);
  assert.equal(
    harness.scheduler.pending()[0]?.delayMs,
    REALTIME_BOOTSTRAP_DEADLINE_MS,
  );
  establishSocket(
    harness.factory.latest(),
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  assert.equal(harness.scheduler.pending().length, 0);
});

test("successful room exit keeps authentication available for another room", async () => {
  const harness = new ControllerHarness();
  await recoverAndEstablish(
    harness,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );

  await harness.controller.leaveCurrentRoom();
  harness.controller.selectRoom(OTHER_ROOM_ID);
  await settleAsyncWork();

  assert.equal(harness.controller.getState().roomId, OTHER_ROOM_ID);
  assert.equal(harness.factory.sockets.length, 2);
  assert.equal(harness.factory.latest().url.includes(OTHER_ROOM_ID), true);
});

test("failed lifecycle requests preserve the selected room", async () => {
  const memberHarness = new ControllerHarness();
  memberHarness.leaveHandler = async () => {
    throw new NetworkApiError();
  };
  await recoverAndEstablish(
    memberHarness,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  await assert.rejects(
    memberHarness.controller.leaveCurrentRoom(),
    (error: unknown) =>
      error instanceof Error && error.message.includes("could not be confirmed"),
  );
  assert.equal(memberHarness.controller.getState().roomId, ROOM_ID);
  assert.equal(memberHarness.controller.getState().pendingRoomExit, null);

  const hostHarness = new ControllerHarness();
  hostHarness.closeHandler = async () => {
    throw new BackendApiError(
      "session_already_active",
      "This room already has an active quiz session.",
      409,
    );
  };
  await recoverAndEstablish(hostHarness, makeLobbySnapshot());
  await assert.rejects(hostHarness.controller.closeCurrentRoom());
  assert.equal(hostHarness.controller.getState().roomId, ROOM_ID);
  assert.equal(
    hostHarness.controller.getState().lastError?.code,
    "session_already_active",
  );
  assert.equal(
    hostHarness.controller.getState().lastError?.message,
    "Finish the current quiz before leaving the room.",
  );
});

test("lifecycle commands enforce role, connection, and active-session guards", async () => {
  const memberHarness = new ControllerHarness();
  await recoverAndEstablish(
    memberHarness,
    makeLobbySnapshot(makeRoomState({ viewerRole: "member" })),
  );
  assert.throws(
    () => memberHarness.controller.closeCurrentRoom(),
    CommandUnavailableError,
  );

  const hostHarness = new ControllerHarness();
  await recoverAndEstablish(hostHarness, makeLobbySnapshot());
  assert.throws(
    () => hostHarness.controller.leaveCurrentRoom(),
    CommandUnavailableError,
  );

  const activeHarness = new ControllerHarness();
  await recoverAndEstablish(
    activeHarness,
    makeOpenSnapshot({
      roomState: makeRoomState({ viewerRole: "member" }),
    }),
  );
  assert.throws(
    () => activeHarness.controller.leaveCurrentRoom(),
    CommandUnavailableError,
  );
  assert.equal(activeHarness.leaveCalls, 0);

  const disconnectedHarness = new ControllerHarness();
  disconnectedHarness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  assert.throws(
    () => disconnectedHarness.controller.closeCurrentRoom(),
    CommandUnavailableError,
  );
  assert.equal(disconnectedHarness.closeCalls, 0);
});

test("sign-out closes an active socket and clears authoritative room state", async () => {
  const harness = new ControllerHarness();
  const socket = await recoverAndEstablish(harness, makeLobbySnapshot());
  harness.controller.setSignedOut();
  assert.equal(socket.closeCalls.length, 1);
  assert.equal(harness.controller.getState().phase, "idle");
  assert.equal(harness.controller.getState().snapshot, null);
});

test("sign-out cancels reconnect timers and stale work", async () => {
  const harness = new ControllerHarness();
  harness.controller.setAuthenticated(0, AUTHENTICATED_USER_ID);
  await settleAsyncWork();
  harness.factory.latest().serverClose(1006);
  assert.equal(harness.scheduler.pending().length, 1);
  const socketCount = harness.factory.sockets.length;
  harness.controller.setSignedOut();
  harness.scheduler.runAll();
  await settleAsyncWork();
  assert.equal(harness.factory.sockets.length, socketCount);
  assert.equal(harness.controller.getState().phase, "idle");
});
