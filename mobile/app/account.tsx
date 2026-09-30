import { router } from "expo-router";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { StyleSheet } from "react-native";

import { deleteAccount } from "../src/api/account";
import { useAuth } from "../src/auth/AuthContext";
import {
  StudioButton,
  StudioCard,
  StudioScreen,
  StudioStack,
  StudioText,
  StudioTextField,
} from "../src/components/studio/StudioPrimitives";
import {
  ACCOUNT_DELETION_CONFIRMATION,
  AccountDeletionController,
  type AccountDeletionState,
} from "../src/features/account/accountDeletion";
import { LearningSummaryCard } from "../src/features/learningSummary/LearningSummaryCard";
import {
  useLearningSummary,
  type LearningSummaryLoadState,
} from "../src/features/learningSummary/useLearningSummary";
import { useSession } from "../src/features/session/SessionContext";
import { useRevenueCat } from "../src/revenuecat/RevenueCatContext";
import { revenueCatReadyData } from "../src/revenuecat/types";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import { spacing } from "../src/theme";
import type { AuthState } from "../src/auth/authFlow";

function confirmationForState(state: AccountDeletionState): string {
  return state.status === "confirming" || state.status === "error"
    ? state.confirmation
    : ACCOUNT_DELETION_CONFIRMATION;
}

export type AccountPresentationProps = {
  authState: Extract<AuthState, { status: "signed-in" | "suspended" }>;
  controller: AccountDeletionController;
  deletionState: AccountDeletionState;
  isPro: boolean;
  onPasswordChange: (value: string) => void;
  onPasswordSubmit: () => void;
  onSignOut: () => void;
  password: string;
  learningSummaryState?: LearningSummaryLoadState;
  onLearningSummaryRetry?: () => void;
};

