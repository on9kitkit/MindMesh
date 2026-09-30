import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useRef, useSyncExternalStore } from "react";
import { StyleSheet } from "react-native";

import { submitSafetyReport } from "../src/api/safetyReports";
import { useAuth } from "../src/auth/AuthContext";
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
  ParticipantReportController,
  type ReportDraft,
} from "../src/features/safety/reportFlow";
import type { SafetyReportReason } from "../src/api/schemas";
import type { AuthState } from "../src/auth/authFlow";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import { spacing } from "../src/theme";

const REASONS: ReadonlyArray<{
  value: SafetyReportReason;
  label: string;
}> = [
  {
    value: "inappropriate_display_name",
    label: "Inappropriate display name",
  },
  {
    value: "disruptive_room_behaviour",
    label: "Disruptive room behaviour",
  },
  { value: "other_safety_concern", label: "Other safety concern" },
];

function draftForState(
  state: ReturnType<ParticipantReportController["getState"]>,
): ReportDraft | null {
  return state.status === "success" ? null : state.draft;
}

export type ReportPresentationProps = {
  authState: Extract<AuthState, { status: "signed-in" }>;
  controller: ParticipantReportController;
  displayName: string;
  roomId: string;
  reportedUserId: string;
  state: ReturnType<ParticipantReportController["getState"]>;
};

export function ReportPresentation({
  controller,
  displayName,
  roomId,
  reportedUserId,
  state,
}: ReportPresentationProps) {
  const theme = useStudioTheme();
  const draft = draftForState(state);
  const isSelecting = state.status === "selecting";
  const isReviewing = state.status === "reviewing";
  const isSubmitting = state.status === "submitting";
  const isError = state.status === "error";

  if (state.status === "success") {
    return (
      <StudioScreen>
        <StudioText variant="eyebrow">SAFETY</StudioText>
        <StudioText variant="title" style={styles.title}>Report received.</StudioText>
        <StudioCard style={styles.card}>
          <StudioText accessibilityLiveRegion="polite" tone="muted" style={styles.body}>
            Thank you. MindMesh will review the concern. Submitting a report
            does not automatically punish another participant.
          </StudioText>
          <StudioButton label="Return to room" onPress={() => router.back()} />
        </StudioCard>
      </StudioScreen>
    );
  }

  if (draft === null) return null;

  return (
    <StudioScreen>
      <StudioText variant="eyebrow">SAFETY</StudioText>
      <StudioText variant="title" style={styles.title}>Report a safety concern</StudioText>
      <StudioText tone="muted" style={styles.description}>
        Reporting participant: {displayName}
      </StudioText>

      {isSelecting ? (
        <StudioCard style={styles.card}>
          <StudioStack>
            <StudioText variant="heading">What happened?</StudioText>
            <StudioText tone="muted" style={styles.body}>
              Choose the closest reason. Only report concerns from this current
              room or quiz context.
            </StudioText>
            {REASONS.map((reason) => (
              // StudioChoiceRow forwards accessibilityRole="radio" and checked state.
              <StudioChoiceRow
                accessibilityLabel={reason.label}
                key={reason.value}
                onPress={() => controller.setReason(reason.value)}
                selected={draft.reason === reason.value}
                title={reason.label}
              />
            ))}
            <StudioTextField
              accessibilityLabel="Optional report details"
              autoCapitalize="sentences"
              autoCorrect
              editable
              inputStyle={styles.detailsInput}
              label="DETAILS"
              multiline
              maxLength={500}
              onChangeText={(value) => controller.setDetails(value)}
              placeholder="Optional details — do not include contact information"
              textAlignVertical="top"
              value={draft.details}
            />
            <StudioText tone="muted" style={styles.helper}>
              Do not include passwords, tokens, email addresses, phone numbers,
              or other contact details.
            </StudioText>
            {state.errorMessage !== null ? (
              <StudioText accessibilityLiveRegion="polite" accessibilityRole="alert" tone="error" style={[styles.error, { backgroundColor: theme.colors.errorBackground }]}>
                {state.errorMessage}
              </StudioText>
            ) : null}
            <StudioButton label="Review report" onPress={() => controller.review()} />
          </StudioStack>
        </StudioCard>
      ) : null}

      {isReviewing || isSubmitting || isError ? (
        <StudioCard style={styles.card}>
          <StudioStack>
            <StudioText variant="heading">Review your report</StudioText>
            <StudioText tone="muted" style={styles.body}>
              {REASONS.find((reason) => reason.value === draft.reason)?.label}
            </StudioText>
            {draft.details ? <StudioText style={styles.reviewDetails}>{draft.details}</StudioText> : null}
            <StudioText tone="muted" style={styles.body}>
              Reports are reviewed separately and do not automatically punish
              another participant.
            </StudioText>
            {isError ? (
              <StudioText accessibilityLiveRegion="polite" accessibilityRole="alert" tone="error" style={[styles.error, { backgroundColor: theme.colors.errorBackground }]}>
                {state.message}
              </StudioText>
            ) : null}
            <StudioButton
              disabled={isSubmitting}
              label={isSubmitting ? "Sending report..." : isError ? "Try again" : "Submit report"}
              onPress={() =>
                void controller.submit({
                  room_id: roomId,
                  reported_user_id: reportedUserId,
                })
              }
            />
            {!isSubmitting ? (
              <StudioButton
                label="Edit report"
                onPress={() => controller.edit()}
                variant="secondary"
              />
            ) : null}
          </StudioStack>
        </StudioCard>
      ) : null}

      {isError && !state.retryable ? (
        <StudioButton label="Return to room" onPress={() => router.back()} variant="secondary" />
      ) : null}
    </StudioScreen>
  );
}

