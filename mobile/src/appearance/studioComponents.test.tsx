import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import React, { createElement, type ReactNode } from "react";

import {
  makeAdaptiveRoomState,
  makeFinishedSnapshot,
  makeGradingSnapshot,
  makeLobbySnapshot,
  makeRoomState,
  makeOpenSnapshot,
  makeRevealSnapshot,
  MEMBER_ID,
  QUESTION_ID,
  ROOM_ID,
  SESSION_ID,
} from "../features/session/sessionTestFixtures";
import {
  initialSessionState,
  sessionReducer,
  type SessionState,
} from "../features/session/sessionState";
import type { LeaderboardRowProps } from "../components/LeaderboardRow";
import type { QuizOptionProps } from "../components/QuizOption";
import { parseSessionReviewResponse } from "../api/schemas";
import { buildReviewPresentation } from "../features/quiz/reviewPresentation";
import { RealtimeNetworkError } from "../realtime/errors";
import {
  AccountDeletionController,
  type AccountDeletionState,
} from "../features/account/accountDeletion";
import {
  ParticipantReportController,
} from "../features/safety/reportFlow";
import { NetworkApiError } from "../api/errors";
import type {
  RevenueCatPlatformCapability,
  RevenueCatReadyData,
  RevenueCatState,
} from "../revenuecat/types";
import { colors, studioDarkTheme, studioLightTheme } from "../theme";
import { studioButtonPresentation } from "./studioPresentation";
import type { AccountPresentationProps } from "../../app/account";
import type { LearningSummaryResponse } from "../api/learningSummary";
import type { LearningSummaryLoadState } from "../features/learningSummary/useLearningSummary";
import type { ReportPresentationProps } from "../../app/report";
import type { SupportPresentationProps } from "../../app/support";

const renderToStaticMarkup = (
  createRequire(import.meta.url)("react-dom/server") as {
    renderToStaticMarkup: (element: React.ReactElement) => string;
  }
).renderToStaticMarkup;

type NativeProps = {
  autoCapitalize?: unknown;
  autoComplete?: unknown;
  accessibilityHint?: unknown;
  accessibilityLabel?: unknown;
  accessibilityRole?: unknown;
  accessibilityState?: unknown;
  accessibilityLiveRegion?: unknown;
  autoCorrect?: unknown;
  children?: ReactNode;
  cursorColor?: unknown;
  disabled?: unknown;
  editable?: unknown;
  keyboardType?: unknown;
  keyboardAppearance?: unknown;
  maxLength?: unknown;
  multiline?: unknown;
  numberOfLines?: unknown;
  onChangeText?: unknown;
  onPress?: unknown;
  placeholder?: unknown;
  placeholderTextColor?: unknown;
  selectionColor?: unknown;
  secureTextEntry?: unknown;
  style?: unknown;
  testID?: string;
  textAlignVertical?: unknown;
  value?: unknown;
};

type Capture = {
  buttonPresses: Array<() => void>;
  buttonProps: NativeProps[];
  alertCalls: Array<{
    buttons: Array<{ onPress?: () => void; style?: string; text: string }>;
    message: string;
    title: string;
  }>;
  inputProps: NativeProps[];
  inputChanges: Array<(value: string) => void>;
  textProps: NativeProps[];
  viewProps: NativeProps[];
};

type HostComponent = (props: NativeProps) => React.ReactElement;

type ModuleLoader = (
  request: string,
  parent: unknown,
  isMain: boolean,
) => unknown;

type ThemeMode = "light" | "dark" | "system";

type StudioComponents = {
  StudioAppearanceSelector: React.ComponentType;
  LeaderboardRow: React.ComponentType<LeaderboardRowProps>;
  QuizOption: React.ComponentType<QuizOptionProps>;
  StudioButton: React.ComponentType<{
    disabled?: boolean;
    label: string;
    onPress: () => void;
  }>;
  StudioChoiceRow: React.ComponentType<{
    accessibilityLabel?: string;
    description?: string;
    disabled?: boolean;
    onPress: () => void;
    selected: boolean;
    title: string;
  }>;
  StudioScreen: React.ComponentType<{
    children?: ReactNode;
  }>;
  StudioLeaderboardRow: React.ComponentType<LeaderboardRowProps>;
  StudioQuizOption: React.ComponentType<QuizOptionProps>;
  StudioStack: React.ComponentType<{ children?: ReactNode }>;
  StudioText: React.ComponentType<{
    accessibilityRole?: "header" | "alert" | "text";
    children?: ReactNode;
    style?: unknown;
    tone?: "primary" | "muted" | "error" | "success";
  }>;
  StudioTextField: React.ComponentType<{
    editable?: boolean;
    error?: string;
    label: string;
    onChangeText: (value: string) => void;
    value: string;
  }>;
  StudioThemeProvider: React.ComponentType<{
    children?: ReactNode;
    mode?: ThemeMode;
  }>;
  useStudioTheme: () => { scheme: "light" | "dark" };
};

type LoadedStudioComponents = {
  capture: Capture;
  components: StudioComponents;
};

function captureFor(): Capture {
  return {
    alertCalls: [],
    buttonPresses: [],
    buttonProps: [],
    inputChanges: [],
    inputProps: [],
    textProps: [],
    viewProps: [],
  };
}

function recordObject(value: unknown): Record<string, unknown> | undefined {
  if (typeof value !== "object" || value === null) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

function host(
  tag: string,
  capture: Capture,
  event: "button" | "input" | undefined = undefined,
): HostComponent {
  return ({ children, ...props }) => {
    if (tag === "input") {
      capture.inputProps.push(props);
    }
    if (tag === "button") {
      capture.buttonProps.push(props);
    }
    if (tag === "span") {
      capture.textProps.push({ ...props, children });
    }
    if (tag === "div") {
      capture.viewProps.push(props);
    }
    const state = recordObject(props.accessibilityState);
    const disabled =
      props.disabled === true ||
      props.editable === false ||
      state?.disabled === true;
    if (!disabled && event === "button" && typeof props.onPress === "function") {
      capture.buttonPresses.push(props.onPress as () => void);
    }
    if (
      !disabled &&
      event === "input" &&
      typeof props.onChangeText === "function"
    ) {
      capture.inputChanges.push(props.onChangeText as (value: string) => void);
    }

    const htmlProps: Record<string, unknown> = {};
    if (typeof props.accessibilityLabel === "string") {
      htmlProps["aria-label"] = props.accessibilityLabel;
    }
    if (typeof props.accessibilityRole === "string") {
      htmlProps.role = props.accessibilityRole;
    }
    if (state?.checked === true || state?.checked === false) {
      htmlProps["aria-checked"] = state.checked;
    }
    if (disabled && (tag === "button" || tag === "input")) {
      htmlProps.disabled = true;
    }
    if (tag === "input") {
      if (typeof props.placeholder === "string") {
        htmlProps.placeholder = props.placeholder;
      }
      if (typeof props.value === "string") {
        htmlProps.value = props.value;
      }
      htmlProps.onChange = () => undefined;
      if (props.secureTextEntry === true) {
        htmlProps.type = "password";
      }
    }
    return createElement(tag, htmlProps, children);
  };
}

function nativeShimFor(capture: Capture) {
  return {
    AppState: {
      currentState: "active",
      addEventListener: () => ({ remove: () => undefined }),
    },
    Alert: {
      alert: (
        title: string,
        message: string,
        buttons: Array<{ onPress?: () => void; style?: string; text: string }>,
      ) => capture.alertCalls.push({ buttons, message, title }),
    },
    KeyboardAvoidingView: host("div", capture),
    Linking: {
      openURL: async (url: string) => {
        activeAccountHelpBindings?.actions.linkingCalls.push(url);
      },
    },
    PanResponder: {
      create: () => ({ panHandlers: {} }),
    },
    Platform: { OS: "ios" },
    Pressable: host("button", capture, "button"),
    ScrollView: host("div", capture),
    StyleSheet: {
      create: <T extends Record<string, unknown>>(styles: T): T => styles,
    },
    Text: host("span", capture),
    TextInput: host("input", capture, "input"),
    View: host("div", capture),
    useColorScheme: (): "light" => "light",
  };
}

async function loadStudioComponents(): Promise<LoadedStudioComponents> {
  const moduleRequire = createRequire(import.meta.url);
  const moduleApi = moduleRequire("node:module") as { _load: ModuleLoader };
  (globalThis as typeof globalThis & { React?: typeof React }).React = React;
  const originalLoad = moduleApi._load;
  const capture = captureFor();
  const nativeShim = nativeShimFor(capture);
  moduleApi._load = (request, parent, isMain) => {
    if (request === "react-native") {
      return nativeShim;
    }
    if (request === "react-native-safe-area-context") {
      return { SafeAreaView: host("div", capture) };
    }
    return originalLoad(request, parent, isMain);
  };
  try {
    const context = (await import("./StudioThemeContext")) as unknown as {
      StudioThemeProvider: StudioComponents["StudioThemeProvider"];
      useStudioTheme: StudioComponents["useStudioTheme"];
    };
    const primitives = (await import(
      "../components/studio/StudioPrimitives"
    )) as unknown as Omit<StudioComponents, "StudioThemeProvider" | "useStudioTheme">;
    const appearance = (await import(
      "./AppearanceSelector"
    )) as unknown as Pick<StudioComponents, "StudioAppearanceSelector">;
    const quizOptions = (await import(
      "../components/QuizOption"
    )) as unknown as Pick<StudioComponents, "QuizOption" | "StudioQuizOption">;
    const leaderboard = (await import(
      "../components/LeaderboardRow"
    )) as unknown as Pick<StudioComponents, "LeaderboardRow" | "StudioLeaderboardRow">;
    return {
      capture,
      components: {
        ...primitives,
        ...appearance,
        ...quizOptions,
        ...leaderboard,
        StudioThemeProvider: context.StudioThemeProvider,
        useStudioTheme: context.useStudioTheme,
      },
    };
  } finally {
    moduleApi._load = originalLoad;
  }
}

let loadedStudioComponents: Promise<LoadedStudioComponents> | undefined;

function getStudioComponents(): Promise<LoadedStudioComponents> {
  loadedStudioComponents ??= loadStudioComponents();
  return loadedStudioComponents;
}

type WaitingRouteActions = {
  closeCalls: number;
  leaveCalls: number;
  prepareRequests: string[];
  readyValues: boolean[];
  requestStateCalls: number;
  retryCalls: number;
  startCalls: number;
};

type WaitingRouteBindings = {
  actions: WaitingRouteActions;
  authStatus: "initializing" | "signed-in" | "signed-out";
  authUserId: string;
  roomParam: string;
  sessionState: SessionState;
};

type LoadedWaitingRoute = LoadedStudioComponents & {
  installBindings: (bindings: WaitingRouteBindings) => void;
  route: React.ComponentType;
  routerPushes: unknown[];
};

type QuizRouteActions = {
  retryCalls: number;
  retryGradingCalls: number;
  submitChoices: Array<{
    sessionQuestionId: string;
    selectedOptionId: string;
  }>;
  submitTexts: Array<{ sessionQuestionId: string; text: string }>;
};

type QuizRouteBindings = {
  actions: QuizRouteActions;
  authStatus: "initializing" | "signed-in" | "signed-out";
  authUserId: string;
  roomParam: string;
  sessionState: SessionState;
};

type LoadedQuizRoute = LoadedStudioComponents & {
  installBindings: (bindings: QuizRouteBindings) => void;
  route: React.ComponentType;
};

type ResultsReviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; review: ReturnType<typeof buildReviewPresentation> }
  | { status: "error"; message: string };

type ResultsRouteActions = {
  dismissCalls: number;
  reportPushes: unknown[];
  retryCalls: number;
  reviewRequests: Array<{ roomId: string; sessionId: string }>;
};

type ResultsRouteBindings = {
  actions: ResultsRouteActions;
  authStatus: "initializing" | "signed-in" | "signed-out";
  authUserId: string;
  roomParam: string;
  reviewResponse: unknown;
  sessionState: SessionState;
};

type LoadedResultsRoute = LoadedStudioComponents & {
  installBindings: (bindings: ResultsRouteBindings) => void;
  reviewSection: React.ComponentType<{
    onLoadReview: () => void;
    reviewState: ResultsReviewState;
  }>;
  route: React.ComponentType;
};

type AuthRouteState =
  | { status: "initializing" }
  | { status: "signed-out" }
  | { status: "signing-up" }
  | { status: "signed-in" }
  | { status: "confirmation-required" }
  | { status: "error"; message: string };

type AuthRouteActions = {
  clearAuthCallbackErrorCalls: number;
  processCallbackCalls: string[];
  routerPushes: unknown[];
  routerReplaces: unknown[];
  signInCalls: Array<{ email: string; password: string }>;
  signOutCalls: number;
  signUpCalls: Array<{ email: string; password: string; displayName: string }>;
};

type AuthRouteBindings = {
  actions: AuthRouteActions;
  authCallbackError: string | null;
  authCallbackStatus: "idle" | "processing" | "failed" | "authenticated";
  authState: AuthRouteState;
  callbackParams: Record<string, string | string[]>;
};

type LoadedAuthRoutes = LoadedStudioComponents & {
  callbackRoute: React.ComponentType;
  installBindings: (bindings: AuthRouteBindings) => void;
  signInRoute: React.ComponentType;
  signUpRoute: React.ComponentType;
};

let activeAuthRouteBindings: AuthRouteBindings | undefined;

function waitingRouteActions(): WaitingRouteActions {
  return {
    closeCalls: 0,
    leaveCalls: 0,
    prepareRequests: [],
    readyValues: [],
    requestStateCalls: 0,
    retryCalls: 0,
    startCalls: 0,
  };
}

