import { router } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Modal, StyleSheet, View } from "react-native";

import {
  acknowledgeDailyInvitation,
  claimDailyInvitation,
  dismissDailyInvitation,
  getRewardOverview,
  selectHomeZone,
} from "../../api/learningCompanions";
import { createApiClient, resolveApiBaseUrl } from "../../api/client";
import { getUserFacingErrorMessage } from "../../api/errors";
import { useStudioTheme } from "../../appearance/StudioThemeContext";
import { getSupabaseClient } from "../../auth/supabase";
import { dailyOfferIsOpen } from "./dailyInvitationPresentation";
import {
  StudioButton,
  StudioCard,
  StudioStack,
  StudioText,
  StudioTextField,
} from "../../components/studio/StudioPrimitives";

type Overview = Awaited<ReturnType<typeof getRewardOverview>>;
type Invitation = Awaited<ReturnType<typeof claimDailyInvitation>>;

type LoadState =
  | { status: "idle" | "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; overview: Overview; invitation: Invitation | null };

function suggestedHomeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/London";
  } catch {
    return "Europe/London";
  }
}

export function HomeCompanions({
  userId,
  roomFree,
  profileReady,
}: {
  userId: string;
  roomFree: boolean;
  profileReady: boolean;
}) {
  const theme = useStudioTheme();
  const requestVersion = useRef(0);
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const [homeZone, setHomeZone] = useState(suggestedHomeZone);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [closedStudyDate, setClosedStudyDate] = useState<string | null>(null);
  const [ackError, setAckError] = useState<string | null>(null);
  const acknowledgedDate = useRef<string | null>(null);
  const ownerClient = useMemo(() => createApiClient(
    resolveApiBaseUrl(process.env.EXPO_PUBLIC_API_BASE_URL),
    { getAccessToken: async () => {
      const { data, error } = await getSupabaseClient().auth.getSession();
      return !error && data.session?.user.id === userId
        ? data.session.access_token : null;
    } },
  ), [userId]);
  const offeredDate = state.status === "ready" && roomFree &&
    state.invitation?.should_open === true ? state.invitation.study_date : null;
  const dailyOfferOpen = dailyOfferIsOpen(
    state.status === "ready" ? state.invitation : null,
    roomFree,
    closedStudyDate,
  );

  useEffect(() => {
    const version = ++requestVersion.current;
    setState({ status: "idle" });
    setPending(false);
    setAckError(null);
    if (!profileReady) {
      return () => { requestVersion.current += 1; };
    }
    setState({ status: "loading" });
    void (async () => {
      try {
        const overview = await getRewardOverview(ownerClient);
        const invitation = overview.home_timezone !== null && roomFree
          ? await claimDailyInvitation(ownerClient)
          : null;
        if (requestVersion.current === version) {
          setState({ status: "ready", overview, invitation });
        }
      } catch (error: unknown) {
        if (requestVersion.current === version) {
          setState({ status: "error", message: getUserFacingErrorMessage(error) });
        }
      }
    })();
    return () => { requestVersion.current += 1; };
  }, [profileReady, roomFree, userId, ownerClient, reloadKey]);

  async function setFixedZone(): Promise<void> {
    if (pending || state.status !== "ready") return;
    const version = requestVersion.current;
    setPending(true);
    try {
      await selectHomeZone(homeZone.trim(), ownerClient);
      const overview = await getRewardOverview(ownerClient);
      const invitation = roomFree ? await claimDailyInvitation(ownerClient) : null;
      if (requestVersion.current === version) {
        setState({ status: "ready", overview, invitation });
      }
    } catch (error: unknown) {
      if (requestVersion.current === version) {
        setState({ status: "error", message: getUserFacingErrorMessage(error) });
      }
    } finally {
      if (requestVersion.current === version) setPending(false);
    }
  }

  async function dismiss(): Promise<void> {
    if (pending || state.status !== "ready" || offeredDate === null) return;
    const version = requestVersion.current;
    setPending(true);
    try {
      const invitation = await dismissDailyInvitation(offeredDate, ownerClient);
      if (requestVersion.current === version) {
        setClosedStudyDate(offeredDate);
        setState((current) => current.status === "ready"
          ? { ...current, invitation }
          : current);
      }
    } catch (error: unknown) {
      if (requestVersion.current === version) {
        setState({ status: "error", message: getUserFacingErrorMessage(error) });
      }
    } finally {
      if (requestVersion.current === version) setPending(false);
    }
  }

  function acknowledgePresentedOffer(): void {
    if (offeredDate === null || acknowledgedDate.current === offeredDate) return;
    const version = requestVersion.current;
    acknowledgedDate.current = offeredDate;
    void acknowledgeDailyInvitation(offeredDate, ownerClient).catch((error: unknown) => {
      if (requestVersion.current !== version) return;
      acknowledgedDate.current = null;
      setAckError(getUserFacingErrorMessage(error));
    });
  }

  return (
    <>
    <Modal
      animationType="fade"
      onRequestClose={() => void dismiss()}
      onShow={acknowledgePresentedOffer}
      transparent
      visible={dailyOfferOpen}
    >
      <View accessibilityViewIsModal style={styles.offerBackdrop}>
        <StudioCard style={styles.offerCard}>
          <StudioStack>
            <StudioText variant="eyebrow" tone="primary">TODAY'S STUDY INVITATION</StudioText>
            <StudioText variant="heading">Ready for a little solo study?</StudioText>
            <StudioText tone="muted">
              Choose a topic and confirm before any quiz preparation starts.
              There is no timer, and you can resume your saved progress later.
            </StudioText>
            {ackError !== null ? (
              <StudioText accessibilityRole="alert" tone="error">
                This invitation could not be saved as seen. You may see it again. {ackError}
              </StudioText>
            ) : null}
            <StudioButton label="Explore solo practice" onPress={() => {
              if (offeredDate !== null) setClosedStudyDate(offeredDate);
              router.push("/solo");
            }} />
            <StudioButton label="Not now" variant="secondary" disabled={pending}
              onPress={() => void dismiss()} />
          </StudioStack>
        </StudioCard>
      </View>
    </Modal>
    <StudioCard style={{ marginTop: theme.spacing.md }}>
      <StudioStack>
        <StudioText variant="heading">Your study companion</StudioText>
        {state.status === "idle" || state.status === "loading" ? (
          <StudioText tone="muted">Loading confirmed study progress...</StudioText>
        ) : null}
        {state.status === "error" ? (
          <>
            <StudioText accessibilityRole="alert" tone="error">{state.message}</StudioText>
            <StudioText tone="muted">
              Rewards and solo progress are unavailable until the test backend is ready.
            </StudioText>
            <StudioButton label="Retry study progress" variant="secondary" onPress={() => setReloadKey((current) => current + 1)} />
          </>
        ) : null}
        {state.status === "ready" ? (
          <>
            <StudioText tone="muted">
              Confirmed balance: {state.overview.balance} coins · Streak: {state.overview.active_streak_days} days
            </StudioText>
            {state.overview.pending_receipt_count > 0 ? (
              <StudioText tone="muted">{state.overview.pending_receipt_count} reward pending confirmation.</StudioText>
            ) : null}
            {state.overview.delayed_receipt_count > 0 ? (
              <StudioText accessibilityRole="alert" tone="error">
                {state.overview.delayed_receipt_count} reward delayed; confirmed balance is unchanged.
              </StudioText>
            ) : null}
            {state.overview.home_timezone === null ? (
              <>
                <StudioText tone="muted">
                  Choose your fixed home timezone for daily rewards. This cannot be changed in this release.
                </StudioText>
                <StudioTextField
                  label="Home timezone (IANA)"
                  value={homeZone}
                  onChangeText={setHomeZone}
                  editable={!pending}
                  autoCapitalize="none"
                  autoCorrect={false}
                />
                <StudioButton
                  label={pending ? "Saving timezone..." : "Confirm home timezone"}
                  disabled={pending || homeZone.trim().length === 0}
                  onPress={() => void setFixedZone()}
                />
              </>
            ) : null}
            {roomFree && state.overview.home_timezone !== null ? (
              <StudioButton label="Solo practice" variant="secondary" onPress={() => router.push("/solo")} />
            ) : null}
            <StudioButton label="Your pets" variant="secondary" onPress={() => router.push("/pets")} />
          </>
        ) : null}
      </StudioStack>
    </StudioCard>
    </>
  );
}

const styles = StyleSheet.create({
  offerBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0, 0, 0, 0.6)",
    justifyContent: "center",
    padding: 20,
  },
  offerCard: { width: "100%" },
});
