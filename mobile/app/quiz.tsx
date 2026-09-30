import { useLocalSearchParams } from "expo-router";
import { useEffect, useReducer, useRef, useState } from "react";
import { AppState, StyleSheet, View } from "react-native";

import { useAuth } from "../src/auth/AuthContext";
import {
  StudioButton,
  StudioCard,
  StudioScreen,
  StudioText,
  StudioTextField,
} from "../src/components/studio/StudioPrimitives";
import { StudioLeaderboardRow } from "../src/components/LeaderboardRow";
import { StudioQuizOption } from "../src/components/QuizOption";
import {
  parseEnrichedWrittenFeedback,
  type EnrichedWrittenFeedback,
} from "../src/feedback/gradingFeedback";
import {
  formatEarnedMarks,
  getGradingStatusLabel,
  MAX_WRITTEN_ANSWER_LENGTH,
} from "../src/features/quiz/adaptiveQuiz";
import { VisualLearningCard } from "../src/features/learning";
import { DrawingWorkspace } from "../src/features/drawing/DrawingWorkspace";
import {
  createDrawingLifecycle,
  dispatchDrawingLifecycle,
  reconcileDrawingLifecycle,
} from "../src/features/drawing/lifecycle";
import { roomDrawingBinding } from "../src/features/drawing/roomBinding";
import type { DrawingAction } from "../src/features/drawing/types";
import { useServerCountdown } from "../src/features/quiz/countdown";
import {
  buildQuizPresentation,
  getQuizCountdownInput,
  getQuizOptionAppearance,
  getSubmissionStatusLabel,
  initialQuizSelectionState,
  quizSelectionReducer,
} from "../src/features/quiz/quizPresentation";
import {
  formatCorrectAnswersLabel,
  formatLeaderboardMarks,
} from "../src/features/quiz/resultsPresentation";
import { useSession } from "../src/features/session/SessionContext";
import { getSessionErrorMessage } from "../src/features/session/sessionErrorMessages";
import { parseViewerFeedbackSummary } from "../src/realtime/protocol";
import { StudyRoomRealtimeError } from "../src/realtime/errors";
import { spacing } from "../src/theme";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";

const STALE_SELECTION_ERROR_CODES = new Set([
  "stale_session_question",
  "invalid_option",
]);

const NUMERICAL_INPUT_MAX_LENGTH = 64;

