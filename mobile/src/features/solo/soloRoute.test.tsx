import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import React, { createElement, type ReactNode } from "react";

import type { SoloAttempt, SoloReview } from "../../api/solo";
import type { SoloControllerState } from "./soloController";

const nodeRequire = createRequire(import.meta.url);
const renderToStaticMarkup = (
  nodeRequire("react-dom/server") as {
    renderToStaticMarkup: (element: React.ReactElement) => string;
  }
).renderToStaticMarkup;

const ATTEMPT_ID = "11111111-1111-4111-8111-111111111111";
const QUESTION_ID = "33333333-3333-4333-8333-333333333333";
const OWNER_ID = "learner-a";

type ModuleLoader = (request: string, parent: unknown, isMain: boolean) => unknown;
type ElementProps = {
  children?: ReactNode;
  label?: string;
  onPress?: () => void;
  disabled?: boolean;
  accessibilityRole?: string;
  accessibilityLabel?: string;
};

const buttons: ElementProps[] = [];
const rewardSources: Array<{ sourceKind: string; sourceId: string; userId: string }> = [];
let snapshot: SoloControllerState;
let signedIn = true;
let roomId: string | null = null;
let roomPhase = "idle";
let createCalls = 0;
let selfCheckCalls = 0;
let abandonCalls = 0;
let reviewCalls = 0;
let finalizedCriteria: readonly string[] | null = null;

function host(tag: "div" | "span" | "button" | "input") {
  return function Host({ children, label, onPress, disabled, accessibilityRole, accessibilityLabel }: ElementProps) {
    if (tag === "button") {
      buttons.push({ label, onPress, disabled, accessibilityRole, accessibilityLabel });
    }
    return createElement(tag, {
      ...(accessibilityRole ? { role: accessibilityRole } : {}),
      ...(accessibilityLabel ? { "aria-label": accessibilityLabel } : {}),
      ...(disabled ? { disabled: true } : {}),
    }, label ?? children);
  };
}

const studio = {
  StudioButton: host("button"),
  StudioCard: host("div"),
  StudioChoiceRow: ({ title }: { title: string }) => createElement("button", null, title),
  StudioScreen: host("div"),
  StudioText: host("span"),
  StudioTextField: ({ label }: { label: string }) => createElement("input", { "aria-label": label }),
};

class MockSoloController {
  subscribe = () => () => undefined;
  getState = () => snapshot;
  setOwner = () => undefined;
  loadActive = async () => undefined;
  dispose = () => undefined;
  refresh = async () => undefined;
  create = async () => { createCalls += 1; };
  start = async () => undefined;
  submitAnswer = async () => undefined;
  loadSelfCheck = async () => { selfCheckCalls += 1; };
  finalizeSelfCheck = async (selected: readonly string[]) => { finalizedCriteria = selected; };
  retryMarking = async () => undefined;
  loadReview = async () => { reviewCalls += 1; };
  abandon = async () => { abandonCalls += 1; };
  clearTerminal = () => undefined;
}

function attempt(overrides: Partial<SoloAttempt> = {}): SoloAttempt {
  return {
    id: ATTEMPT_ID,
    request_id: "22222222-2222-4222-8222-222222222222",
    status: "IN_PROGRESS",
    state_version: 2,
    subject: "physics",
    topic: "forces",
    total_marks: 5,
    current_question_position: 0,
    created_at: "2026-09-27T09:00:00Z",
    started_at: "2026-09-27T09:01:00Z",
    terminal_at: null,
    questions: [{
      id: QUESTION_ID, position: 0, question_type: "WRITTEN", max_marks: 5,
      prompt: "Explain the force.", options: [], original_extract: null,
    }],
    answers: [],
    ...overrides,
  };
}

function state(overrides: Partial<SoloControllerState> = {}): SoloControllerState {
  return {
    ownerId: OWNER_ID, loaded: true, attempt: null, selfCheck: null, review: null,
    busy: null, error: null, needsReconcile: false, ...overrides,
  };
}

