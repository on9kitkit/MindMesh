import assert from "node:assert/strict";
import test from "node:test";

import { BackendApiError, NetworkApiError } from "../../api/errors";
import type {
  CreateRoomInput,
  JoinByCodeResponse,
  RoomResponse,
} from "../../api/schemas";
import { RealtimeNetworkError } from "../../realtime/errors";
import {
  initialSessionState,
  sessionReducer,
} from "../session/sessionState";
import {
  createRoomInputForPreset,
  createRoomInputForSelection,
  DEFAULT_ROOM_CAPACITY_PRESET,
  deriveHomeScreenState,
  getJoinCodeValidationMessage,
  getQuizSelectionValidationMessage,
  HomeRoomRequestCoordinator,
  homeOperationReducer,
  initialHomeOperationState,
  reconcileRoomCapacityPreset,
  roomCapacityIsAvailable,
  type HomeRoomRequestDependencies,
} from "./homeFlow";

const room: RoomResponse = {
  id: "room-123",
  name: "Physics Sprint",
  join_code: "PHYS42",
  maximum_members: 8,
  member_count: 1,
  quiz_mode: "LEGACY_PHYSICS",
  education_level: null,
  quiz_subject: null,
  quiz_topic: null,
  target_total_marks: null,
};

const joinedRoom: JoinByCodeResponse = {
  room,
  member: {
    user_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    display_name: "Student",
    room_id: room.id,
  },
};

class HomeRequestHarness {
  readonly createInputs: CreateRoomInput[] = [];
  readonly joinCodes: string[] = [];
  readonly selectedRoomIds: string[] = [];
  recoveryCalls = 0;
  selectedRoomId: string | null = null;
  current = true;
  createHandler: (input: CreateRoomInput) => Promise<RoomResponse> = async () =>
    room;
  joinHandler: (joinCode: string) => Promise<JoinByCodeResponse> = async () =>
    joinedRoom;

  readonly dependencies: HomeRoomRequestDependencies = {
    createRoom: async (input) => {
      this.createInputs.push(input);
      return this.createHandler(input);
    },
    joinRoomByCode: async (joinCode) => {
      this.joinCodes.push(joinCode);
      return this.joinHandler(joinCode);
    },
    selectRoom: (roomId) => {
      this.selectedRoomId = roomId;
      this.selectedRoomIds.push(roomId);
    },
    recoverActiveRoom: async () => {
      this.recoveryCalls += 1;
    },
    getSelectedRoomId: () => this.selectedRoomId,
    resultIsCurrent: () => this.current,
  };
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve(value: T): void;
} {
  let resolver: ((value: T) => void) | null = null;
  const promise = new Promise<T>((resolve) => {
    resolver = resolve;
  });
  return {
    promise,
    resolve(value) {
      if (resolver === null) {
        throw new Error("Deferred promise is not initialized.");
      }
      resolver(value);
    },
  };
}

test("Home waits for active-room recovery before exposing room actions", () => {
  const recovering = sessionReducer(initialSessionState, {
    type: "RECOVERY_STARTED",
    generation: 1,
  });
  assert.deepEqual(
    deriveHomeScreenState(recovering, initialHomeOperationState),
    { status: "checking-active-room" },
  );
});

test("no active room produces the explicit ready state", () => {
  assert.deepEqual(
    deriveHomeScreenState(initialSessionState, initialHomeOperationState),
    { status: "no-active-room" },
  );
});

test("create sends one fixed atomic room request and selects its returned ID", async () => {
  const harness = new HomeRequestHarness();
  const coordinator = new HomeRoomRequestCoordinator();
  assert.deepEqual(await coordinator.createRoom(harness.dependencies), {
    status: "selected",
    roomId: room.id,
  });
  assert.deepEqual(harness.createInputs, [createRoomInputForPreset("standard")]);
  assert.deepEqual(harness.selectedRoomIds, [room.id]);
  const serializedInput = JSON.stringify(harness.createInputs[0]);
  assert.equal(serializedInput.includes("user_id"), false);
  assert.equal(serializedInput.includes("owner_id"), false);
  assert.equal(serializedInput.includes("isPro"), false);
  assert.equal(serializedInput.includes("entitlement"), false);
});

test("Standard is the default free room and Large maps only to capacity twenty", async () => {
  assert.equal(DEFAULT_ROOM_CAPACITY_PRESET, "standard");
  assert.deepEqual(createRoomInputForPreset("standard"), {
    name: "Physics Sprint",
    maximum_members: 8,
  });
  assert.deepEqual(createRoomInputForPreset("large"), {
    name: "Physics Sprint",
    maximum_members: 20,
  });
  assert.equal(roomCapacityIsAvailable("standard", false), true);
  assert.equal(roomCapacityIsAvailable("large", false), false);
  assert.equal(roomCapacityIsAvailable("large", true), true);
});