export default function QuizRoute() {
  const { state: authState } = useAuth();
  const {
    state: sessionState,
    retryConnection,
    submitAnswer,
    submitTextAnswer,
    retryGrading,
  } = useSession();
  const { roomId: rawRoomId } = useLocalSearchParams<{
    roomId?: string | string[];
  }>();
  const routeRoomId = typeof rawRoomId === "string" ? rawRoomId : null;
  const [selection, selectionDispatch] = useReducer(
    quizSelectionReducer,
    initialQuizSelectionState,
  );
  const [localCommandError, setLocalCommandError] = useState<string | null>(
    null,
  );
  const [appActive, setAppActive] = useState(AppState.currentState === "active");
  const [drawingState, setDrawingState] = useState(createDrawingLifecycle);
  const [drawingOpen, setDrawingOpen] = useState(false);
  const countdownInput = getQuizCountdownInput(sessionState);
  const countdown = useServerCountdown(
    countdownInput?.serverTime ?? null,
    countdownInput?.deadline ?? null,
  );
  const theme = useStudioTheme();
  const presentation = buildQuizPresentation(
    sessionState,
    selection,
    countdown.expired,
  );
  const currentQuestionId = presentation?.sessionQuestionId ?? null;
  const drawingBinding = roomDrawingBinding(
    authState.status === "signed-in" ? authState.user.id : null,
    routeRoomId,
    sessionState,
    presentation,
    appActive,
  );
  const latestDrawingBinding = useRef(drawingBinding);
  latestDrawingBinding.current = drawingBinding;
  const currentDrawing = reconcileDrawingLifecycle(
    drawingState,
    drawingBinding.scope,
    drawingBinding.phase,
    drawingBinding.connected,
  );

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      setAppActive(state === "active");
    });
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    setDrawingState((previous) =>
      reconcileDrawingLifecycle(
        previous,
        drawingBinding.scope,
        drawingBinding.phase,
        drawingBinding.connected,
      ),
    );
  }, [
    drawingBinding.scope?.userId,
    drawingBinding.scope?.mode,
    drawingBinding.scope?.sessionId,
    drawingBinding.scope?.questionId,
    drawingBinding.phase,
    drawingBinding.connected,
  ]);

  useEffect(() => {
    if (drawingBinding.scope === null || currentDrawing.epoch !== drawingState.epoch) {
      setDrawingOpen(false);
    }
  }, [drawingBinding.scope === null, currentDrawing.epoch, drawingState.epoch]);

  function dispatchWorking(action: DrawingAction): void {
    const capturedEpoch = currentDrawing.epoch;
    setDrawingState((previous) => {
      const latest = latestDrawingBinding.current;
      const reconciled = reconcileDrawingLifecycle(
        previous,
        latest.scope,
        latest.phase,
        latest.connected,
      );
      return dispatchDrawingLifecycle(reconciled, capturedEpoch, action);
    });
  }

  useEffect(() => {
    if (currentQuestionId !== null) {
      selectionDispatch({
        type: "QUESTION_CHANGED",
        sessionQuestionId: currentQuestionId,
      });
    }
    setLocalCommandError(null);
  }, [currentQuestionId]);

  useEffect(() => {
    const code = sessionState.lastError?.code;
    if (code !== undefined && STALE_SELECTION_ERROR_CODES.has(code)) {
      selectionDispatch({ type: "SELECTION_CLEARED" });
    }
  }, [sessionState.lastError]);

  if (
    authState.status !== "signed-in" ||
    routeRoomId === null ||
    routeRoomId !== sessionState.roomId ||
    presentation === null
  ) {
    return (
      <StudioScreen>
        <StudioText color={theme.colors.primary} variant="eyebrow">
          PHYSICS SPRINT
        </StudioText>
        <StudioText variant="title" style={styles.title}>
          Opening the current quiz...
        </StudioText>
        <StudioText tone="muted" style={styles.description}>
          Waiting for the latest authoritative session state.
        </StudioText>
      </StudioScreen>
    );
  }

  const sessionError =
    sessionState.lastError === null
      ? null
      : getSessionErrorMessage(sessionState.lastError);
  const visibleError = localCommandError ?? sessionError;
  const reconnecting = sessionState.phase === "reconnecting";
  const connectionLabel = reconnecting
    ? "Reconnecting…"
    : sessionState.connectionStage === "established"
      ? "Connected"
      : "Connection unavailable";
  const eyebrow =
    presentation.quizMode === "ADAPTIVE" ? "ADAPTIVE GCSE" : "PHYSICS SPRINT";
  const isAdaptive = presentation.quizMode === "ADAPTIVE";

  function selectOption(optionId: string): void {
    const currentPresentation = presentation;
    if (
      currentPresentation === null ||
      currentPresentation.status !== "question-open" ||
      !currentPresentation.canInteract
    ) {
      return;
    }
    setLocalCommandError(null);
    selectionDispatch({
      type: "OPTION_SELECTED",
      sessionQuestionId: currentPresentation.sessionQuestionId,
      selectedOptionId: optionId,
    });
  }

  function changeText(text: string): void {
    const currentPresentation = presentation;
    if (
      currentPresentation === null ||
      currentPresentation.status !== "question-open" ||
      !currentPresentation.canInteract
    ) {
      return;
    }
    selectionDispatch({
      type: "TEXT_CHANGED",
      sessionQuestionId: currentPresentation.sessionQuestionId,
      text,
    });
  }

  function sendAnswer(): void {
    const currentPresentation = presentation;
    if (
      currentPresentation === null ||
      currentPresentation.status !== "question-open" ||
      !currentPresentation.canSubmit
    ) {
      return;
    }
    setLocalCommandError(null);
    try {
      if (currentPresentation.questionType === "MULTIPLE_CHOICE") {
        if (currentPresentation.selectedOptionId === null) {
          return;
        }
        submitAnswer(
          currentPresentation.sessionQuestionId,
          currentPresentation.selectedOptionId,
        );
      } else {
        submitTextAnswer(
          currentPresentation.sessionQuestionId,
          currentPresentation.draftText,
        );
      }
    } catch (error: unknown) {
      setLocalCommandError(
        error instanceof StudyRoomRealtimeError
          ? getSessionErrorMessage(error)
          : "Your answer could not be submitted right now.",
      );
    }
  }

  function retryDelayedGrading(): void {
    setLocalCommandError(null);
    try {
      retryGrading();
    } catch (error: unknown) {
      setLocalCommandError(
        error instanceof StudyRoomRealtimeError
          ? getSessionErrorMessage(error)
          : "Marking could not be retried right now.",
      );
    }
  }

  const questionContent = (
    <>
      {presentation.originalExtract !== null ? (
        <View
          style={[
            styles.extractBlock,
            { backgroundColor: theme.colors.selectedBackground },
          ]}
        >
          <StudioText tone="muted" variant="label" style={styles.extractLabel}>
            SOURCE EXTRACT
          </StudioText>
          <StudioText style={styles.extract}>
            {presentation.originalExtract}
          </StudioText>
        </View>
      ) : null}
      <StudioText style={styles.question}>{presentation.prompt}</StudioText>
    </>
  );

  return (
    <StudioScreen>
      <View style={styles.progressRow}>
        <StudioText color={theme.colors.primary} variant="eyebrow">
          {eyebrow}
        </StudioText>
        <StudioText tone="muted" variant="caption" style={styles.progressText}>
          Question {presentation.questionNumber} of {presentation.totalQuestions}
        </StudioText>
      </View>
      <View style={styles.statusRow}>
        <StudioText
          accessibilityLiveRegion="polite"
          color={theme.colors.primary}
          variant="caption"
          style={styles.connection}
        >
          {connectionLabel}
        </StudioText>
        <StudioText tone="muted" variant="caption" style={styles.countdown}>
          {presentation.status === "question-open"
            ? `Time remaining: ${countdown.remainingWholeSeconds}s`
            : presentation.status === "question-grading"
              ? "Marking answers"
              : `Next question in: ${countdown.remainingWholeSeconds}s`}
        </StudioText>
      </View>
      {isAdaptive ? (
        <StudioText tone="muted" variant="caption" style={styles.marksBudget}>
          Worth {presentation.maxMarks} {presentation.maxMarks === 1 ? "mark" : "marks"}
        </StudioText>
      ) : null}

      {visibleError !== null ? (
        <StudioCard style={styles.errorCard}>
          <StudioText accessibilityRole="alert" tone="error" style={styles.error}>
            {visibleError}
          </StudioText>
          {sessionState.phase === "recoverable-error" ? (
            <StudioButton label="Retry connection" onPress={retryConnection} />
          ) : null}
        </StudioCard>
      ) : null}

      {drawingOpen ? (
        <View style={styles.drawingFocus}>
          <StudioCard style={styles.drawingPrompt}>
            <StudioText variant="label">Current question</StudioText>
            {questionContent}
          </StudioCard>
          {currentDrawing.visible ? (
            <DrawingWorkspace
              document={currentDrawing.document}
              dispatch={dispatchWorking}
              editable={currentDrawing.phase === "answer-open"}
              onClose={() => {
                dispatchWorking({ type: "CANCEL" });
                setDrawingOpen(false);
              }}
              theme={theme}
            />
          ) : (
            <StudioCard>
              <StudioText tone="muted">
                Reconnecting before showing private working for this question.
              </StudioText>
              <StudioButton
                label="Return to answer"
                onPress={() => setDrawingOpen(false)}
                variant="secondary"
              />
            </StudioCard>
          )}
        </View>
      ) : (
        <>
      <StudioCard style={styles.questionCard}>
        {questionContent}
        {presentation.status === "question-open" &&
        presentation.questionType === "MULTIPLE_CHOICE" ? (
          <View style={styles.options}>
            {presentation.options.map((option) => {
              const appearance = getQuizOptionAppearance(presentation, option.id);
              const selected = presentation.selectedOptionId === option.id;
              return (
                <StudioQuizOption
                  key={option.id}
                  appearance={appearance}
                  disabled={
                    presentation.status !== "question-open" ||
                    !presentation.canInteract
                  }
                  onPress={() => selectOption(option.id)}
                  option={option}
                  selected={selected}
                />
              );
            })}
          </View>
        ) : null}
        {presentation.status === "question-open" &&
        presentation.questionType === "NUMERICAL" ? (
          <View style={styles.textBlock}>
            <StudioTextField
              accessibilityLabel="Numerical answer"
              label="Numerical answer"
              autoCorrect={false}
              editable={presentation.canInteract}
              keyboardType="numbers-and-punctuation"
              maxLength={NUMERICAL_INPUT_MAX_LENGTH}
              onChangeText={changeText}
              placeholder="Type the value with its unit"
              value={presentation.draftText}
            />
          </View>
        ) : null}
        {presentation.status === "question-open" &&
        presentation.questionType === "WRITTEN" ? (
          <View style={styles.textBlock}>
            <StudioTextField
              accessibilityLabel="Written answer"
              label="Written answer"
              autoCorrect
              editable={presentation.canInteract}
              maxLength={MAX_WRITTEN_ANSWER_LENGTH}
              multiline
              numberOfLines={5}
              onChangeText={changeText}
              placeholder="Explain in your own words"
              textAlignVertical="top"
              inputStyle={styles.multilineInput}
              value={presentation.draftText}
            />
            <StudioText tone="muted" variant="caption" style={styles.characterCount}>
              {presentation.draftText.length}/{MAX_WRITTEN_ANSWER_LENGTH}
            </StudioText>
          </View>
        ) : null}
      </StudioCard>

      <StudioCard style={styles.workingCard}>
        <StudioText variant="label">Private working</StudioText>
        <StudioText tone="muted" variant="caption" style={styles.workingDescription}>
          Draw maths notes for this question. They are not submitted or marked.
        </StudioText>
        <StudioButton
          label="Open drawing workspace"
          disabled={!currentDrawing.visible}
          onPress={() => setDrawingOpen(true)}
          variant="secondary"
        />
        {!currentDrawing.visible ? (
          <StudioText tone="muted" variant="caption">
            Reconnect to view private working.
          </StudioText>
        ) : null}
      </StudioCard>

      {presentation.status === "question-open" ? (
        <View style={styles.buttonContainer}>
          <StudioButton
            label={getSubmissionStatusLabel(presentation.submissionStatus)}
            disabled={!presentation.canSubmit}
            onPress={sendAnswer}
          />
          {presentation.submissionStatus === "submitted" ? (
            <StudioText
              accessibilityLiveRegion="polite"
              tone="success"
              style={styles.acknowledgement}
            >
              Answer submitted.
              {presentation.ownGradingStatus !== null &&
              presentation.ownGradingStatus !== "GRADED"
                ? ` ${getGradingStatusLabel(presentation.ownGradingStatus)}.`
                : ""}
            </StudioText>
          ) : countdown.expired ? (
            <StudioText
              accessibilityLiveRegion="polite"
              tone="muted"
              style={styles.waitingMessage}
            >
              The answer window has closed. Waiting for the server.
            </StudioText>
          ) : null}
        </View>
      ) : presentation.status === "question-grading" ? (
        <GradingPanel
          presentation={presentation}
          onRetry={retryDelayedGrading}
        />
      ) : (
        <RevealPanel
          authenticatedUserId={authState.user.id}
          isAdaptive={isAdaptive}
          presentation={presentation}
          subject={sessionState.snapshot?.room_state.quiz_subject ?? null}
          topic={sessionState.snapshot?.room_state.quiz_topic ?? null}
        />
      )}
        </>
      )}
    </StudioScreen>
  );
}

