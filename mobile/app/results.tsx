import { router, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { StyleSheet, View } from "react-native";

import { getUserFacingErrorMessage } from "../src/api/errors";
import { getSessionReview } from "../src/api/sessionReview";
import { useAuth } from "../src/auth/AuthContext";
import { StudioLeaderboardRow } from "../src/components/LeaderboardRow";
import {
  StudioButton,
  StudioCard,
  StudioScreen,
  StudioText,
} from "../src/components/studio/StudioPrimitives";
import {
  buildReviewPresentation,
  type ReviewPresentation,
} from "../src/features/quiz/reviewPresentation";
import {
  buildResultsPresentation,
  canDismissFinishedSession,
  formatCorrectAnswersLabel,
  formatLeaderboardMarks,
} from "../src/features/quiz/resultsPresentation";
import { useSession } from "../src/features/session/SessionContext";
import { getSessionErrorMessage } from "../src/features/session/sessionErrorMessages";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import { RoomRewardStatus } from "../src/features/learningCompanions/RoomRewardStatus";
import { spacing } from "../src/theme";

export type ReviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; review: ReviewPresentation }
  | { status: "error"; message: string };

export type ResultsReviewSectionProps = {
  onLoadReview: () => void;
  reviewState: ReviewState;
};

export function ResultsReviewSection({
  onLoadReview,
  reviewState,
}: ResultsReviewSectionProps) {
  const theme = useStudioTheme();
  return (
    <View style={styles.reviewSection}>
      <StudioText variant="heading" style={styles.sectionTitle}>
        Review answers
      </StudioText>
      <StudioText tone="muted" style={styles.description}>
        Your own responses, marks, and explanations for this finished quiz.
      </StudioText>
      {reviewState.status === "idle" || reviewState.status === "error" ? (
        <>
          {reviewState.status === "error" ? (
            <StudioCard style={styles.errorCard}>
              <StudioText accessibilityRole="alert" tone="error" style={styles.error}>
                {reviewState.message}
              </StudioText>
            </StudioCard>
          ) : null}
          <StudioButton
            label="Review My Answers"
            onPress={onLoadReview}
            variant="secondary"
          />
        </>
      ) : null}
      {reviewState.status === "loading" ? (
        <StudioCard style={styles.statusCard}>
          <StudioText
            accessibilityLiveRegion="polite"
            tone="muted"
            style={styles.description}
          >
            Loading your review...
          </StudioText>
        </StudioCard>
      ) : null}
      {reviewState.status === "loaded" ? (
        <StudioCard style={styles.statusCard}>
          <StudioText tone="muted" variant="label" style={styles.scoreLabel}>
            YOUR TOTAL
          </StudioText>
          <StudioText variant="heading" style={styles.score}>
            {reviewState.review.totalsLabel}
          </StudioText>
        </StudioCard>
      ) : null}
      {reviewState.status === "loaded"
        ? reviewState.review.questions.map((item) => (
            <StudioCard key={item.sessionQuestionId} style={styles.reviewCard}>
              <StudioText tone="muted" variant="label" style={styles.reviewPosition}>
                Question {item.questionNumber} · {item.questionTypeLabel} · {item.marksLabel}
              </StudioText>
              {item.originalExtract !== null ? (
                <StudioText
                  style={[
                    styles.reviewExtract,
                    { backgroundColor: theme.colors.selectedBackground },
                  ]}
                >
                  {item.originalExtract}
                </StudioText>
              ) : null}
              <StudioText variant="heading" style={styles.reviewPrompt}>
                {item.prompt}
              </StudioText>
              <StudioText tone="muted" style={styles.reviewResponse}>
                {item.ownResponseLabel === null
                  ? "No answer submitted."
                  : `Your answer: ${item.ownResponseLabel}`}
              </StudioText>
              {item.correctOptionLabel !== null ? (
                <StudioText tone="muted" style={styles.reviewResponse}>
                  Correct answer: {item.correctOptionLabel}
                </StudioText>
              ) : null}
              {item.enrichedFeedback !== null ? (
                <>
                  {item.enrichedFeedback.summary.length > 0 ? (
                    <StudioText style={styles.reviewFeedback}>
                      {item.enrichedFeedback.summary}
                    </StudioText>
                  ) : null}
                  {item.enrichedFeedback.awarded.map((point) => (
                    <StudioText key={point.id} tone="muted" style={styles.reviewResponse}>
                      Awarded: {point.explanation} (+{point.marks}{" "}
                      {point.marks === 1 ? "mark" : "marks"})
                    </StudioText>
                  ))}
                  {item.enrichedFeedback.missing.map((point) => (
                    <StudioText key={point.id} tone="muted" style={styles.reviewResponse}>
                      Missing: {point.explanation} (worth {point.marks}{" "}
                      {point.marks === 1 ? "mark" : "marks"})
                    </StudioText>
                  ))}
                </>
              ) : (
                <>
                  {item.feedbackSummary !== null ? (
                    <StudioText style={styles.reviewFeedback}>
                      {item.feedbackSummary}
                    </StudioText>
                  ) : null}
                  {item.awardedCriterionCount > 0 ? (
                    <StudioText tone="muted" style={styles.reviewResponse}>
                      Marking points awarded: {item.awardedCriterionCount}
                    </StudioText>
                  ) : null}
                </>
              )}
              {item.workedExplanation.length > 0 ? (
                <StudioText style={styles.reviewExplanation}>
                  {item.workedExplanation}
                </StudioText>
              ) : null}
            </StudioCard>
          ))
        : null}
    </View>
  );
}

