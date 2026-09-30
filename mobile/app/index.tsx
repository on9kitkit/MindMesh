import { router } from "expo-router";
import { useEffect, useReducer, useRef, useState } from "react";
import { View } from "react-native";

import {
  createRoom as requestCreateRoom,
  joinRoomByCode as requestJoinRoomByCode,
} from "../src/api/rooms";
import { useAuth } from "../src/auth/AuthContext";
import { StudioAppearanceSelector } from "../src/appearance/AppearanceSelector";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import {
  StudioButton,
  StudioCard,
  StudioChoiceRow,
  StudioScreen,
  StudioStack,
  StudioText,
  StudioTextField,
} from "../src/components/studio/StudioPrimitives";
import {
  ADAPTIVE_SUBJECTS,
  clampTotalMarks,
  DEFAULT_TOTAL_MARKS,
  MAX_TOTAL_MARKS,
  MIN_TOTAL_MARKS,
  type AdaptiveSubject,
  type AdaptiveTopic,
} from "../src/features/quiz/adaptiveQuiz";
import {
  deriveHomeScreenState,
  DEFAULT_ROOM_CAPACITY_PRESET,
  getJoinCodeValidationMessage,
  getQuizSelectionValidationMessage,
  HomeRoomRequestCoordinator,
  homeOperationReducer,
  initialHomeOperationState,
  reconcileRoomCapacityPreset,
  roomCapacityIsAvailable,
  type HomeRoomRequestDependencies,
  type HomeRoomRequestOutcome,
  type QuizModeSelection,
  type RoomCapacityPreset,
} from "../src/features/rooms/homeFlow";
import { useSession } from "../src/features/session/SessionContext";
import { HomeCompanions } from "../src/features/learningCompanions/HomeCompanions";
import { useRevenueCat } from "../src/revenuecat/RevenueCatContext";
import { revenueCatReadyData } from "../src/revenuecat/types";

