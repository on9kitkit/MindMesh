import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";

import { useAuth } from "../src/auth/AuthContext";
import { getUserFacingErrorMessage } from "../src/api/errors";
import { prepareQuiz as requestPrepareQuiz } from "../src/api/rooms";
import {
  StudioButton,
  StudioCard,
  StudioScreen,
  StudioText,
} from "../src/components/studio/StudioPrimitives";
import { StudioPlayerRow } from "../src/components/PlayerRow";
import { createPreparationRequestId } from "../src/features/quiz/adaptiveQuiz";
import {
  buildWaitingRoomPresentation,
  derivePreparationControl,
  deriveReadinessControl,
  deriveRoomLifecycleControl,
  getConnectionLabel,
  getStartEligibilityMessage,
  selectStartEligibility,
  waitingRoomRouteMatches,
} from "../src/features/rooms/waitingRoomPresentation";
import { useSession } from "../src/features/session/SessionContext";
import { getSessionErrorMessage } from "../src/features/session/sessionErrorMessages";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import {
  CommandUnavailableError,
  StudyRoomRealtimeError,
} from "../src/realtime/errors";

export default function WaitingRoomRoute() {
  const { state: authState } = useAuth();
  const {
    state: sessionState,
    retryConnection,
    closeCurrentRoom,
    leaveCurrentRoom,
    setReady,
    startSession,
    prepareQuiz,
    requestState,
  } = useSession();
  const { roomId: rawRoomId } = useLocalSearchParams<{
    roomId?: string | string[];
  }>();
  const theme = useStudioTheme();
  const roomId = typeof rawRoomId === "string" ? rawRoomId : null;
  const [localCommandError, setLocalCommandError] = useState<string | null>(
    null,
  );
  const [httpPreparationPending, setHttpPreparationPending] = useState(false);
  const routeDoesNotMatch =
    authState.status === "signed-in" &&
    !waitingRoomRouteMatches(roomId, sessionState);

  if (authState.status === "initializing") {
    return (
      <StudioScreen>
        <StudioText color={theme.colors.primary} variant="eyebrow">
          WAITING ROOM
        </StudioText>
        <StudioText variant="title" style={styles.title}>
          Restoring your session...
        </StudioText>
      </StudioScreen>
    );
  }

  if (authState.status !== "signed-in") {
    return (
      <StudioScreen>
        <StudioText color={theme.colors.primary} variant="eyebrow">
          WAITING ROOM
        </StudioText>
        <StudioText variant="title" style={styles.title}>
          Returning to sign in...
        </StudioText>
      </StudioScreen>
    );
  }

  if (routeDoesNotMatch) {
    return (
      <StudioScreen>
        <StudioText color={theme.colors.primary} variant="eyebrow">
          WAITING ROOM
        </StudioText>
        <StudioText variant="title" style={styles.title}>
          Opening your current room...
        </StudioText>
      </StudioScreen>
    );
  }

  const presentation = buildWaitingRoomPresentation(sessionState);
  const readinessControl = deriveReadinessControl(sessionState);
  const preparationControl = derivePreparationControl(sessionState, httpPreparationPending);
  const eligibility = selectStartEligibility(sessionState);
  const lifecycleControl = deriveRoomLifecycleControl(sessionState);
  const sessionError =
    sessionState.lastError === null
      ? null
      : getSessionErrorMessage(sessionState.lastError);

  function changeReadiness(desiredReady: boolean): void {
    setLocalCommandError(null);
    try {
      setReady(desiredReady);
    } catch {
      setLocalCommandError("Readiness is not available right now.");
    }
  }

  function startAuthoritativeSession(): void {
    if (!eligibility.eligible) {
      return;
    }
    setLocalCommandError(null);
    try {
      startSession();
    } catch (error: unknown) {
      setLocalCommandError(
        error instanceof StudyRoomRealtimeError
          ? getSessionErrorMessage(error)
          : "The quiz could not be started right now.",
      );
    }
  }

  function generateQuizContent(): void {
    if (
      preparationControl.status !== "generate-available" &&
      !(preparationControl.status === "failed" && preparationControl.canRetry)
    ) {
      return;
    }
    setLocalCommandError(null);
    const requestId = createPreparationRequestId();
    try {
      prepareQuiz(requestId);
    } catch (error: unknown) {
      if (!(error instanceof CommandUnavailableError)) {
        setLocalCommandError(
          error instanceof StudyRoomRealtimeError
            ? getSessionErrorMessage(error)
            : "The quiz could not be generated right now.",
        );
        return;
      }
      const roomId = sessionState.roomId;
      if (roomId === null) {
        setLocalCommandError("The quiz could not be generated right now.");
        return;
      }
      setHttpPreparationPending(true);
      void requestPrepareQuiz(roomId, requestId)
        .then(() => {
          try {
            requestState();
          } catch {
            // The refreshed snapshot arrives through the next connection.
          }
        })
        .catch((requestError: unknown) => {
          setLocalCommandError(getUserFacingErrorMessage(requestError));
        })
        .finally(() => setHttpPreparationPending(false));
    }
  }

  async function executeLifecycleAction(
    action: "leave" | "close",
  ): Promise<void> {
    setLocalCommandError(null);
    try {
      if (action === "leave") {
        await leaveCurrentRoom();
      } else {
        await closeCurrentRoom();
      }
    } catch (error: unknown) {
      setLocalCommandError(
        error instanceof StudyRoomRealtimeError
          ? error.kind === "command-rejected"
            ? error.message
            : getSessionErrorMessage(error)
          : "The room lifecycle request could not be completed.",
      );
    }
  }

  function confirmLifecycleAction(action: "leave" | "close"): void {
    if (lifecycleControl?.disabled !== false) {
      return;
    }
    if (action === "close") {
      Alert.alert(
        "Close room?",
        "Closing the room removes every current member. Completed quiz results will remain saved.",
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Close Room",
            style: "destructive",
            onPress: () => void executeLifecycleAction("close"),
          },
        ],
      );
      return;
    }
    Alert.alert(
      "Leave room?",
      "Leave this room and return Home? Completed quiz results will remain saved.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Leave Room",
          style: "destructive",
          onPress: () => void executeLifecycleAction("leave"),
        },
      ],
    );
  }

  if (presentation === null) {
    const connectionFailed =
      sessionState.phase === "recoverable-error" ||
      sessionState.phase === "fatal-error";
    return (
      <StudioScreen>
        <StudioText color={theme.colors.primary} variant="eyebrow">
          WAITING ROOM
        </StudioText>
        <StudioText variant="title" style={styles.title}>
          {connectionFailed
            ? "Room connection unavailable"
            : "Connecting to room..."}
        </StudioText>
        <StudioText tone="muted" variant="body" style={styles.description}>
          {connectionFailed
            ? sessionError
            : "Waiting for the latest authoritative room state."}
        </StudioText>
        {sessionState.phase === "recoverable-error" ? (
          <View style={styles.buttonContainer}>
            <StudioButton label="Retry" onPress={retryConnection} />
          </View>
        ) : null}
      </StudioScreen>
    );
  }

  const visibleError = localCommandError ?? sessionError;
  const startPending = sessionState.pendingCommand?.kind === "start";

  return (
    <StudioScreen>
      <StudioText color={theme.colors.primary} variant="eyebrow">
        WAITING ROOM
      </StudioText>
      <StudioText variant="title" style={styles.title}>
        {presentation.name}
      </StudioText>
      <StudioText tone="muted" variant="body" style={styles.description}>
        {presentation.viewerRole === "host"
          ? "You are the room host."
          : "You joined as a room member."}
      </StudioText>
      <Text
        accessibilityLiveRegion="polite"
        style={[
          theme.typography.caption,
          styles.connection,
          { color: theme.colors.primary },
        ]}
      >
        {getConnectionLabel(sessionState)}
      </Text>

      {visibleError !== null ? (
        <StudioCard style={styles.errorCard}>
          <StudioText
            accessibilityRole="alert"
            tone="error"
            variant="body"
            style={styles.error}
          >
            {visibleError}
          </StudioText>
          {sessionState.phase === "recoverable-error" ? (
            <StudioButton label="Retry connection" onPress={retryConnection} />
          ) : null}
        </StudioCard>
      ) : null}

      <StudioCard style={styles.roomCard}>
        <StudioText tone="muted" variant="label" style={styles.label}>
          ROOM CODE
        </StudioText>
        <StudioText variant="heading" style={styles.code}>
          {presentation.joinCode}
        </StudioText>
        <StudioText tone="muted" variant="caption" style={styles.memberCount}>
          {presentation.participantCount} / {presentation.maximumMembers}{" "}
          participants
        </StudioText>
      </StudioCard>

      {presentation.adaptiveSummary !== null ? (
        <StudioCard style={styles.quizCard}>
          <StudioText tone="muted" variant="label" style={styles.label}>
            ADAPTIVE GCSE PRACTICE
          </StudioText>
          <StudioText variant="heading" style={styles.cardTitle}>
            {presentation.adaptiveSummary.subjectLabel} ·{" "}
            {presentation.adaptiveSummary.topicLabel}
          </StudioText>
          <StudioText tone="muted" variant="body" style={styles.cardDescription}>
            {presentation.adaptiveSummary.targetTotalMarks === null
              ? "The host's mark budget applies to everyone in this room."
              : `Total marks: ${presentation.adaptiveSummary.targetTotalMarks}. The question set always adds up to this budget.`}{" "}
            The selection is shared and cannot be changed in this room.
          </StudioText>
        </StudioCard>
      ) : null}

      {preparationControl.status === "legacy" ? null : (
        <StudioCard style={styles.quizCard}>
          <StudioText variant="heading" style={styles.cardTitle}>
            Quiz content
          </StudioText>
          <Text
            accessibilityLiveRegion="polite"
            style={[
              theme.typography.body,
              styles.cardDescription,
              { color: theme.colors.mutedText },
            ]}
          >
            {preparationControl.label}
          </Text>
          {preparationControl.status === "generate-available" ||
          (preparationControl.status === "failed" &&
            preparationControl.canRetry) ? (
            <StudioButton
              label={
                preparationControl.status === "failed"
                  ? "Retry Generation"
                  : "Generate Quiz"
              }
              onPress={generateQuizContent}
            />
          ) : null}
          {preparationControl.status === "generate-pending" ||
          preparationControl.status === "generating" ? (
            <StudioButton
              disabled
              label="Generating Quiz..."
              onPress={() => undefined}
            />
          ) : null}
        </StudioCard>
      )}

      <View style={styles.playersSection}>
        <StudioText variant="heading" style={styles.sectionTitle}>
          Participants ({presentation.participantCount})
        </StudioText>
        <StudioCard>
          {presentation.participants.map((participant) => (
            <StudioPlayerRow
              key={participant.user_id}
              onReport={
                participant.user_id === authState.user.id
                  ? undefined
                  : () =>
                      router.push({
                        pathname: "/report",
                        params: {
                          roomId: presentation.roomId,
                          reportedUserId: participant.user_id,
                          displayName: participant.display_name,
                        },
                      })
              }
              participant={participant}
            />
          ))}
        </StudioCard>
      </View>

      {readinessControl.status === "host" ? (
        <StudioCard style={styles.readinessCard}>
          <StudioText variant="heading" style={styles.cardTitle}>
            Host — ready automatically
          </StudioText>
          <StudioText tone="muted" variant="body" style={styles.cardDescription}>
            {getStartEligibilityMessage(eligibility)}
          </StudioText>
          <StudioButton
            disabled={!eligibility.eligible}
            label={startPending ? "Starting Quiz..." : "Start Quiz"}
            onPress={startAuthoritativeSession}
          />
        </StudioCard>
      ) : (
        <StudioCard style={styles.readinessCard}>
          <StudioText variant="heading" style={styles.cardTitle}>
            Your readiness
          </StudioText>
          <StudioText tone="muted" variant="body" style={styles.cardDescription}>
            The server confirms readiness for everyone in this room.
          </StudioText>
          {readinessControl.status === "available" ? (
            <StudioButton
              label={readinessControl.label}
              onPress={() => changeReadiness(readinessControl.desiredReady)}
            />
          ) : (
            <StudioButton
              disabled
              label={readinessControl.label}
              onPress={() => undefined}
            />
          )}
        </StudioCard>
      )}

      {lifecycleControl !== null ? (
        <StudioCard style={styles.lifecycleCard}>
          <StudioText variant="heading" style={styles.cardTitle}>
            {lifecycleControl.kind === "close" ? "Room lifecycle" : "Leave room"}
          </StudioText>
          <Text
            accessibilityLiveRegion="polite"
            style={[
              theme.typography.body,
              styles.cardDescription,
              { color: theme.colors.mutedText },
            ]}
          >
            {lifecycleControl.message}
          </Text>
          <StudioButton
            disabled={lifecycleControl.disabled}
            label={lifecycleControl.label}
            onPress={() => confirmLifecycleAction(lifecycleControl.kind)}
            variant="secondary"
          />
        </StudioCard>
      ) : null}
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  title: {
    marginTop: 6,
  },
  description: {
    marginTop: 10,
  },
  connection: {
    marginTop: 10,
  },
  roomCard: {
    marginTop: 24,
  },
  quizCard: {
    marginTop: 24,
  },
  label: {
    marginBottom: 2,
  },
  code: {
    letterSpacing: 4,
    marginTop: 6,
  },
  memberCount: {
    marginTop: 10,
  },
  errorCard: {
    marginTop: 24,
  },
  error: {
    marginBottom: 16,
  },
  playersSection: {
    marginTop: 24,
  },
  sectionTitle: {
    marginBottom: 10,
  },
  readinessCard: {
    marginTop: 24,
  },
  lifecycleCard: {
    marginTop: 24,
  },
  cardTitle: {
    marginBottom: 2,
  },
  cardDescription: {
    marginBottom: 16,
    marginTop: 6,
  },
  buttonContainer: {
    marginTop: 24,
  },
});