test("a refreshed Free status returns an unavailable Large selection to Standard", () => {
  assert.equal(reconcileRoomCapacityPreset("large", true), "large");
  assert.equal(reconcileRoomCapacityPreset("large", false), "standard");
  assert.equal(reconcileRoomCapacityPreset("standard", false), "standard");
});

test("adaptive selection builds the strict nested quiz settings contract", () => {
  assert.deepEqual(
    createRoomInputForSelection("standard", {
      mode: "adaptive",
      subject: "english_literature",
      topic: "poetry_analysis",
      totalMarks: 20,
    }),
    {
      name: "GCSE English Literature: Poetry analysis",
      maximum_members: 8,
      quiz_settings: {
        mode: "adaptive",
        level: "gcse",
        subject: "english_literature",
        topic: "poetry_analysis",
        total_marks: 20,
      },
    },
  );
  assert.deepEqual(
    createRoomInputForSelection("standard", { mode: "legacy" }),
    createRoomInputForPreset("standard"),
  );
  assert.equal(
    getQuizSelectionValidationMessage({ mode: "legacy" }),
    null,
  );
  assert.ok(
    getQuizSelectionValidationMessage({
      mode: "adaptive",
      subject: "physics",
      topic: "algebra",
      totalMarks: 20,
    }) !== null,
  );
  assert.ok(
    getQuizSelectionValidationMessage({
      mode: "adaptive",
      subject: "physics",
      topic: "energy",
      totalMarks: 41,
    }) !== null,
  );
});

test("adaptive create sends quiz settings and rejects invalid selections locally", async () => {
  const harness = new HomeRequestHarness();
  const outcome = await new HomeRoomRequestCoordinator().createRoomWithSelection(
    harness.dependencies,
    "standard",
    { mode: "adaptive", subject: "physics", topic: "energy", totalMarks: 20 },
  );
  assert.equal(outcome.status, "selected");
  const body = JSON.stringify(harness.createInputs[0]);
  assert.equal(body.includes('"mode":"adaptive"'), true);
  assert.equal(body.includes('"level":"gcse"'), true);
  assert.equal(body.includes('"subject":"physics"'), true);
  assert.equal(body.includes('"topic":"energy"'), true);
  assert.equal(body.includes('"total_marks":20'), true);

  const invalid = new HomeRequestHarness();
  const rejected = await new HomeRoomRequestCoordinator().createRoomWithSelection(
    invalid.dependencies,
    "standard",
    { mode: "adaptive", subject: "physics", topic: "algebra", totalMarks: 20 },
  );
  assert.equal(rejected.status, "failed");
  assert.equal(invalid.createInputs.length, 0);
});

test("a selected Large Room sends capacity twenty without client premium authority", async () => {
  const harness = new HomeRequestHarness();
  const outcome = await new HomeRoomRequestCoordinator().createRoom(
    harness.dependencies,
    "large",
  );
  assert.equal(outcome.status, "selected");
  assert.deepEqual(harness.createInputs, [
    { name: "Physics Sprint", maximum_members: 20 },
  ]);
  assert.deepEqual(Object.keys(harness.createInputs[0] ?? {}).sort(), [
    "maximum_members",
    "name",
  ]);
});

test("duplicate create taps share one request gate", async () => {
  const harness = new HomeRequestHarness();
  const pending = deferred<RoomResponse>();
  harness.createHandler = () => pending.promise;
  const coordinator = new HomeRoomRequestCoordinator();
  const first = coordinator.createRoom(harness.dependencies);
  const duplicate = await coordinator.createRoom(harness.dependencies);
  assert.deepEqual(duplicate, { status: "blocked" });
  assert.equal(harness.createInputs.length, 1);
  pending.resolve(room);
  assert.equal((await first).status, "selected");
});

test("join normalizes the code and selects the returned room ID", async () => {
  const harness = new HomeRequestHarness();
  const coordinator = new HomeRoomRequestCoordinator();
  const outcome = await coordinator.joinRoom(
    "  phys42  ",
    harness.dependencies,
  );
  assert.deepEqual(outcome, { status: "selected", roomId: room.id });
  assert.deepEqual(harness.joinCodes, ["PHYS42"]);
  assert.deepEqual(harness.selectedRoomIds, [room.id]);
});

test("invalid join codes fail locally without a request", async () => {
  const harness = new HomeRequestHarness();
  const coordinator = new HomeRoomRequestCoordinator();
  const outcome = await coordinator.joinRoom("ROOM01", harness.dependencies);
  assert.deepEqual(outcome, {
    status: "failed",
    message: "Use six characters: A–Z and 2–9.",
  });
  assert.deepEqual(harness.joinCodes, []);
  assert.equal(getJoinCodeValidationMessage("ROOM01") !== null, true);
  assert.equal(getJoinCodeValidationMessage("phys42"), null);
});