function lobbyState(roomState: ReturnType<typeof makeRoomState>): SessionState {
  const snapshot = makeLobbySnapshot(roomState);
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

async function loadWaitingRoute(): Promise<LoadedWaitingRoute> {
  const loaded = await getStudioComponents();
  const moduleRequire = createRequire(import.meta.url);
  const moduleApi = moduleRequire("node:module") as { _load: ModuleLoader };
  const originalLoad = moduleApi._load;
  const routerPushes: unknown[] = [];
  const nativeShim = nativeShimFor(loaded.capture);
  const activeBindings = {
    current: undefined as WaitingRouteBindings | undefined,
  };
  moduleApi._load = (request, parent, isMain) => {
    if (request === "react-native") {
      return nativeShim;
    }
    if (request === "react-native-safe-area-context") {
      return { SafeAreaView: host("div", loaded.capture) };
    }
    if (request === "expo-router") {
      return {
        router: {
          push: (value: unknown) => routerPushes.push(value),
        },
        useLocalSearchParams: () => ({
          roomId: activeBindings.current?.roomParam ?? ROOM_ID,
        }),
      };
    }
    if (request.endsWith("/src/auth/AuthContext")) {
      return {
        useAuth: () => ({
          state: {
            status: activeBindings.current?.authStatus ?? "signed-in",
            user: { id: activeBindings.current?.authUserId ?? ROOM_ID },
          },
        }),
      };
    }
    if (request.endsWith("/src/features/session/SessionContext")) {
      return {
        useSession: () => {
          const bindings = activeBindings.current;
          if (bindings === undefined) {
            throw new Error("Waiting Room bindings were not installed.");
          }
          return {
            state: bindings.sessionState,
            retryConnection: () => {
              bindings.actions.retryCalls += 1;
            },
            closeCurrentRoom: async () => {
              bindings.actions.closeCalls += 1;
            },
            leaveCurrentRoom: async () => {
              bindings.actions.leaveCalls += 1;
            },
            setReady: (ready: boolean) => {
              bindings.actions.readyValues.push(ready);
            },
            startSession: () => {
              bindings.actions.startCalls += 1;
            },
            prepareQuiz: (requestId: string) => {
              bindings.actions.prepareRequests.push(requestId);
            },
            requestState: () => {
              bindings.actions.requestStateCalls += 1;
            },
          };
        },
      };
    }
    if (request.endsWith("/src/api/rooms")) {
      return {
        prepareQuiz: async () => undefined,
      };
    }
    return originalLoad(request, parent, isMain);
  };
  try {
    const routeModule = (await import("../../app/waiting-room")) as {
      default: React.ComponentType;
    };
    return {
      ...loaded,
      installBindings: (bindings: WaitingRouteBindings) => {
        activeBindings.current = bindings;
      },
      route: routeModule.default,
      routerPushes,
    };
  } finally {
    moduleApi._load = originalLoad;
  }
}

function renderWaitingRoute(
  loaded: LoadedWaitingRoute,
  mode: "light" | "dark",
  bindings: WaitingRouteBindings,
): string {
  loaded.installBindings(bindings);
  return renderToStaticMarkup(
    createElement(
      loaded.components.StudioThemeProvider,
      { mode },
      createElement(loaded.route),
    ),
  );
}

function quizRouteActions(): QuizRouteActions {
  return {
    retryCalls: 0,
    retryGradingCalls: 0,
    submitChoices: [],
    submitTexts: [],
  };
}

function quizStateFromSnapshot(
  snapshot: NonNullable<SessionState["snapshot"]>,
): SessionState {
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

function quizRouteBindings(
  sessionState: SessionState,
  options: Partial<Pick<QuizRouteBindings, "authStatus" | "authUserId" | "roomParam">> = {},
): QuizRouteBindings {
  return {
    actions: quizRouteActions(),
    authStatus: options.authStatus ?? "signed-in",
    authUserId: options.authUserId ?? ROOM_ID,
    roomParam: options.roomParam ?? ROOM_ID,
    sessionState,
  };
}

async function loadQuizRoute(): Promise<LoadedQuizRoute> {
  const loaded = await getStudioComponents();
  const moduleRequire = createRequire(import.meta.url);
  const moduleApi = moduleRequire("node:module") as { _load: ModuleLoader };
  const originalLoad = moduleApi._load;
  const nativeShim = nativeShimFor(loaded.capture);
  const activeBindings = {
    current: undefined as QuizRouteBindings | undefined,
  };
  moduleApi._load = (request, parent, isMain) => {
    if (request === "react-native") {
      return nativeShim;
    }
    if (request === "react-native-safe-area-context") {
      return { SafeAreaView: host("div", loaded.capture) };
    }
    if (request === "react-native-svg") {
      return {
        __esModule: true,
        default: host("svg", loaded.capture),
        Circle: host("circle", loaded.capture),
        G: host("g", loaded.capture),
        Line: host("line", loaded.capture),
        Path: host("path", loaded.capture),
        Rect: host("rect", loaded.capture),
        Text: host("text", loaded.capture),
      };
    }
    if (request === "expo-router") {
      return {
        useLocalSearchParams: () => ({
          roomId: activeBindings.current?.roomParam ?? ROOM_ID,
        }),
      };
    }
    if (request.endsWith("/src/auth/AuthContext")) {
      return {
        useAuth: () => ({
          state: {
            status: activeBindings.current?.authStatus ?? "signed-in",
            user: { id: activeBindings.current?.authUserId ?? ROOM_ID },
          },
        }),
      };
    }
    if (request.endsWith("/src/features/session/SessionContext")) {
      return {
        useSession: () => {
          const bindings = activeBindings.current;
          if (bindings === undefined) {
            throw new Error("Quiz bindings were not installed.");
          }
          return {
            state: bindings.sessionState,
            retryConnection: () => {
              bindings.actions.retryCalls += 1;
            },
            submitAnswer: (sessionQuestionId: string, selectedOptionId: string) => {
              bindings.actions.submitChoices.push({
                sessionQuestionId,
                selectedOptionId,
              });
            },
            submitTextAnswer: (sessionQuestionId: string, text: string) => {
              bindings.actions.submitTexts.push({ sessionQuestionId, text });
            },
            retryGrading: () => {
              bindings.actions.retryGradingCalls += 1;
            },
          };
        },
      };
    }
    return originalLoad(request, parent, isMain);
  };
  try {
    const routeModule = (await import("../../app/quiz")) as {
      default: React.ComponentType;
    };
    return {
      ...loaded,
      installBindings: (bindings: QuizRouteBindings) => {
        activeBindings.current = bindings;
      },
      route: routeModule.default,
    };
  } finally {
    moduleApi._load = originalLoad;
  }
}

function renderQuizRoute(
  loaded: LoadedQuizRoute,
  mode: "light" | "dark",
  bindings: QuizRouteBindings,
): string {
  loaded.installBindings(bindings);
  return renderToStaticMarkup(
    createElement(
      loaded.components.StudioThemeProvider,
      { mode },
      createElement(loaded.route),
    ),
  );
}

function resultsRouteActions(): ResultsRouteActions {
  return {
    dismissCalls: 0,
    reportPushes: [],
    retryCalls: 0,
    reviewRequests: [],
  };
}

function resultsRouteBindings(
  sessionState: SessionState,
  reviewResponse: unknown,
  options: Partial<Pick<ResultsRouteBindings, "authStatus" | "authUserId" | "roomParam">> = {},
): ResultsRouteBindings {
  return {
    actions: resultsRouteActions(),
    authStatus: options.authStatus ?? "signed-in",
    authUserId: options.authUserId ?? ROOM_ID,
    roomParam: options.roomParam ?? ROOM_ID,
    reviewResponse,
    sessionState,
  };
}

async function loadResultsRoute(): Promise<LoadedResultsRoute> {
  const loaded = await getStudioComponents();
  const moduleRequire = createRequire(import.meta.url);
  const moduleApi = moduleRequire("node:module") as { _load: ModuleLoader };
  const originalLoad = moduleApi._load;
  const nativeShim = nativeShimFor(loaded.capture);
  const activeBindings = {
    current: undefined as ResultsRouteBindings | undefined,
  };
  moduleApi._load = (request, parent, isMain) => {
    if (request === "react-native") {
      return nativeShim;
    }
    if (request === "react-native-safe-area-context") {
      return { SafeAreaView: host("div", loaded.capture) };
    }
    if (request === "expo-router") {
      return {
        router: {
          push: (value: unknown) => {
            activeBindings.current?.actions.reportPushes.push(value);
          },
        },
        useLocalSearchParams: () => ({
          roomId: activeBindings.current?.roomParam ?? ROOM_ID,
        }),
      };
    }
    if (request.endsWith("/src/auth/AuthContext")) {
      return {
        useAuth: () => ({
          state: {
            status: activeBindings.current?.authStatus ?? "signed-in",
            user: { id: activeBindings.current?.authUserId ?? ROOM_ID },
          },
        }),
      };
    }
    if (request.endsWith("/src/features/session/SessionContext")) {
      return {
        useSession: () => {
          const bindings = activeBindings.current;
          if (bindings === undefined) {
            throw new Error("Results bindings were not installed.");
          }
          return {
            state: bindings.sessionState,
            dismissFinishedSession: () => {
              bindings.actions.dismissCalls += 1;
            },
            retryConnection: () => {
              bindings.actions.retryCalls += 1;
            },
          };
        },
      };
    }
    if (request.endsWith("/src/api/sessionReview")) {
      return {
        getSessionReview: async (roomId: string, sessionId: string) => {
          const bindings = activeBindings.current;
          if (bindings === undefined) {
            throw new Error("Results bindings were not installed.");
          }
          bindings.actions.reviewRequests.push({ roomId, sessionId });
          return bindings.reviewResponse;
        },
      };
    }
    return originalLoad(request, parent, isMain);
  };
  try {
    const routeModule = (await import("../../app/results")) as {
      ResultsReviewSection: LoadedResultsRoute["reviewSection"];
      default: React.ComponentType;
    };
    return {
      ...loaded,
      installBindings: (bindings: ResultsRouteBindings) => {
        activeBindings.current = bindings;
      },
      reviewSection: routeModule.ResultsReviewSection,
      route: routeModule.default,
    };
  } finally {
    moduleApi._load = originalLoad;
  }
}

function renderResultsRoute(
  loaded: LoadedResultsRoute,
  mode: "light" | "dark",
  bindings: ResultsRouteBindings,
): string {
  loaded.installBindings(bindings);
  return renderToStaticMarkup(
    createElement(
      loaded.components.StudioThemeProvider,
      { mode },
      createElement(loaded.route),
    ),
  );
}

function authRouteActions(): AuthRouteActions {
  return {
    clearAuthCallbackErrorCalls: 0,
    processCallbackCalls: [],
    routerPushes: [],
    routerReplaces: [],
    signInCalls: [],
    signOutCalls: 0,
    signUpCalls: [],
  };
}

function authRouteBindings(
  authState: AuthRouteState,
  options: Partial<
    Pick<AuthRouteBindings, "authCallbackError" | "authCallbackStatus" | "callbackParams">
  > = {},
): AuthRouteBindings {
  return {
    actions: authRouteActions(),
    authCallbackError: options.authCallbackError ?? null,
    authCallbackStatus: options.authCallbackStatus ?? "idle",
    authState,
    callbackParams: options.callbackParams ?? {},
  };
}

async function loadAuthRoutes(): Promise<LoadedAuthRoutes> {
  const loaded = await getStudioComponents();
  const moduleRequire = createRequire(import.meta.url);
  const moduleApi = moduleRequire("node:module") as { _load: ModuleLoader };
  const originalLoad = moduleApi._load;
  const nativeShim = nativeShimFor(loaded.capture);
  moduleApi._load = (request, parent, isMain) => {
    if (request === "react-native") {
      return nativeShim;
    }
    if (request === "react-native-safe-area-context") {
      return { SafeAreaView: host("div", loaded.capture) };
    }
    if (request === "expo-router") {
      return {
        router: {
          push: (value: unknown) => {
            activeAuthRouteBindings?.actions.routerPushes.push(value);
          },
          replace: (value: unknown) => {
            activeAuthRouteBindings?.actions.routerReplaces.push(value);
          },
        },
        useLocalSearchParams: () => activeAuthRouteBindings?.callbackParams ?? {},
      };
    }
    if (request.endsWith("/src/auth/AuthContext")) {
      return {
        useAuth: () => {
          const bindings = activeAuthRouteBindings;
          if (bindings === undefined) {
            throw new Error("Auth route bindings were not installed.");
          }
          return {
            authCallbackError: bindings.authCallbackError,
            authCallbackStatus: bindings.authCallbackStatus,
            clearAuthCallbackError: () => {
              bindings.actions.clearAuthCallbackErrorCalls += 1;
            },
            processAuthCallback: async (url: string) => {
              bindings.actions.processCallbackCalls.push(url);
            },
            signIn: async (email: string, password: string) => {
              bindings.actions.signInCalls.push({ email, password });
            },
            signOut: async () => {
              bindings.actions.signOutCalls += 1;
            },
            signUp: async (
              email: string,
              password: string,
              displayName: string,
            ) => {
              bindings.actions.signUpCalls.push({ email, password, displayName });
            },
            signedOutMessage: null,
            state: bindings.authState,
          };
        },
      };
    }
    return originalLoad(request, parent, isMain);
  };
  try {
    const signInModule = (await import("../../app/sign-in")) as {
      default: React.ComponentType;
    };
    const signUpModule = (await import("../../app/sign-up")) as {
      default: React.ComponentType;
    };
    const callbackModule = (await import("../../app/auth/callback")) as {
      default: React.ComponentType;
    };
    return {
      ...loaded,
      callbackRoute: callbackModule.default,
      installBindings: (bindings: AuthRouteBindings) => {
        activeAuthRouteBindings = bindings;
      },
      signInRoute: signInModule.default,
      signUpRoute: signUpModule.default,
    };
  } finally {
    moduleApi._load = originalLoad;
  }
}

function renderAuthRoute(
  loaded: LoadedAuthRoutes,
  route: React.ComponentType,
  mode: "light" | "dark",
  bindings: AuthRouteBindings,
): string {
  loaded.installBindings(bindings);
  return renderToStaticMarkup(
    createElement(
      loaded.components.StudioThemeProvider,
      { mode },
      createElement(route),
    ),
  );
}

type AccountHelpActions = {
  accountDeleteCalls: number;
  authCompleteDeletionCalls: string[];
  authReauthenticateCalls: string[];
  authSignOutCalls: number;
  clearIdentityCalls: number;
  linkingCalls: string[];
  reportRequests: Array<Record<string, unknown>>;
  routerBackCalls: number;
  routerPushes: unknown[];
  routerReplaces: unknown[];
  terminateSessionCalls: number;
};

type AccountHelpBindings = {
  actions: AccountHelpActions;
  authStatus: "initializing" | "signed-in" | "suspended" | "signed-out";
  displayName: string | null;
  reportParams: Record<string, string | string[]>;
  supportContact: { status: "configured"; email: string } | { status: "unavailable" };
};

type LoadedAccountHelpRoutes = LoadedStudioComponents & {
  accountPresentation: React.ComponentType<AccountPresentationProps>;
  accountRoute: React.ComponentType;
  installBindings: (bindings: AccountHelpBindings) => void;
  privacyRoute: React.ComponentType;
  reportRoute: React.ComponentType;
  reportPresentation: React.ComponentType<ReportPresentationProps>;
  routerBackCalls: () => number;
  routerPushes: unknown[];
  routerReplaces: unknown[];
  supportRoute: React.ComponentType;
  supportPresentation: React.ComponentType<SupportPresentationProps>;
};

type ProActions = {
  paywallArgs: unknown[][];
  paywallCalls: number;
  refreshArgs: unknown[][];
  refreshCalls: number;
  restoreArgs: unknown[][];
  restoreCalls: number;
  routerReplaces: unknown[];
};

type ProBindings = {
  actions: ProActions;
  authStatus: "signed-in" | "signed-out";
  revenueCatState: RevenueCatState;
};

type LoadedProRoute = LoadedStudioComponents & {
  installBindings: (bindings: ProBindings) => void;
  proRoute: React.ComponentType;
};

let activeAccountHelpBindings: AccountHelpBindings | undefined;
let activeProBindings: ProBindings | undefined;

function accountHelpActions(): AccountHelpActions {
  return {
    accountDeleteCalls: 0,
    authCompleteDeletionCalls: [],
    authReauthenticateCalls: [],
    authSignOutCalls: 0,
    clearIdentityCalls: 0,
    linkingCalls: [],
    reportRequests: [],
    routerBackCalls: 0,
    routerPushes: [],
    routerReplaces: [],
    terminateSessionCalls: 0,
  };
}

function accountHelpBindings(
  options: Partial<Omit<AccountHelpBindings, "actions">> = {},
): AccountHelpBindings {
  return {
    actions: accountHelpActions(),
    authStatus: options.authStatus ?? "signed-in",
    displayName: options.displayName ?? "Account learner",
    reportParams: options.reportParams ?? {
      roomId: ROOM_ID,
      reportedUserId: MEMBER_ID,
      displayName: "Room participant",
    },
    supportContact: options.supportContact ?? {
      status: "configured",
      email: "support@example.test",
    },
  };
}

async function loadAccountHelpRoutes(): Promise<LoadedAccountHelpRoutes> {
  const loaded = await getStudioComponents();
  const moduleRequire = createRequire(import.meta.url);
  const moduleApi = moduleRequire("node:module") as { _load: ModuleLoader };
  const originalLoad = moduleApi._load;
  const nativeShim = nativeShimFor(loaded.capture);
  const routerPushes: unknown[] = [];
  const routerReplaces: unknown[] = [];
  let routerBackCalls = 0;
  moduleApi._load = (request, parent, isMain) => {
    if (request === "react-native") return nativeShim;
    if (request === "react-native-safe-area-context") {
      return { SafeAreaView: host("div", loaded.capture) };
    }
    if (request === "expo-router") {
      return {
        router: {
          back: () => {
            routerBackCalls += 1;
            if (activeAccountHelpBindings !== undefined) {
              activeAccountHelpBindings.actions.routerBackCalls += 1;
            }
          },
          push: (value: unknown) => {
            routerPushes.push(value);
            activeAccountHelpBindings?.actions.routerPushes.push(value);
          },
          replace: (value: unknown) => {
            routerReplaces.push(value);
            activeAccountHelpBindings?.actions.routerReplaces.push(value);
          },
        },
        useLocalSearchParams: () => activeAccountHelpBindings?.reportParams ?? {},
      };
    }
    if (request.endsWith("/src/auth/AuthContext")) {
      return {
        useAuth: () => {
          const bindings = activeAccountHelpBindings;
          if (bindings === undefined) throw new Error("Account/help bindings were not installed.");
          return {
            completeAccountDeletion: async (message: string) => {
              bindings.actions.authCompleteDeletionCalls.push(message);
            },
            reauthenticateCurrentUser: async (password: string) => {
              bindings.actions.authReauthenticateCalls.push(password);
            },
            signOut: async () => {
              bindings.actions.authSignOutCalls += 1;
            },
            state: bindings.authStatus === "signed-in"
              ? {
                  status: "signed-in",
                  user: { displayName: bindings.displayName, email: null, id: ROOM_ID },
                  profileBootstrap: { status: "ready" },
                }
              : bindings.authStatus === "suspended"
                ? {
                    status: "suspended",
                    message: "Account is suspended.",
                    user: { displayName: bindings.displayName, email: null, id: ROOM_ID },
                  }
                : { status: bindings.authStatus },
          };
        },
      };
    }
    if (request.endsWith("/src/features/session/SessionContext")) {
      return {
          useSession: () => ({
          terminateAuthenticatedState: () => {
            if (activeAccountHelpBindings !== undefined) {
              activeAccountHelpBindings.actions.terminateSessionCalls += 1;
            }
          },
        }),
      };
    }
    if (request.endsWith("/src/revenuecat/RevenueCatContext")) {
      return {
        useRevenueCat: () => ({
          clearIdentity: async () => {
            if (activeAccountHelpBindings !== undefined) {
              activeAccountHelpBindings.actions.clearIdentityCalls += 1;
            }
          },
          state: { status: "signed-out" },
        }),
      };
    }
    if (request.endsWith("/src/api/account")) {
      return {
        deleteAccount: async () => {
          if (activeAccountHelpBindings !== undefined) {
            activeAccountHelpBindings.actions.accountDeleteCalls += 1;
          }
          return { provider_cleanup_pending: false };
        },
      };
    }
    if (request.endsWith("/src/api/safetyReports")) {
      return {
        submitSafetyReport: async (input: Record<string, unknown>) => {
          activeAccountHelpBindings?.actions.reportRequests.push(input);
          return { status: "report_received" };
        },
      };
    }
    if (request.endsWith("/src/config/support")) {
      return {
        resolveSupportContact: () =>
          activeAccountHelpBindings?.supportContact ?? { status: "unavailable" },
        supportMailto: (contact: { status: string; email?: string }) =>
          contact.status === "configured" ? `mailto:${contact.email ?? ""}` : null,
      };
    }
    return originalLoad(request, parent, isMain);
  };
  try {
    const accountModule = (await import("../../app/account")) as { default: React.ComponentType; AccountPresentation: LoadedAccountHelpRoutes["accountPresentation"] };
    const privacyModule = (await import("../../app/privacy")) as { default: React.ComponentType };
    const supportModule = (await import("../../app/support")) as { default: React.ComponentType; SupportPresentation: LoadedAccountHelpRoutes["supportPresentation"] };
    const reportModule = (await import("../../app/report")) as { default: React.ComponentType; ReportPresentation: LoadedAccountHelpRoutes["reportPresentation"] };
    return {
      ...loaded,
      accountRoute: accountModule.default,
      accountPresentation: accountModule.AccountPresentation,
      installBindings: (bindings: AccountHelpBindings) => {
        activeAccountHelpBindings = bindings;
      },
      privacyRoute: privacyModule.default,
      reportRoute: reportModule.default,
      reportPresentation: reportModule.ReportPresentation,
      routerBackCalls: () => routerBackCalls,
      routerPushes,
      routerReplaces,
      supportRoute: supportModule.default,
      supportPresentation: supportModule.SupportPresentation,
    };
  } finally {
    moduleApi._load = originalLoad;
  }
}

async function loadProRoute(): Promise<LoadedProRoute> {
  const loaded = await getStudioComponents();
  const moduleRequire = createRequire(import.meta.url);
  const moduleApi = moduleRequire("node:module") as { _load: ModuleLoader };
  const originalLoad = moduleApi._load;
  const nativeShim = nativeShimFor(loaded.capture);
  moduleApi._load = (request, parent, isMain) => {
    if (request === "react-native") return nativeShim;
    if (request === "react-native-safe-area-context") {
      return { SafeAreaView: host("div", loaded.capture) };
    }
    if (request === "expo-router") {
      return {
        router: {
          replace: (value: unknown) => {
            activeProBindings?.actions.routerReplaces.push(value);
          },
        },
      };
    }
    if (request.endsWith("/src/auth/AuthContext")) {
      return {
        useAuth: () => ({
          state:
            activeProBindings?.authStatus === "signed-in"
              ? {
                  status: "signed-in",
                  user: { displayName: "Pro learner", email: null, id: ROOM_ID },
                  profileBootstrap: { status: "ready" },
                }
              : { status: "signed-out" },
        }),
      };
    }
    if (request.endsWith("/src/revenuecat/RevenueCatContext")) {
      return {
        useRevenueCat: () => ({
          presentPaywall: async (...args: unknown[]) => {
            if (activeProBindings !== undefined) {
              activeProBindings.actions.paywallCalls += 1;
              activeProBindings.actions.paywallArgs.push(args);
            }
            return { status: "cancelled" } as const;
          },
          refreshCustomerInfo: async (...args: unknown[]) => {
            if (activeProBindings !== undefined) {
              activeProBindings.actions.refreshCalls += 1;
              activeProBindings.actions.refreshArgs.push(args);
            }
          },
          restorePurchases: async (...args: unknown[]) => {
            if (activeProBindings !== undefined) {
              activeProBindings.actions.restoreCalls += 1;
              activeProBindings.actions.restoreArgs.push(args);
            }
            return { status: "cancelled" } as const;
          },
          state: activeProBindings?.revenueCatState,
        }),
      };
    }
    return originalLoad(request, parent, isMain);
  };
  try {
    const proModule = (await import("../../app/pro")) as { default: React.ComponentType };
    return {
      ...loaded,
      installBindings: (bindings: ProBindings) => {
        activeProBindings = bindings;
      },
      proRoute: proModule.default,
    };
  } finally {
    moduleApi._load = originalLoad;
  }
}

function renderAccountHelpRoute(
  loaded: LoadedAccountHelpRoutes,
  route: React.ComponentType,
  mode: "light" | "dark",
  bindings: AccountHelpBindings,
): string {
  loaded.installBindings(bindings);
  return renderToStaticMarkup(
    createElement(
      loaded.components.StudioThemeProvider,
      { mode },
      createElement(route),
    ),
  );
}

function assertAccountHelpPalette(
  capture: Capture,
  mode: "light" | "dark",
  options: {
    expectCard?: boolean;
    expectMuted?: boolean;
    expectPrimary?: boolean;
    expectSecondary?: boolean;
  } = {},
): void {
  const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
  const viewStyles = capture.viewProps.map((props) => flattenStyle(props.style));
  const textStyles = capture.textProps.map((props) => flattenStyle(props.style));
  const buttonStyles = capture.buttonProps.map((props) =>
    flattenStyle(props.style),
  );
  assert.ok(
    viewStyles.some((style) => style.backgroundColor === theme.colors.background),
    `${mode} account/help screen background did not reach the rendered host`,
  );
  if (options.expectCard ?? true) {
    assert.ok(
      viewStyles.some((style) => style.backgroundColor === theme.colors.surface),
      `${mode} account/help card surface did not reach the rendered host`,
    );
  }
  assert.ok(
    textStyles.some((style) => style.color === theme.colors.text),
    `${mode} account/help primary text did not reach the rendered host`,
  );
  if (options.expectMuted ?? true) {
    assert.ok(
      textStyles.some((style) => style.color === theme.colors.mutedText),
      `${mode} account/help muted text did not reach the rendered host`,
    );
  }
  if (options.expectPrimary ?? true) {
    assert.ok(
      buttonStyles.some((style) => style.backgroundColor === theme.colors.primary),
      `${mode} account/help primary button did not reach the rendered host`,
    );
  }
  if (options.expectSecondary ?? true) {
    assert.ok(
      buttonStyles.some((style) => style.backgroundColor === theme.colors.surface),
      `${mode} account/help secondary button did not reach the rendered host`,
    );
  }
  const title = capture.textProps.find((props) =>
    props.children === "Privacy" ||
    props.children === "Account & settings" ||
    props.children === "Support & Safety" ||
    props.children === "Report a safety concern" ||
    props.children === "Report unavailable" ||
    props.children === "Sign in to report a concern.",
  );
  assert.ok(title, `${mode} route title was not captured`);
  const titleStyle = flattenStyle(title.style);
  assert.equal(titleStyle.fontSize, 34);
  assert.equal(titleStyle.lineHeight, 40);
}

function assertNoAccountHelpRenderActions(
  bindings: AccountHelpBindings,
  capture: Capture,
): void {
  assert.equal(bindings.actions.accountDeleteCalls, 0);
  assert.equal(bindings.actions.authCompleteDeletionCalls.length, 0);
  assert.equal(bindings.actions.authReauthenticateCalls.length, 0);
  assert.equal(bindings.actions.authSignOutCalls, 0);
  assert.equal(bindings.actions.clearIdentityCalls, 0);
  assert.equal(bindings.actions.linkingCalls.length, 0);
  assert.equal(bindings.actions.reportRequests.length, 0);
  assert.equal(bindings.actions.terminateSessionCalls, 0);
  assert.equal(bindings.actions.routerBackCalls, 0);
  assert.equal(bindings.actions.routerPushes.length, 0);
  assert.equal(bindings.actions.routerReplaces.length, 0);
  assert.equal(capture.alertCalls.length, 0);
}

function resetCapture(capture: Capture): void {
  capture.alertCalls.length = 0;
  capture.buttonPresses.length = 0;
  capture.buttonProps.length = 0;
  capture.inputChanges.length = 0;
  capture.inputProps.length = 0;
  capture.textProps.length = 0;
  capture.viewProps.length = 0;
}

function routeBindings(
  sessionState: SessionState,
  options: Partial<Pick<WaitingRouteBindings, "authStatus" | "authUserId" | "roomParam">> = {},
): WaitingRouteBindings {
  return {
    actions: waitingRouteActions(),
    authStatus: options.authStatus ?? "signed-in",
    authUserId: options.authUserId ?? ROOM_ID,
    roomParam: options.roomParam ?? ROOM_ID,
    sessionState,
  };
}

function buttonByLabel(capture: Capture, label: string): NativeProps {
  const button = capture.buttonProps.find(
    (props) => props.accessibilityLabel === label,
  );
  assert.ok(button, `Expected a button labelled ${label}.`);
  return button;
}

function textByChildren(capture: Capture, children: string): NativeProps {
  const text = capture.textProps.find((props) => props.children === children);
  assert.ok(text, `Expected text ${children}.`);
  return text;
}

function invokeButton(button: NativeProps): void {
  assert.equal(typeof button.onPress, "function");
  (button.onPress as () => void)();
}

function colorChannel(value: number): number {
  const normalized = value / 255;
  return normalized <= 0.03928
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
}

function colorLuminance(hex: string): number {
  return (
    0.2126 * colorChannel(Number.parseInt(hex.slice(1, 3), 16)) +
    0.7152 * colorChannel(Number.parseInt(hex.slice(3, 5), 16)) +
    0.0722 * colorChannel(Number.parseInt(hex.slice(5, 7), 16))
  );
}

function colorContrast(first: string, second: string): number {
  const firstLuminance = colorLuminance(first);
  const secondLuminance = colorLuminance(second);
  return (
    (Math.max(firstLuminance, secondLuminance) + 0.05) /
    (Math.min(firstLuminance, secondLuminance) + 0.05)
  );
}

type StyleRecord = Record<string, unknown>;

function flattenStyle(value: unknown): StyleRecord {
  if (Array.isArray(value)) {
    return Object.assign({}, ...value.map((entry) => flattenStyle(entry)));
  }
  if (typeof value === "function") {
    return flattenStyle(
      (value as (state: { pressed: boolean }) => unknown)({ pressed: false }),
    );
  }
  return recordObject(value) ?? {};
}

function assertRoutePalette(capture: Capture, mode: "light" | "dark"): void {
  const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
  const viewStyles = capture.viewProps.map((props) => flattenStyle(props.style));
  const textStyles = capture.textProps.map((props) => flattenStyle(props.style));
  const buttonStyles = capture.buttonProps.map((props) =>
    flattenStyle(props.style),
  );
  assert.ok(
    viewStyles.some((style) => style.backgroundColor === theme.colors.background),
    `${mode} screen background did not reach the rendered host`,
  );
  assert.ok(
    viewStyles.some((style) => style.backgroundColor === theme.colors.surface),
    `${mode} card surface did not reach the rendered host`,
  );
  assert.ok(
    viewStyles.some(
      (style) => style.backgroundColor === theme.colors.selectedBackground,
    ),
    `${mode} participant-row background did not reach the rendered host`,
  );
  for (const color of [
    theme.colors.text,
    theme.colors.mutedText,
    theme.colors.primary,
    theme.colors.success,
  ]) {
    assert.ok(
      textStyles.some((style) => style.color === color),
      `${mode} rendered text is missing palette color ${color}`,
    );
  }
  assert.ok(
    buttonStyles.some((style) => style.backgroundColor === theme.colors.primary),
    `${mode} primary button color did not reach the rendered host`,
  );
  assert.ok(
    buttonStyles.some((style) => style.backgroundColor === theme.colors.surface),
    `${mode} secondary button color did not reach the rendered host`,
  );
}

function assertNoRenderActions(
  bindings: WaitingRouteBindings,
  capture: Capture,
  routerPushes: unknown[],
): void {
  assert.equal(bindings.actions.closeCalls, 0);
  assert.equal(bindings.actions.leaveCalls, 0);
  assert.equal(bindings.actions.prepareRequests.length, 0);
  assert.equal(bindings.actions.readyValues.length, 0);
  assert.equal(bindings.actions.requestStateCalls, 0);
  assert.equal(bindings.actions.retryCalls, 0);
  assert.equal(bindings.actions.startCalls, 0);
  assert.equal(capture.alertCalls.length, 0);
  assert.equal(routerPushes.length, 0);
}

function assertQuizPalette(
  capture: Capture,
  mode: "light" | "dark",
  options: { expectButton?: boolean; expectSelected?: boolean } = {},
): void {
  const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
  const viewStyles = capture.viewProps.map((props) => flattenStyle(props.style));
  const textStyles = capture.textProps.map((props) => flattenStyle(props.style));
  const buttonStyles = capture.buttonProps.map((props) =>
    flattenStyle(props.style),
  );
  assert.ok(
    viewStyles.some((style) => style.backgroundColor === theme.colors.background),
    `${mode} quiz canvas did not receive its background`,
  );
  assert.ok(
    viewStyles.some((style) => style.backgroundColor === theme.colors.surface),
    `${mode} quiz card did not receive its surface`,
  );
  assert.ok(
    textStyles.some((style) => style.color === theme.colors.text),
    `${mode} quiz text did not receive its foreground`,
  );
  assert.ok(
    textStyles.some((style) => style.color === theme.colors.mutedText),
    `${mode} quiz supporting text did not receive its muted foreground`,
  );
  if (options.expectSelected) {
    assert.ok(
      [...viewStyles, ...buttonStyles].some(
        (style) => style.backgroundColor === theme.colors.selectedBackground,
      ),
      `${mode} selected quiz surface did not receive its palette`,
    );
  }
  if (options.expectButton) {
    assert.ok(
      buttonStyles.some((style) => style.backgroundColor === theme.colors.primary),
      `${mode} quiz submit/retry button did not receive its palette`,
    );
  }
}

function assertAuthPalette(
  capture: Capture,
  mode: "light" | "dark",
  options: {
    expectCard?: boolean;
    expectError?: boolean;
    expectMuted?: boolean;
  } = {},
): void {
  const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
  const viewStyles = capture.viewProps.map((props) => flattenStyle(props.style));
  const textStyles = capture.textProps.map((props) => flattenStyle(props.style));
  const buttonStyles = capture.buttonProps.map((props) =>
    flattenStyle(props.style),
  );
  assert.ok(
    viewStyles.some((style) => style.backgroundColor === theme.colors.background),
    `${mode} auth screen background did not reach the rendered host`,
  );
  assert.ok(
    textStyles.some((style) => style.color === theme.colors.text),
    `${mode} auth primary text did not reach the rendered host`,
  );
  if (options.expectMuted ?? true) {
    assert.ok(
      textStyles.some((style) => style.color === theme.colors.mutedText),
      `${mode} auth muted text did not reach the rendered host`,
    );
  }
  assert.ok(
    colorContrast(theme.colors.text, theme.colors.background) >= 4.5,
    `${mode} auth primary text does not meet used contrast`,
  );
  if (options.expectMuted ?? true) {
    assert.ok(
      colorContrast(theme.colors.mutedText, theme.colors.background) >= 4.5,
      `${mode} auth muted text does not meet used contrast`,
    );
  }
  if (options.expectCard) {
    assert.ok(
      viewStyles.some((style) => style.backgroundColor === theme.colors.surface),
      `${mode} auth card surface did not reach the rendered host`,
    );
    assert.ok(
      buttonStyles.some((style) => style.backgroundColor === theme.colors.primary),
      `${mode} auth primary button did not reach the rendered host`,
    );
    assert.ok(
      buttonStyles.some((style) => style.backgroundColor === theme.colors.surface),
      `${mode} auth secondary button did not reach the rendered host`,
    );
  }
  if (options.expectError) {
    const error = textStyles.find((style) => style.color === theme.colors.error);
    assert.ok(error, `${mode} auth error foreground did not reach the host`);
    assert.equal(error?.backgroundColor, theme.colors.errorBackground);
    assert.ok(
      colorContrast(theme.colors.error, theme.colors.errorBackground) >= 4.5,
      `${mode} auth error does not meet used contrast`,
    );
  }
}

function assertQuizInputPalette(
  input: NativeProps | undefined,
  mode: "light" | "dark",
): void {
  assert.ok(input, `${mode} quiz input did not render`);
  const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
  const style = flattenStyle(input.style);
  assert.equal(input.keyboardAppearance, mode);
  assert.equal(input.cursorColor, theme.colors.primary);
  assert.equal(input.selectionColor, theme.colors.primary);
  assert.equal(input.placeholderTextColor, theme.colors.mutedText);
  assert.equal(style.backgroundColor, theme.colors.input);
  assert.equal(style.borderColor, theme.colors.border);
  assert.equal(style.color, theme.colors.text);
}

function assertNoQuizRenderActions(
  bindings: QuizRouteBindings,
  capture: Capture,
): void {
  assert.equal(bindings.actions.retryCalls, 0);
  assert.equal(bindings.actions.retryGradingCalls, 0);
  assert.equal(bindings.actions.submitChoices.length, 0);
  assert.equal(bindings.actions.submitTexts.length, 0);
  assert.equal(capture.alertCalls.length, 0);
}

function assertNoResultsRenderActions(
  bindings: ResultsRouteBindings,
  capture: Capture,
): void {
  assert.equal(bindings.actions.dismissCalls, 0);
  assert.equal(bindings.actions.reportPushes.length, 0);
  assert.equal(bindings.actions.retryCalls, 0);
  assert.equal(bindings.actions.reviewRequests.length, 0);
  assert.equal(capture.alertCalls.length, 0);
}

function assertNoAuthRenderActions(
  bindings: AuthRouteBindings,
  capture: Capture,
): void {
  assert.equal(bindings.actions.clearAuthCallbackErrorCalls, 0);
  assert.equal(bindings.actions.processCallbackCalls.length, 0);
  assert.equal(bindings.actions.routerPushes.length, 0);
  assert.equal(bindings.actions.routerReplaces.length, 0);
  assert.equal(bindings.actions.signInCalls.length, 0);
  assert.equal(bindings.actions.signOutCalls, 0);
  assert.equal(bindings.actions.signUpCalls.length, 0);
  assert.equal(capture.alertCalls.length, 0);
}

function assertResultsTypography(capture: Capture): void {
  const textStyles = capture.textProps.map((props) => flattenStyle(props.style));
  assert.ok(
    textStyles.some((style) => style.fontSize === 30 && style.lineHeight === 36),
    "Results title must retain a compatible explicit line height",
  );
  assert.ok(
    textStyles.some((style) => style.fontSize === 36 && style.lineHeight === 43),
    "Results total must retain a compatible explicit line height",
  );
}

function assertResultsReviewPalette(
  capture: Capture,
  mode: "light" | "dark",
  options: { expectError?: boolean; expectExtract?: boolean } = {},
): void {
  const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
  const textStyles = capture.textProps.map((props) => flattenStyle(props.style));
  const viewStyles = capture.viewProps.map((props) => flattenStyle(props.style));
  assert.ok(
    viewStyles.some((style) => style.backgroundColor === theme.colors.surface),
    `${mode} review card did not reach the rendered host`,
  );
  const muted = textStyles.find((style) => style.color === theme.colors.mutedText);
  assert.ok(muted, `${mode} review is missing its muted foreground`);
  assert.ok(
    colorContrast(theme.colors.mutedText, theme.colors.surface) >= 4.5,
    `${mode} review muted text does not meet used contrast`,
  );
  if (options.expectExtract) {
    const extract = textStyles.find(
      (style) => style.backgroundColor === theme.colors.selectedBackground,
    );
    assert.ok(extract, `${mode} review extract did not reach its palette`);
    assert.equal(extract?.color, theme.colors.text);
    assert.ok(
      colorContrast(theme.colors.text, theme.colors.selectedBackground) >= 4.5,
      `${mode} review extract does not meet used contrast`,
    );
  }
  if (options.expectError) {
    const error = textStyles.find((style) => style.color === theme.colors.error);
    assert.ok(error, `${mode} review error foreground did not reach the host`);
    assert.ok(
      colorContrast(theme.colors.error, theme.colors.surface) >= 4.5,
      `${mode} review error does not meet used contrast`,
    );
  }
}

function renderInStudio(
  components: StudioComponents,
  mode: "light" | "dark",
  child: React.ReactElement,
): string {
  return renderToStaticMarkup(
    createElement(
      components.StudioThemeProvider,
      { mode },
      createElement(components.StudioScreen, null, child),
    ),
  );
}

test("real Studio controls execute accessible callbacks and disabled contracts", async () => {
  const loaded = await getStudioComponents();
  const { capture, components } = loaded;
  capture.buttonPresses.length = 0;
  capture.inputChanges.length = 0;
  capture.inputProps.length = 0;
  let buttonPresses = 0;
  let choicePresses = 0;
  let inputValue = "";
  const markup = renderInStudio(
    components,
    "light",
    createElement(
      components.StudioStack,
      null,
      createElement(components.StudioButton, {
        label: "Continue",
        onPress: () => {
          buttonPresses += 1;
        },
      }),
      createElement(components.StudioChoiceRow, {
        description: "Selected option",
        onPress: () => {
          choicePresses += 1;
        },
        selected: true,
        title: "Option A",
      }),
      createElement(components.StudioChoiceRow, {
        disabled: true,
        onPress: () => undefined,
        selected: false,
        title: "Title only",
      }),
      createElement(components.StudioChoiceRow, {
        accessibilityLabel: "Override name",
        description: "Not part of the explicit label",
        disabled: true,
        onPress: () => undefined,
        selected: false,
        title: "Override title",
      }),
      createElement(components.StudioTextField, {
        label: "Email",
        onChangeText: (value: string) => {
          inputValue = value;
        },
        value: "old@example.com",
      }),
    ),
  );
  assert.match(markup, /aria-label="Continue"/);
  assert.match(markup, /aria-label="Option A, Selected option"/);
  assert.match(markup, /aria-label="Title only"/);
  assert.match(markup, /aria-label="Override name"/);
  assert.doesNotMatch(markup, /aria-label="Override title, Not part of the explicit label"/);
  assert.match(markup, /role="radio"/);
  assert.match(markup, /aria-checked="true"/);
  assert.match(markup, /aria-label="Email"/);
  assert.equal(capture.buttonPresses.length, 2);
  assert.equal(capture.inputChanges.length, 1);
  capture.buttonPresses[0]();
  capture.buttonPresses[1]();
  capture.inputChanges[0]("new@example.com");
  assert.equal(buttonPresses, 1);
  assert.equal(choicePresses, 1);
  assert.equal(inputValue, "new@example.com");
  assert.equal(capture.inputProps.at(-1)?.keyboardAppearance, "light");
  assert.equal(capture.inputProps.at(-1)?.selectionColor, "#5146E5");
  assert.equal(capture.inputProps.at(-1)?.cursorColor, "#5146E5");

  capture.buttonPresses.length = 0;
  capture.inputChanges.length = 0;
  capture.inputProps.length = 0;
  const disabledMarkup = renderInStudio(
    components,
    "dark",
    createElement(
      components.StudioStack,
      null,
      createElement(components.StudioButton, {
        disabled: true,
        label: "Unavailable",
        onPress: () => {
          throw new Error("disabled button dispatched");
        },
      }),
      createElement(components.StudioChoiceRow, {
        disabled: true,
        onPress: () => {
          throw new Error("disabled choice dispatched");
        },
        selected: false,
        title: "Locked option",
      }),
      createElement(components.StudioTextField, {
        editable: false,
        label: "Locked email",
        onChangeText: () => {
          throw new Error("disabled input dispatched");
        },
        value: "",
      }),
    ),
  );
  assert.match(disabledMarkup, /aria-label="Unavailable"/);
  assert.match(disabledMarkup, /aria-label="Locked option"/);
  assert.match(disabledMarkup, /aria-label="Locked email"/);
  assert.match(disabledMarkup, /disabled=""/g);
  assert.equal(capture.buttonPresses.length, 0);
  assert.equal(capture.inputChanges.length, 0);
  assert.equal(capture.inputProps.at(-1)?.keyboardAppearance, "dark");
  assert.equal(capture.inputProps.at(-1)?.selectionColor, "#9B95FF");
  assert.equal(capture.inputProps.at(-1)?.cursorColor, "#9B95FF");
});

test("real Studio dark shell renders errors and long text without native runtime", async () => {
  const { components } = await getStudioComponents();
  const longText = "A".repeat(480);
  const markup = renderInStudio(
    components,
    "dark",
    createElement(
      components.StudioStack,
      null,
      createElement(components.StudioText, { accessibilityRole: "alert" }, "Try again"),
      createElement(components.StudioText, null, longText),
      createElement(components.StudioTextField, {
        error: "Use a valid email address",
        label: "Email",
        onChangeText: () => undefined,
        value: "invalid",
      }),
    ),
  );
  assert.match(markup, /role="alert"/);
  assert.match(markup, /Try again/);
  assert.match(markup, new RegExp(longText));
  assert.match(markup, /Use a valid email address/);
  assert.match(markup, /aria-label="Email"/);
});

test("real appearance selector exposes the device-local choice and recovery copy", async () => {
  const { components } = await getStudioComponents();
  const markup = renderInStudio(
    components,
    "light",
    createElement(components.StudioAppearanceSelector),
  );
  assert.match(markup, /Appearance/);
  assert.match(markup, /Choose appearance: Light/);
  assert.match(markup, /not linked to your account/);
  assert.match(markup, /Changes apply immediately; this setting is device-local\./);
  assert.doesNotMatch(markup, /Using Light while this device preference loads\./);
  assert.doesNotMatch(markup, /Saved on this device when storage is available\./);
});

test("Studio provider resolves both palettes across a stable outer boundary", async () => {
  const { components } = await getStudioComponents();
  function ThemeProbe() {
    const theme = components.useStudioTheme();
    return createElement("span", { "data-scheme": theme.scheme }, theme.scheme);
  }
  function renderProbe(mode: "light" | "dark"): string {
    return renderToStaticMarkup(
      createElement(
        "div",
        { "data-boundary": "auth-session-stable" },
        createElement(components.StudioThemeProvider, { mode }, createElement(ThemeProbe)),
      ),
    );
  }
  const lightMarkup = renderProbe("light");
  const darkMarkup = renderProbe("dark");
  assert.match(lightMarkup, /data-boundary="auth-session-stable"/);
  assert.match(lightMarkup, /data-scheme="light"/);
  assert.match(darkMarkup, /data-boundary="auth-session-stable"/);
  assert.match(darkMarkup, /data-scheme="dark"/);
});

test("static root layout retains the exact fourteen-route boundary and ownership", () => {
  const source = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "../../app/_layout.tsx"),
    "utf8",
  );
  const routes = [...source.matchAll(/pathname === "([^"]+)"/gu)].map(
    (match) => match[1],
  );
  assert.deepEqual(routes, [
    "/",
    "/sign-in",
    "/waiting-room",
    "/quiz",
    "/results",
    "/sign-up",
    "/auth/callback",
    "/account",
    "/privacy",
    "/support",
    "/report",
    "/pro",
    "/solo",
    "/pets",
  ]);
  assert.match(
    source,
    /contentStyle:\s*\{[\s\S]*?backgroundColor:\s*appearanceEnabled\s*\?\s*theme\.colors\.background\s*:\s*colors\.background/su,
  );
  assert.ok(source.indexOf("<AuthProvider>") < source.indexOf("<RevenueCatProvider>"));
  assert.ok(source.indexOf("<RevenueCatProvider>") < source.indexOf("<SessionProvider>"));
  assert.ok(source.indexOf("<SessionProvider>") < source.indexOf("<SessionRouteCoordinator />"));
  assert.ok(source.indexOf("<SessionRouteCoordinator />") < source.indexOf("<StudioThemeProvider"));
  assert.match(source, /unknown paths retain the existing Light fallback|appearanceEnabled/);
});

