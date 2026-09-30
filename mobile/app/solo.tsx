import { router } from "expo-router";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AppState, Pressable, StyleSheet, View } from "react-native";

import type { SoloAnswer, SoloAttempt, SoloQuestion } from "../src/api/solo";
import { useAuth } from "../src/auth/AuthContext";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import {
  StudioButton,
  StudioCard,
  StudioChoiceRow,
  StudioScreen,
  StudioText,
  StudioTextField,
} from "../src/components/studio/StudioPrimitives";
import { DrawingWorkspace } from "../src/features/drawing/DrawingWorkspace";
import {
  createDrawingLifecycle,
  dispatchDrawingLifecycle,
  reconcileDrawingLifecycle,
} from "../src/features/drawing/lifecycle";
import type { DrawingAction } from "../src/features/drawing/types";
import {
  ADAPTIVE_SUBJECTS,
  DEFAULT_TOTAL_MARKS,
  MAX_NUMERICAL_ANSWER_LENGTH,
  MAX_WRITTEN_ANSWER_LENGTH,
  getAdaptiveSelectionValidationMessage,
  getSubjectLabel,
  getTopicLabel,
  type AdaptiveQuizSelection,
  type AdaptiveSubject,
  type AdaptiveTopic,
} from "../src/features/quiz/adaptiveQuiz";
import { useSession } from "../src/features/session/SessionContext";
import { RewardSourceStatusCard } from "../src/features/learningCompanions/RoomRewardStatus";
import { SoloController, visibleSoloState } from "../src/features/solo/soloController";
import { soloDrawingBinding } from "../src/features/solo/soloDrawingBinding";

const MARKING_POLL_MS = 5_000;

function currentQuestion(attempt: SoloAttempt | null): SoloQuestion | null {
  if (attempt?.status !== "IN_PROGRESS") return null;
  return attempt.questions[attempt.current_question_position] ?? null;
}

function currentAnswer(attempt: SoloAttempt | null, question: SoloQuestion | null): SoloAnswer | null {
  if (attempt === null || question === null) return null;
  return attempt.answers.find((answer) => answer.question_id === question.id) ?? null;
}

function answerStatusLabel(answer: SoloAnswer): string {
  if (answer.mark_provenance === "SELF_ASSESSED") {
    return answer.grading_status === "SELF_CHECK_PENDING"
      ? "Answer saved. Your self-check is still needed."
      : `Self-assessed: ${answer.earned_marks ?? 0} marks`;
  }
  if (answer.grading_status === "GRADED") return `${answer.earned_marks ?? 0} marks, server marked`;
  if (answer.grading_status === "UNAVAILABLE") return "AI marking is delayed. Your answer is saved.";
  return "AI marking is in progress. Your answer is saved.";
}

function destinationForRoom(roomId: string, phase: string): string {
  return ["question-open", "submitting", "submitted", "grading", "reveal"].includes(phase)
    ? `/quiz?roomId=${encodeURIComponent(roomId)}`
    : `/waiting-room?roomId=${encodeURIComponent(roomId)}`;
}