export function AccountPresentation({
  authState,
  controller,
  deletionState,
  isPro,
  onPasswordChange,
  onPasswordSubmit,
  onSignOut,
  password,
  learningSummaryState = { status: "inactive" },
  onLearningSummaryRetry = () => undefined,
}: AccountPresentationProps) {
  const theme = useStudioTheme();
  const confirmation = confirmationForState(deletionState);
  const isConfirming =
    deletionState.status === "confirming" || deletionState.status === "error";
  const isDeleting =
    deletionState.status === "deleting" ||
    deletionState.status === "reauthenticating";

  return (
    <StudioScreen>
      <StudioText variant="eyebrow">STUDYROOM</StudioText>
      <StudioText variant="title" style={styles.title}>
        Account & settings
      </StudioText>
      <StudioText tone="muted" style={styles.description}>
        Manage your StudyRoom account and its local data.
      </StudioText>

      <StudioCard style={styles.card}>
        <StudioText variant="heading">Your profile</StudioText>
        <StudioText style={styles.profileName}>
          {authState.user.displayName ?? "StudyRoom member"}
        </StudioText>
      </StudioCard>

      {authState.status === "signed-in" && deletionState.status === "idle" ? (
        <LearningSummaryCard
          state={learningSummaryState}
          onRetry={onLearningSummaryRetry}
        />
      ) : null}

      {deletionState.status === "idle" ? (
        <StudioCard style={styles.card}>
          <StudioStack>
            <StudioText variant="heading">Delete account</StudioText>
            <StudioText tone="muted" style={styles.cardDescription}>
              This removes your local StudyRoom profile, room memberships,
              participant records, answers, solo practice content, earned coin
              records, and pet ownership. Anonymized shared quiz history may
              remain. Linked service records are scheduled for cleanup.
            </StudioText>
            {isPro ? (
              <StudioText tone="muted" style={styles.notice}>
                You currently have StudyRoom Pro. Deleting your account does not
                cancel the store subscription; cancel it separately through your
                store account.
              </StudioText>
            ) : null}
            <StudioButton
              label="Delete Account"
              onPress={() => controller.start()}
              variant="destructive"
            />
          </StudioStack>
        </StudioCard>
      ) : null}

      {isConfirming ? (
        <StudioCard style={styles.card}>
          <StudioStack>
            <StudioText variant="heading">Confirm account deletion</StudioText>
            <StudioText tone="muted" style={styles.cardDescription}>
              This action cannot be undone. Type DELETE exactly to continue.
            </StudioText>
            {deletionState.status === "error" ? (
              <StudioText accessibilityLiveRegion="polite" accessibilityRole="alert" tone="error" style={[styles.error, { backgroundColor: theme.colors.errorBackground }]}>
                {deletionState.message}
              </StudioText>
            ) : deletionState.status === "confirming" && deletionState.errorMessage ? (
              <StudioText accessibilityLiveRegion="polite" accessibilityRole="alert" tone="error" style={[styles.error, { backgroundColor: theme.colors.errorBackground }]}>
                {deletionState.errorMessage}
              </StudioText>
            ) : null}
            <StudioTextField
              accessibilityLabel="Type DELETE to confirm account deletion"
              autoCapitalize="none"
              autoCorrect={false}
              editable={!isDeleting}
              inputStyle={styles.confirmationInput}
              label="CONFIRMATION"
              onChangeText={(value) => controller.setConfirmation(value)}
              value={confirmation}
            />
            <StudioButton
              disabled={
                isDeleting || confirmation !== ACCOUNT_DELETION_CONFIRMATION
              }
              label={
                deletionState.status === "error" && deletionState.retryable
                  ? "Try again"
                  : "Delete my account"
              }
              onPress={() => void controller.submit()}
              variant="destructive"
            />
            {deletionState.status === "error" && !deletionState.retryable ? (
              <StudioButton
                label="Start again"
                onPress={() => controller.reset()}
                variant="secondary"
              />
            ) : null}
          </StudioStack>
        </StudioCard>
      ) : null}

      {deletionState.status === "reauth_required" ||
      deletionState.status === "reauthenticating" ? (
        <StudioCard style={styles.card}>
          <StudioStack>
            <StudioText variant="heading">Confirm your password</StudioText>
            <StudioText tone="muted" style={styles.cardDescription}>
              For security, enter your current password to continue deleting
              this account.
            </StudioText>
            {deletionState.status === "reauth_required" &&
            deletionState.errorMessage ? (
              <StudioText accessibilityLiveRegion="polite" accessibilityRole="alert" tone="error" style={[styles.error, { backgroundColor: theme.colors.errorBackground }]}>
                {deletionState.errorMessage}
              </StudioText>
            ) : null}
            <StudioTextField
              accessibilityLabel="Current password for account deletion"
              autoCapitalize="none"
              autoComplete="current-password"
              editable={deletionState.status === "reauth_required"}
              inputStyle={styles.confirmationInput}
              label="CURRENT PASSWORD"
              onChangeText={onPasswordChange}
              secureTextEntry
              value={password}
            />
            <StudioButton
              disabled={
                deletionState.status === "reauthenticating" || password.length === 0
              }
              label={
                deletionState.status === "reauthenticating"
                  ? "Checking password..."
                  : "Confirm password and delete"
              }
              onPress={onPasswordSubmit}
              variant="destructive"
            />
          </StudioStack>
        </StudioCard>
      ) : null}

      {deletionState.status === "deleting" ? (
        <StudioCard style={styles.card}>
          <StudioText accessibilityLiveRegion="polite" variant="heading">
            Deleting your account...
          </StudioText>
          <StudioText tone="muted" style={styles.cardDescription}>
            Please wait while StudyRoom completes the local deletion.
          </StudioText>
        </StudioCard>
      ) : null}

      {deletionState.status === "deleted" ? (
        <StudioCard style={styles.card}>
          <StudioText accessibilityLiveRegion="polite" accessibilityRole="alert" tone="success">
            Your account has been deleted. Returning to sign in...
          </StudioText>
        </StudioCard>
      ) : null}

      <StudioCard style={styles.card}>
        <StudioStack>
          <StudioText variant="heading">Privacy and support</StudioText>
          <StudioText tone="muted" style={styles.cardDescription}>
            Read how StudyRoom handles data or get help with an account or safety
            concern.
          </StudioText>
          <StudioButton
            label="Privacy"
            onPress={() => router.push("/privacy")}
            variant="secondary"
          />
          <StudioButton
            label="Support & Safety"
            onPress={() => router.push("/support")}
            variant="secondary"
          />
        </StudioStack>
      </StudioCard>

      <StudioCard style={styles.card}>
        <StudioStack>
          <StudioText variant="heading">Session</StudioText>
          <StudioText tone="muted" style={styles.cardDescription}>
            Sign out of this device without deleting your account.
          </StudioText>
          <StudioButton
            disabled={isDeleting}
            label="Sign out"
            onPress={onSignOut}
            variant="secondary"
          />
        </StudioStack>
      </StudioCard>
    </StudioScreen>
  );
}