test("real Pro route preserves RevenueCat states and actions in both palettes", async () => {
  const loaded = await loadProRoute();
  const nativeCapability: RevenueCatPlatformCapability = {
    platform: "ios",
    status: "native-purchase-supported",
  };
  const previewCapability: RevenueCatPlatformCapability = {
    message: "Purchases are preview-only in this build.",
    platform: "ios",
    status: "preview-only",
  };
  const unsupportedWebCapability: RevenueCatPlatformCapability = {
    message: "Purchases are unavailable on web.",
    platform: "web",
    status: "unsupported-with-current-web-configuration",
  };
  const freePackage = {
    description: "Monthly access",
    identifier: "$rc_monthly",
    period: "P1M",
    price: "£3.99",
    productIdentifier: "studyroom_monthly",
    title: "MindMesh Pro Monthly",
  };
  const annualPackage = {
    description: "Annual access",
    identifier: "$rc_annual",
    period: "P1Y",
    price: "£39.99",
    productIdentifier: "studyroom_annual",
    title: "MindMesh Pro Annual",
  };
  const baseData: RevenueCatReadyData = {
    appUserId: ROOM_ID,
    entitlementIdentifier: "pro",
    expirationDate: null,
    isPro: false,
    isSandbox: null,
    managementUrl: null,
    offering: {
      identifier: "default",
      packages: [freePackage, annualPackage],
    },
    offeringStatus: "available",
    willRenew: null,
  };
  const makeData = (
    overrides: Partial<RevenueCatReadyData> = {},
  ): RevenueCatReadyData => ({ ...baseData, ...overrides });
  const freeData = makeData();
  const proData = makeData({
    expirationDate: "2026-12-31T12:00:00Z",
    isPro: true,
    isSandbox: true,
    managementUrl: "https://store.example/manage",
    willRenew: false,
  });
  const renewingProData = makeData({
    expirationDate: null,
    isPro: true,
    isSandbox: false,
    managementUrl: null,
    willRenew: true,
  });
  const invalidExpiryProData = makeData({
    expirationDate: "not-a-date",
    isPro: true,
    isSandbox: false,
    managementUrl: "https://store.example/manage",
    willRenew: false,
  });
  const emptyData = makeData({
    offering: { identifier: "default", packages: [] },
    offeringStatus: "empty",
  });
  const missingData = makeData({
    offering: null,
    offeringStatus: "missing",
  });
  const longTitle = "MindMesh Pro " + "Long package title ".repeat(12);
  const longData = makeData({
    offering: {
      identifier: "default",
      packages: [
        {
          ...freePackage,
          description: "A".repeat(220),
          price: "£123456789.99 per month",
          title: longTitle,
        },
        annualPackage,
      ],
    },
  });
  const unsupportedPlatformCapability: RevenueCatPlatformCapability = {
    message: "Purchases are unavailable on this device.",
    platform: "desktop",
    status: "unsupported-platform",
  };
  const stateCases: Array<[string, RevenueCatState]> = [
    ["preview", { capability: previewCapability, status: "ready", data: freeData, notice: null }],
    ["unsupported", { capability: unsupportedWebCapability, message: unsupportedWebCapability.message, reason: "platform", status: "unavailable" }],
    ["unsupported-platform", { capability: unsupportedPlatformCapability, message: unsupportedPlatformCapability.message, reason: "platform", status: "unavailable" }],
    ["unconfigured", { capability: nativeCapability, status: "unconfigured" }],
    ["initializing", { capability: nativeCapability, status: "initializing" }],
    ["loading-customer", { appUserId: ROOM_ID, capability: nativeCapability, status: "loading-customer" }],
    ["unavailable", { capability: nativeCapability, message: "RevenueCat is unavailable in this build.", reason: "sdk", status: "unavailable" }],
    ["free", { capability: nativeCapability, data: freeData, notice: null, status: "ready" }],
    ["pro", { capability: nativeCapability, data: proData, notice: null, status: "ready" }],
    ["renewing-pro", { capability: nativeCapability, data: renewingProData, notice: null, status: "ready" }],
    ["invalid-expiry-pro", { capability: nativeCapability, data: invalidExpiryProData, notice: null, status: "ready" }],
    ["ready-notice", { capability: nativeCapability, data: freeData, notice: { message: "No MindMesh Pro purchase is active.", tone: "neutral" }, status: "ready" }],
    ["empty", { capability: nativeCapability, data: emptyData, notice: null, status: "ready" }],
    ["missing", { capability: nativeCapability, data: missingData, notice: null, status: "ready" }],
    ["purchasing", { capability: nativeCapability, data: freeData, status: "purchasing" }],
    ["restoring", { capability: nativeCapability, data: freeData, status: "restoring" }],
    ["recoverable-error", { appUserId: ROOM_ID, capability: nativeCapability, code: "network-failure", data: freeData, message: "RevenueCat could not be reached. Check your connection and try again.", status: "recoverable-error" }],
    ["long-package", { capability: nativeCapability, data: longData, notice: null, status: "ready" }],
    ["rc-signed-out", { capability: nativeCapability, status: "signed-out" }],
  ];
  const expectedAccessLabels: Readonly<Record<string, string>> = {
    empty: "Free",
    free: "Free",
    initializing: "Loading",
    "loading-customer": "Loading",
    "long-package": "Free",
    missing: "Free",
    preview: "Preview only",
    pro: "Pro",
    purchasing: "Free",
    "ready-notice": "Free",
    restoring: "Free",
    unavailable: "Unavailable",
    unconfigured: "Loading",
    unsupported: "Unavailable on this platform",
    "recoverable-error": "Free",
    "unsupported-platform": "Unavailable on this platform",
    "renewing-pro": "Pro",
    "invalid-expiry-pro": "Pro",
    "rc-signed-out": "Signed out",
  };

  const assertProPalette = (mode: "light" | "dark", expectCard = true) => {
    const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
    const viewStyles = loaded.capture.viewProps.map((props) => flattenStyle(props.style));
    const textStyles = loaded.capture.textProps.map((props) => flattenStyle(props.style));
    assert.ok(viewStyles.some((style) => style.backgroundColor === theme.colors.background));
    if (expectCard) {
      assert.ok(viewStyles.some((style) => style.backgroundColor === theme.colors.surface));
    }
    assert.ok(textStyles.some((style) => style.color === theme.colors.text));
    if (expectCard) {
      assert.ok(textStyles.some((style) => style.color === theme.colors.mutedText));
    }
    const title = loaded.capture.textProps.find(
      (props) => props.children === "MindMesh Pro" || props.children === "Returning to sign in...",
    );
    assert.ok(title);
    const titleStyle = flattenStyle(title.style);
    assert.equal(titleStyle.fontSize, 34);
    assert.equal(titleStyle.lineHeight, 40);
  };
  const assertNoProRenderActions = (bindings: ProBindings) => {
    assert.equal(bindings.actions.paywallCalls, 0);
    assert.equal(bindings.actions.restoreCalls, 0);
    assert.equal(bindings.actions.refreshCalls, 0);
    assert.deepEqual(bindings.actions.routerReplaces, []);
  };
  const expectedEligibility: Readonly<Record<string, {
    purchase: boolean;
    restore: boolean;
    refresh: boolean;
  }>> = {
    preview: { purchase: false, restore: false, refresh: true },
    unsupported: { purchase: false, restore: false, refresh: false },
    "unsupported-platform": { purchase: false, restore: false, refresh: false },
    unconfigured: { purchase: false, restore: false, refresh: false },
    initializing: { purchase: false, restore: false, refresh: false },
    "loading-customer": { purchase: false, restore: false, refresh: false },
    unavailable: { purchase: false, restore: false, refresh: false },
    free: { purchase: true, restore: true, refresh: true },
    pro: { purchase: false, restore: true, refresh: true },
    "renewing-pro": { purchase: false, restore: true, refresh: true },
    "invalid-expiry-pro": { purchase: false, restore: true, refresh: true },
    "ready-notice": { purchase: true, restore: true, refresh: true },
    empty: { purchase: false, restore: true, refresh: true },
    missing: { purchase: false, restore: true, refresh: true },
    purchasing: { purchase: false, restore: false, refresh: false },
    restoring: { purchase: false, restore: false, refresh: false },
    "recoverable-error": { purchase: true, restore: true, refresh: true },
    "long-package": { purchase: true, restore: true, refresh: true },
    "rc-signed-out": { purchase: false, restore: false, refresh: false },
  };
  const renderPro = (
    mode: "light" | "dark",
    bindings: ProBindings,
  ): string => {
    loaded.installBindings(bindings);
    return renderToStaticMarkup(
      createElement(
        loaded.components.StudioThemeProvider,
        { mode },
        createElement(loaded.proRoute),
      ),
    );
  };
  const newBindings = (
    revenueCatState: RevenueCatState,
    authStatus: ProBindings["authStatus"] = "signed-in",
  ): ProBindings => ({
    actions: {
      paywallArgs: [],
      paywallCalls: 0,
      refreshArgs: [],
      refreshCalls: 0,
      restoreArgs: [],
      restoreCalls: 0,
      routerReplaces: [],
    },
    authStatus,
    revenueCatState,
  });

  for (const mode of ["light", "dark"] as const) {
    const signedOut = newBindings({ capability: nativeCapability, status: "signed-out" }, "signed-out");
    resetCapture(loaded.capture);
    const signedOutMarkup = renderPro(mode, signedOut);
    assert.match(signedOutMarkup, /Returning to sign in/);
    assertProPalette(mode, false);
    assertNoProRenderActions(signedOut);
    const signedOutWithReadyRevenueCat = newBindings(
      { capability: nativeCapability, data: freeData, notice: null, status: "ready" },
      "signed-out",
    );
    resetCapture(loaded.capture);
    const signedOutReadyMarkup = renderPro(mode, signedOutWithReadyRevenueCat);
    assert.match(signedOutReadyMarkup, /Returning to sign in/);
    assertProPalette(mode, false);
    assertNoProRenderActions(signedOutWithReadyRevenueCat);

    for (const [name, revenueCatState] of stateCases) {
      const bindings = newBindings(revenueCatState);
      resetCapture(loaded.capture);
      const markup = renderPro(mode, bindings);
      assert.match(markup, /MindMesh Pro/);
      assertProPalette(mode);
      assertNoProRenderActions(bindings);
      assert.ok(textByChildren(loaded.capture, expectedAccessLabels[name]));
      const eligibility = expectedEligibility[name];
      assert.ok(eligibility, `Missing eligibility fixture for ${name}`);
      const purchaseLabel = name === "purchasing"
        ? "Opening Paywall..."
        : "Open RevenueCat Paywall";
      const restoreLabel = name === "restoring"
        ? "Restoring Purchases..."
        : "Restore Purchases";
      const refreshLabel = name === "loading-customer"
        ? "Refreshing Pro Status..."
        : "Refresh Pro Status";
      assert.deepEqual(
        buttonByLabel(loaded.capture, purchaseLabel).accessibilityState,
        { disabled: !eligibility.purchase },
      );
      assert.deepEqual(
        buttonByLabel(loaded.capture, restoreLabel).accessibilityState,
        { disabled: !eligibility.restore },
      );
      assert.deepEqual(
        buttonByLabel(loaded.capture, refreshLabel).accessibilityState,
        { disabled: !eligibility.refresh },
      );
      assert.deepEqual(
        buttonByLabel(loaded.capture, "Return Home").accessibilityState,
        { disabled: name === "purchasing" || name === "restoring" },
      );
      assert.equal(
        loaded.capture.buttonPresses.length,
        Number(eligibility.purchase) +
          Number(eligibility.restore) +
          Number(eligibility.refresh) +
          Number(name !== "purchasing" && name !== "restoring"),
        `${name} exposed a callback for a disabled Pro control`,
      );
      if (name === "free" || name === "pro") {
        const accessStyle = flattenStyle(textByChildren(loaded.capture, expectedAccessLabels[name]).style);
        assert.equal(accessStyle.fontSize, 24);
        assert.equal(accessStyle.lineHeight, 30);
      }
      if (name === "free") {
        assert.match(markup, /Monthly access/);
        assert.match(markup, /£3\.99/);
        assert.match(markup, /1 month/);
        assert.match(markup, /Annual access/);
        assert.match(markup, /£39\.99/);
        assert.match(markup, /1 year/);
        const packageChildren = loaded.capture.textProps.map((props) => String(props.children));
        assert.ok(packageChildren.indexOf("MindMesh Pro Monthly") < packageChildren.indexOf("MindMesh Pro Annual"));
      }
      if (name === "pro") {
        assert.match(markup, /Active until/);
        assert.match(markup, /Will not renew/);
        assert.match(markup, /Test Store \/ sandbox entitlement/);
        assert.match(markup, /Subscription management is available from the store account\./);
      }
      if (name === "renewing-pro") {
        assert.match(markup, /Active without an expiry date/);
        assert.match(markup, /Renews automatically/);
        assert.doesNotMatch(markup, /Active until/);
      }
      if (name === "invalid-expiry-pro") {
        assert.match(markup, /Active until not-a-date/);
        assert.match(markup, /Will not renew/);
        assert.match(markup, /Subscription management is available from the store account\./);
      }
      if (name === "preview" || name === "unsupported" || name === "unsupported-platform") {
        assert.match(markup, /Purchases are/);
      }
      if (name === "empty") {
        assert.match(markup, /This offering has no available packages\./);
      }
      if (name === "missing") {
        assert.match(markup, /The configured MindMesh Pro offering is unavailable\./);
      }
      if (name === "purchasing") {
        const pending = textByChildren(loaded.capture, "The RevenueCat paywall is open.");
        assert.equal(pending.accessibilityLiveRegion, "polite");
      }
      if (name === "restoring") {
        const pending = textByChildren(loaded.capture, "Restoring purchases...");
        assert.equal(pending.accessibilityLiveRegion, "polite");
      }
      if (name === "ready-notice") {
        const notice = textByChildren(loaded.capture, "No MindMesh Pro purchase is active.");
        const noticeStyle = flattenStyle(notice.style);
        assert.equal(notice.accessibilityLiveRegion, "polite");
        assert.equal(notice.accessibilityRole, undefined);
        assert.ok(colorContrast(noticeStyle.color as string, noticeStyle.backgroundColor as string) >= 4.5);
      }
      if (name === "recoverable-error" || name === "unavailable") {
        const message = name === "recoverable-error"
          ? "RevenueCat could not be reached. Check your connection and try again."
          : "RevenueCat is unavailable in this build.";
        const alert = textByChildren(loaded.capture, message);
        assert.equal(alert.accessibilityRole, "alert");
        assert.equal(alert.accessibilityLiveRegion, "polite");
        const alertStyle = flattenStyle(alert.style);
        assert.ok(
          colorContrast(
            alertStyle.color as string,
            alertStyle.backgroundColor as string,
          ) >= 4.5,
        );
      }
      if (name === "long-package") {
        assert.match(markup, new RegExp(longTitle));
        assert.match(markup, /A{220}/);
        assert.match(markup, /£123456789\.99 per month/);
        assert.match(markup, /Annual access/);
        const longTitleStyle = flattenStyle(textByChildren(loaded.capture, longTitle).style);
        assert.equal(longTitleStyle.height, undefined);
        assert.equal(longTitleStyle.lineHeight, 24);
        const priceStyle = flattenStyle(textByChildren(loaded.capture, "£123456789.99 per month").style);
        assert.equal(priceStyle.flexShrink, 1);
        const packageChildren = loaded.capture.textProps.map((props) => String(props.children));
        assert.ok(packageChildren.indexOf(longTitle) < packageChildren.indexOf("MindMesh Pro Annual"));
      }
    }

    const freeBindings = newBindings({ capability: nativeCapability, data: freeData, notice: null, status: "ready" });
    resetCapture(loaded.capture);
    renderPro(mode, freeBindings);
    assert.deepEqual(buttonByLabel(loaded.capture, "Open RevenueCat Paywall").accessibilityState, { disabled: false });
    assert.deepEqual(buttonByLabel(loaded.capture, "Restore Purchases").accessibilityState, { disabled: false });
    assert.deepEqual(buttonByLabel(loaded.capture, "Refresh Pro Status").accessibilityState, { disabled: false });
    assert.deepEqual(buttonByLabel(loaded.capture, "Return Home").accessibilityState, { disabled: false });
    assertNoProRenderActions(freeBindings);
    invokeButton(buttonByLabel(loaded.capture, "Open RevenueCat Paywall"));
    invokeButton(buttonByLabel(loaded.capture, "Restore Purchases"));
    invokeButton(buttonByLabel(loaded.capture, "Refresh Pro Status"));
    invokeButton(buttonByLabel(loaded.capture, "Return Home"));
    assert.equal(freeBindings.actions.paywallCalls, 1);
    assert.equal(freeBindings.actions.restoreCalls, 1);
    assert.equal(freeBindings.actions.refreshCalls, 1);
    assert.deepEqual(freeBindings.actions.paywallArgs, [[]]);
    assert.deepEqual(freeBindings.actions.restoreArgs, [[]]);
    assert.deepEqual(freeBindings.actions.refreshArgs, [[]]);
    assert.deepEqual(freeBindings.actions.routerReplaces, ["/"]);

    const pendingBindings = newBindings({ capability: nativeCapability, data: freeData, status: "purchasing" });
    resetCapture(loaded.capture);
    renderPro(mode, pendingBindings);
    for (const label of ["Opening Paywall...", "Restore Purchases", "Refresh Pro Status", "Return Home"]) {
      assert.deepEqual(buttonByLabel(loaded.capture, label).accessibilityState, { disabled: true });
    }
    assertNoProRenderActions(pendingBindings);

    const restorePendingBindings = newBindings({ capability: nativeCapability, data: freeData, status: "restoring" });
    resetCapture(loaded.capture);
    renderPro(mode, restorePendingBindings);
    for (const label of ["Open RevenueCat Paywall", "Restoring Purchases...", "Refresh Pro Status", "Return Home"]) {
      assert.deepEqual(buttonByLabel(loaded.capture, label).accessibilityState, { disabled: true });
    }
    assertNoProRenderActions(restorePendingBindings);
  }
});