export default function SoloRoute() {
  const theme = useStudioTheme();
  const { state: authState } = useAuth();
  const { state: sessionState } = useSession();
  const [controller] = useState(() => new SoloController());
  const stored = useSyncExternalStore(controller.subscribe, controller.getState, controller.getState);
  const profileAvailable = authState.status === "signed-in" &&
    authState.profileBootstrap.status !== "pending" &&
    authState.profileBootstrap.status !== "syncing" &&
    authState.profileBootstrap.status !== "recoverable-error";
  const roomRecovering = sessionState.phase === "recovering-room";
  const ownerId = profileAvailable && !roomRecovering && sessionState.roomId === null
    ? authState.user.id : null;
  const state = visibleSoloState(ownerId, stored);
  const attempt = state.attempt;
  const question = currentQuestion(attempt);
  const answer = currentAnswer(attempt, question);

  const [subject, setSubject] = useState<AdaptiveSubject>("physics");
  const [topic, setTopic] = useState<AdaptiveTopic>("energy");
  const [marksText, setMarksText] = useState(String(DEFAULT_TOTAL_MARKS));
  const [confirmCreate, setConfirmCreate] = useState(false);
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [selectedCriteria, setSelectedCriteria] = useState<readonly string[]>([]);
  const [appActive, setAppActive] = useState(AppState.currentState === "active");
  const [drawingState, setDrawingState] = useState(createDrawingLifecycle);
  const [drawingOpen, setDrawingOpen] = useState(false);

  const selection: AdaptiveQuizSelection = { subject, topic, totalMarks: Number(marksText) };
  const selectionError = getAdaptiveSelectionValidationMessage(selection);
  const drawingBinding = soloDrawingBinding(ownerId, attempt, appActive, state.needsReconcile);
  const latestDrawingBinding = useRef(drawingBinding);
  latestDrawingBinding.current = drawingBinding;
  const currentDrawing = reconcileDrawingLifecycle(
    drawingState, drawingBinding.scope, drawingBinding.phase, drawingBinding.connected,
  );

  useEffect(() => {
    controller.setOwner(ownerId);
    if (ownerId !== null) void controller.loadActive();
  }, [controller, ownerId]);

  useEffect(() => () => controller.dispose(), [controller]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (next) => setAppActive(next === "active"));
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    setDrawingState((previous) => reconcileDrawingLifecycle(
      previous, drawingBinding.scope, drawingBinding.phase, drawingBinding.connected,
    ));
  }, [
    drawingBinding.scope?.userId, drawingBinding.scope?.mode,
    drawingBinding.scope?.sessionId, drawingBinding.scope?.questionId,
    drawingBinding.phase, drawingBinding.connected,
  ]);

  useEffect(() => {
    if (!currentDrawing.visible || currentDrawing.epoch !== drawingState.epoch) setDrawingOpen(false);
  }, [currentDrawing.visible, currentDrawing.epoch, drawingState.epoch]);

  useEffect(() => {
    setSelectedOption(null);
    setAnswerText("");
    setSelectedCriteria([]);
    setConfirmAbandon(false);
  }, [attempt?.id, question?.id]);

  useEffect(() => {
    if (
      ownerId === null || !appActive || state.busy !== null || state.needsReconcile ||
      attempt === null || !(
        attempt.status === "PREPARING" || attempt.status === "AWAITING_MARKING" ||
        attempt.answers.some((item) => ["PENDING", "IN_PROGRESS", "RETRYABLE"].includes(item.grading_status))
      )
    ) return;
    const timer = setInterval(() => void controller.refresh(), MARKING_POLL_MS);
    return () => clearInterval(timer);
  }, [controller, ownerId, appActive, state.busy, state.needsReconcile, attempt]);

  useEffect(() => {
    if (ownerId !== null && attempt?.status === "FINISHED" && state.review === null) {
      void controller.loadReview();
    }
    // A failed review is retried by its visible button, not a render loop.
  }, [controller, ownerId, attempt?.id, attempt?.status]);

  function dispatchWorking(action: DrawingAction): void {
    const capturedEpoch = currentDrawing.epoch;
    setDrawingState((previous) => {
      const latest = latestDrawingBinding.current;
      const reconciled = reconcileDrawingLifecycle(
        previous, latest.scope, latest.phase, latest.connected,
      );
      return dispatchDrawingLifecycle(reconciled, capturedEpoch, action);
    });
  }

  function chooseSubject(next: AdaptiveSubject): void {
    setSubject(next);
    const first = ADAPTIVE_SUBJECTS.find((entry) => entry.id === next)?.topics[0];
    if (first !== undefined) setTopic(first.id);
    setConfirmCreate(false);
  }

  function toggleCriterion(id: string): void {
    setSelectedCriteria((current) => current.includes(id)
      ? current.filter((item) => item !== id)
      : [...current, id]);
  }

  function submitCurrentAnswer(): void {
    if (question === null || answer !== null || state.busy !== null || state.needsReconcile) return;
    if (question.question_type === "MULTIPLE_CHOICE") {
      if (selectedOption !== null) {
        void controller.submitAnswer({ question_id: question.id, selected_option_id: selectedOption });
      }
      return;
    }
    const clean = answerText.trim();
    if (clean) void controller.submitAnswer({ question_id: question.id, text: clean });
  }

  if (authState.status !== "signed-in") {
    return <StudioScreen><StudioText variant="title">Sign in to study solo.</StudioText></StudioScreen>;
  }
  if (!profileAvailable || roomRecovering) {
    return (
      <StudioScreen>
        <StudioText tone="primary" variant="eyebrow">SOLO STUDY</StudioText>
        <StudioText variant="title">Restoring your study state…</StudioText>
        <StudioText tone="muted">Finish profile and room recovery before starting solo practice.</StudioText>
      </StudioScreen>
    );
  }
  if (sessionState.roomId !== null) {
    return (
      <StudioScreen>
        <StudioText tone="primary" variant="eyebrow">SOLO STUDY</StudioText>
        <StudioText variant="title">Your room comes first.</StudioText>
        <StudioText tone="muted">Return to your active room before starting solo study.</StudioText>
        <StudioButton label="Return to room" onPress={() =>
          router.replace(destinationForRoom(sessionState.roomId as string, sessionState.phase))
        } />
      </StudioScreen>
    );
  }

  const busy = state.busy !== null;
  const hasUnavailableMarking = attempt?.answers.some((item) => item.grading_status === "UNAVAILABLE") ?? false;
  const pendingMarkingCount = attempt?.answers.filter((item) =>
    item.mark_provenance === "AI_RUBRIC" && item.grading_status !== "GRADED").length ?? 0;

  return (
    <StudioScreen>
      <StudioText tone="primary" variant="eyebrow">SOLO GCSE PRACTICE</StudioText>
      <StudioText variant="title" style={{ marginTop: theme.spacing.xs }}>
        Study at your own pace.
      </StudioText>
      <StudioText tone="muted" style={{ marginTop: theme.spacing.sm }}>
        Your answers are saved. Leaving this screen does not abandon your quiz.
      </StudioText>

      {state.error !== null ? (
        <StudioCard style={styles.section}>
          <StudioText tone="error" accessibilityRole="alert">{state.error}</StudioText>
          <StudioButton label="Refresh saved progress" variant="secondary" disabled={busy}
            onPress={() => void controller.refresh()} />
        </StudioCard>
      ) : null}
      {state.needsReconcile ? (
        <StudioCard style={styles.section}>
          <StudioText>Your last action may have saved. Refresh before continuing so an answer is not changed.</StudioText>
          <StudioButton label="Confirm saved progress" onPress={() => void controller.refresh()} disabled={busy} />
        </StudioCard>
      ) : null}

      {(!state.loaded && state.error === null) || state.busy === "load" ? (
        <StudioCard style={styles.section}><StudioText>Checking for a saved solo quiz…</StudioText></StudioCard>
      ) : null}

      {state.loaded && attempt === null ? (
        <StudioCard style={styles.section}>
          <StudioText variant="heading">Choose a quiz</StudioText>
          <StudioText tone="muted">Six GCSE subjects and 18 starter topics are available.</StudioText>
          <View style={styles.optionList}>
            {ADAPTIVE_SUBJECTS.map((entry) => (
              <StudioChoiceRow key={entry.id} title={entry.label}
                selected={entry.id === subject} disabled={busy || state.needsReconcile}
                onPress={() => chooseSubject(entry.id)} />
            ))}
          </View>
          <StudioText variant="label" style={styles.subheading}>Topic</StudioText>
          <View style={styles.optionList}>
            {ADAPTIVE_SUBJECTS.find((entry) => entry.id === subject)?.topics.map((entry) => (
              <StudioChoiceRow key={entry.id} title={entry.label}
                selected={entry.id === topic} disabled={busy || state.needsReconcile}
                onPress={() => { setTopic(entry.id); setConfirmCreate(false); }} />
            ))}
          </View>
          <StudioTextField label="Total marks" value={marksText}
            keyboardType="number-pad" maxLength={2} editable={!busy && !state.needsReconcile}
            onChangeText={(value) => { setMarksText(value); setConfirmCreate(false); }}
            error={selectionError ?? undefined} />
          {confirmCreate ? (
            <StudioCard style={styles.section}>
              <StudioText variant="heading">Ready to prepare this quiz?</StudioText>
              <StudioText>{getSubjectLabel(subject)} · {getTopicLabel(topic)} · {selection.totalMarks} marks</StudioText>
              <StudioText tone="muted">Preparation starts only when you confirm. There is no quiz timer.</StudioText>
              <StudioButton label="Confirm and prepare quiz" disabled={busy || selectionError !== null}
                onPress={() => void controller.create(selection)} />
              <StudioButton label="Change selection" variant="secondary" onPress={() => setConfirmCreate(false)} />
            </StudioCard>
          ) : (
            <StudioButton label="Review quiz selection" disabled={busy || state.needsReconcile || selectionError !== null}
              onPress={() => setConfirmCreate(true)} />
          )}
        </StudioCard>
      ) : null}

      {attempt?.status === "PREPARING" ? (
        <StudioCard style={styles.section}>
          <StudioText variant="heading">Preparing your quiz…</StudioText>
          <StudioText tone="muted">You can leave and resume later. Questions appear only after verification.</StudioText>
          <StudioButton label="Check preparation" variant="secondary" disabled={busy}
            onPress={() => void controller.refresh()} />
        </StudioCard>
      ) : null}

      {attempt?.status === "READY" ? (
        <StudioCard style={styles.section}>
          <StudioText variant="heading">Quiz ready</StudioText>
          <StudioText>{getSubjectLabel(attempt.subject)} · {getTopicLabel(attempt.topic)}</StudioText>
          <StudioText tone="muted">Begin when you are ready. Progress is saved without a timer.</StudioText>
          <StudioButton label="Start solo quiz" disabled={busy || state.needsReconcile}
            onPress={() => void controller.start()} />
        </StudioCard>
      ) : null}

      {question !== null && attempt !== null ? (
        <StudioCard style={styles.section}>
          <StudioText variant="heading">Question {question.position + 1} of {attempt.questions.length}</StudioText>
          <StudioText tone="muted">{question.max_marks} {question.max_marks === 1 ? "mark" : "marks"} · Untimed</StudioText>
          {question.original_extract ? <StudioText style={styles.extract}>{question.original_extract}</StudioText> : null}
          <StudioText style={styles.prompt}>{question.prompt}</StudioText>

          {drawingOpen && currentDrawing.visible ? (
            <View style={styles.drawingFocus}>
              <DrawingWorkspace document={currentDrawing.document} dispatch={dispatchWorking}
                editable={currentDrawing.phase === "answer-open"} onClose={() => setDrawingOpen(false)} />
            </View>
          ) : (
            <>
              <StudioText tone="muted">Scratchpad strokes stay on this device and are never submitted or marked.</StudioText>
              <StudioButton label="Open drawing workspace" variant="secondary"
                disabled={!currentDrawing.visible} onPress={() => setDrawingOpen(true)} />
              {answer === null ? (
                <>
                  {question.question_type === "MULTIPLE_CHOICE" ? (
                    <View style={styles.optionList}>
                      {question.options.map((option) => (
                        <StudioChoiceRow key={option.id} title={option.label}
                          selected={selectedOption === option.id} disabled={busy || state.needsReconcile}
                          onPress={() => setSelectedOption(option.id)} />
                      ))}
                    </View>
                  ) : (
                    <StudioTextField label={question.question_type === "NUMERICAL" ? "Your numerical answer" : "Your written answer"}
                      value={answerText} onChangeText={setAnswerText} multiline={question.question_type === "WRITTEN"}
                      maxLength={question.question_type === "NUMERICAL" ? MAX_NUMERICAL_ANSWER_LENGTH : MAX_WRITTEN_ANSWER_LENGTH}
                      editable={!busy && !state.needsReconcile} />
                  )}
                  <StudioText tone="muted">Submitting locks this answer. You cannot edit it afterwards.</StudioText>
                  <StudioButton label="Submit answer" disabled={busy || state.needsReconcile ||
                    (question.question_type === "MULTIPLE_CHOICE" ? selectedOption === null : answerText.trim().length === 0)}
                    onPress={submitCurrentAnswer} />
                </>
              ) : (
                <>
                  <StudioText tone="success">{answerStatusLabel(answer)}</StudioText>
                  {answer.grading_status === "SELF_CHECK_PENDING" && answer.mark_provenance === "SELF_ASSESSED" ? (
                    <>
                      <StudioText tone="muted">Your answer is locked. Compare it with the intended answer and mark the points you earned.</StudioText>
                      {state.selfCheck?.question_id === question.id ? (
                        <StudioCard style={styles.section}>
                          <StudioText variant="label">Your saved answer</StudioText>
                          <StudioText>{state.selfCheck.locked_answer}</StudioText>
                          <StudioText variant="label" style={styles.subheading}>Intended answer</StudioText>
                          <StudioText>{state.selfCheck.intended_answer}</StudioText>
                          <StudioText variant="label" style={styles.subheading}>Marking points</StudioText>
                          {state.selfCheck.criteria.map((criterion) => (
                            <Pressable key={criterion.id} accessibilityRole="checkbox"
                              accessibilityLabel={`${criterion.marking_point}, ${criterion.marks} marks`}
                              accessibilityState={{ checked: selectedCriteria.includes(criterion.id), disabled: busy || state.needsReconcile }}
                              disabled={busy || state.needsReconcile}
                              onPress={() => toggleCriterion(criterion.id)}
                              style={[styles.criterion, { borderColor: theme.colors.border, borderRadius: theme.radii.md }]}
                            >
                              <StudioText>{selectedCriteria.includes(criterion.id) ? "☑" : "□"} {criterion.marking_point}</StudioText>
                              <StudioText tone="muted">{criterion.explanation} · {criterion.marks} marks</StudioText>
                            </Pressable>
                          ))}
                          <StudioText tone="muted">Self-assessed marks describe your own check, not an official grade. No boxes ticked is a valid zero.</StudioText>
                          <StudioButton label="Finish self-check" disabled={busy || state.needsReconcile}
                            onPress={() => void controller.finalizeSelfCheck(selectedCriteria)} />
                        </StudioCard>
                      ) : (
                        <StudioButton label="Show marking guide" disabled={busy || state.needsReconcile}
                          onPress={() => void controller.loadSelfCheck()} />
                      )}
                    </>
                  ) : null}
                </>
              )}
            </>
          )}
        </StudioCard>
      ) : null}

      {attempt?.status === "IN_PROGRESS" && pendingMarkingCount > 0 ? (
        <StudioCard style={styles.section}>
          <StudioText>{pendingMarkingCount} longer {pendingMarkingCount === 1 ? "answer is" : "answers are"} awaiting AI marking.</StudioText>
          <StudioText tone="muted">You can continue other questions while marking runs.</StudioText>
        </StudioCard>
      ) : null}

      {attempt?.status === "AWAITING_MARKING" ? (
        <StudioCard style={styles.section}>
          <StudioText variant="heading">All answers saved. Marking is pending.</StudioText>
          <StudioText tone="muted">Your completed review and daily credit wait until marking finishes. You can leave and resume this status.</StudioText>
          {hasUnavailableMarking ? (
            <>
              <StudioText tone="error">AI marking is temporarily unavailable. No marks have been invented.</StudioText>
              <StudioButton label="Retry AI marking" disabled={busy || state.needsReconcile}
                onPress={() => void controller.retryMarking()} />
            </>
          ) : null}
          <StudioButton label="Check marking status" variant="secondary" disabled={busy}
            onPress={() => void controller.refresh()} />
        </StudioCard>
      ) : null}

      {attempt?.status === "FINISHED" ? (
        <>
          <StudioCard style={styles.section}>
            <StudioText variant="heading">Quiz complete</StudioText>
            <StudioText tone="muted">Every question has a saved answer. Self-assessed marks are labelled separately below.</StudioText>
            {state.review === null ? (
              <StudioButton label="Load completed review" disabled={busy}
                onPress={() => void controller.loadReview()} />
            ) : state.review.questions.map((item, index) => (
              <StudioCard key={item.question.id} style={styles.section}>
                <StudioText variant="label">Question {index + 1} · {item.question.max_marks} marks</StudioText>
                <StudioText>{item.question.prompt}</StudioText>
                <StudioText tone="muted">Your answer: {item.answer.answer_text ??
                  item.question.options.find((option) => option.id === item.answer.selected_option_id)?.label ?? "Selected option"}</StudioText>
                <StudioText>{answerStatusLabel(item.answer)}</StudioText>
                {item.question.question_type === "MULTIPLE_CHOICE" ? (
                  <StudioText>Correct option: {item.question.options.find((option) => option.id === item.correct_option_id)?.label ?? "Unavailable"}</StudioText>
                ) : <StudioText>Intended answer: {item.intended_answer}</StudioText>}
              </StudioCard>
            ))}
          </StudioCard>
          {ownerId !== null ? (
            <RewardSourceStatusCard key={`${ownerId}:${attempt.id}`} sourceKind="solo"
              sourceId={attempt.id} userId={ownerId} />
          ) : null}
        </>
      ) : null}

      {attempt?.status === "FAILED" || attempt?.status === "ABANDONED" ? (
        <StudioCard style={styles.section}>
          <StudioText variant="heading">{attempt.status === "FAILED" ? "Preparation did not finish" : "Quiz abandoned"}</StudioText>
          <StudioText tone="muted">This attempt does not earn daily credit.</StudioText>
          <StudioButton label="Choose another solo quiz" onPress={() => controller.clearTerminal()} disabled={busy} />
        </StudioCard>
      ) : null}

      {attempt !== null && ["PREPARING", "READY", "IN_PROGRESS", "AWAITING_MARKING"].includes(attempt.status) ? (
        <StudioCard style={styles.section}>
          {confirmAbandon ? (
            <>
              <StudioText variant="heading">Abandon this quiz?</StudioText>
              <StudioText tone="muted">Saved answers will no longer count toward a completed quiz or daily credit.</StudioText>
              <StudioButton label="Confirm abandon" variant="destructive" disabled={busy || state.needsReconcile}
                onPress={() => { setConfirmAbandon(false); void controller.abandon(); }} />
              <StudioButton label="Keep quiz" variant="secondary" onPress={() => setConfirmAbandon(false)} />
            </>
          ) : (
            <StudioButton label="Abandon quiz" variant="secondary" disabled={busy || state.needsReconcile}
              onPress={() => setConfirmAbandon(true)} />
          )}
        </StudioCard>
      ) : null}

      <View style={styles.footer}>
        <StudioButton label="Exit to Home" variant="secondary" onPress={() => router.replace("/")} />
      </View>
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: 16, gap: 12 },
  subheading: { marginTop: 12 },
  optionList: { gap: 8, marginVertical: 8 },
  extract: { marginTop: 12 },
  prompt: { marginVertical: 12 },
  drawingFocus: { minHeight: 680, marginTop: 12 },
  criterion: { borderWidth: 1, minHeight: 52, padding: 12, justifyContent: "center" },
  footer: { marginTop: 20 },
});
