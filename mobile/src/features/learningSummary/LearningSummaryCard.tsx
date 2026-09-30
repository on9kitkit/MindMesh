import { StyleSheet, View } from "react-native";

import type { LearningTopicKey, LearningTopicSummary } from "../../api/learningSummary";
import {
  StudioButton,
  StudioCard,
  StudioStack,
  StudioText,
} from "../../components/studio/StudioPrimitives";
import { getSubjectLabel, getTopicLabel } from "../quiz/adaptiveQuiz";
import { spacing } from "../../theme";
import type { LearningSummaryLoadState } from "./useLearningSummary";

export type LearningSummaryCardProps = {
  state: LearningSummaryLoadState;
  onRetry: () => void;
};

function labelForTopic(key: LearningTopicKey): string {
  return `${getSubjectLabel(key.subject) ?? key.subject} · ${getTopicLabel(key.topic) ?? key.topic}`;
}

function containsKey(keys: LearningTopicKey[], row: LearningTopicSummary): boolean {
  return keys.some((key) => key.subject === row.subject && key.topic === row.topic);
}

export function LearningSummaryCard({ state, onRetry }: LearningSummaryCardProps) {
  if (state.status === "inactive") return null;

  return (
    <StudioCard style={styles.card}>
      <StudioStack>
        <StudioText variant="heading">Your retained practice history</StudioText>
        <StudioText tone="muted">
          Your own finished adaptive GCSE practice that StudyRoom still retains,
          including previous rooms you left or that closed. Existing data purge
          or account deletion can remove it; this is not a lifetime record.
          These StudyRoom questions are not an AQA grade or full-syllabus measure.
        </StudioText>

        {state.status === "loading" ? (
          <StudioText accessibilityLiveRegion="polite" tone="muted">
            Loading your practice summary...
          </StudioText>
        ) : null}

        {state.status === "error" ? (
          <>
            <StudioText accessibilityLiveRegion="polite" accessibilityRole="alert" tone="error">
              {state.message ?? "Your practice summary is unavailable right now."}
            </StudioText>
            <StudioButton label="Try loading practice again" onPress={onRetry} variant="secondary" />
          </>
        ) : null}

        {state.status === "ready" ? (
          <>
            <StudioText accessibilityLiveRegion="polite" tone="muted">
              {`Showing ${state.summary.session_window.included} eligible finished sessions (newest 100 maximum).`}
              {state.summary.session_window.truncated
                ? " Older eligible sessions are not included."
                : ""}
            </StudioText>

            {state.summary.status === "no_data" ? (
              <StudioText tone="muted">
                No graded answers are available yet. Unanswered and ungraded
                questions are listed below when present.
              </StudioText>
            ) : null}

            {state.summary.status === "insufficient_evidence" ? (
              <StudioText tone="muted">
                Too little varied practice to compare topics yet. The display
                minimum is five distinct graded question versions across two finished
                sessions per topic; it is not a statistical confidence test.
              </StudioText>
            ) : null}

            {state.summary.topics.map((row) => {
              const isHigher = containsKey(state.summary.strongest_topics, row);
              const isLower = containsKey(state.summary.weakest_topics, row);
              const comparativeLabel =
                isHigher && isLower
                  ? "Tied among sampled topics in this subject."
                  : isHigher
                    ? "Relatively stronger in this subject's sampled topics."
                    : isLower
                      ? "Relatively weaker in this subject's sampled topics."
                      : null;
              return (
                <View key={`${row.subject}/${row.topic}`} style={styles.topic}>
                  <StudioText variant="heading">{labelForTopic(row)}</StudioText>
                  <StudioText>
                    {row.accuracy_on_graded_answers_percent === null
                      ? "Accuracy on graded answers: not available"
                      : `Accuracy on graded answers: ${row.accuracy_on_graded_answers_percent.toFixed(1)}% (${row.earned_marks}/${row.possible_marks} marks)`}
                  </StudioText>
                  <StudioText tone="muted">
                    {`${row.graded_attempt_count} graded attempts: ${row.full_credit_attempt_count} full, ${row.partial_credit_attempt_count} partial, ${row.zero_credit_attempt_count} zero credit. ${row.unanswered_question_count} unanswered; ${row.ungraded_attempt_count} ungraded.`}
                  </StudioText>
                  <StudioText tone="muted">
                    {`${row.distinct_question_count} distinct graded question versions, ${row.repeat_attempt_count} repeat attempts across ${row.finished_session_count} finished sessions. Exact-match repeats only; similar questions may not be detected.`}
                  </StudioText>
                  {row.evidence_status === "insufficient_evidence" ? (
                    <StudioText tone="muted">Small sample; no relative topic comparison yet.</StudioText>
                  ) : null}
                  {comparativeLabel ? (
                    <StudioText tone="muted">{comparativeLabel}</StudioText>
                  ) : null}
                </View>
              );
            })}
            <StudioButton
              label="Refresh practice summary"
              onPress={onRetry}
              variant="secondary"
            />
          </>
        ) : null}
      </StudioStack>
    </StudioCard>
  );
}

const styles = StyleSheet.create({
  card: { marginTop: spacing.md },
  topic: { gap: spacing.xs, marginTop: spacing.sm },
});