test("real sign-up and sign-in routes preserve auth fields and actions in both palettes", async () => {
  const loaded = await loadAuthRoutes();
  for (const mode of ["light", "dark"] as const) {
    resetCapture(loaded.capture);
    const signUpBindings = authRouteBindings({ status: "signed-out" });
    const signUpMarkup = renderAuthRoute(
      loaded,
      loaded.signUpRoute,
      mode,
      signUpBindings,
    );
    assert.match(signUpMarkup, /Create your account/);
    assertAuthPalette(loaded.capture, mode, { expectCard: true });
    assertNoAuthRenderActions(signUpBindings, loaded.capture);
    assert.equal(loaded.capture.inputProps.length, 3);
    const [displayNameInput, emailInput, passwordInput] = loaded.capture.inputProps;
    assert.equal(displayNameInput?.accessibilityLabel, "Display name");
    assert.equal(displayNameInput?.autoCapitalize, "words");
    assert.equal(displayNameInput?.placeholder, "Your name");
    assert.equal(emailInput?.accessibilityLabel, "Email");
    assert.equal(emailInput?.autoCapitalize, "none");
    assert.equal(emailInput?.autoComplete, "email");
    assert.equal(emailInput?.keyboardType, "email-address");
    assert.equal(passwordInput?.accessibilityLabel, "Password");
    assert.equal(passwordInput?.autoCapitalize, "none");
    assert.equal(passwordInput?.autoComplete, "new-password");
    assert.equal(passwordInput?.secureTextEntry, true);
    for (const input of loaded.capture.inputProps) {
      const style = flattenStyle(input.style);
      assert.equal(input.keyboardAppearance, mode);
      assert.equal(input.cursorColor, mode === "light" ? studioLightTheme.colors.primary : studioDarkTheme.colors.primary);
      assert.equal(input.selectionColor, mode === "light" ? studioLightTheme.colors.primary : studioDarkTheme.colors.primary);
      assert.equal(input.placeholderTextColor, mode === "light" ? studioLightTheme.colors.mutedText : studioDarkTheme.colors.mutedText);
      assert.equal(style.color, mode === "light" ? studioLightTheme.colors.text : studioDarkTheme.colors.text);
    }
    invokeButton(buttonByLabel(loaded.capture, "I already have an account"));
    assert.deepEqual(signUpBindings.actions.routerReplaces, ["/sign-in"]);
    invokeButton(buttonByLabel(loaded.capture, "Privacy"));
    assert.deepEqual(signUpBindings.actions.routerPushes, ["/privacy"]);

    resetCapture(loaded.capture);
    const pendingBindings = authRouteBindings({ status: "signing-up" });
    renderAuthRoute(loaded, loaded.signUpRoute, mode, pendingBindings);
    assert.deepEqual(buttonByLabel(loaded.capture, "Creating account...").accessibilityState, {
      disabled: true,
    });
    assertNoAuthRenderActions(pendingBindings, loaded.capture);

    resetCapture(loaded.capture);
    const confirmationBindings = authRouteBindings({ status: "confirmation-required" });
    const confirmationMarkup = renderAuthRoute(
      loaded,
      loaded.signUpRoute,
      mode,
      confirmationBindings,
    );
    assert.match(confirmationMarkup, /Check your email/);
    assertNoAuthRenderActions(confirmationBindings, loaded.capture);
    invokeButton(buttonByLabel(loaded.capture, "Return to sign in"));
    assert.deepEqual(confirmationBindings.actions.routerReplaces, ["/sign-in"]);

    resetCapture(loaded.capture);
    const errorBindings = authRouteBindings(
      { status: "error", message: "Authentication failed" },
    );
    const errorMarkup = renderAuthRoute(loaded, loaded.signUpRoute, mode, errorBindings);
    assert.match(errorMarkup, /Authentication failed/);
    assertAuthPalette(loaded.capture, mode, { expectCard: true, expectError: true });
    assert.ok(
      loaded.capture.textProps.some(
        (props) => props.accessibilityRole === "alert" &&
          String(props.children).includes("Authentication failed"),
      ),
    );
    assertNoAuthRenderActions(errorBindings, loaded.capture);

    resetCapture(loaded.capture);
    const signedInBindings = authRouteBindings({ status: "signed-in" });
    const signedInMarkup = renderAuthRoute(
      loaded,
      loaded.signUpRoute,
      mode,
      signedInBindings,
    );
    assert.match(signedInMarkup, /Opening your current session/);
    assertAuthPalette(loaded.capture, mode, { expectMuted: false });
    assertNoAuthRenderActions(signedInBindings, loaded.capture);

    resetCapture(loaded.capture);
    const signInBindings = authRouteBindings({ status: "signed-out" });
    const signInMarkup = renderAuthRoute(
      loaded,
      loaded.signInRoute,
      mode,
      signInBindings,
    );
    assert.match(signInMarkup, /Welcome back/);
    assertAuthPalette(loaded.capture, mode, { expectCard: true });
    assertNoAuthRenderActions(signInBindings, loaded.capture);
    assert.equal(loaded.capture.inputProps.length, 2);
    assert.equal(loaded.capture.inputProps[0]?.accessibilityLabel, "EMAIL");
    assert.equal(loaded.capture.inputProps[0]?.autoComplete, "email");
    assert.equal(loaded.capture.inputProps[0]?.keyboardType, "email-address");
    assert.equal(loaded.capture.inputProps[1]?.accessibilityLabel, "PASSWORD");
    assert.equal(loaded.capture.inputProps[1]?.secureTextEntry, true);
    invokeButton(buttonByLabel(loaded.capture, "Create an account"));
    assert.deepEqual(signInBindings.actions.routerPushes, ["/sign-up"]);
    invokeButton(buttonByLabel(loaded.capture, "Privacy"));
    assert.deepEqual(signInBindings.actions.routerPushes, ["/sign-up", "/privacy"]);
  }
});

