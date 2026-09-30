import assert from "node:assert/strict";
import test from "node:test";

import {
  recommendSessionRoute,
  type SessionNavigationInput,
} from "./navigation";
import { ROOM_ID, SESSION_ID } from "./sessionTestFixtures";

const baseInput: SessionNavigationInput = {
  authentication: "signed-in",
  activeRoomId: ROOM_ID,
  sessionId: null,
  sessionStatus: null,
  reconnecting: false,
  dismissedFinishedSessionId: null,
  fatalRoomLoss: false,
  currentRoute: "home",
  currentRouteRoomId: null,
};

test("initializing authentication retains the current route", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      authentication: "initializing",
    }),
    "retain-current-route",
  );
});

test("signed-out users are directed to sign-in", () => {
  assert.equal(
    recommendSessionRoute({ ...baseInput, authentication: "signed-out" }),
    "sign-in",
  );
});

test("sign-out from every protected room route is directed to sign-in", () => {
  for (const currentRoute of ["waiting-room", "quiz", "results"] as const) {
    assert.equal(
      recommendSessionRoute({
        ...baseInput,
        authentication: "signed-out",
        currentRoute,
        currentRouteRoomId: ROOM_ID,
      }),
      "sign-in",
    );
  }
});

test("signed-in users without an active room are directed home", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      activeRoomId: null,
      currentRoute: "quiz",
    }),
    "home",
  );
});

test("signed-in users without a room may stay on MindMesh Pro", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      activeRoomId: null,
      currentRoute: "pro",
    }),
    "retain-current-route",
  );
});

test("signed-in users without a room may stay on Account & settings", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      activeRoomId: null,
      currentRoute: "account",
    }),
    "retain-current-route",
  );
});

test("solo and pets remain protected but cannot displace an active room", () => {
  for (const currentRoute of ["solo", "pets"] as const) {
    assert.equal(recommendSessionRoute({
      ...baseInput, currentRoute, activeRoomId: null,
    }), "retain-current-route");
    assert.equal(recommendSessionRoute({
      ...baseInput, currentRoute, authentication: "signed-out",
    }), "sign-in");
    assert.equal(recommendSessionRoute({
      ...baseInput, currentRoute,
    }), "waiting-room");
  }
});

test("signed-out direct Pro access is directed to sign-in", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      authentication: "signed-out",
      activeRoomId: null,
      currentRoute: "pro",
    }),
    "sign-in",
  );
});

test("privacy and support remain accessible while signed out", () => {
  for (const currentRoute of ["privacy", "support"] as const) {
    assert.equal(
      recommendSessionRoute({
        ...baseInput,
        authentication: "signed-out",
        currentRoute,
      }),
      "retain-current-route",
    );
  }
});

test("privacy and support remain accessible while signed in", () => {
  for (const currentRoute of ["privacy", "support"] as const) {
    assert.equal(
      recommendSessionRoute({ ...baseInput, currentRoute }),
      "retain-current-route",
    );
  }
});

test("a report route remains available only for its active room", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      currentRoute: "report",
      currentRouteRoomId: ROOM_ID,
    }),
    "retain-current-route",
  );
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      currentRoute: "report",
      currentRouteRoomId: "different-room",
      activeRoomId: null,
    }),
    "home",
  );
});

test("an active room takes priority over the Pro route", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      currentRoute: "pro",
    }),
    "waiting-room",
  );
});

test("a room without a visible session is directed to waiting room", () => {
  assert.equal(recommendSessionRoute(baseInput), "waiting-room");
});

test("direct Results access without a finished session returns to waiting", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      currentRoute: "results",
      currentRouteRoomId: ROOM_ID,
    }),
    "waiting-room",
  );
});

test("an open question is directed to quiz", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      sessionId: SESSION_ID,
      sessionStatus: "QUESTION_OPEN",
    }),
    "quiz",
  );
});

test("a question reveal remains on quiz", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      sessionId: SESSION_ID,
      sessionStatus: "QUESTION_REVEAL",
    }),
    "quiz",
  );
});

test("delayed marking remains on quiz", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      sessionId: SESSION_ID,
      sessionStatus: "QUESTION_GRADING",
    }),
    "quiz",
  );
});

test("an undismissed finished session is directed to results", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      sessionId: SESSION_ID,
      sessionStatus: "FINISHED",
    }),
    "results",
  );
});

test("the exact dismissed finished session is presented as waiting", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      sessionId: SESSION_ID,
      sessionStatus: "FINISHED",
      dismissedFinishedSessionId: SESSION_ID,
    }),
    "waiting-room",
  );
});

test("reconnecting retains a current valid room route", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      sessionId: SESSION_ID,
      sessionStatus: "QUESTION_OPEN",
      reconnecting: true,
      currentRoute: "quiz",
      currentRouteRoomId: ROOM_ID,
    }),
    "retain-current-route",
  );
});

test("fatal room loss is directed home", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      fatalRoomLoss: true,
      currentRoute: "waiting-room",
      currentRouteRoomId: ROOM_ID,
    }),
    "home",
  );
});

test("already-correct routes do not produce navigation loops", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      sessionId: SESSION_ID,
      sessionStatus: "QUESTION_OPEN",
      currentRoute: "quiz",
      currentRouteRoomId: ROOM_ID,
    }),
    "retain-current-route",
  );
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      authentication: "signed-out",
      currentRoute: "sign-in",
    }),
    "retain-current-route",
  );
});

test("a room route with the wrong room parameter is replaced safely", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      currentRoute: "waiting-room",
      currentRouteRoomId: "different-room",
    }),
    "waiting-room",
  );
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      sessionId: SESSION_ID,
      sessionStatus: "QUESTION_OPEN",
      currentRoute: "quiz",
      currentRouteRoomId: null,
    }),
    "quiz",
  );
});

test("reconnecting retains only the route matching retained authoritative state", () => {
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      reconnecting: true,
      currentRoute: "waiting-room",
      currentRouteRoomId: ROOM_ID,
    }),
    "retain-current-route",
  );
  assert.equal(
    recommendSessionRoute({
      ...baseInput,
      reconnecting: true,
      sessionId: SESSION_ID,
      sessionStatus: "FINISHED",
      currentRoute: "results",
      currentRouteRoomId: ROOM_ID,
      dismissedFinishedSessionId: SESSION_ID,
    }),
    "waiting-room",
  );
});