type GradingPanelProps = {
  presentation: Extract<
    NonNullable<ReturnType<typeof buildQuizPresentation>>,
    { status: "question-grading" }
  >;
  onRetry(): void;
};

function GradingPanel({ presentation, onRetry }: GradingPanelProps) {
  const status = presentation.ownGradingStatus;
  const title =
    status === "UNAVAILABLE" ? "Marking unavailable" : "Marking in progress";
  return (
    <StudioCard style={styles.revealCard}>
      <StudioText
        accessibilityLiveRegion="polite"
        tone={status === "UNAVAILABLE" ? "error" : "primary"}
        style={styles.revealTitle}
      >
        {title}
      </StudioText>
      {presentation.ownSelectedOptionId !== null ||
      presentation.ownAnswerText !== null ? (
        <StudioText tone="muted" style={styles.revealDetail}>
          Your answer:{" "}
          {presentation.ownSelectedOptionId !== null
            ? (presentation.options.find(
                (option) => option.id === presentation.ownSelectedOptionId,
              )?.label ?? "Unavailable")
            : (presentation.ownAnswerText ?? "Unavailable")}
        </StudioText>
      ) : (
        <StudioText tone="muted" style={styles.revealDetail}>
          No answer submitted.
        </StudioText>
      )}
      <StudioText tone="muted" style={styles.waitingMessage}>
        Marks appear here once the server finishes marking. Response time
        never changes your mark.
      </StudioText>
      {presentation.gradingRetryNeeded ? (
        <View style={styles.buttonContainer}>
          {presentation.canRetryGrading ? (
            <StudioButton
              label="Retry Marking"
              onPress={onRetry}
              variant="secondary"
            />
          ) : (
            <StudioText
              accessibilityLiveRegion="polite"
              tone="muted"
              style={styles.waitingMessage}
            >
              Marking is delayed for this question. The host can retry marking.
            </StudioText>
          )}
        </View>
      ) : null}
    </StudioCard>
  );
}