let SoloRoute: React.ComponentType;
const moduleApi = nodeRequire("node:module") as { _load: ModuleLoader };
const originalLoad = moduleApi._load;
moduleApi._load = (request, parent, isMain) => {
  if (request === "react-native") {
    return {
      AppState: { currentState: "active", addEventListener: () => ({ remove: () => undefined }) },
      Pressable: host("button"),
      StyleSheet: { create: <T extends Record<string, unknown>>(styles: T): T => styles },
      View: host("div"),
    };
  }
  if (request === "expo-router") return { router: { replace: () => undefined } };
  if (request.endsWith("/src/auth/AuthContext")) {
    return { useAuth: () => ({ state: signedIn
      ? { status: "signed-in", user: { id: OWNER_ID }, profileBootstrap: { status: "ready" } }
      : { status: "signed-out" } }) };
  }
  if (request.endsWith("/src/features/session/SessionContext")) {
    return { useSession: () => ({ state: { roomId, phase: roomPhase } }) };
  }
  if (request.endsWith("/src/appearance/StudioThemeContext")) {
    return { useStudioTheme: () => ({
      spacing: { xs: 4, sm: 8 }, colors: { border: "#999" }, radii: { md: 8 },
    }) };
  }
  if (request.endsWith("/src/components/studio/StudioPrimitives")) return studio;
  if (request.endsWith("/src/features/learningCompanions/RoomRewardStatus")) {
    return {
      RewardSourceStatusCard: (props: { sourceKind: string; sourceId: string; userId: string }) => {
        rewardSources.push(props);
        return createElement("div", null, "Checking reward status with server");
      },
    };
  }
  if (request.endsWith("/src/features/drawing/DrawingWorkspace")) {
    return { DrawingWorkspace: host("div") };
  }
  if (request.endsWith("/src/features/solo/soloController")) {
    return {
      SoloController: MockSoloController,
      visibleSoloState: (ownerId: string | null, current: SoloControllerState) =>
        ownerId === current.ownerId ? current : state({ ownerId, loaded: false, attempt: null }),
    };
  }
  return originalLoad(request, parent, isMain);
};
try {
  (globalThis as typeof globalThis & { React?: typeof React }).React = React;
  SoloRoute = (nodeRequire("../../../app/solo") as { default: React.ComponentType }).default;
} finally {
  moduleApi._load = originalLoad;
}

function render(next: SoloControllerState, options: {
  authenticated?: boolean;
  room?: string | null;
  phase?: string;
} = {}): string {
  snapshot = next;
  signedIn = options.authenticated ?? true;
  roomId = options.room ?? null;
  roomPhase = options.phase ?? "idle";
  buttons.length = 0;
  rewardSources.length = 0;
  return renderToStaticMarkup(createElement(SoloRoute));
}

function button(label: string): ElementProps {
  const found = buttons.find((entry) => entry.label === label);
  assert.ok(found, `Missing button: ${label}`);
  return found;
}

test("solo route gates unauthenticated and active-room states before solo controls", () => {
  const signedOut = render(state(), { authenticated: false });
  assert.match(signedOut, /Sign in to study solo/);
  assert.doesNotMatch(signedOut, /Review quiz selection/);

  const room = render(state(), { room: ATTEMPT_ID, phase: "question-open" });
  assert.match(room, /Your room comes first/);
  assert.ok(button("Return to room"));
  assert.doesNotMatch(room, /Review quiz selection/);
});

test("selection requires explicit confirmation; first render never starts generation", () => {
  const markup = render(state());
  assert.match(markup, /Choose a quiz/);
  assert.ok(button("Review quiz selection"));
  assert.doesNotMatch(markup, /Confirm and prepare quiz/);
  assert.equal(createCalls, 0);
});

test("locked short written answer exposes guide only after submission and labels self assessment", () => {
  const question = {
    id: QUESTION_ID, position: 0, question_type: "WRITTEN" as const,
    max_marks: 3, prompt: "Explain the force.", options: [], original_extract: null,
  };
  const other = {
    id: "44444444-4444-4444-8444-444444444444", position: 1,
    question_type: "NUMERICAL" as const, max_marks: 2, prompt: "Calculate.",
    options: [], original_extract: null,
  };
  const base = attempt({ questions: [question, other] });
  const open = render(state({ attempt: base }));
  assert.match(open, /Submitting locks this answer/);
  assert.doesNotMatch(open, /Intended answer/);
  assert.doesNotMatch(open, /Show marking guide/);

  const locked = render(state({ attempt: {
    ...base, answers: [{
      question_id: QUESTION_ID, selected_option_id: null, answer_text: "My answer",
      accepted_at: "2026-09-27T09:02:00Z", grading_status: "SELF_CHECK_PENDING",
      mark_provenance: "SELF_ASSESSED", earned_marks: null, feedback: {},
    }],
  } }));
  assert.match(locked, /Your answer is locked/);
  assert.ok(button("Show marking guide"));
  assert.doesNotMatch(locked, /Reference answer/);
  assert.equal(selfCheckCalls, 0);
});