export default function HomeRoute() {
  const theme = useStudioTheme();
  const {
    retryProfileBootstrap,
    signOut,
    state: authState,
  } = useAuth();
  const {
    state: sessionState,
    recoverActiveRoom,
    retryConnection,
    selectRoom,
  } = useSession();
  const { state: revenueCatState } = useRevenueCat();
  const [operationState, operationDispatch] = useReducer(
    homeOperationReducer,
    initialHomeOperationState,
  );
  const [capacityPreset, setCapacityPreset] = useState<RoomCapacityPreset>(
    DEFAULT_ROOM_CAPACITY_PRESET,
  );
  const [quizMode, setQuizMode] = useState<"legacy" | "adaptive">("legacy");
  const [adaptiveSubject, setAdaptiveSubject] =
    useState<AdaptiveSubject>("physics");
  const [adaptiveTopic, setAdaptiveTopic] = useState<AdaptiveTopic>("energy");
  const [totalMarksText, setTotalMarksText] = useState<string>(
    String(DEFAULT_TOTAL_MARKS),
  );
  const requestCoordinatorRef = useRef(new HomeRoomRequestCoordinator());
  const sessionStateRef = useRef(sessionState);
  const authStateRef = useRef(authState);
  sessionStateRef.current = sessionState;
  authStateRef.current = authState;
  const revenueCatData = revenueCatReadyData(revenueCatState);
  const isPro = revenueCatData?.isPro === true;
  const proStatusResolved = revenueCatData !== null;

  useEffect(() => {
    if (proStatusResolved && !isPro) {
      setCapacityPreset((current) =>
        reconcileRoomCapacityPreset(current, isPro),
      );
    }
  }, [isPro, proStatusResolved]);

  if (authState.status === "initializing") {
    return (
      <StudioScreen>
        <StudioText tone="primary" variant="eyebrow">STUDYROOM</StudioText>
        <StudioText style={{ marginTop: theme.spacing.xs }} variant="title">
          Restoring your session...
        </StudioText>
      </StudioScreen>
    );
  }

  if (authState.status !== "signed-in") {
    return (
      <StudioScreen>
        <StudioText tone="primary" variant="eyebrow">STUDYROOM</StudioText>
        <StudioText style={{ marginTop: theme.spacing.xs }} variant="title">
          Returning to sign in...
        </StudioText>
      </StudioScreen>
    );
  }

  const signedInUserId = authState.user.id;
  const profileBootstrap = authState.profileBootstrap;
  const profileBootstrapPending =
    profileBootstrap.status === "pending" ||
    profileBootstrap.status === "syncing";
  const profileBootstrapFailed =
    profileBootstrap.status === "recoverable-error";
  const profileBootstrapBlocksRooms =
    profileBootstrapPending || profileBootstrapFailed;
  const viewState = deriveHomeScreenState(sessionState, operationState);
  const joinValidationMessage = getJoinCodeValidationMessage(
    operationState.joinCode,
  );
  const requestActionsAvailable =
    !profileBootstrapBlocksRooms &&
    (viewState.status === "no-active-room" ||
      (viewState.status === "recoverable-error" &&
        viewState.source === "request"));
  const createPending = viewState.status === "creating-room";
  const joinPending = viewState.status === "joining-room";
  const roomActionsPending = createPending || joinPending;
  const capacityControlsDisabled =
    !requestActionsAvailable || roomActionsPending;
  const selectedCapacityUnavailable = !roomCapacityIsAvailable(
    capacityPreset,
    isPro,
  );

  function requestDependencies(): HomeRoomRequestDependencies {
    return {
      createRoom: requestCreateRoom,
      joinRoomByCode: requestJoinRoomByCode,
      selectRoom,
      recoverActiveRoom,
      getSelectedRoomId: () => sessionStateRef.current.roomId,
      resultIsCurrent: () =>
        authStateRef.current.status === "signed-in" &&
        authStateRef.current.user.id === signedInUserId,
    };
  }

  function applyRequestOutcome(outcome: HomeRoomRequestOutcome): void {
    switch (outcome.status) {
      case "selected":
        operationDispatch({ type: "ROOM_SELECTED", roomId: outcome.roomId });
        return;
      case "recovery-requested":
        operationDispatch({ type: "REQUEST_COMPLETED" });
        return;
      case "failed":
        operationDispatch({
          type: "REQUEST_FAILED",
          message: outcome.message,
          ...(outcome.code === undefined ? {} : { code: outcome.code }),
        });
        return;
      case "blocked":
      case "cancelled":
        return;
    }
  }

  const parsedTotalMarks = Number(totalMarksText);
  const quizSelection: QuizModeSelection =
    quizMode === "legacy"
      ? { mode: "legacy" }
      : {
          mode: "adaptive",
          subject: adaptiveSubject,
          topic: adaptiveTopic,
          totalMarks: parsedTotalMarks,
        };
  const quizSelectionMessage =
    getQuizSelectionValidationMessage(quizSelection);

  function handleSubjectSelection(subject: AdaptiveSubject): void {
    if (capacityControlsDisabled) {
      return;
    }
    setAdaptiveSubject(subject);
    const firstTopic = ADAPTIVE_SUBJECTS.find(
      (entry) => entry.id === subject,
    )?.topics[0];
    if (firstTopic !== undefined) {
      setAdaptiveTopic(firstTopic.id);
    }
  }

  async function handleCreateRoom(): Promise<void> {
    if (
      !requestActionsAvailable ||
      selectedCapacityUnavailable ||
      quizSelectionMessage !== null
    ) {
      return;
    }
    operationDispatch({ type: "CREATE_REQUESTED" });
    const outcome = await requestCoordinatorRef.current.createRoomWithSelection(
      requestDependencies(),
      capacityPreset,
      quizSelection,
    );
    applyRequestOutcome(outcome);
  }

  function handleCapacitySelection(preset: RoomCapacityPreset): void {
    if (capacityControlsDisabled) {
      return;
    }
    if (!roomCapacityIsAvailable(preset, isPro)) {
      router.push("/pro");
      return;
    }
    setCapacityPreset(preset);
  }

  async function handleJoinRoom(): Promise<void> {
    if (!requestActionsAvailable || joinValidationMessage !== null) {
      return;
    }
    operationDispatch({ type: "JOIN_REQUESTED" });
    const outcome = await requestCoordinatorRef.current.joinRoom(
      operationState.joinCode,
      requestDependencies(),
    );
    applyRequestOutcome(outcome);
  }

  function retrySession(): void {
    if (sessionState.roomId === null) {
      void recoverActiveRoom();
      return;
    }
    retryConnection();
  }

  return (
    <StudioScreen>
      <StudioText tone="primary" variant="eyebrow">STUDYROOM</StudioText>
      <StudioText style={{ marginTop: theme.spacing.xs }} variant="title">
        Make revision a team sport.
      </StudioText>
      <StudioText color={theme.colors.mutedText} style={{ marginTop: theme.spacing.sm }}>
        Create a quiz room or join one with its six-character code.
      </StudioText>

      <View style={{ marginTop: theme.spacing.lg }}>
        <StudioAppearanceSelector />
      </View>

      {viewState.status === "checking-active-room" ? (
        <StudioCard style={{ marginTop: theme.spacing.lg }}>
          <StudioStack>
            <StudioText variant="heading">Checking for an active room...</StudioText>
            <StudioText color={theme.colors.mutedText}>
              Room actions will be available when recovery is complete.
            </StudioText>
          </StudioStack>
        </StudioCard>
      ) : null}

      {viewState.status === "active-room-found" ? (
        <StudioCard style={{ marginTop: theme.spacing.lg }}>
          <StudioStack>
            <StudioText variant="heading">
              {viewState.coherent
                ? "Opening your room..."
                : "Connecting to your room..."}
            </StudioText>
            <StudioText color={theme.colors.mutedText}>
              Waiting for the latest authoritative room state.
            </StudioText>
          </StudioStack>
        </StudioCard>
      ) : null}

      {viewState.status === "recoverable-error" ? (
        <StudioCard style={{ marginTop: theme.spacing.lg }}>
          <StudioStack>
            <StudioText accessibilityRole="alert" tone="error">
              {viewState.message}
            </StudioText>
            {viewState.source === "session" ? (
              <StudioButton label="Retry" onPress={retrySession} />
            ) : null}
          </StudioStack>
        </StudioCard>
      ) : null}

      {profileBootstrapPending ? (
        <StudioCard style={{ marginTop: theme.spacing.lg }}>
          <StudioStack>
            <StudioText variant="heading">Setting up your profile...</StudioText>
            <StudioText color={theme.colors.mutedText}>
              Room actions will be available when profile setup is complete.
            </StudioText>
          </StudioStack>
        </StudioCard>
      ) : null}

      {profileBootstrap.status === "recoverable-error" ? (
        <StudioCard style={{ marginTop: theme.spacing.lg }}>
          <StudioStack>
            <StudioText accessibilityRole="alert" tone="error">
              Profile setup could not finish. {profileBootstrap.message}
            </StudioText>
            <StudioButton
              label="Retry Profile Setup"
              onPress={retryProfileBootstrap}
            />
          </StudioStack>
        </StudioCard>
      ) : null}

      {viewState.status === "no-active-room" && profileBootstrap.status === "ready" ? (
        <HomeCompanions
          key={signedInUserId}
          userId={signedInUserId}
          roomFree
          profileReady
        />
      ) : null}

      <StudioCard style={{ marginTop: theme.spacing.lg }}>
        <StudioStack>
          <StudioText variant="heading">Create a room</StudioText>
          <StudioText color={theme.colors.mutedText}>
            Choose the quiz and the room size before creating.
          </StudioText>
          <StudioChoiceRow
            description="The classic five-question demo quiz"
            disabled={capacityControlsDisabled}
            onPress={() => {
              if (!capacityControlsDisabled) {
                setQuizMode("legacy");
              }
            }}
            selected={quizMode === "legacy"}
            title="Physics Sprint"
          />
          <StudioChoiceRow
            description="AI-generated questions for a chosen topic and mark budget"
            disabled={capacityControlsDisabled}
            onPress={() => {
              if (!capacityControlsDisabled) {
                setQuizMode("adaptive");
              }
            }}
            selected={quizMode === "adaptive"}
            title="Adaptive GCSE practice"
          />
          {quizMode === "adaptive" ? (
            <View style={{ gap: theme.spacing.sm }}>
              <StudioText color={theme.colors.mutedText} variant="label">
                SUBJECT
              </StudioText>
              {ADAPTIVE_SUBJECTS.map((subject) => (
                <StudioChoiceRow
                  key={subject.id}
                  disabled={capacityControlsDisabled}
                  onPress={() => handleSubjectSelection(subject.id)}
                  selected={adaptiveSubject === subject.id}
                  title={subject.label}
                />
              ))}
              <StudioText color={theme.colors.mutedText} variant="label">
                TOPIC
              </StudioText>
              {ADAPTIVE_SUBJECTS.find(
                (subject) => subject.id === adaptiveSubject,
              )?.topics.map((topic) => (
                <StudioChoiceRow
                  key={topic.id}
                  disabled={capacityControlsDisabled}
                  onPress={() => {
                    if (!capacityControlsDisabled) {
                      setAdaptiveTopic(topic.id);
                    }
                  }}
                  selected={adaptiveTopic === topic.id}
                  title={topic.label}
                />
              ))}
              <StudioText color={theme.colors.mutedText} variant="label">
                TOTAL MARKS
              </StudioText>
              <StudioText color={theme.colors.mutedText} variant="caption">
                {`Whole marks from ${MIN_TOTAL_MARKS} to ${MAX_TOTAL_MARKS}. The question set always adds up to this budget.`}
              </StudioText>
              <StudioTextField
                autoCorrect={false}
                containerStyle={{ marginTop: theme.spacing.xs }}
                editable={!capacityControlsDisabled}
                keyboardType="number-pad"
                label="Total marks"
                maxLength={2}
                onChangeText={setTotalMarksText}
                onBlur={() =>
                  setTotalMarksText((current) => {
                    const parsed = Number(current);
                    if (!Number.isFinite(parsed)) {
                      return String(DEFAULT_TOTAL_MARKS);
                    }
                    return String(clampTotalMarks(parsed));
                  })
                }
                placeholder={String(DEFAULT_TOTAL_MARKS)}
                value={totalMarksText}
              />
              {quizSelectionMessage !== null ? (
                <StudioText accessibilityRole="alert" tone="error">
                  {quizSelectionMessage}
                </StudioText>
              ) : null}
            </View>
          ) : null}
          <StudioChoiceRow
            accessibilityLabel="Standard Room. Free. Up to 8 members"
            description="Free · up to 8 members"
            disabled={capacityControlsDisabled}
            onPress={() => handleCapacitySelection("standard")}
            selected={capacityPreset === "standard"}
            title="Standard Room"
          />
          <StudioChoiceRow
            accessibilityLabel={`Large Room. ${isPro ? "StudyRoom Pro" : "StudyRoom Pro required"}. Up to 20 members`}
            description={isPro ? "StudyRoom Pro · up to 20 members" : "StudyRoom Pro required · up to 20 members"}
            disabled={capacityControlsDisabled}
            onPress={() => handleCapacitySelection("large")}
            selected={capacityPreset === "large"}
            title="Large Room"
          />
          <StudioButton
            disabled={
              capacityControlsDisabled ||
              selectedCapacityUnavailable ||
              quizSelectionMessage !== null
            }
            label={createPending ? "Creating Room..." : "Create Room"}
            onPress={() => void handleCreateRoom()}
          />
        </StudioStack>
      </StudioCard>

      <StudioCard style={{ marginTop: theme.spacing.md }}>
        <StudioStack>
          <StudioText variant="heading">Join by code</StudioText>
          <StudioText color={theme.colors.mutedText}>
            {JOIN_CODE_DESCRIPTION}
          </StudioText>
          <StudioTextField
            autoCapitalize="characters"
            autoCorrect={false}
            editable={requestActionsAvailable && !createPending && !joinPending}
            label="Room code"
            maxLength={6}
            onChangeText={(value) =>
              operationDispatch({ type: "JOIN_CODE_CHANGED", value })
            }
            placeholder="PHYS42"
            value={operationState.joinCode}
          />
          {operationState.joinTouched && joinValidationMessage !== null ? (
            <StudioText accessibilityRole="alert" tone="error">
              {joinValidationMessage}
            </StudioText>
          ) : null}
          <StudioButton
            disabled={
              !requestActionsAvailable ||
              createPending ||
              joinPending ||
              joinValidationMessage !== null
            }
            label={joinPending ? "Joining Room..." : "Join Room"}
            onPress={() => void handleJoinRoom()}
          />
        </StudioStack>
      </StudioCard>

      <StudioCard style={{ marginTop: theme.spacing.md }}>
        <StudioStack>
          <StudioText variant="heading">StudyRoom Pro</StudioText>
          <StudioText color={theme.colors.mutedText}>
            Advanced StudyRoom Pro features are being introduced progressively.
          </StudioText>
          <StudioButton
            label="Explore StudyRoom Pro"
            onPress={() => router.push("/pro")}
            variant="secondary"
          />
        </StudioStack>
      </StudioCard>

      <StudioCard style={{ marginTop: theme.spacing.md }}>
        <StudioStack>
          <StudioText variant="heading">Account & settings</StudioText>
          <StudioText color={theme.colors.mutedText}>
            {authState.user.displayName ?? "StudyRoom member"}
          </StudioText>
          <StudioButton
            label="Open Account & settings"
            onPress={() => router.push("/account")}
            variant="secondary"
          />
        </StudioStack>
      </StudioCard>

      <View style={{ marginTop: theme.spacing.md }}>
        <StudioButton
          label="Sign out"
          onPress={() => void signOut()}
          variant="secondary"
        />
      </View>
    </StudioScreen>
  );
}

const JOIN_CODE_DESCRIPTION =
  "Enter the room code shared by the host. Use letters A–Z and digits 2–9.";
