import { router } from "expo-router";
import { useState } from "react";
import { Linking, StyleSheet } from "react-native";

import { useAuth } from "../src/auth/AuthContext";
import type { AuthState } from "../src/auth/authFlow";
import {
  StudioButton,
  StudioCard,
  StudioScreen,
  StudioStack,
  StudioText,
} from "../src/components/studio/StudioPrimitives";
import {
  resolveSupportContact,
  supportMailto,
  type SupportContact,
} from "../src/config/support";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import { spacing } from "../src/theme";

export type SupportPresentationProps = {
  authStatus: AuthState["status"];
  contact: SupportContact;
  errorMessage: string | null;
  onContactSupport: () => void;
  onOpenAccount: () => void;
  onOpenPrivacy: () => void;
  onSignIn: () => void;
};

export function SupportPresentation({
  authStatus,
  contact,
  errorMessage,
  onContactSupport,
  onOpenAccount,
  onOpenPrivacy,
  onSignIn,
}: SupportPresentationProps) {
  const theme = useStudioTheme();
  const hasAccountAccess =
    authStatus === "signed-in" || authStatus === "suspended";

  return (
    <StudioScreen>
      <StudioText variant="eyebrow">STUDYROOM</StudioText>
      <StudioText variant="title" style={styles.title}>Support & Safety</StudioText>
      <StudioText tone="muted" style={styles.description}>
        Get help with StudyRoom or report a safety concern from a current room.
      </StudioText>

      <StudioCard style={styles.card}>
        <StudioStack>
          <StudioText variant="heading">Contact support</StudioText>
          <StudioText tone="muted" style={styles.body}>
            {contact.status === "configured"
              ? `Email ${contact.email} for support, privacy, or safety questions.`
              : "The support contact is not configured in this build."}
          </StudioText>
          {errorMessage !== null ? (
            <StudioText accessibilityLiveRegion="polite" accessibilityRole="alert" tone="error" style={[styles.error, { backgroundColor: theme.colors.errorBackground }]}>
              {errorMessage}
            </StudioText>
          ) : null}
          <StudioButton label="Contact Support" onPress={onContactSupport} />
        </StudioStack>
      </StudioCard>

      <StudioCard style={styles.card}>
        <StudioStack>
          <StudioText variant="heading">Report a safety concern</StudioText>
          <StudioText tone="muted" style={styles.body}>
            You can report an inappropriate display name, disruptive room
            behaviour, or another safety concern from a participant in the
            Waiting Room or Results. Reports are reviewed separately and do not
            automatically punish another person. Do not include passwords,
            tokens, or personal contact details in report details. For urgent
            real-world danger, contact local emergency services.
          </StudioText>
        </StudioStack>
      </StudioCard>

      <StudioCard style={styles.card}>
        <StudioStack>
          <StudioText variant="heading">Account and subscription help</StudioText>
          <StudioText tone="muted" style={styles.body}>
            {hasAccountAccess
              ? "Account deletion is available in Account & settings. Deleting StudyRoom does not cancel a store subscription."
              : "Sign in to access Account & settings and start account deletion. Deleting StudyRoom does not cancel a store subscription."}
          </StudioText>
          {hasAccountAccess ? (
            <StudioButton
              label="Open Account & settings"
              onPress={onOpenAccount}
              variant="secondary"
            />
          ) : (
            <StudioButton label="Sign in" onPress={onSignIn} variant="secondary" />
          )}
        </StudioStack>
      </StudioCard>

      <StudioButton label="Read Privacy" onPress={onOpenPrivacy} variant="secondary" />
    </StudioScreen>
  );
}

export default function SupportRoute() {
  const { state: authState } = useAuth();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const contact = resolveSupportContact();
  function contactSupport(): void {
    const mailto = supportMailto(contact);
    if (mailto === null) {
      setErrorMessage("Support contact is not configured in this build.");
      return;
    }
    setErrorMessage(null);
    void Linking.openURL(mailto).catch(() => {
      setErrorMessage("The support email could not be opened on this device.");
    });
  }

  return (
    <SupportPresentation
      authStatus={authState.status}
      contact={contact}
      errorMessage={errorMessage}
      onContactSupport={contactSupport}
      onOpenAccount={() => router.push("/account")}
      onOpenPrivacy={() => router.push("/privacy")}
      onSignIn={() => router.replace("/sign-in")}
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
    marginBottom: spacing.md,
    marginTop: spacing.sm,
  },
  error: {
    borderRadius: 8,
    padding: spacing.sm,
  },
});