test("short written marking guide supports zero ticks and completed review keeps self assessment labelled", () => {
  const question = {
    id: QUESTION_ID, position: 0, question_type: "WRITTEN" as const,
    max_marks: 3, prompt: "Explain the force.", options: [], original_extract: null,
  };
  const other = {
    id: "44444444-4444-4444-8444-444444444444", position: 1,
    question_type: "NUMERICAL" as const, max_marks: 2, prompt: "Calculate.",
    options: [], original_extract: null,
  };
  const lockedAnswer = {
    question_id: QUESTION_ID, selected_option_id: null, answer_text: "My answer",
    accepted_at: "2026-09-27T09:02:00Z", grading_status: "SELF_CHECK_PENDING" as const,
    mark_provenance: "SELF_ASSESSED" as const, earned_marks: null, feedback: {},
  };
  const progress = attempt({ questions: [question, other], answers: [lockedAnswer] });
  const markup = render(state({
    attempt: progress,
    selfCheck: {
      question_id: QUESTION_ID, locked_answer: "My answer",
      intended_answer: "Reference answer", max_marks: 3,
      criteria: [
        { id: "one", marks: 2, marking_point: "Principle", explanation: "State it" },
        { id: "two", marks: 1, marking_point: "Application", explanation: "Apply it" },
      ],
    },
  }));
  assert.match(markup, /Reference answer/);
  assert.match(markup, /No boxes ticked is a valid zero/);
  button("Finish self-check").onPress?.();
  assert.deepEqual(finalizedCriteria, []);

  const graded = { ...lockedAnswer, grading_status: "GRADED" as const, earned_marks: 0 };
  const otherAnswer = {
    question_id: other.id, selected_option_id: null, answer_text: "2",
    accepted_at: "2026-09-27T09:03:00Z", grading_status: "GRADED" as const,
    mark_provenance: "DETERMINISTIC_NUMERICAL" as const, earned_marks: 2, feedback: {},
  };
  const completed = attempt({
    status: "FINISHED", questions: [question, other], answers: [graded, otherAnswer],
    current_question_position: 2, terminal_at: "2026-09-27T09:03:10Z",
  });
  const review: SoloReview = {
    attempt: completed,
    questions: [
      { question, answer: graded, correct_option_id: null, intended_answer: "Reference answer" },
      { question: other, answer: otherAnswer, correct_option_id: null, intended_answer: "2" },
    ],
  };
  const reviewMarkup = render(state({ attempt: completed, review }));
  assert.match(reviewMarkup, /Self-assessed: 0 marks/);
  assert.match(reviewMarkup, /2 marks, server marked/);
  assert.deepEqual(rewardSources, [{ sourceKind: "solo", sourceId: ATTEMPT_ID, userId: OWNER_ID }]);
  assert.doesNotMatch(reviewMarkup, /\b\d+ coins\b/);
});

test("long written marking stays pending and abandonment requires another action", () => {
  const pending = attempt({
    status: "AWAITING_MARKING", current_question_position: 1,
    answers: [{
      question_id: QUESTION_ID, selected_option_id: null, answer_text: "Saved answer",
      accepted_at: "2026-09-27T09:02:00Z", grading_status: "UNAVAILABLE",
      mark_provenance: "AI_RUBRIC", earned_marks: null, feedback: {},
    }],
  });
  const markup = render(state({ attempt: pending }));
  assert.match(markup, /All answers saved. Marking is pending/);
  assert.match(markup, /No marks have been invented/);
  assert.ok(button("Retry AI marking"));
  assert.ok(button("Abandon quiz"));
  assert.equal(buttons.some((entry) => entry.label === "Confirm abandon"), false);
  assert.equal(abandonCalls, 0);
  assert.equal(reviewCalls, 0);
  assert.deepEqual(rewardSources, []);
});