test("real auth callback route preserves progress, session-aware errors, and effect boundaries", async () => {
  const loaded = await loadAuthRoutes();
  for (const mode of ["light", "dark"] as const) {
    resetCapture(loaded.capture);
    const progressBindings = authRouteBindings(
      { status: "signed-out" },
      {
        authCallbackStatus: "processing",
        callbackParams: { code: "synthetic-code" },
      },
    );
    const progressMarkup = renderAuthRoute(
      loaded,
      loaded.callbackRoute,
      mode,
      progressBindings,
    );
    assert.match(progressMarkup, /Confirming your account/);
    assertAuthPalette(loaded.capture, mode);
    assert.ok(
      loaded.capture.textProps.some(
        (props) => props.accessibilityLiveRegion === "polite" &&
          String(props.children).includes("Confirming your account"),
      ),
    );
    assertNoAuthRenderActions(progressBindings, loaded.capture);

    resetCapture(loaded.capture);
    const signedOutErrorBindings = authRouteBindings(
      { status: "signed-out" },
      {
        authCallbackError: "This confirmation link has expired.",
        authCallbackStatus: "failed",
      },
    );
    const signedOutErrorMarkup = renderAuthRoute(
      loaded,
      loaded.callbackRoute,
      mode,
      signedOutErrorBindings,
    );
    assert.match(signedOutErrorMarkup, /This confirmation link has expired/);
    assertAuthPalette(loaded.capture, mode, {
      expectError: true,
      expectMuted: false,
    });
    assert.deepEqual(
      buttonByLabel(loaded.capture, "Return to sign in").accessibilityState,
      { disabled: false },
    );
    assertNoAuthRenderActions(signedOutErrorBindings, loaded.capture);
    invokeButton(buttonByLabel(loaded.capture, "Return to sign in"));
    assert.equal(signedOutErrorBindings.actions.clearAuthCallbackErrorCalls, 1);
    assert.deepEqual(signedOutErrorBindings.actions.routerReplaces, ["/sign-in"]);

    resetCapture(loaded.capture);
    const signedInErrorBindings = authRouteBindings(
      { status: "signed-in" },
      {
        authCallbackError: "Confirmation needs attention.",
        authCallbackStatus: "failed",
      },
    );
    const signedInErrorMarkup = renderAuthRoute(
      loaded,
      loaded.callbackRoute,
      mode,
      signedInErrorBindings,
    );
    assert.match(signedInErrorMarkup, /Confirmation needs attention/);
    assertAuthPalette(loaded.capture, mode, {
      expectError: true,
      expectMuted: false,
    });
    assertNoAuthRenderActions(signedInErrorBindings, loaded.capture);
    invokeButton(buttonByLabel(loaded.capture, "Continue to MindMesh"));
    assert.equal(signedInErrorBindings.actions.clearAuthCallbackErrorCalls, 1);
    assert.deepEqual(signedInErrorBindings.actions.routerReplaces, ["/"]);
  }
});