export default function ResultsRoute() {
  const { state: authState } = useAuth();
  const {
    state: sessionState,
    dismissFinishedSession,
    retryConnection,
  } = useSession();
  const { roomId: rawRoomId } = useLocalSearchParams<{
    roomId?: string | string[];
  }>();
  const routeRoomId = typeof rawRoomId === "string" ? rawRoomId : null;
  const presentation =
    authState.status === "signed-in"
      ? buildResultsPresentation(sessionState, authState.user.id)
      : null;
  const [reviewState, setReviewState] = useState<ReviewState>({
    status: "idle",
  });

  if (
    authState.status !== "signed-in" ||
    routeRoomId === null ||
    routeRoomId !== sessionState.roomId ||
    presentation === null
  ) {
    return (
      <StudioScreen>
        <StudioText tone="primary" variant="label" style={styles.eyebrow}>
          RESULTS
        </StudioText>
        <StudioText variant="heading" style={styles.title}>
          Opening authoritative results...
        </StudioText>
        <StudioText tone="muted" style={styles.description}>
          Waiting for the completed server session.
        </StudioText>
      </StudioScreen>
    );
  }

  const currentUserRow = presentation.leaderboard.find(
    (row) => row.isCurrentUser,
  );
  const sessionError =
    sessionState.lastError === null
      ? null
      : getSessionErrorMessage(sessionState.lastError);
  const isAdaptive = presentation.quizMode === "ADAPTIVE";
  const reviewRoomId = presentation.roomId;
  const reviewSessionId = presentation.sessionId;

  async function loadReview(): Promise<void> {
    if (reviewState.status === "loading") {
      return;
    }
    setReviewState({ status: "loading" });
    try {
      const response = await getSessionReview(reviewRoomId, reviewSessionId);
      setReviewState({
        status: "loaded",
        review: buildReviewPresentation(response),
      });
    } catch (error: unknown) {
      setReviewState({
        status: "error",
        message: getUserFacingErrorMessage(error),
      });
    }
  }

  return (
    <StudioScreen>
      <StudioText tone="primary" variant="label" style={styles.eyebrow}>
        RESULTS
      </StudioText>
      <StudioText variant="heading" style={styles.title}>
        Quiz complete
      </StudioText>
      <StudioText tone="muted" style={styles.description}>
        Final scores are confirmed by the MindMesh server.
      </StudioText>
      <StudioText accessibilityLiveRegion="polite" tone="primary" style={styles.connection}>
        {sessionState.phase === "reconnecting"
          ? "Reconnecting…"
          : sessionState.connectionStage === "established"
            ? "Results confirmed"
            : "Connection unavailable"}
      </StudioText>

      {sessionError !== null ? (
        <StudioCard style={styles.errorCard}>
          <StudioText accessibilityRole="alert" tone="error" style={styles.error}>
            {sessionError}
          </StudioText>
          {sessionState.phase === "recoverable-error" ? (
            <StudioButton label="Retry connection" onPress={retryConnection} />
          ) : null}
        </StudioCard>
      ) : null}

      {currentUserRow !== undefined ? (
        <StudioCard style={styles.scoreCard}>
          <StudioText tone="muted" variant="label" style={styles.scoreLabel}>
            YOUR RESULT
          </StudioText>
          <StudioText variant="heading" style={styles.score}>
            {isAdaptive
              ? `${presentation.totalEarnedMarks}/${presentation.totalAvailableMarks} marks`
              : `${currentUserRow.entry.total_points} points`}
          </StudioText>
          <StudioText tone="muted" style={styles.correctAnswers}>
            {isAdaptive
              ? `${currentUserRow.entry.correct_answers} of ${presentation.totalQuestions} full-mark answers`
              : `${currentUserRow.entry.correct_answers} of ${presentation.totalQuestions} correct`}
          </StudioText>
        </StudioCard>
      ) : null}

      <RoomRewardStatus
        key={`${authState.user.id}:${presentation.sessionId}`}
        sessionId={presentation.sessionId}
        userId={authState.user.id}
      />

      <View style={styles.leaderboardSection}>
        <StudioText variant="heading" style={styles.sectionTitle}>
          Final leaderboard
        </StudioText>
        <StudioCard>
          {presentation.leaderboard.map((row) => (
            <StudioLeaderboardRow
              key={row.entry.user_id}
              entry={row.entry}
              isCurrentUser={row.isCurrentUser}
              marksText={
                isAdaptive ? formatLeaderboardMarks(row.entry) : null
              }
              correctAnswersLabel={
                isAdaptive
                  ? formatCorrectAnswersLabel(
                      row.entry.correct_answers,
                      "ADAPTIVE",
                    )
                  : null
              }
              onReport={
                row.isCurrentUser
                  ? undefined
                  : () =>
                      router.push({
                        pathname: "/report",
                        params: {
                          roomId: routeRoomId,
                          reportedUserId: row.entry.user_id,
                          displayName: row.entry.display_name,
                        },
                      })
              }
              position={row.placement}
            />
          ))}
        </StudioCard>
      </View>

      <ResultsReviewSection
        reviewState={reviewState}
        onLoadReview={() => void loadReview()}
      />

      <View style={styles.actions}>
        <StudioButton
          disabled={!canDismissFinishedSession(sessionState)}
          label="Return to Room"
          onPress={dismissFinishedSession}
        />
      </View>
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  eyebrow: {
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 1.1,
  },
  title: {
    fontSize: 30,
    fontWeight: "800",
    lineHeight: 36,
    marginTop: spacing.xs,
  },
  description: {
    fontSize: 16,
    lineHeight: 23,
    marginTop: spacing.sm,
  },
  connection: {
    fontSize: 14,
    fontWeight: "700",
    marginTop: spacing.sm,
  },
  errorCard: {
    marginTop: spacing.lg,
  },
  error: {
    fontSize: 15,
    lineHeight: 21,
    marginBottom: spacing.md,
  },
  scoreCard: {
    alignItems: "center",
    marginTop: spacing.lg,
  },
  scoreLabel: {
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 1,
  },
  score: {
    fontSize: 36,
    fontWeight: "800",
    lineHeight: 43,
    marginTop: spacing.xs,
  },
  correctAnswers: {
    fontSize: 15,
    marginTop: spacing.xs,
  },
  leaderboardSection: {
    marginTop: spacing.lg,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "700",
    marginBottom: spacing.sm,
  },
  reviewSection: {
    marginTop: spacing.lg,
  },
  statusCard: {
    marginTop: spacing.md,
  },
  reviewCard: {
    marginTop: spacing.md,
  },
  reviewPosition: {
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 1,
  },
  reviewPrompt: {
    fontSize: 17,
    fontWeight: "700",
    lineHeight: 24,
    marginTop: spacing.sm,
  },
  reviewExtract: {
    borderRadius: 8,
    fontSize: 14,
    lineHeight: 21,
    marginTop: spacing.sm,
    padding: spacing.sm,
  },
  reviewResponse: {
    fontSize: 15,
    lineHeight: 22,
    marginTop: spacing.xs,
  },
  reviewFeedback: {
    fontSize: 15,
    lineHeight: 22,
    marginTop: spacing.sm,
  },
  reviewExplanation: {
    fontSize: 15,
    lineHeight: 22,
    marginTop: spacing.sm,
  },
  actions: {
    marginTop: spacing.lg,
  },
});
