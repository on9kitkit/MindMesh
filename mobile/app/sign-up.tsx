import { router } from "expo-router";
import { useState } from "react";
import { StyleSheet } from "react-native";

import { useAuth } from "../src/auth/AuthContext";
import { validateDisplayName } from "../src/auth/displayNamePolicy";
import {
  StudioButton,
  StudioCard,
  StudioScreen,
  StudioStack,
  StudioText,
  StudioTextField,
} from "../src/components/studio/StudioPrimitives";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import { spacing } from "../src/theme";

export default function SignUpRoute() {
  const { authCallbackError, clearAuthCallbackError, signUp, state } = useAuth();
  const theme = useStudioTheme();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [validationError, setValidationError] = useState<string | undefined>();
  const isSubmitting = state.status === "signing-up";

  if (state.status === "signed-in") {
    return <StudioScreen>
      <StudioText variant="eyebrow">STUDYROOM</StudioText>
      <StudioText variant="title" style={styles.title}>
        Opening your current session...
      </StudioText>
    </StudioScreen>;
  }

  if (state.status === "confirmation-required") {
    return (
      <StudioScreen>
        <StudioText variant="eyebrow">STUDYROOM</StudioText>
        <StudioText variant="title" style={styles.title}>
          Check your email.
        </StudioText>
        <StudioCard style={styles.card}>
          <StudioStack>
            <StudioText style={styles.confirmation}>
              Check your email to confirm your account.
            </StudioText>
            <StudioButton
              label="Return to sign in"
              onPress={() => router.replace("/sign-in")}
            />
          </StudioStack>
        </StudioCard>
      </StudioScreen>
    );
  }

  function submit() {
    const normalizedEmail = email.trim();
    const displayNameResult = validateDisplayName(displayName);
    if (!normalizedEmail.includes("@")) {
      setValidationError("Enter a valid email address.");
      return;
    }
    if (password.length < 6) {
      setValidationError("Password must contain at least 6 characters.");
      return;
    }
    if (!displayNameResult.valid) {
      setValidationError(displayNameResult.message);
      return;
    }
    setValidationError(undefined);
    clearAuthCallbackError();
    void signUp(normalizedEmail, password, displayNameResult.value);
  }

  const errorMessage =
    validationError ??
    authCallbackError ??
    (state.status === "error" ? state.message : undefined);

  return (
    <StudioScreen>
      <StudioText variant="eyebrow">STUDYROOM</StudioText>
      <StudioText variant="title" style={styles.title}>
        Create your account.
      </StudioText>
      <StudioText tone="muted" style={styles.description}>
        Choose a name your room members will recognise.
      </StudioText>

      <StudioCard style={styles.card}>
        <StudioStack>
        <StudioTextField
          accessibilityLabel="Display name"
          autoCapitalize="words"
          containerStyle={styles.field}
          inputStyle={styles.input}
          label="DISPLAY NAME"
          onChangeText={setDisplayName}
          placeholder="Your name"
          value={displayName}
        />
        <StudioTextField
          accessibilityLabel="Email"
          autoCapitalize="none"
          autoComplete="email"
          containerStyle={styles.field}
          keyboardType="email-address"
          inputStyle={styles.input}
          label="EMAIL"
          onChangeText={setEmail}
          placeholder="you@example.com"
          value={email}
        />
        <StudioTextField
          accessibilityLabel="Password"
          autoCapitalize="none"
          autoComplete="new-password"
          containerStyle={styles.field}
          inputStyle={styles.input}
          label="PASSWORD"
          onChangeText={setPassword}
          placeholder="At least 6 characters"
          secureTextEntry
          value={password}
        />
        {errorMessage ? (
          <StudioText
            accessibilityRole="alert"
            tone="error"
            style={[styles.error, { backgroundColor: theme.colors.errorBackground }]}
          >
            {errorMessage}
          </StudioText>
        ) : null}
        <StudioButton
          disabled={isSubmitting}
          label={isSubmitting ? "Creating account..." : "Sign up"}
          onPress={submit}
        />
        <StudioButton
          label="I already have an account"
          onPress={() => router.replace("/sign-in")}
          variant="secondary"
        />
        <StudioButton
          label="Privacy"
          onPress={() => router.push("/privacy")}
          variant="secondary"
        />
        </StudioStack>
      </StudioCard>
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  eyebrow: {
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 1.4,
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
  card: {
    marginTop: spacing.lg,
  },
  field: {
    marginTop: spacing.sm,
  },
  input: {
    borderRadius: 8,
    minHeight: 48,
  },
  error: {
    fontSize: 14,
    lineHeight: 20,
    marginBottom: spacing.sm,
    marginTop: spacing.md,
    padding: spacing.sm,
  },
  confirmation: {
    fontSize: 16,
    lineHeight: 24,
    marginBottom: spacing.md,
  },
});