test("real account/help routes render both palettes with inert sensitive boundaries", async () => {
  const loaded = await loadAccountHelpRoutes();
  for (const mode of ["light", "dark"] as const) {
    const accountBindings = accountHelpBindings();
    resetCapture(loaded.capture);
    const accountMarkup = renderAccountHelpRoute(
      loaded,
      loaded.accountRoute,
      mode,
      accountBindings,
    );
    assert.match(accountMarkup, /Account &amp; settings|Account & settings/);
    assert.match(accountMarkup, /MindMesh member|Account learner/);
    assertAccountHelpPalette(loaded.capture, mode, { expectPrimary: false });
    const deleteButton = buttonByLabel(loaded.capture, "Delete Account");
    const deleteStyle = flattenStyle(deleteButton.style);
    assert.equal(deleteStyle.backgroundColor, (mode === "light" ? studioLightTheme : studioDarkTheme).colors.error);
    assert.ok(
      colorContrast(
        deleteStyle.backgroundColor as string,
        flattenStyle(textByChildren(loaded.capture, "Delete Account").style).color as string,
      ) >= 4.5,
      `${mode} destructive control foreground contrast is insufficient`,
    );
    assertNoAccountHelpRenderActions(accountBindings, loaded.capture);
    invokeButton(buttonByLabel(loaded.capture, "Privacy"));
    invokeButton(buttonByLabel(loaded.capture, "Support & Safety"));
    assert.deepEqual(accountBindings.actions.routerPushes, ["/privacy", "/support"]);

    const privacyBindings = accountHelpBindings();
    resetCapture(loaded.capture);
    const privacyMarkup = renderAccountHelpRoute(
      loaded,
      loaded.privacyRoute,
      mode,
      privacyBindings,
    );
    const normalizedPrivacy = privacyMarkup
      .replace(/<[^>]+>/gu, " ")
      .replace(/&#x27;|&apos;/gu, "'")
      .replace(/&amp;/gu, "&")
      .replace(/\s+/gu, " ");
    for (const paragraph of [
      "MindMesh uses your Supabase identity, email, authentication session, display name, room memberships, quiz participation, answers, results, timestamps, and necessary service metadata. RevenueCat and the store handle purchase and entitlement records used for MindMesh Pro.",
      "We use this information to authenticate you, run invite-only rooms, calculate session results, provide subscription access, operate the service, and respond to support or safety concerns.",
      "MindMesh does not currently collect location, contacts, photos, advertising IDs, direct messages, chat, or public profiles. Room participants see display names and the room or quiz state needed for multiplayer. Exact answers and feedback stay viewer-private. Your own bounded practice summary may combine your still-retained results from previous rooms; there is no public performance directory.",
      "When you are signed in, Account & settings can calculate your own marks and topic counts on demand from finished adaptive GCSE sessions you participated in, including previous rooms you have left or that closed. It shows accuracy only for graded answers, separately counts unanswered and ungraded questions, and may include exact repeats. This creates no separate saved analytics profile. Existing room-data purge or account deletion can remove these source results, so the summary is not a lifetime history. These sampled MindMesh results are not an AQA grade or full-syllabus assessment.",
      "Generating an adaptive GCSE quiz sends the selected subject, topic, mark budget, and a bounded list of recent question prompts to OpenAI to reduce repetition. Marking a written answer sends the question, any source extract, the hidden marking rubric, and the student's answer.",
      "You can start account deletion from Account & settings. MindMesh removes or anonymizes local account data under its current deletion contract and schedules linked provider cleanup. Deleting MindMesh does not cancel an App Store or Google Play subscription. Current retention periods are not yet automated.",
    ]) {
      assert.ok(normalizedPrivacy.includes(paragraph), `Privacy paragraph missing: ${paragraph}`);
    }
    assertAccountHelpPalette(loaded.capture, mode, { expectPrimary: false });
    assertNoAccountHelpRenderActions(privacyBindings, loaded.capture);
    invokeButton(buttonByLabel(loaded.capture, "Support & Safety"));
    assert.deepEqual(privacyBindings.actions.routerPushes, ["/support"]);

    const supportBindings = accountHelpBindings();
    resetCapture(loaded.capture);
    const supportMarkup = renderAccountHelpRoute(
      loaded,
      loaded.supportRoute,
      mode,
      supportBindings,
    );
    assert.match(supportMarkup, /support@example.test/);
    assert.match(supportMarkup, /Report a safety concern/);
    assertAccountHelpPalette(loaded.capture, mode);
    assertNoAccountHelpRenderActions(supportBindings, loaded.capture);
    invokeButton(buttonByLabel(loaded.capture, "Contact Support"));
    assert.deepEqual(supportBindings.actions.linkingCalls, [
      "mailto:support@example.test",
    ]);

    const signedOutSupport = accountHelpBindings({
      authStatus: "signed-out",
      supportContact: { status: "unavailable" },
    });
    resetCapture(loaded.capture);
    const signedOutSupportMarkup = renderAccountHelpRoute(
      loaded,
      loaded.supportRoute,
      mode,
      signedOutSupport,
    );
    assert.match(signedOutSupportMarkup, /not configured in this build/);
    assert.match(signedOutSupportMarkup, />Sign in</);
    assertAccountHelpPalette(loaded.capture, mode);
    assertNoAccountHelpRenderActions(signedOutSupport, loaded.capture);

    const signedOutReport = accountHelpBindings({ authStatus: "signed-out" });
    resetCapture(loaded.capture);
    const signedOutReportMarkup = renderAccountHelpRoute(
      loaded,
      loaded.reportRoute,
      mode,
      signedOutReport,
    );
    assert.match(signedOutReportMarkup, /Sign in to report a concern/);
    assertAccountHelpPalette(loaded.capture, mode, {
      expectCard: false,
      expectMuted: false,
      expectSecondary: false,
    });
    assertNoAccountHelpRenderActions(signedOutReport, loaded.capture);

    const unavailableReport = accountHelpBindings({ reportParams: {} });
    resetCapture(loaded.capture);
    const unavailableMarkup = renderAccountHelpRoute(
      loaded,
      loaded.reportRoute,
      mode,
      unavailableReport,
    );
    assert.match(unavailableMarkup, /Report unavailable/);
    assertAccountHelpPalette(loaded.capture, mode, {
      expectCard: false,
      expectPrimary: false,
    });
    assertNoAccountHelpRenderActions(unavailableReport, loaded.capture);

    const reportBindings = accountHelpBindings();
    resetCapture(loaded.capture);
    const reportMarkup = renderAccountHelpRoute(
      loaded,
      loaded.reportRoute,
      mode,
      reportBindings,
    );
    assert.match(reportMarkup, /Report a safety concern/);
    for (const reason of [
      "Inappropriate display name",
      "Disruptive room behaviour",
      "Other safety concern",
    ]) {
      assert.ok(buttonByLabel(loaded.capture, reason));
    }
    const detailsInput = loaded.capture.inputProps.find(
      (props) => props.accessibilityLabel === "Optional report details",
    );
    assert.ok(detailsInput);
    assert.equal(detailsInput.autoCapitalize, "sentences");
    assert.equal(detailsInput.autoCorrect, true);
    assert.equal(detailsInput.editable, true);
    assert.equal(detailsInput.maxLength, 500);
    assert.equal(detailsInput.multiline, true);
    assert.equal(detailsInput.textAlignVertical, "top");
    const detailsStyle = flattenStyle(detailsInput.style);
    assert.equal(detailsStyle.fontSize, 15);
    assert.equal(detailsStyle.lineHeight, 21);
    assert.equal(detailsInput.placeholderTextColor, (mode === "light" ? studioLightTheme : studioDarkTheme).colors.mutedText);
    assert.equal(detailsInput.cursorColor, (mode === "light" ? studioLightTheme : studioDarkTheme).colors.primary);
    assert.equal(detailsInput.selectionColor, (mode === "light" ? studioLightTheme : studioDarkTheme).colors.primary);
    assertAccountHelpPalette(loaded.capture, mode);
    assertNoAccountHelpRenderActions(reportBindings, loaded.capture);

    const accountDependencyCalls = { cleanup: 0, delete: 0, reauthenticate: 0 };
    const inertAccountController = new AccountDeletionController({
      completeLocalCleanup: async () => {
        accountDependencyCalls.cleanup += 1;
      },
      deleteAccount: async () => {
        accountDependencyCalls.delete += 1;
        return {
        local_deletion_complete: true,
        provider_cleanup_pending: false,
        status: "account_deleted",
        };
      },
      reauthenticate: async () => {
        accountDependencyCalls.reauthenticate += 1;
      },
    });
    let summaryRetryCalls = 0;
    const accountPresentation = (
      state: AccountDeletionState,
      isPro = false,
      summaryState?: LearningSummaryLoadState,
      authStatus: "signed-in" | "suspended" = "signed-in",
    ) => {
      const beforeCalls = { ...accountDependencyCalls };
      const accountAuthState: AccountPresentationProps["authState"] =
        authStatus === "signed-in"
          ? {
              status: "signed-in",
              user: { displayName: "Presentation learner", email: null, id: ROOM_ID },
              profileBootstrap: { status: "ready" },
            }
          : {
              status: "suspended",
              user: { displayName: "Presentation learner", email: null, id: ROOM_ID },
              message: "Account is suspended.",
            };
      resetCapture(loaded.capture);
      renderToStaticMarkup(
        createElement(
          loaded.components.StudioThemeProvider,
          { mode },
          createElement(loaded.accountPresentation, {
            authState: accountAuthState,
            controller: inertAccountController,
            deletionState: state,
            isPro,
            onPasswordChange: () => undefined,
            onPasswordSubmit: () => undefined,
            password: "",
            onSignOut: () => undefined,
            learningSummaryState: summaryState,
            onLearningSummaryRetry: () => {
              summaryRetryCalls += 1;
            },
          }),
        ),
      );
      assert.deepEqual(accountDependencyCalls, beforeCalls);
    };
    accountPresentation({ status: "idle" }, true);
    assert.match(loaded.capture.textProps.map((props) => String(props.children)).join(" "), /MindMesh Pro/);
    assertAccountHelpPalette(loaded.capture, mode, { expectPrimary: false });

    accountPresentation({ status: "idle" }, false, { status: "loading", ownerId: ROOM_ID });
    assert.ok(textByChildren(loaded.capture, "Loading your practice summary..."));
    assert.equal(summaryRetryCalls, 0);

    const summary: LearningSummaryResponse = {
      status: "observed",
      session_window: { limit: 100, included: 4, truncated: true },
      topics: [
        {
          subject: "physics", topic: "forces", evidence_status: "observed",
          finished_session_count: 2, presented_question_count: 7,
          answered_attempt_count: 6, graded_attempt_count: 5,
          ungraded_attempt_count: 1, unanswered_question_count: 1,
          distinct_question_count: 5, repeat_attempt_count: 0,
          earned_marks: 4, possible_marks: 5, accuracy_on_graded_answers_percent: 80,
          full_credit_attempt_count: 4, partial_credit_attempt_count: 0,
          zero_credit_attempt_count: 1,
        },
        {
          subject: "physics", topic: "energy", evidence_status: "observed",
          finished_session_count: 2, presented_question_count: 5,
          answered_attempt_count: 5, graded_attempt_count: 5,
          ungraded_attempt_count: 0, unanswered_question_count: 0,
          distinct_question_count: 5, repeat_attempt_count: 0,
          earned_marks: 2, possible_marks: 5, accuracy_on_graded_answers_percent: 40,
          full_credit_attempt_count: 2, partial_credit_attempt_count: 0,
          zero_credit_attempt_count: 3,
        },
      ],
      strongest_topics: [{ subject: "physics", topic: "forces" }],
      weakest_topics: [{ subject: "physics", topic: "energy" }],
    };
    accountPresentation({ status: "idle" }, false, {
      status: "ready", ownerId: ROOM_ID, summary,
    });
    const summaryText = loaded.capture.textProps.map((props) => String(props.children)).join(" ");
    assert.match(summaryText, /Your retained practice history/);
    assert.match(summaryText, /Accuracy on graded answers: 80\.0% \(4\/5 marks\)/);
    assert.match(summaryText, /1 unanswered; 1 ungraded/);
    assert.match(summaryText, /Relatively stronger in this subject/);
    assert.match(summaryText, /Relatively weaker in this subject/);
    assert.match(summaryText, /Older eligible sessions are not included/);
    assert.match(summaryText, /not an AQA grade/);
    assert.doesNotMatch(summaryText, new RegExp(SESSION_ID));
    assert.equal(summaryRetryCalls, 0);
    assertAccountHelpPalette(loaded.capture, mode, { expectPrimary: false });
    invokeButton(buttonByLabel(loaded.capture, "Refresh practice summary"));
    assert.equal(summaryRetryCalls, 1);

    accountPresentation({ status: "idle" }, false, { status: "error", ownerId: ROOM_ID });
    const summaryError = textByChildren(
      loaded.capture, "Your practice summary is unavailable right now.",
    );
    assert.equal(summaryError.accessibilityRole, "alert");
    assert.ok(
      colorContrast(
        flattenStyle(summaryError.style).color as string,
        (mode === "light" ? studioLightTheme : studioDarkTheme).colors.surface,
      ) >= 4.5,
    );
    assert.equal(summaryRetryCalls, 1);
    invokeButton(buttonByLabel(loaded.capture, "Try loading practice again"));
    assert.equal(summaryRetryCalls, 2);

    accountPresentation({ status: "idle" }, false, {
      status: "ready", ownerId: ROOM_ID, summary,
    }, "suspended");
    assert.equal(
      loaded.capture.textProps.some((props) => props.children === "Your retained practice history"),
      false,
    );
    accountPresentation({ status: "confirming", confirmation: "NO", errorMessage: null });
    const confirmationInput = loaded.capture.inputProps.find(
      (props) => props.accessibilityLabel === "Type DELETE to confirm account deletion",
    );
    assert.equal(confirmationInput?.autoCapitalize, "none");
    assert.equal(confirmationInput?.autoCorrect, false);
    assert.equal(confirmationInput?.editable, true);
    assert.equal(confirmationInput?.cursorColor, (mode === "light" ? studioLightTheme : studioDarkTheme).colors.primary);
    assert.equal(confirmationInput?.selectionColor, (mode === "light" ? studioLightTheme : studioDarkTheme).colors.primary);
    assert.deepEqual(buttonByLabel(loaded.capture, "Delete my account").accessibilityState, { disabled: true });
    accountPresentation({ status: "confirming", confirmation: "DELETE", errorMessage: "Type DELETE exactly to confirm account deletion." });
    assert.ok(
      loaded.capture.textProps.some(
        (props) =>
          props.accessibilityRole === "alert" &&
          String(props.children).includes("Type DELETE exactly"),
      ),
    );
    const confirmationError = loaded.capture.textProps.find(
      (props) => props.accessibilityRole === "alert" && String(props.children).includes("Type DELETE exactly"),
    );
    assert.ok(confirmationError);
    const confirmationErrorStyle = flattenStyle(confirmationError.style);
    assert.ok(colorContrast(confirmationErrorStyle.color as string, confirmationErrorStyle.backgroundColor as string) >= 4.5);
    assert.deepEqual(buttonByLabel(loaded.capture, "Delete my account").accessibilityState, { disabled: false });
    accountPresentation({
      status: "error",
      confirmation: "DELETE",
      message: "Could not reach the MindMesh server.",
      retryable: true,
      retriedAfterReauthentication: false,
    });
    assert.ok(buttonByLabel(loaded.capture, "Try again"));
    const retryableError = loaded.capture.textProps.find(
      (props) => props.accessibilityRole === "alert" && String(props.children).includes("Could not reach"),
    );
    assert.ok(retryableError);
    const retryableErrorStyle = flattenStyle(retryableError.style);
    assert.ok(colorContrast(retryableErrorStyle.color as string, retryableErrorStyle.backgroundColor as string) >= 4.5);
    accountPresentation({
      status: "error",
      confirmation: "DELETE",
      message: "Sign in again and try again.",
      retryable: false,
      retriedAfterReauthentication: true,
    });
    assert.ok(buttonByLabel(loaded.capture, "Start again"));
    accountPresentation({
      status: "reauth_required",
      confirmation: "DELETE",
      errorMessage: "The password could not be confirmed. Check it and try again.",
    });
    const passwordInput = loaded.capture.inputProps.find(
      (props) => props.accessibilityLabel === "Current password for account deletion",
    );
    assert.ok(passwordInput);
    assert.equal(passwordInput.secureTextEntry, true);
    assert.equal(passwordInput.autoComplete, "current-password");
    assert.equal(passwordInput.editable, true);
    assert.equal(passwordInput.cursorColor, (mode === "light" ? studioLightTheme : studioDarkTheme).colors.primary);
    assert.equal(passwordInput.selectionColor, (mode === "light" ? studioLightTheme : studioDarkTheme).colors.primary);
    accountPresentation({ status: "reauthenticating", confirmation: "DELETE" });
    const checkingInput = loaded.capture.inputProps.find(
      (props) => props.accessibilityLabel === "Current password for account deletion",
    );
    assert.equal(checkingInput?.editable, false);
    assert.deepEqual(buttonByLabel(loaded.capture, "Checking password...").accessibilityState, { disabled: true });
    assert.deepEqual(buttonByLabel(loaded.capture, "Sign out").accessibilityState, { disabled: true });
    accountPresentation({ status: "deleting", confirmation: "DELETE", retriedAfterReauthentication: true });
    assert.deepEqual(buttonByLabel(loaded.capture, "Sign out").accessibilityState, { disabled: true });
    assert.match(loaded.capture.textProps.map((props) => String(props.children)).join(" "), /Deleting your account/);
    accountPresentation({ status: "deleted", providerCleanupPending: true });
    assert.equal(textByChildren(loaded.capture, "Your account has been deleted. Returning to sign in...").accessibilityRole, "alert");
    inertAccountController.dispose();

    let resolveReport: (() => void) | undefined;
    const reportRequests: Array<Record<string, unknown>> = [];
    const reportController = new ParticipantReportController({
      submitReport: async (input) => {
        reportRequests.push(input);
        await new Promise<void>((resolve) => {
          resolveReport = resolve;
        });
        return { status: "report_received" };
      },
    });
    reportController.setReason("other_safety_concern");
    reportController.setDetails("  Long but permitted safety details.  ");
    reportController.review();
    resetCapture(loaded.capture);
    renderToStaticMarkup(
      createElement(
        loaded.components.StudioThemeProvider,
        { mode },
        createElement(loaded.reportPresentation, {
          authState: {
            status: "signed-in",
            user: { displayName: "Report learner", email: null, id: ROOM_ID },
            profileBootstrap: { status: "ready" },
          },
          controller: reportController,
          displayName: "Participant",
          roomId: ROOM_ID,
          reportedUserId: MEMBER_ID,
          state: reportController.getState(),
        }),
      ),
    );
    assert.ok(buttonByLabel(loaded.capture, "Submit report"));
    invokeButton(buttonByLabel(loaded.capture, "Submit report"));
    assert.deepEqual(reportRequests, [{
      details: "Long but permitted safety details.",
      reason: "other_safety_concern",
      reported_user_id: MEMBER_ID,
      room_id: ROOM_ID,
    }]);
    resetCapture(loaded.capture);
    renderToStaticMarkup(
      createElement(
        loaded.components.StudioThemeProvider,
        { mode },
        createElement(loaded.reportPresentation, {
          authState: {
            status: "signed-in",
            user: { displayName: "Report learner", email: null, id: ROOM_ID },
            profileBootstrap: { status: "ready" },
          },
          controller: reportController,
          displayName: "Participant",
          roomId: ROOM_ID,
          reportedUserId: MEMBER_ID,
          state: reportController.getState(),
        }),
      ),
    );
    assert.deepEqual(buttonByLabel(loaded.capture, "Sending report...").accessibilityState, { disabled: true });
    resolveReport?.();
    await new Promise<void>((resolve) => setImmediate(resolve));
    resetCapture(loaded.capture);
    renderToStaticMarkup(
      createElement(
        loaded.components.StudioThemeProvider,
        { mode },
        createElement(loaded.reportPresentation, {
          authState: {
            status: "signed-in",
            user: { displayName: "Report learner", email: null, id: ROOM_ID },
            profileBootstrap: { status: "ready" },
          },
          controller: reportController,
          displayName: "Participant",
          roomId: ROOM_ID,
          reportedUserId: MEMBER_ID,
          state: reportController.getState(),
        }),
      ),
    );
    assert.equal(textByChildren(loaded.capture, "Thank you. MindMesh will review the concern. Submitting a report does not automatically punish another participant.").accessibilityLiveRegion, "polite");
    reportController.dispose();

    const reportErrorController = new ParticipantReportController({
      submitReport: async () => {
        throw new NetworkApiError();
      },
    });
    reportErrorController.setReason("inappropriate_display_name");
    reportErrorController.review();
    await reportErrorController.submit({ room_id: ROOM_ID, reported_user_id: MEMBER_ID });
    resetCapture(loaded.capture);
    renderToStaticMarkup(
      createElement(
        loaded.components.StudioThemeProvider,
        { mode },
        createElement(loaded.reportPresentation, {
          authState: {
            status: "signed-in",
            user: { displayName: "Report learner", email: null, id: ROOM_ID },
            profileBootstrap: { status: "ready" },
          },
          controller: reportErrorController,
          displayName: "Participant",
          roomId: ROOM_ID,
          reportedUserId: MEMBER_ID,
          state: reportErrorController.getState(),
        }),
      ),
    );
    assert.ok(buttonByLabel(loaded.capture, "Try again"));
    assert.ok(loaded.capture.textProps.some((props) => props.accessibilityRole === "alert"));
    reportErrorController.dispose();

    resetCapture(loaded.capture);
    renderToStaticMarkup(
      createElement(
        loaded.components.StudioThemeProvider,
        { mode },
        createElement(loaded.supportPresentation, {
          authStatus: "suspended",
          contact: { status: "configured", email: "support@example.test" },
          errorMessage: "The support email could not be opened on this device.",
          onContactSupport: () => accountBindings.actions.linkingCalls.push("mailto:support@example.test"),
          onOpenAccount: () => undefined,
          onOpenPrivacy: () => undefined,
          onSignIn: () => undefined,
        }),
      ),
    );
    assert.match(loaded.capture.textProps.map((props) => String(props.children)).join(" "), /Account deletion is available/);
    assert.ok(loaded.capture.textProps.some((props) => props.accessibilityRole === "alert"));
    invokeButton(buttonByLabel(loaded.capture, "Contact Support"));
    assert.deepEqual(accountBindings.actions.linkingCalls, ["mailto:support@example.test"]);

    resetCapture(loaded.capture);
    let selected = false;
    renderToStaticMarkup(
      createElement(
        loaded.components.StudioThemeProvider,
        { mode },
        createElement(loaded.components.StudioChoiceRow, {
          onPress: () => {
            selected = true;
          },
          selected: true,
          title: "Selected safety reason",
        }),
      ),
    );
    const selectedRow = buttonByLabel(loaded.capture, "Selected safety reason");
    const selectedRowStyle = flattenStyle(selectedRow.style);
    const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
    assert.equal(selectedRowStyle.backgroundColor, theme.colors.selectedBackground);
    const selectedLabel = textByChildren(loaded.capture, "Selected safety reason");
    const selectedLabelStyle = flattenStyle(selectedLabel.style);
    assert.equal(selectedLabelStyle.color, theme.colors.text);
    assert.ok(
      colorContrast(
        selectedLabelStyle.color as string,
        selectedRowStyle.backgroundColor as string,
      ) >= 4.5,
    );
    invokeButton(selectedRow);
    assert.equal(selected, true);

    resetCapture(loaded.capture);
    const errorTheme = mode === "light" ? studioLightTheme : studioDarkTheme;
    renderToStaticMarkup(
      createElement(
        loaded.components.StudioThemeProvider,
        { mode },
        createElement(loaded.components.StudioText, {
          accessibilityRole: "alert",
          children: "Synthetic inert error",
          style: { backgroundColor: errorTheme.colors.errorBackground },
          tone: "error",
        }),
      ),
    );
    const errorText = loaded.capture.textProps.find(
      (props) => props.children === "Synthetic inert error",
    );
    assert.ok(errorText);
    const errorStyle = flattenStyle(errorText.style);
    assert.equal(errorStyle.color, errorTheme.colors.error);
    assert.equal(errorStyle.backgroundColor, errorTheme.colors.errorBackground);
    assert.ok(colorContrast(errorTheme.colors.error, errorTheme.colors.errorBackground) >= 4.5);
  }
});

test("real Waiting Room route renders Light/Dark branches and preserves actions", async () => {
  const loaded = await loadWaitingRoute();
  const longName = "A".repeat(38);
  const baseRoom = makeRoomState({ memberName: longName });
  const longNameOfflineRoom = {
    ...baseRoom,
    participants: baseRoom.participants.map((participant, index) => ({
      ...participant,
      online: index === 0,
    })),
  };
  const hostSessionState = lobbyState(longNameOfflineRoom);
  for (const mode of ["light", "dark"] as const) {
    const host = routeBindings(hostSessionState);
    resetCapture(loaded.capture);
    loaded.routerPushes.length = 0;
    const markup = renderWaitingRoute(loaded, mode, host);
    assert.match(markup, /Room Owner/);
    assert.match(markup, /A{38}/);
    assert.match(markup, /Online/);
    assert.match(markup, /Offline/);
    assert.match(markup, /Participants/);
    assertRoutePalette(loaded.capture, mode);
    assertNoRenderActions(host, loaded.capture, loaded.routerPushes);
    assert.ok(
      loaded.capture.textProps.some(
        (props) => props.accessibilityLiveRegion === "polite",
      ),
    );
    assert.equal(
      loaded.capture.buttonProps.some(
        (props) => props.accessibilityLabel === "Report Room Owner",
      ),
      false,
    );
    const blockedStart = buttonByLabel(loaded.capture, "Start Quiz");
    assert.deepEqual(blockedStart.accessibilityState, { disabled: true });
    assert.equal(
      loaded.capture.buttonPresses.includes(blockedStart.onPress as () => void),
      false,
    );
    invokeButton(buttonByLabel(loaded.capture, `Report ${longName}`));
    assert.deepEqual(loaded.routerPushes.at(-1), {
      pathname: "/report",
      params: {
        displayName: longName,
        reportedUserId: MEMBER_ID,
        roomId: ROOM_ID,
      },
    });
  }

  for (const mode of ["light", "dark"] as const) {
    const member = routeBindings(
      lobbyState(makeRoomState({ viewerRole: "member", viewerReady: false })),
      { authUserId: MEMBER_ID },
    );
    resetCapture(loaded.capture);
    loaded.routerPushes.length = 0;
    const markup = renderWaitingRoute(loaded, mode, member);
    assert.match(markup, /Your readiness/);
    assertRoutePalette(loaded.capture, mode);
    assertNoRenderActions(member, loaded.capture, loaded.routerPushes);
    assert.equal(
      loaded.capture.buttonProps.some(
        (props) => props.accessibilityLabel === "Report Second User",
      ),
      false,
    );
    invokeButton(buttonByLabel(loaded.capture, "I'm ready"));
    assert.deepEqual(member.actions.readyValues, [true]);
    invokeButton(buttonByLabel(loaded.capture, "Report Room Owner"));
    invokeButton(buttonByLabel(loaded.capture, "Leave Room"));
    assert.equal(loaded.capture.alertCalls.at(-1)?.title, "Leave room?");
    assert.equal(loaded.capture.alertCalls.at(-1)?.buttons.at(-1)?.style, "destructive");
    const leaveConfirmation = loaded.capture.alertCalls.at(-1)?.buttons.at(-1);
    assert.equal(typeof leaveConfirmation?.onPress, "function");
    leaveConfirmation?.onPress?.();
    assert.equal(member.actions.leaveCalls, 1);
  }

  const adaptiveStatuses = [
    { status: null, version: null, button: "Generate Quiz" },
    { status: "GENERATING" as const, version: 1, button: "Generating Quiz..." },
    { status: "READY" as const, version: 2, button: null },
    { status: "FAILED" as const, version: 3, button: "Retry Generation" },
  ];
  for (const mode of ["light", "dark"] as const) {
    for (const preparation of adaptiveStatuses) {
      resetCapture(loaded.capture);
      loaded.routerPushes.length = 0;
      const adaptive = routeBindings(
        lobbyState(
          makeAdaptiveRoomState({
            preparationStatus: preparation.status,
            preparationVersion: preparation.version,
          }),
        ),
      );
      renderWaitingRoute(loaded, mode, adaptive);
      assertRoutePalette(loaded.capture, mode);
      assertNoRenderActions(adaptive, loaded.capture, loaded.routerPushes);
      if (preparation.button === null) {
        assert.equal(
          loaded.capture.buttonProps.some(
            (props) => props.accessibilityLabel === "Generate Quiz",
          ),
          false,
        );
      } else {
        const preparationButton = buttonByLabel(loaded.capture, preparation.button);
        if (preparation.status === "GENERATING") {
          assert.deepEqual(preparationButton.accessibilityState, { disabled: true });
          assert.equal(
            loaded.capture.buttonPresses.includes(
              preparationButton.onPress as () => void,
            ),
            false,
          );
        } else {
          invokeButton(preparationButton);
          assert.equal(adaptive.actions.prepareRequests.length, 1);
        }
      }
    }
  }

  for (const mode of ["light", "dark"] as const) {
    let pendingState = lobbyState(makeAdaptiveRoomState());
    pendingState = sessionReducer(pendingState, {
      type: "PREPARE_COMMAND_STARTED",
      generation: 1,
      requestId: "44444444-4444-4444-8444-444444444444",
    });
    const pending = routeBindings(pendingState);
    resetCapture(loaded.capture);
    loaded.routerPushes.length = 0;
    renderWaitingRoute(loaded, mode, pending);
    assertRoutePalette(loaded.capture, mode);
    assertNoRenderActions(pending, loaded.capture, loaded.routerPushes);
    const pendingButton = buttonByLabel(loaded.capture, "Generating Quiz...");
    assert.deepEqual(pendingButton.accessibilityState, { disabled: true });
    assert.equal(
      loaded.capture.buttonPresses.includes(pendingButton.onPress as () => void),
      false,
    );
  }

  for (const mode of ["light", "dark"] as const) {
    const memberFailed = routeBindings(
      lobbyState(
        makeAdaptiveRoomState({
          preparationStatus: "FAILED",
          preparationVersion: 3,
          viewerRole: "member",
        }),
      ),
      { authUserId: MEMBER_ID },
    );
    resetCapture(loaded.capture);
    loaded.routerPushes.length = 0;
    const markup = renderWaitingRoute(loaded, mode, memberFailed);
    assert.match(markup, /Quiz generation failed/);
    assertRoutePalette(loaded.capture, mode);
    assertNoRenderActions(memberFailed, loaded.capture, loaded.routerPushes);
    assert.equal(
      loaded.capture.buttonProps.some(
        (props) => props.accessibilityLabel === "Retry Generation",
      ),
      false,
    );
    assert.equal(
      loaded.capture.buttonProps.some(
        (props) => props.accessibilityLabel === "Generate Quiz",
      ),
      false,
    );
  }

  resetCapture(loaded.capture);
  const errorState: SessionState = {
    ...hostSessionState,
    connectionStage: "disconnected",
    lastError: new RealtimeNetworkError(),
    phase: "recoverable-error",
    roomId: ROOM_ID,
  };
  const errorBindings = routeBindings(errorState);
  const errorMarkup = renderWaitingRoute(loaded, "dark", errorBindings);
  assert.match(errorMarkup, /Connection paused/);
  assert.match(errorMarkup, /role="alert"/);
  assert.match(errorMarkup, /Retry connection/);
  assert.equal(
    loaded.capture.textProps.some((props) => props.accessibilityRole === "alert"),
    true,
  );
  invokeButton(buttonByLabel(loaded.capture, "Retry connection"));
  assert.equal(errorBindings.actions.retryCalls, 1);

  resetCapture(loaded.capture);
  const unavailableBindings = routeBindings({
    ...initialSessionState,
    connectionStage: "disconnected",
    lastError: new RealtimeNetworkError(),
    phase: "recoverable-error",
    roomId: ROOM_ID,
  });
  const unavailableMarkup = renderWaitingRoute(
    loaded,
    "dark",
    unavailableBindings,
  );
  assert.match(unavailableMarkup, /Room connection unavailable/);
  invokeButton(buttonByLabel(loaded.capture, "Retry"));
  assert.equal(unavailableBindings.actions.retryCalls, 1);

  resetCapture(loaded.capture);
  const restoringMarkup = renderWaitingRoute(
    loaded,
    "light",
    routeBindings(hostSessionState, { authStatus: "initializing" }),
  );
  assert.match(restoringMarkup, /Restoring your session/);
  const openingMarkup = renderWaitingRoute(
    loaded,
    "light",
    routeBindings(hostSessionState, { roomParam: "different-room" }),
  );
  assert.match(openingMarkup, /Opening your current room/);

  resetCapture(loaded.capture);
  const closeBindings = routeBindings(lobbyState(makeRoomState()));
  renderWaitingRoute(loaded, "dark", closeBindings);
  invokeButton(buttonByLabel(loaded.capture, "Close Room"));
  const closeAlert = loaded.capture.alertCalls.at(-1);
  assert.equal(closeAlert?.title, "Close room?");
  assert.equal(closeAlert?.buttons.at(-1)?.style, "destructive");
  closeAlert?.buttons.at(-1)?.onPress?.();
  assert.equal(closeBindings.actions.closeCalls, 1);

  const legacy = (await import("../components/PlayerRow")) as {
    PlayerRow: React.ComponentType<{
      onReport?: () => void;
      participant: {
        display_name: string;
        online: boolean;
        presenceLabel: "Online" | "Offline";
        readinessLabel: "Ready automatically" | "Ready" | "Not ready";
        roleLabel: "Host" | "Member";
        user_id: string;
      };
    }>;
  };
  resetCapture(loaded.capture);
  const legacyMarkup = renderToStaticMarkup(
    createElement(legacy.PlayerRow, {
      onReport: () => undefined,
      participant: {
        display_name: "Legacy participant",
        online: true,
        presenceLabel: "Online",
        readinessLabel: "Ready",
        roleLabel: "Member",
        user_id: MEMBER_ID,
      },
    }),
  );
  assert.match(legacyMarkup, /Legacy participant/);
  assert.equal(
    loaded.capture.buttonProps.some(
      (props) => props.accessibilityLabel === "Report Legacy participant",
    ),
    true,
  );
});

test("real Quiz route preserves typed states, private reveal, and actions in both palettes", async () => {
  const loaded = await loadQuizRoute();
  const openState = quizStateFromSnapshot(makeOpenSnapshot());
  const adaptiveNumericalState = quizStateFromSnapshot(
    makeOpenSnapshot({
      roomState: makeAdaptiveRoomState(),
      questionType: "NUMERICAL",
      maxMarks: 2,
    }),
  );
  const adaptiveWrittenState = quizStateFromSnapshot(
    makeOpenSnapshot({
      roomState: makeAdaptiveRoomState(),
      questionType: "WRITTEN",
      maxMarks: 4,
      originalExtract: "A short original extract about energy transfer.",
    }),
  );
  const adaptiveNumericalSubmittedState = quizStateFromSnapshot(
    makeOpenSnapshot({
      roomState: makeAdaptiveRoomState(),
      questionType: "NUMERICAL",
      answerText: "-3.50 m/s",
      gradingStatus: "GRADED",
      maxMarks: 2,
    }),
  );
  const longWrittenAnswer = "A".repeat(1000);
  const adaptiveWrittenSubmittedState = quizStateFromSnapshot(
    makeOpenSnapshot({
      roomState: makeAdaptiveRoomState(),
      questionType: "WRITTEN",
      answerText: longWrittenAnswer,
      gradingStatus: "GRADED",
      maxMarks: 4,
    }),
  );

  for (const mode of ["light", "dark"] as const) {
    resetCapture(loaded.capture);
    const opening = quizRouteBindings(openState, { roomParam: "different-room" });
    const openingMarkup = renderQuizRoute(loaded, mode, opening);
    assert.match(openingMarkup, /Opening the current quiz/);
    assert.doesNotMatch(openingMarkup, /Open drawing workspace/);
    assertNoQuizRenderActions(opening, loaded.capture);
    assert.ok(
      loaded.capture.viewProps
        .map((props) => flattenStyle(props.style))
        .some((style) => {
          const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
          return style.backgroundColor === theme.colors.background;
        }),
    );

    resetCapture(loaded.capture);
    const connectionError: SessionState = {
      ...openState,
      lastError: new RealtimeNetworkError(),
      phase: "recoverable-error",
    };
    const connectionBindings = quizRouteBindings(connectionError);
    const connectionMarkup = renderQuizRoute(loaded, mode, connectionBindings);
    assert.match(connectionMarkup, /Could not reach the MindMesh server/);
    assert.match(connectionMarkup, /Retry connection/);
    assert.ok(
      loaded.capture.textProps.some(
        (props) =>
          props.accessibilityRole === "alert" &&
          typeof props.children === "string" &&
          props.children.includes("Could not reach the MindMesh server"),
      ),
    );
    assertQuizPalette(loaded.capture, mode, { expectButton: true });
    assertNoQuizRenderActions(connectionBindings, loaded.capture);
    invokeButton(buttonByLabel(loaded.capture, "Retry connection"));
    assert.equal(connectionBindings.actions.retryCalls, 1);

    resetCapture(loaded.capture);
    const openBindings = quizRouteBindings(openState);
    const openMarkup = renderQuizRoute(loaded, mode, openBindings);
    assert.match(openMarkup, /Submit Answer/);
    assert.match(openMarkup, /What is the SI unit of force/);
    assert.match(openMarkup, /Open drawing workspace/);
    assert.match(openMarkup, /They are not submitted or marked/);
    assert.deepEqual(
      buttonByLabel(loaded.capture, "Open drawing workspace").accessibilityState,
      { disabled: false },
    );
    assertQuizPalette(loaded.capture, mode, { expectButton: true });
    assertNoQuizRenderActions(openBindings, loaded.capture);
    assert.equal(
      loaded.capture.buttonProps.filter(
        (props) => props.accessibilityRole === "radio",
      ).length,
      2,
    );
    assert.equal(
      loaded.capture.buttonProps.some(
        (props) => props.accessibilityLabel === "Joule" &&
          recordObject(props.accessibilityState)?.checked === true,
      ),
      false,
    );
    assert.deepEqual(buttonByLabel(loaded.capture, "Submit Answer").accessibilityState, {
      disabled: true,
    });
    assert.equal(
      typeof buttonByLabel(loaded.capture, "Newton").onPress,
      "function",
    );

    resetCapture(loaded.capture);
    let submittingState = quizStateFromSnapshot(makeOpenSnapshot());
    submittingState = sessionReducer(submittingState, {
      type: "ANSWER_COMMAND_STARTED",
      generation: 1,
      sessionId: SESSION_ID,
      sessionQuestionId: QUESTION_ID,
      selectedOptionId: "newton",
      answerText: null,
    });
    const submittingBindings = quizRouteBindings(submittingState);
    const submittingMarkup = renderQuizRoute(loaded, mode, submittingBindings);
    assert.match(submittingMarkup, /Submitting/);
    assertQuizPalette(loaded.capture, mode, { expectButton: true, expectSelected: true });
    assertNoQuizRenderActions(submittingBindings, loaded.capture);
    assert.deepEqual(buttonByLabel(loaded.capture, "Newton").accessibilityState, {
      checked: true,
      disabled: true,
    });

    resetCapture(loaded.capture);
    const confirmedBindings = quizRouteBindings(
      quizStateFromSnapshot(makeOpenSnapshot({ selectedOptionId: "newton" })),
    );
    const confirmedMarkup = renderQuizRoute(loaded, mode, confirmedBindings);
    assert.match(confirmedMarkup, /Answer submitted/);
    assertQuizPalette(loaded.capture, mode, { expectButton: true, expectSelected: true });
    assertNoQuizRenderActions(confirmedBindings, loaded.capture);
    assert.deepEqual(buttonByLabel(loaded.capture, "Answer submitted").accessibilityState, {
      disabled: true,
    });

    resetCapture(loaded.capture);
    const expiredSnapshot = makeOpenSnapshot();
    if (expiredSnapshot.status !== "QUESTION_OPEN") {
      throw new Error("Expected an open quiz fixture.");
    }
    const expiredState = quizStateFromSnapshot({
      ...expiredSnapshot,
      closes_at: expiredSnapshot.server_time,
    });
    const expiredBindings = quizRouteBindings(expiredState);
    const expiredMarkup = renderQuizRoute(loaded, mode, expiredBindings);
    assert.match(expiredMarkup, /answer window has closed/i);
    assertQuizPalette(loaded.capture, mode, { expectButton: true });
    assertNoQuizRenderActions(expiredBindings, loaded.capture);
    assert.deepEqual(buttonByLabel(loaded.capture, "Submit Answer").accessibilityState, {
      disabled: true,
    });

    resetCapture(loaded.capture);
    const numericalBindings = quizRouteBindings(adaptiveNumericalState);
    const numericalMarkup = renderQuizRoute(loaded, mode, numericalBindings);
    assert.match(numericalMarkup, /Numerical answer/);
    assert.match(numericalMarkup, /Type the value with its unit/);
    assertQuizPalette(loaded.capture, mode, { expectButton: true });
    assertNoQuizRenderActions(numericalBindings, loaded.capture);
    const numericalInput = loaded.capture.inputProps.at(-1);
    assert.equal(numericalInput?.keyboardType, "numbers-and-punctuation");
    assert.equal(numericalInput?.maxLength, 64);
    assert.equal(numericalInput?.editable, true);
    assert.equal(numericalInput?.autoCorrect, false);
    assert.equal(typeof numericalInput?.onChangeText, "function");
    assert.equal(numericalInput?.placeholder, "Type the value with its unit");
    assertQuizInputPalette(numericalInput, mode);
    (numericalInput?.onChangeText as ((value: string) => void) | undefined)?.("42 N");
    assert.equal(numericalBindings.actions.submitTexts.length, 0);

    resetCapture(loaded.capture);
    let numericalSubmitting = quizStateFromSnapshot(
      makeOpenSnapshot({
        roomState: makeAdaptiveRoomState(),
        questionType: "NUMERICAL",
        maxMarks: 2,
      }),
    );
    numericalSubmitting = sessionReducer(numericalSubmitting, {
      type: "ANSWER_COMMAND_STARTED",
      generation: 1,
      sessionId: SESSION_ID,
      sessionQuestionId: QUESTION_ID,
      selectedOptionId: null,
      answerText: "-3.50 m/s",
    });
    const numericalSubmittingBindings = quizRouteBindings(numericalSubmitting);
    const numericalSubmittingMarkup = renderQuizRoute(
      loaded,
      mode,
      numericalSubmittingBindings,
    );
    assert.match(numericalSubmittingMarkup, /Submitting/);
    assertNoQuizRenderActions(numericalSubmittingBindings, loaded.capture);
    const numericalSubmittingInput = loaded.capture.inputProps.at(-1);
    assert.equal(numericalSubmittingInput?.value, "-3.50 m/s");
    assert.equal(numericalSubmittingInput?.editable, false);
    assertQuizInputPalette(numericalSubmittingInput, mode);

    resetCapture(loaded.capture);
    const numericalConfirmedBindings = quizRouteBindings(
      adaptiveNumericalSubmittedState,
    );
    const numericalConfirmedMarkup = renderQuizRoute(
      loaded,
      mode,
      numericalConfirmedBindings,
    );
    assert.match(numericalConfirmedMarkup, /Answer submitted/);
    assertNoQuizRenderActions(numericalConfirmedBindings, loaded.capture);
    const numericalConfirmedInput = loaded.capture.inputProps.at(-1);
    assert.equal(numericalConfirmedInput?.value, "-3.50 m/s");
    assert.equal(numericalConfirmedInput?.editable, false);
    assertQuizInputPalette(numericalConfirmedInput, mode);

    resetCapture(loaded.capture);
    const writtenBindings = quizRouteBindings(adaptiveWrittenState);
    const writtenMarkup = renderQuizRoute(loaded, mode, writtenBindings);
    assert.match(writtenMarkup, /SOURCE EXTRACT/);
    assert.match(writtenMarkup, /Written answer/);
    assert.match(writtenMarkup, /0\/1000/);
    assertQuizPalette(loaded.capture, mode, { expectButton: true });
    assertNoQuizRenderActions(writtenBindings, loaded.capture);
    const writtenInput = loaded.capture.inputProps.at(-1);
    assert.equal(writtenInput?.autoCorrect, true);
    assert.equal(writtenInput?.multiline, true);
    assert.equal(writtenInput?.numberOfLines, 5);
    assert.equal(writtenInput?.textAlignVertical, "top");
    assert.equal(writtenInput?.maxLength, 1000);
    assert.equal(writtenInput?.editable, true);
    assert.equal(writtenInput?.placeholder, "Explain in your own words");
    assertQuizInputPalette(writtenInput, mode);
    assert.doesNotMatch(writtenMarkup, /MARKING POINTS AWARDED|STILL MISSING|WHY THIS ANSWER/);
    assert.doesNotMatch(writtenMarkup, /Force is measured in newtons\.|Heat flows\.|Room Owner|B{38}/);

    resetCapture(loaded.capture);
    let writtenSubmitting = quizStateFromSnapshot(
      makeOpenSnapshot({
        roomState: makeAdaptiveRoomState(),
        questionType: "WRITTEN",
        originalExtract: "A short original extract about energy transfer.",
        maxMarks: 4,
      }),
    );
    writtenSubmitting = sessionReducer(writtenSubmitting, {
      type: "ANSWER_COMMAND_STARTED",
      generation: 1,
      sessionId: SESSION_ID,
      sessionQuestionId: QUESTION_ID,
      selectedOptionId: null,
      answerText: longWrittenAnswer,
    });
    const writtenSubmittingBindings = quizRouteBindings(writtenSubmitting);
    const writtenSubmittingMarkup = renderQuizRoute(
      loaded,
      mode,
      writtenSubmittingBindings,
    );
    assert.match(writtenSubmittingMarkup, /Submitting/);
    assertNoQuizRenderActions(writtenSubmittingBindings, loaded.capture);
    const writtenSubmittingInput = loaded.capture.inputProps.at(-1);
    assert.equal(writtenSubmittingInput?.value, longWrittenAnswer);
    assert.equal(writtenSubmittingInput?.editable, false);
    assertQuizInputPalette(writtenSubmittingInput, mode);
    assert.ok(
      loaded.capture.viewProps
        .map((props) => flattenStyle(props.style))
        .some(
          (style) =>
            style.backgroundColor ===
            (mode === "light"
              ? studioLightTheme.colors.selectedBackground
              : studioDarkTheme.colors.selectedBackground),
        ),
      `${mode} source extract did not receive the selected-surface palette`,
    );

    resetCapture(loaded.capture);
    const writtenConfirmedBindings = quizRouteBindings(
      adaptiveWrittenSubmittedState,
    );
    const writtenConfirmedMarkup = renderQuizRoute(
      loaded,
      mode,
      writtenConfirmedBindings,
    );
    assert.match(writtenConfirmedMarkup, /Answer submitted/);
    assertNoQuizRenderActions(writtenConfirmedBindings, loaded.capture);
    const writtenConfirmedInput = loaded.capture.inputProps.at(-1);
    assert.equal(writtenConfirmedInput?.value, longWrittenAnswer);
    assert.equal(writtenConfirmedInput?.editable, false);
    assertQuizInputPalette(writtenConfirmedInput, mode);

    resetCapture(loaded.capture);
    const expiredNumericalSnapshot = makeOpenSnapshot({
      roomState: makeAdaptiveRoomState(),
      questionType: "NUMERICAL",
      maxMarks: 2,
    });
    if (expiredNumericalSnapshot.status !== "QUESTION_OPEN") {
      throw new Error("Expected an open numerical fixture.");
    }
    const expiredNumerical = quizRouteBindings(
      quizStateFromSnapshot({
        ...expiredNumericalSnapshot,
        closes_at: expiredNumericalSnapshot.server_time,
      }),
    );
    const expiredNumericalMarkup = renderQuizRoute(loaded, mode, expiredNumerical);
    assert.match(expiredNumericalMarkup, /answer window has closed/i);
    assertNoQuizRenderActions(expiredNumerical, loaded.capture);
    const expiredNumericalInput = loaded.capture.inputProps.at(-1);
    assert.equal(expiredNumericalInput?.value, "");
    assert.equal(expiredNumericalInput?.editable, false);
    assertQuizInputPalette(expiredNumericalInput, mode);

    resetCapture(loaded.capture);
    const expiredWrittenSnapshot = makeOpenSnapshot({
      roomState: makeAdaptiveRoomState(),
      questionType: "WRITTEN",
      maxMarks: 4,
    });
    if (expiredWrittenSnapshot.status !== "QUESTION_OPEN") {
      throw new Error("Expected an open written fixture.");
    }
    const expiredWritten = quizRouteBindings(
      quizStateFromSnapshot({
        ...expiredWrittenSnapshot,
        closes_at: expiredWrittenSnapshot.server_time,
      }),
    );
    const expiredWrittenMarkup = renderQuizRoute(loaded, mode, expiredWritten);
    assert.match(expiredWrittenMarkup, /answer window has closed/i);
    assertNoQuizRenderActions(expiredWritten, loaded.capture);
    const expiredWrittenInput = loaded.capture.inputProps.at(-1);
    assert.equal(expiredWrittenInput?.value, "");
    assert.equal(expiredWrittenInput?.editable, false);
    assertQuizInputPalette(expiredWrittenInput, mode);

    resetCapture(loaded.capture);
    const gradingHost = quizRouteBindings(
      quizStateFromSnapshot(
        makeGradingSnapshot({
          roomState: makeAdaptiveRoomState({ viewerRole: "host" }),
          questionType: "WRITTEN",
          selectedOptionId: null,
          answerText: "Heat flows.",
          gradingStatus: "UNAVAILABLE",
          gradingRetryNeeded: true,
        }),
      ),
    );
    const gradingHostMarkup = renderQuizRoute(loaded, mode, gradingHost);
    assert.match(gradingHostMarkup, /Marking unavailable/);
    assert.match(gradingHostMarkup, /Your answer: Heat flows/);
    assert.match(gradingHostMarkup, /Retry Marking/);
    assert.ok(
      loaded.capture.textProps.some(
        (props) =>
          props.accessibilityLiveRegion === "polite" &&
          props.children === "Marking unavailable",
      ),
    );
    assert.equal(loaded.capture.inputProps.length, 0);
    assert.doesNotMatch(gradingHostMarkup, /Submit Answer|Submitting|Numerical answer|Written answer/);
    assertQuizPalette(loaded.capture, mode, { expectButton: false });
    assertNoQuizRenderActions(gradingHost, loaded.capture);
    invokeButton(buttonByLabel(loaded.capture, "Retry Marking"));
    assert.equal(gradingHost.actions.retryGradingCalls, 1);

    resetCapture(loaded.capture);
    const gradingMember = quizRouteBindings(
      quizStateFromSnapshot(
        makeGradingSnapshot({
          roomState: makeAdaptiveRoomState({ viewerRole: "member" }),
          selectedOptionId: null,
          answerText: null,
          gradingStatus: "PENDING",
          gradingRetryNeeded: true,
        }),
      ),
      { authUserId: MEMBER_ID },
    );
    const gradingMemberMarkup = renderQuizRoute(loaded, mode, gradingMember);
    assert.match(gradingMemberMarkup, /No answer submitted/);
    assert.match(gradingMemberMarkup, /host can retry marking/);
    assert.doesNotMatch(gradingMemberMarkup, /Retry Marking/);
    assert.ok(
      loaded.capture.textProps.some(
        (props) =>
          props.accessibilityLiveRegion === "polite" &&
          props.children === "Marking in progress",
      ),
    );
    assert.equal(loaded.capture.inputProps.length, 0);
    assert.doesNotMatch(gradingMemberMarkup, /Submit Answer|Submitting|Numerical answer|Written answer/);
    assertQuizPalette(loaded.capture, mode);
    assertNoQuizRenderActions(gradingMember, loaded.capture);

    resetCapture(loaded.capture);
    const adaptiveRevealSnapshot = makeRevealSnapshot({
      roomState: makeAdaptiveRoomState(),
      questionType: "WRITTEN",
      maxMarks: 4,
      selectedOptionId: null,
      answerText: "A".repeat(1000),
      earnedMarks: 2,
      feedback: {
        summary: "Mention energy transfer.",
        awarded: [{ id: "c1", marks: 2, explanation: "Named vibration." }],
        missing: [{ id: "c2", marks: 2, explanation: "Link to energy." }],
        awarded_count: 1,
        total_criteria: 2,
      },
      awardedCriterionIds: ["c1"],
    });
    const adaptiveReveal = quizRouteBindings(
      quizStateFromSnapshot({
        ...adaptiveRevealSnapshot,
        leaderboard: [
          {
            user_id: ROOM_ID,
            display_name: "Room Owner",
            total_points: 0,
            correct_answers: 0,
            rank: 1,
            earned_marks: 2,
            total_available_marks: 4,
          },
          {
            user_id: MEMBER_ID,
            display_name: "B".repeat(38),
            total_points: 0,
            correct_answers: 0,
            rank: 1,
            earned_marks: 2,
            total_available_marks: 4,
          },
        ],
      }),
    );
    const adaptiveRevealMarkup = renderQuizRoute(loaded, mode, adaptiveReveal);
    assert.match(adaptiveRevealMarkup, /Partially correct/);
    assert.match(adaptiveRevealMarkup, /MARKING POINTS AWARDED/);
    assert.match(adaptiveRevealMarkup, /STILL MISSING/);
    assert.match(adaptiveRevealMarkup, /WHY THIS ANSWER/);
    assert.match(adaptiveRevealMarkup, /B{38}/);
    assertQuizPalette(loaded.capture, mode, { expectSelected: true });
    assertNoQuizRenderActions(adaptiveReveal, loaded.capture);
    assert.equal(loaded.capture.inputProps.length, 0);
    assert.doesNotMatch(adaptiveRevealMarkup, /Submit Answer|Submitting|Numerical answer|Written answer/);
    assert.ok(
      loaded.capture.textProps.some(
        (props) =>
          props.accessibilityLiveRegion === "polite" &&
          props.children === "Partially correct",
      ),
    );

    resetCapture(loaded.capture);
    const adaptiveFullReveal = quizRouteBindings(
      quizStateFromSnapshot(
        makeRevealSnapshot({
          roomState: makeAdaptiveRoomState(),
          questionType: "WRITTEN",
          maxMarks: 4,
          answerText: "A complete explanation of energy transfer.",
          earnedMarks: 4,
          feedback: {
            summary: "Complete explanation.",
            awarded: [{ id: "c1", marks: 4, explanation: "Complete." }],
            missing: [],
            awarded_count: 1,
            total_criteria: 1,
          },
          awardedCriterionIds: ["c1"],
        }),
      ),
    );
    const adaptiveFullRevealMarkup = renderQuizRoute(
      loaded,
      mode,
      adaptiveFullReveal,
    );
    assert.match(adaptiveFullRevealMarkup, /Correct/);
    assert.match(adaptiveFullRevealMarkup, /A complete explanation of energy transfer/);
    assertQuizPalette(loaded.capture, mode, { expectSelected: true });
    assertNoQuizRenderActions(adaptiveFullReveal, loaded.capture);
    assert.equal(loaded.capture.inputProps.length, 0);
    assert.doesNotMatch(adaptiveFullRevealMarkup, /Submit Answer|Submitting|Numerical answer|Written answer/);
    assert.ok(
      loaded.capture.textProps.some(
        (props) =>
          props.accessibilityLiveRegion === "polite" &&
          props.children === "Correct",
      ),
    );

    resetCapture(loaded.capture);
    const adaptiveAnsweredZeroReveal = quizRouteBindings(
      quizStateFromSnapshot(
        makeRevealSnapshot({
          roomState: makeAdaptiveRoomState(),
          questionType: "WRITTEN",
          maxMarks: 4,
          answerText: "No measurable transfer.",
          earnedMarks: 0,
          feedback: {
            summary: "No credit awarded.",
            awarded: [],
            missing: [{ id: "c1", marks: 4, explanation: "Explain transfer." }],
            awarded_count: 0,
            total_criteria: 1,
          },
          awardedCriterionIds: [],
        }),
      ),
    );
    const adaptiveAnsweredZeroMarkup = renderQuizRoute(
      loaded,
      mode,
      adaptiveAnsweredZeroReveal,
    );
    assert.match(adaptiveAnsweredZeroMarkup, /Incorrect/);
    assert.match(adaptiveAnsweredZeroMarkup, /No measurable transfer/);
    assert.doesNotMatch(adaptiveAnsweredZeroMarkup, /No answer submitted/);
    assertQuizPalette(loaded.capture, mode, { expectSelected: true });
    assertNoQuizRenderActions(adaptiveAnsweredZeroReveal, loaded.capture);
    assert.equal(loaded.capture.inputProps.length, 0);
    assert.doesNotMatch(adaptiveAnsweredZeroMarkup, /Submit Answer|Submitting|Numerical answer|Written answer/);
    assert.ok(
      loaded.capture.textProps.some(
        (props) =>
          props.accessibilityLiveRegion === "polite" &&
          props.children === "Incorrect",
      ),
    );

    resetCapture(loaded.capture);
    const legacyRevealSnapshot = makeRevealSnapshot({ earnedMarks: null });
    if (
      legacyRevealSnapshot.status !== "QUESTION_REVEAL" ||
      legacyRevealSnapshot.viewer_submission === null
    ) {
      throw new Error("Expected a legacy reveal fixture.");
    }
    const legacyReveal = quizRouteBindings(
      quizStateFromSnapshot({
        ...legacyRevealSnapshot,
        viewer_submission: {
          ...legacyRevealSnapshot.viewer_submission,
          earned_marks: null,
          is_correct: true,
          points: 100,
        },
      }),
    );
    const legacyRevealMarkup = renderQuizRoute(loaded, mode, legacyReveal);
    assert.match(legacyRevealMarkup, /100 points/);
    assert.match(legacyRevealMarkup, /Correct answer/);
    assertQuizPalette(loaded.capture, mode, { expectSelected: true });
    assertNoQuizRenderActions(legacyReveal, loaded.capture);
    assert.equal(loaded.capture.inputProps.length, 0);
    assert.doesNotMatch(legacyRevealMarkup, /Submit Answer|Submitting|Numerical answer|Written answer/);

    resetCapture(loaded.capture);
    const noAnswerReveal = quizRouteBindings(
      quizStateFromSnapshot(
        makeRevealSnapshot({
          selectedOptionId: null,
          answerText: null,
          earnedMarks: 0,
        }),
      ),
    );
    const noAnswerMarkup = renderQuizRoute(loaded, mode, noAnswerReveal);
    assert.match(noAnswerMarkup, /No answer submitted/);
    assertQuizPalette(loaded.capture, mode);
    assertNoQuizRenderActions(noAnswerReveal, loaded.capture);
    assert.equal(loaded.capture.inputProps.length, 0);
    assert.ok(
      loaded.capture.textProps.some(
        (props) =>
          props.accessibilityLiveRegion === "polite" &&
          props.children === "No answer submitted",
      ),
    );

    const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
    for (const viewerRole of ["host", "member"] as const) {
      const forcesRoomState = {
        ...makeAdaptiveRoomState({ viewerRole }),
        quiz_subject: "physics",
        quiz_topic: "forces",
      };
      const authUserId = viewerRole === "host" ? ROOM_ID : MEMBER_ID;
      for (const unrevealedSnapshot of [
        makeOpenSnapshot({ roomState: forcesRoomState }),
        makeGradingSnapshot({ roomState: forcesRoomState }),
      ]) {
        resetCapture(loaded.capture);
        const bindings = quizRouteBindings(
          quizStateFromSnapshot(unrevealedSnapshot),
          { authUserId },
        );
        const markup = renderQuizRoute(loaded, mode, bindings);
        assert.doesNotMatch(markup, /Topic Concept Illustration|Forces on a Surface/);
        assert.equal(
          loaded.capture.viewProps.some(
            (props) => props.testID === "visual-learning-card",
          ),
          false,
        );
        assertNoQuizRenderActions(bindings, loaded.capture);
      }

      resetCapture(loaded.capture);
      const revealedBindings = quizRouteBindings(
        quizStateFromSnapshot(
          makeRevealSnapshot({ roomState: forcesRoomState }),
        ),
        { authUserId },
      );
      const revealedMarkup = renderQuizRoute(loaded, mode, revealedBindings);
      assert.match(revealedMarkup, /Topic Concept Illustration/);
      assert.match(revealedMarkup, /Forces on a Surface/);
      assert.match(revealedMarkup, /not specific to this question/);
      const visualCard = loaded.capture.viewProps.find(
        (props) => props.testID === "visual-learning-card",
      );
      assert.ok(visualCard);
      assert.equal(flattenStyle(visualCard.style).backgroundColor, theme.colors.surface);
      assert.equal(flattenStyle(visualCard.style).borderColor, theme.colors.border);
      assert.ok(colorContrast(theme.colors.text, theme.colors.surface) >= 4.5);
      assert.ok(colorContrast(theme.colors.primary, theme.colors.primarySoft) >= 4.5);
      assertNoQuizRenderActions(revealedBindings, loaded.capture);
    }

    resetCapture(loaded.capture);
    const geometryRoomState = {
      ...makeAdaptiveRoomState(),
      quiz_subject: "mathematics",
      quiz_topic: "geometry",
    };
    const geometryBindings = quizRouteBindings(
      quizStateFromSnapshot(makeRevealSnapshot({ roomState: geometryRoomState })),
    );
    const geometryMarkup = renderQuizRoute(loaded, mode, geometryBindings);
    assert.match(geometryMarkup, /Square-Based Pyramid/);
    assert.ok(
      loaded.capture.buttonProps.some(
        (props) => props.accessibilityLabel === "Rotate Left",
      ),
    );
    assertNoQuizRenderActions(geometryBindings, loaded.capture);
  }
});

test("real Results route and review presentation preserve private states in both palettes", async () => {
  const loaded = await loadResultsRoute();
  const longExtract = "Source extract about energy transfer. ".repeat(18);
  const longWrittenAnswer = "A".repeat(1000);
  const reviewResponse = {
    session_id: SESSION_ID,
    room_id: ROOM_ID,
    viewer_user_id: ROOM_ID,
    total_earned_marks: 5,
    total_available_marks: 16,
    questions: [
      {
        session_question_id: QUESTION_ID,
        position: 0,
        question_type: "MULTIPLE_CHOICE",
        prompt: "What is the SI unit of force?",
        max_marks: 1,
        options: [
          { id: "joule", label: "Joule" },
          { id: "newton", label: "Newton" },
        ],
        correct_option_id: "newton",
        worked_explanation: "Force is measured in newtons.",
        original_extract: null,
        selected_option_id: "newton",
        answer_text: null,
        earned_marks: 1,
        feedback: {},
        awarded_criterion_ids: [],
      },
      {
        session_question_id: "33333333-3333-4333-8333-444444444444",
        position: 1,
        question_type: "NUMERICAL",
        prompt: "Calculate the force.",
        max_marks: 3,
        options: [],
        correct_option_id: null,
        worked_explanation: "Use force equals mass times acceleration.",
        original_extract: null,
        selected_option_id: null,
        answer_text: "12 N",
        earned_marks: 2,
        feedback: {
          value_awarded: true,
          unit_awarded: false,
          earned_marks: 2,
          max_marks: 3,
        },
        awarded_criterion_ids: [],
      },
      {
        session_question_id: "33333333-3333-4333-8333-555555555555",
        position: 2,
        question_type: "WRITTEN",
        prompt: "Explain energy transfer.",
        max_marks: 4,
        options: [],
        correct_option_id: null,
        worked_explanation: "Energy moves between stores.",
        original_extract: longExtract,
        selected_option_id: null,
        answer_text: longWrittenAnswer,
        earned_marks: 2,
        feedback: {
          summary: "Mention energy transfer.",
          awarded: [{ id: "c1", marks: 2, explanation: "Named transfer." }],
          missing: [{ id: "c2", marks: 2, explanation: "Link the stores." }],
          awarded_count: 1,
          total_criteria: 2,
        },
        awarded_criterion_ids: ["c1"],
      },
      {
        session_question_id: "33333333-3333-4333-8333-666666666666",
        position: 3,
        question_type: "WRITTEN",
        prompt: "Describe the source.",
        max_marks: 4,
        options: [],
        correct_option_id: null,
        worked_explanation: "Use the evidence in the source.",
        original_extract: null,
        selected_option_id: null,
        answer_text: "I am unsure.",
        earned_marks: 0,
        feedback: {},
        awarded_criterion_ids: [],
      },
      {
        session_question_id: "33333333-3333-4333-8333-777777777777",
        position: 4,
        question_type: "WRITTEN",
        prompt: "Explain conduction.",
        max_marks: 4,
        options: [],
        correct_option_id: null,
        worked_explanation: "Conduction needs particles.",
        original_extract: null,
        selected_option_id: null,
        answer_text: null,
        earned_marks: 0,
        feedback: {},
        awarded_criterion_ids: [],
      },
    ],
  };
  const reviewPresentation = buildReviewPresentation(
    parseSessionReviewResponse(reviewResponse),
  );
  assert.deepEqual(
    reviewPresentation.questions.map((question) => [
      question.questionTypeLabel,
      question.marksLabel,
      question.ownResponseLabel,
    ]),
    [
      ["Multiple choice", "1/1 marks", "Newton"],
      ["Numerical", "2/3 marks", "12 N"],
      ["Written", "2/4 marks", longWrittenAnswer],
      ["Written", "0/4 marks", "I am unsure."],
      ["Written", "0/4 marks", null],
    ],
  );
  const basicReviewPresentation = {
    ...reviewPresentation,
    questions: reviewPresentation.questions.map((question, index) =>
      index === 1
        ? {
            ...question,
            enrichedFeedback: null,
            feedbackSummary: "Basic feedback fallback",
          }
        : question,
    ),
  };
  const leaderboard = [
    {
      user_id: ROOM_ID,
      display_name: "Room Owner",
      total_points: 500,
      correct_answers: 5,
      rank: 1,
      earned_marks: 5,
      total_available_marks: 13,
    },
    {
      user_id: MEMBER_ID,
      display_name: "Long learner name that wraps naturally",
      total_points: 500,
      correct_answers: 5,
      rank: 1,
      earned_marks: 5,
      total_available_marks: 13,
    },
  ];
  const legacySnapshot = makeFinishedSnapshot({ leaderboard });
  const adaptiveSnapshot = {
    ...legacySnapshot,
    room_state: makeAdaptiveRoomState(),
    quiz_mode: "ADAPTIVE" as const,
    total_available_marks: 13,
  };
  const legacyState = quizStateFromSnapshot(legacySnapshot);
  const adaptiveState = quizStateFromSnapshot(adaptiveSnapshot);

  for (const mode of ["light", "dark"] as const) {
    resetCapture(loaded.capture);
    const openingBindings = resultsRouteBindings(
      initialSessionState,
      reviewResponse,
    );
    const openingMarkup = renderResultsRoute(loaded, mode, openingBindings);
    assert.match(openingMarkup, /Opening authoritative results/);
    assertNoResultsRenderActions(openingBindings, loaded.capture);

    resetCapture(loaded.capture);
    const legacyBindings = resultsRouteBindings(legacyState, reviewResponse);
    const legacyMarkup = renderResultsRoute(loaded, mode, legacyBindings);
    assert.match(legacyMarkup, /500 points/);
    assert.match(legacyMarkup, /Final leaderboard/);
    assert.match(legacyMarkup, /Long learner name that wraps naturally/);
    assertQuizPalette(loaded.capture, mode, {
      expectButton: true,
      expectSelected: true,
    });
    assertResultsTypography(loaded.capture);
    assertNoResultsRenderActions(legacyBindings, loaded.capture);
    assert.deepEqual(buttonByLabel(loaded.capture, "Return to Room").accessibilityState, {
      disabled: false,
    });
    invokeButton(buttonByLabel(loaded.capture, "Report Long learner name that wraps naturally"));
    assert.deepEqual(legacyBindings.actions.reportPushes, [
      {
        pathname: "/report",
        params: {
          roomId: ROOM_ID,
          reportedUserId: MEMBER_ID,
          displayName: "Long learner name that wraps naturally",
        },
      },
    ]);
    assert.equal(
      loaded.capture.buttonProps.some(
        (props) => props.accessibilityLabel === "Report Room Owner",
      ),
      false,
    );
    invokeButton(buttonByLabel(loaded.capture, "Return to Room"));
    assert.equal(legacyBindings.actions.dismissCalls, 1);
    invokeButton(buttonByLabel(loaded.capture, "Review My Answers"));
    assert.deepEqual(legacyBindings.actions.reviewRequests, [
      { roomId: ROOM_ID, sessionId: SESSION_ID },
    ]);

    resetCapture(loaded.capture);
    const dismissedBindings = resultsRouteBindings(
      { ...legacyState, dismissedFinishedSessionId: SESSION_ID },
      reviewResponse,
    );
    const dismissedMarkup = renderResultsRoute(loaded, mode, dismissedBindings);
    assert.match(dismissedMarkup, /Quiz complete/);
    assert.deepEqual(buttonByLabel(loaded.capture, "Return to Room").accessibilityState, {
      disabled: true,
    });
    assertNoResultsRenderActions(dismissedBindings, loaded.capture);

    resetCapture(loaded.capture);
    const adaptiveBindings = resultsRouteBindings(adaptiveState, reviewResponse);
    const adaptiveMarkup = renderResultsRoute(loaded, mode, adaptiveBindings);
    assert.match(adaptiveMarkup, /5\/13 marks/);
    assert.match(adaptiveMarkup, /full-mark answers/);
    assertQuizPalette(loaded.capture, mode, {
      expectButton: true,
      expectSelected: true,
    });
    assertResultsTypography(loaded.capture);
    assertNoResultsRenderActions(adaptiveBindings, loaded.capture);

    resetCapture(loaded.capture);
    const absentOwnRowSnapshot = makeFinishedSnapshot({
      leaderboard: [leaderboard[1]!],
    });
    const absentOwnRowBindings = resultsRouteBindings(
      quizStateFromSnapshot(absentOwnRowSnapshot),
      reviewResponse,
    );
    const absentOwnRowMarkup = renderResultsRoute(
      loaded,
      mode,
      absentOwnRowBindings,
    );
    assert.doesNotMatch(absentOwnRowMarkup, /YOUR RESULT/);
    assertQuizPalette(loaded.capture, mode, { expectButton: true });
    assertNoResultsRenderActions(absentOwnRowBindings, loaded.capture);

    resetCapture(loaded.capture);
    const connectionState: SessionState = {
      ...legacyState,
      connectionStage: "disconnected",
      lastError: new RealtimeNetworkError(),
      phase: "recoverable-error",
    };
    const connectionBindings = resultsRouteBindings(connectionState, reviewResponse);
    const connectionMarkup = renderResultsRoute(loaded, mode, connectionBindings);
    assert.match(connectionMarkup, /Retry connection/);
    assert.match(connectionMarkup, /Could not reach the MindMesh server/);
    assert.ok(
      loaded.capture.textProps.some(
        (props) => props.accessibilityRole === "alert" &&
          String(props.children).includes("Could not reach the MindMesh server"),
      ),
    );
    assert.ok(
      loaded.capture.textProps.some(
        (props) => props.accessibilityLiveRegion === "polite" &&
          String(props.children) === "Connection unavailable",
        ),
    );
    assertNoResultsRenderActions(connectionBindings, loaded.capture);
    invokeButton(buttonByLabel(loaded.capture, "Retry connection"));
    assert.equal(connectionBindings.actions.retryCalls, 1);

    for (const reviewState of [
      { status: "idle" as const },
      { status: "loading" as const },
      { status: "error" as const, message: "Review unavailable" },
      { status: "loaded" as const, review: reviewPresentation },
      { status: "loaded" as const, review: basicReviewPresentation },
    ]) {
      resetCapture(loaded.capture);
      let reviewButtonCalls = 0;
      const reviewMarkup = renderToStaticMarkup(
        createElement(
          loaded.components.StudioThemeProvider,
          { mode },
          createElement(
            loaded.components.StudioScreen,
            null,
            createElement(loaded.reviewSection, {
              reviewState,
              onLoadReview: () => {
                reviewButtonCalls += 1;
              },
            }),
          ),
        ),
      );
      assert.match(reviewMarkup, /Review answers/);
      assert.equal(reviewButtonCalls, 0);
      if (reviewState.status === "idle") {
        invokeButton(buttonByLabel(loaded.capture, "Review My Answers"));
        assert.equal(reviewButtonCalls, 1);
      }
      if (reviewState.status === "loading") {
        assert.match(reviewMarkup, /Loading your review/);
        assert.equal(
          loaded.capture.buttonProps.some(
            (props) => props.accessibilityLabel === "Review My Answers",
          ),
          false,
        );
        assert.equal(
          loaded.capture.textProps.some(
            (props) => props.accessibilityLiveRegion === "polite" &&
              props.children === "Loading your review...",
          ),
          true,
        );
      }
      if (reviewState.status === "error") {
        assert.match(reviewMarkup, /Review unavailable/);
        assertResultsReviewPalette(loaded.capture, mode, { expectError: true });
        assert.ok(
          loaded.capture.textProps.some(
            (props) => props.accessibilityRole === "alert" &&
              props.children === "Review unavailable",
          ),
        );
        invokeButton(buttonByLabel(loaded.capture, "Review My Answers"));
        assert.equal(reviewButtonCalls, 1);
      }
      if (reviewState.status === "loaded") {
        assert.match(reviewMarkup, /5\/16 marks/);
        assert.match(reviewMarkup, /Multiple choice/);
        assert.match(reviewMarkup, /Numerical/);
        assert.match(reviewMarkup, /Written/);
        assert.match(reviewMarkup, /No answer submitted/);
        assert.match(reviewMarkup, /Awarded: Named transfer/);
        assert.match(reviewMarkup, /Missing: Link the stores/);
        if (reviewState.review === basicReviewPresentation) {
          assert.match(reviewMarkup, /Basic feedback fallback/);
        }
        assert.equal(
          loaded.capture.buttonProps.some(
            (props) => props.accessibilityLabel === "Review My Answers",
          ),
          false,
        );
        assertResultsReviewPalette(loaded.capture, mode, { expectExtract: true });
        assert.match(reviewMarkup, /Source extract about energy transfer/);
        assert.match(reviewMarkup, new RegExp(longWrittenAnswer));
        assert.equal(
          loaded.capture.textProps
            .map((props) => flattenStyle(props.style))
            .some(
              (style) =>
                style.backgroundColor ===
                (mode === "light"
                  ? studioLightTheme.colors.selectedBackground
                  : studioDarkTheme.colors.selectedBackground),
            ),
          true,
        );
        assert.equal(reviewButtonCalls, 0);
      }
    }
  }
});

test("direct quiz variants preserve legacy exports and used palette pairs", async () => {
  const loaded = await getStudioComponents();
  const { capture, components } = loaded;
  const optionVariants = [
    { appearance: "default" as const, label: "Default option", selected: false },
    { appearance: "selected" as const, label: "Selected option", selected: true },
    { appearance: "correct" as const, label: "Correct option", selected: true },
    {
      appearance: "incorrect-selected" as const,
      label: "Incorrect option",
      selected: true,
    },
  ];
  const entry = {
    user_id: MEMBER_ID,
    display_name: "Direct learner",
    total_points: 42,
    correct_answers: 3,
    rank: 2,
    earned_marks: 6,
    total_available_marks: 8,
  };
  let legacyOptionLightStyle: StyleRecord | undefined;
  let legacyRowLightStyle: StyleRecord | undefined;

  for (const mode of ["light", "dark"] as const) {
    resetCapture(capture);
    let optionPresses = 0;
    let reportPresses = 0;
    const markup = renderToStaticMarkup(
      createElement(
        components.StudioThemeProvider,
        { mode },
        createElement(
          components.StudioStack,
          null,
          ...optionVariants.map((variant) =>
            createElement(components.StudioQuizOption, {
              key: variant.label,
              option: { id: variant.label, label: variant.label },
              selected: variant.selected,
              appearance: variant.appearance,
              disabled: false,
              onPress: () => {
                optionPresses += 1;
              },
            }),
          ),
          createElement(components.StudioQuizOption, {
            option: { id: "locked", label: "Locked option" },
            selected: false,
            appearance: "default",
            disabled: true,
            onPress: () => {
              throw new Error("disabled themed option dispatched");
            },
          }),
          createElement(components.StudioLeaderboardRow, {
            entry,
            position: 2,
            isCurrentUser: true,
            marksText: "6 / 8 marks",
            correctAnswersLabel: "3 correct",
            onReport: () => {
              reportPresses += 1;
            },
          }),
          createElement(components.StudioLeaderboardRow, {
            entry: { ...entry, user_id: ROOM_ID, display_name: "Peer learner" },
            position: 3,
            isCurrentUser: false,
            marksText: "4 / 8 marks",
            correctAnswersLabel: "2 correct",
          }),
          createElement(components.QuizOption, {
            option: { id: "legacy-option", label: "Legacy option" },
            selected: false,
            appearance: "default",
            disabled: false,
            onPress: () => {
              optionPresses += 1;
            },
          }),
          createElement(components.LeaderboardRow, {
            entry: { ...entry, display_name: "Legacy learner" },
            position: 4,
            isCurrentUser: true,
            onReport: () => {
              reportPresses += 1;
            },
          }),
        ),
      ),
    );
    assert.match(markup, /Direct learner/);
    assert.match(markup, /Peer learner/);
    assert.match(markup, /Legacy learner/);
    const theme = mode === "light" ? studioLightTheme : studioDarkTheme;
    for (const variant of optionVariants) {
      const button = buttonByLabel(capture, variant.label);
      assert.equal(button.accessibilityRole, "radio");
      assert.deepEqual(button.accessibilityState, {
        checked: variant.selected,
        disabled: false,
      });
      const style = flattenStyle(button.style);
      const expectedBackground =
        variant.appearance === "correct"
          ? theme.colors.successBackground
          : variant.appearance === "incorrect-selected"
            ? theme.colors.errorBackground
            : variant.appearance === "selected"
              ? theme.colors.selectedBackground
              : theme.colors.surface;
      assert.equal(style.backgroundColor, expectedBackground);
      const labelProps = capture.textProps.find(
        (props) => props.children === variant.label,
      );
      assert.ok(labelProps, `Expected ${variant.label} foreground text.`);
      const expectedForeground =
        variant.appearance === "correct"
          ? theme.colors.success
          : variant.appearance === "incorrect-selected"
            ? theme.colors.error
            : variant.appearance === "selected"
              ? theme.colors.primary
              : theme.colors.text;
      assert.equal(flattenStyle(labelProps.style).color, expectedForeground);
    }
    const locked = buttonByLabel(capture, "Locked option");
    assert.deepEqual(locked.accessibilityState, { checked: false, disabled: true });
    assert.equal(
      capture.viewProps
        .map((props) => flattenStyle(props.style))
        .some((style) => style.backgroundColor === theme.colors.selectedBackground),
      true,
    );
    assert.ok(capture.textProps.some((props) => props.children === 2));
    assert.ok(capture.textProps.some((props) => props.children === "6 / 8 marks"));
    assert.ok(
      capture.textProps.some(
        (props) =>
          String(props.children).includes("3 correct"),
      ),
    );
    const legacyOptionStyle = flattenStyle(
      buttonByLabel(capture, "Legacy option").style,
    );
    const legacyRowStyle = capture.viewProps
      .map((props) => flattenStyle(props.style))
      .find((style) => style.backgroundColor === colors.selectedBackground);
    assert.ok(legacyRowStyle, "Expected the legacy current-user row style.");
    if (mode === "light") {
      legacyOptionLightStyle = legacyOptionStyle;
      legacyRowLightStyle = legacyRowStyle;
    } else {
      assert.deepEqual(legacyOptionStyle, legacyOptionLightStyle);
      assert.deepEqual(legacyRowStyle, legacyRowLightStyle);
    }
    assert.equal(legacyRowStyle.backgroundColor, colors.selectedBackground);
    assert.equal(buttonByLabel(capture, "Report Direct learner").accessibilityRole, "button");
    assert.equal(buttonByLabel(capture, "Report Legacy learner").accessibilityRole, "button");
    for (const label of [
      "Default option",
      "Selected option",
      "Correct option",
      "Incorrect option",
      "Legacy option",
      "Report Direct learner",
      "Report Legacy learner",
    ]) {
      invokeButton(buttonByLabel(capture, label));
    }
    assert.equal(optionPresses, 5);
    assert.equal(reportPresses, 2);
    assert.ok(colorContrast(theme.colors.text, theme.colors.surface) >= 4.5);
    assert.ok(
      colorContrast(theme.colors.primary, theme.colors.selectedBackground) >= 4.5,
    );
    assert.ok(
      colorContrast(theme.colors.success, theme.colors.successBackground) >= 4.5,
    );
    assert.ok(colorContrast(theme.colors.error, theme.colors.errorBackground) >= 4.5);
  }
});

test("Waiting Room lifecycle and destructive foregrounds meet the existing contrast contract", () => {
  for (const theme of [studioLightTheme, studioDarkTheme]) {
    assert.ok(colorContrast(theme.colors.text, theme.colors.surface) >= 4.5);
    const secondary = studioButtonPresentation(theme, "secondary", false);
    assert.ok(
      colorContrast(
        String(secondary.label.color),
        String(secondary.button.backgroundColor),
      ) >= 4.5,
    );
    assert.ok(colorContrast(theme.colors.success, theme.colors.surface) >= 4.5);
    assert.ok(colorContrast(theme.colors.mutedText, theme.colors.surface) >= 4.5);
  }
  // Alert action colors are platform-owned; the route supplies only semantic
  // destructive/confirmation intent and never injects native alert colors.
});