export default function ReportRoute() {
  const { state: authState } = useAuth();
  const { roomId: rawRoomId, reportedUserId: rawReportedUserId, displayName: rawDisplayName } =
    useLocalSearchParams<{
      roomId?: string | string[];
      reportedUserId?: string | string[];
      displayName?: string | string[];
    }>();
  const roomId = typeof rawRoomId === "string" ? rawRoomId : null;
  const reportedUserId =
    typeof rawReportedUserId === "string" ? rawReportedUserId : null;
  const displayName = typeof rawDisplayName === "string" ? rawDisplayName : null;
  const controllerRef = useRef<ParticipantReportController | null>(null);
  if (controllerRef.current === null) {
    controllerRef.current = new ParticipantReportController({
      submitReport: (input) => submitSafetyReport(input),
    });
  }
  const controller = controllerRef.current;
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getState,
    controller.getState,
  );

  useEffect(
    () => () => {
      controller.dispose();
    },
    [controller],
  );

  if (authState.status !== "signed-in") {
    return (
      <StudioScreen>
        <StudioText variant="eyebrow">SAFETY</StudioText>
        <StudioText variant="title" style={styles.title}>
          Sign in to report a concern.
        </StudioText>
        <StudioButton label="Sign in" onPress={() => router.replace("/sign-in")} />
      </StudioScreen>
    );
  }

  if (roomId === null || reportedUserId === null || displayName === null) {
    return (
      <StudioScreen>
        <StudioText variant="eyebrow">SAFETY</StudioText>
        <StudioText variant="title" style={styles.title}>Report unavailable</StudioText>
        <StudioText tone="muted" style={styles.description}>
          This participant report is no longer connected to a current room.
        </StudioText>
        <StudioButton label="Return" onPress={() => router.back()} variant="secondary" />
      </StudioScreen>
    );
  }

  return (
    <ReportPresentation
      authState={authState}
      controller={controller}
      displayName={displayName}
      roomId={roomId}
      reportedUserId={reportedUserId}
      state={state}
    />
  );
}

const styles = StyleSheet.create({
  title: {
    marginTop: spacing.xs,
  },
  description: {
    marginTop: spacing.sm,
  },
  card: {
    marginTop: spacing.md,
  },
  body: {
    marginTop: spacing.sm,
  },
  detailsInput: {
    fontSize: 15,
    lineHeight: 21,
    minHeight: 96,
    padding: spacing.sm,
  },
  helper: {
    marginTop: spacing.xs,
  },
  reviewDetails: {
    marginTop: spacing.md,
  },
  error: {
    marginTop: spacing.md,
    borderRadius: 8,
    padding: spacing.sm,
  },
});