test("duplicate join requests are blocked while the first is unresolved", async () => {
  const harness = new HomeRequestHarness();
  const pending = deferred<JoinByCodeResponse>();
  harness.joinHandler = () => pending.promise;
  const coordinator = new HomeRoomRequestCoordinator();
  const first = coordinator.joinRoom("PHYS42", harness.dependencies);
  const duplicate = await coordinator.joinRoom("PHYS42", harness.dependencies);
  assert.deepEqual(duplicate, { status: "blocked" });
  assert.equal(harness.joinCodes.length, 1);
  pending.resolve(joinedRoom);
  assert.equal((await first).status, "selected");
});

test("existing-room conflicts trigger exactly one bounded recovery", async () => {
  const harness = new HomeRequestHarness();
  harness.joinHandler = async () => {
    throw new BackendApiError(
      "user_already_in_another_room",
      "User is already in another room.",
      409,
    );
  };
  const coordinator = new HomeRoomRequestCoordinator();
  assert.deepEqual(
    await coordinator.joinRoom("PHYS42", harness.dependencies),
    { status: "recovery-requested" },
  );
  assert.equal(harness.recoveryCalls, 1);
  assert.deepEqual(harness.selectedRoomIds, []);
});

test("join maps required backend conflicts to readable messages", async () => {
  const cases = [
    ["room_not_found", "This room could not be found.", 404],
    ["room_full", "This room is full.", 409],
    ["session_already_active", "This quiz has already started.", 409],
  ] as const;
  for (const [code, message, status] of cases) {
    const harness = new HomeRequestHarness();
    harness.joinHandler = async () => {
      throw new BackendApiError(code, "Backend detail", status);
    };
    const outcome = await new HomeRoomRequestCoordinator().joinRoom(
      "PHYS42",
      harness.dependencies,
    );
    assert.deepEqual(outcome, { status: "failed", message, code });
  }
});

test("network failures remain readable and retryable", async () => {
  const harness = new HomeRequestHarness();
  harness.createHandler = async () => {
    throw new NetworkApiError();
  };
  assert.deepEqual(
    await new HomeRoomRequestCoordinator().createRoom(harness.dependencies),
    {
      status: "failed",
      message: "Could not reach the StudyRoom server.",
    },
  );
});

test("premium gate failures remain readable and retryable", async () => {
  const cases = [
    [
      "pro_required",
      "StudyRoom Pro could not be verified for a Large Room. Open StudyRoom Pro to refresh your status.",
      403,
    ],
    [
      "premium_verification_unavailable",
      "We couldn't verify StudyRoom Pro right now. Try again shortly.",
      503,
    ],
  ] as const;
  for (const [code, message, status] of cases) {
    const harness = new HomeRequestHarness();
    harness.createHandler = async () => {
      throw new BackendApiError(code, "Backend detail", status);
    };
    assert.deepEqual(
      await new HomeRoomRequestCoordinator().createRoom(
        harness.dependencies,
        "large",
      ),
      { status: "failed", message, code },
    );
  }
});

test("stale signed-out request results cannot select or navigate to a room", async () => {
  const harness = new HomeRequestHarness();
  const pending = deferred<RoomResponse>();
  harness.createHandler = () => pending.promise;
  const coordinator = new HomeRoomRequestCoordinator();
  const result = coordinator.createRoom(harness.dependencies);
  harness.current = false;
  pending.resolve(room);
  assert.deepEqual(await result, { status: "cancelled" });
  assert.deepEqual(harness.selectedRoomIds, []);
});

test("a selected active room blocks another create request", async () => {
  const harness = new HomeRequestHarness();
  harness.selectedRoomId = room.id;
  assert.deepEqual(
    await new HomeRoomRequestCoordinator().createRoom(harness.dependencies),
    { status: "blocked" },
  );
  assert.deepEqual(harness.createInputs, []);
});

test("recovery failure exposes a session Retry state", () => {
  let state = sessionReducer(initialSessionState, {
    type: "RECOVERY_STARTED",
    generation: 1,
  });
  state = sessionReducer(state, {
    type: "RECOVERY_FAILED",
    generation: 1,
    error: new RealtimeNetworkError(),
  });
  assert.deepEqual(
    deriveHomeScreenState(state, initialHomeOperationState),
    {
      status: "recoverable-error",
      source: "session",
      message: "Could not reach the StudyRoom server.",
    },
  );
});

test("Home operation state distinguishes creating and joining", () => {
  const creating = homeOperationReducer(initialHomeOperationState, {
    type: "CREATE_REQUESTED",
  });
  assert.deepEqual(deriveHomeScreenState(initialSessionState, creating), {
    status: "creating-room",
  });
  const withCode = homeOperationReducer(initialHomeOperationState, {
    type: "JOIN_CODE_CHANGED",
    value: "phys42",
  });
  const joining = homeOperationReducer(withCode, { type: "JOIN_REQUESTED" });
  assert.deepEqual(deriveHomeScreenState(initialSessionState, joining), {
    status: "joining-room",
  });
});