function readEnrichedFeedback(
  feedback: Record<string, unknown> | null,
): EnrichedWrittenFeedback | null {
  if (feedback === null) {
    return null;
  }
  try {
    return parseEnrichedWrittenFeedback(feedback);
  } catch {
    return null;
  }
}

function MarkingPointsFeedback({
  feedback,
}: {
  feedback: EnrichedWrittenFeedback;
}) {
  return (
    <>
      {feedback.summary.length > 0 ? (
        <StudioText style={styles.feedback}>{feedback.summary}</StudioText>
      ) : null}
      {feedback.awarded.length > 0 ? (
        <>
          <StudioText tone="muted" style={styles.explanationLabel}>
            MARKING POINTS AWARDED
          </StudioText>
          {feedback.awarded.map((point) => (
            <StudioText key={point.id} tone="muted" style={styles.revealDetail}>
              {point.explanation} (+{point.marks}{" "}
              {point.marks === 1 ? "mark" : "marks"})
            </StudioText>
          ))}
        </>
      ) : null}
      {feedback.missing.length > 0 ? (
        <>
          <StudioText tone="muted" style={styles.explanationLabel}>
            STILL MISSING
          </StudioText>
          {feedback.missing.map((point) => (
            <StudioText key={point.id} tone="muted" style={styles.revealDetail}>
              {point.explanation} (worth {point.marks}{" "}
              {point.marks === 1 ? "mark" : "marks"})
            </StudioText>
          ))}
        </>
      ) : null}
    </>
  );
}