export default function AccountRoute() {
  const auth = useAuth();
  const session = useSession();
  const revenueCat = useRevenueCat();
  const authRef = useRef(auth);
  const sessionRef = useRef(session);
  const revenueCatRef = useRef(revenueCat);
  authRef.current = auth;
  sessionRef.current = session;
  revenueCatRef.current = revenueCat;

  const controllerRef = useRef<AccountDeletionController | null>(null);
  if (controllerRef.current === null) {
    controllerRef.current = new AccountDeletionController({
      deleteAccount,
      reauthenticate: (password) =>
        authRef.current.reauthenticateCurrentUser(password),
      completeLocalCleanup: async (message) => {
        sessionRef.current.terminateAuthenticatedState();
        void revenueCatRef.current.clearIdentity().catch(() => undefined);
        await authRef.current.completeAccountDeletion(message);
      },
    });
  }
  const controller = controllerRef.current;
  const deletionState = useSyncExternalStore(
    controller.subscribe,
    controller.getState,
    controller.getState,
  );
  const summaryUserId =
    auth.state.status === "signed-in" &&
    auth.state.profileBootstrap.status === "ready" &&
    deletionState.status === "idle"
      ? auth.state.user.id
      : null;
  const learningSummary = useLearningSummary(summaryUserId);
  const [password, setPassword] = useState("");
  useEffect(
    () => () => {
      controller.dispose();
    },
    [controller],
  );

  useEffect(() => {
    if (
      deletionState.status !== "reauth_required" &&
      deletionState.status !== "reauthenticating"
    ) {
      setPassword("");
    }
  }, [deletionState.status]);

  if (auth.state.status !== "signed-in" && auth.state.status !== "suspended") {
    return (
      <StudioScreen>
        <StudioText variant="eyebrow">STUDYROOM</StudioText>
        <StudioText variant="title" style={styles.title}>
          Returning to sign in...
        </StudioText>
      </StudioScreen>
    );
  }

  const revenueCatData = revenueCatReadyData(revenueCat.state);
  return (
    <AccountPresentation
      authState={auth.state}
      controller={controller}
      deletionState={deletionState}
      isPro={revenueCatData?.isPro === true}
      onPasswordChange={setPassword}
      onPasswordSubmit={() => {
        const enteredPassword = password;
        setPassword("");
        void controller.submitPassword(enteredPassword);
      }}
      onSignOut={() => void auth.signOut()}
      password={password}
      learningSummaryState={learningSummary.state}
      onLearningSummaryRetry={learningSummary.retry}
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
  cardDescription: {
    marginTop: spacing.xs,
  },
  profileName: {
    marginTop: spacing.sm,
  },
  notice: {
    marginBottom: spacing.md,
  },
  confirmationInput: {
    fontSize: 18,
    lineHeight: 24,
    minHeight: 50,
    paddingHorizontal: spacing.sm,
  },
  error: {
    borderRadius: 8,
    padding: spacing.sm,
  },
});