type RevealPanelProps = {
  authenticatedUserId: string;
  isAdaptive: boolean;
  subject: string | null;
  topic: string | null;
  presentation: Extract<
    NonNullable<ReturnType<typeof buildQuizPresentation>>,
    { status: "question-reveal" }
  >;
};

function RevealPanel({
  authenticatedUserId,
  isAdaptive,
  presentation,
  subject,
  topic,
}: RevealPanelProps) {
  const theme = useStudioTheme();
  const submission = presentation.viewerSubmission;
  const selectedOptionLabel = presentation.options.find(
    (option) => option.id === submission?.selected_option_id,
  )?.label;
  const feedbackSummary =
    submission === null ? null : parseViewerFeedbackSummary(submission.feedback);
  const enrichedFeedback = readEnrichedFeedback(
    submission === null ? null : submission.feedback,
  );
  const earnedMarks = submission?.earned_marks ?? null;
  const maxMarks = submission?.max_marks ?? presentation.maxMarks;
  const fullyCorrect = submission?.is_correct === true;

  return (
    <>
      <StudioCard style={styles.revealCard}>
        <StudioText
          accessibilityLiveRegion="polite"
          color={fullyCorrect ? theme.colors.success : theme.colors.error}
          style={styles.revealTitle}
        >
          {submission === null
            ? "No answer submitted"
            : fullyCorrect
              ? "Correct"
              : earnedMarks !== null && earnedMarks > 0
                ? "Partially correct"
                : "Incorrect"}
        </StudioText>
        {submission !== null ? (
          <>
            <StudioText tone="muted" style={styles.revealDetail}>
              Your answer:{" "}
              {selectedOptionLabel ??
                submission.answer_text ??
                "Unavailable"}
            </StudioText>
            {submission.grading_status === "UNAVAILABLE" ? (
              <StudioText tone="muted" style={styles.revealDetail}>
                {getGradingStatusLabel("UNAVAILABLE")}.
              </StudioText>
            ) : isAdaptive || earnedMarks !== null ? (
              <StudioText style={styles.points}>
                {formatEarnedMarks(earnedMarks, maxMarks)}
              </StudioText>
            ) : (
              <StudioText style={styles.points}>{submission.points} points</StudioText>
            )}
            {enrichedFeedback !== null ? (
              <MarkingPointsFeedback feedback={enrichedFeedback} />
            ) : (
              <>
                {submission.awarded_criterion_ids.length > 0 ? (
                  <StudioText tone="muted" style={styles.revealDetail}>
                    Marking points awarded:{" "}
                    {submission.awarded_criterion_ids.length}
                  </StudioText>
                ) : null}
                {feedbackSummary !== null ? (
                  <StudioText style={styles.feedback}>{feedbackSummary}</StudioText>
                ) : null}
              </>
            )}
          </>
        ) : null}
        {presentation.correctOptionId !== null ? (
          <StudioText tone="muted" style={styles.revealDetail}>
            Correct answer:{" "}
            {presentation.options.find(
              (option) => option.id === presentation.correctOptionId,
            )?.label ?? "Unavailable"}
          </StudioText>
        ) : null}
        {presentation.workedExplanation.length > 0 ? (
          <>
            <StudioText tone="muted" style={styles.explanationLabel}>
              WHY THIS ANSWER
            </StudioText>
            <StudioText style={styles.explanation}>
              {presentation.workedExplanation}
            </StudioText>
          </>
        ) : null}
      </StudioCard>

      {isAdaptive && subject !== null && topic !== null ? (
        <VisualLearningCard
          subject={subject}
          topic={topic}
          isRevealed={presentation.status === "question-reveal"}
          theme={theme}
        />
      ) : null}

      {presentation.leaderboard.length > 0 ? (
        <View style={styles.leaderboardSection}>
          <StudioText variant="heading" style={styles.sectionTitle}>
            Current leaderboard
          </StudioText>
          <StudioCard>
            {presentation.leaderboard.map((entry) => (
              <StudioLeaderboardRow
                key={entry.user_id}
                entry={entry}
                isCurrentUser={entry.user_id === authenticatedUserId}
                marksText={
                  isAdaptive ? formatLeaderboardMarks(entry) : null
                }
                correctAnswersLabel={
                  isAdaptive
                    ? formatCorrectAnswersLabel(
                        entry.correct_answers,
                        "ADAPTIVE",
                      )
                    : null
                }
                position={entry.rank}
              />
            ))}
          </StudioCard>
        </View>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  drawingFocus: {
    minHeight: 680,
    marginTop: spacing.md,
  },
  drawingPrompt: {
    marginBottom: spacing.sm,
  },
  workingCard: {
    marginTop: spacing.md,
  },
  workingDescription: {
    marginBottom: spacing.sm,
  },
  progressRow: {
    alignItems: "flex-start",
    flexDirection: "row",
    justifyContent: "space-between",
  },
  statusRow: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: spacing.sm,
  },
  eyebrow: {
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 1.1,
  },
  title: {
    fontSize: 30,
    fontWeight: "800",
    marginTop: spacing.xs,
  },
  description: {
    fontSize: 16,
    lineHeight: 23,
    marginTop: spacing.sm,
  },
  marksBudget: {
    fontSize: 14,
    fontWeight: "700",
    marginTop: spacing.xs,
  },
  progressText: {
    fontSize: 14,
  },
  connection: {
    fontSize: 14,
    fontWeight: "700",
  },
  countdown: {
    fontSize: 14,
    fontWeight: "700",
  },
  errorCard: {
    marginTop: spacing.md,
  },
  error: {
    fontSize: 15,
    lineHeight: 21,
    marginBottom: spacing.md,
  },
  questionCard: {
    marginTop: spacing.md,
  },
  question: {
    fontSize: 23,
    fontWeight: "700",
    lineHeight: 31,
  },
  extractBlock: {
    borderRadius: 8,
    marginBottom: spacing.md,
    padding: spacing.sm,
  },
  extractLabel: {
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 1,
  },
  extract: {
    fontSize: 15,
    lineHeight: 22,
    marginTop: spacing.xs,
  },
  options: {
    marginTop: spacing.sm,
  },
  textBlock: {
    marginTop: spacing.md,
  },
  multilineInput: {
    minHeight: 140,
  },
  characterCount: {
    fontSize: 13,
    marginTop: spacing.xs,
    textAlign: "right",
  },
  buttonContainer: {
    marginTop: spacing.lg,
  },
  acknowledgement: {
    fontSize: 15,
    fontWeight: "700",
    marginTop: spacing.sm,
    textAlign: "center",
  },
  waitingMessage: {
    fontSize: 14,
    lineHeight: 20,
    marginTop: spacing.sm,
    textAlign: "center",
  },
  revealCard: {
    marginTop: spacing.lg,
  },
  revealTitle: {
    fontSize: 24,
    fontWeight: "800",
  },
  revealDetail: {
    fontSize: 15,
    marginTop: spacing.sm,
  },
  feedback: {
    fontSize: 15,
    lineHeight: 22,
    marginTop: spacing.sm,
  },
  explanationLabel: {
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 1,
    marginTop: spacing.md,
  },
  explanation: {
    fontSize: 15,
    lineHeight: 22,
    marginTop: spacing.xs,
  },
  points: {
    fontSize: 18,
    fontWeight: "800",
    marginTop: spacing.sm,
  },
  leaderboardSection: {
    marginTop: spacing.lg,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "700",
    marginBottom: spacing.sm,
  },
});
