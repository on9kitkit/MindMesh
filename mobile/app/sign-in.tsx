import { router } from "expo-router";
import { useState } from "react";
import { View } from "react-native";

import { useAuth } from "../src/auth/AuthContext";
import { StudioAppearanceSelector } from "../src/appearance/AppearanceSelector";
import {
  StudioButton,
  StudioCard,
  StudioScreen,
  StudioStack,
  StudioText,
  StudioTextField,
} from "../src/components/studio/StudioPrimitives";

export default function SignInRoute() {
  const {
    authCallbackError,
    clearAuthCallbackError,
    signedOutMessage,
    signIn,
    signOut,
    state,
  } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [validationError, setValidationError] = useState<string | undefined>();
  const isSubmitting = state.status === "signing-in";

  if (state.status === "signed-in") {
    return (
      <StudioScreen>
        <StudioText variant="eyebrow">STUDYROOM</StudioText>
        <StudioText style={{ marginTop: 6 }} variant="title">
          Opening your current session...
        </StudioText>
      </StudioScreen>
    );
  }

  if (state.status === "suspended") {
    return (
      <StudioScreen>
        <StudioText variant="eyebrow">STUDYROOM</StudioText>
        <StudioText style={{ marginTop: 6 }} variant="title">
          Account unavailable.
        </StudioText>
        <StudioText
          accessibilityRole="alert"
          tone="error"
          style={{ marginTop: 16 }}
        >
          {state.message}
        </StudioText>
        <StudioCard style={{ marginTop: 24 }}>
          <StudioStack>
            <StudioButton
              label="Support & Safety"
              onPress={() => router.push("/support")}
            />
            <StudioButton
              label="Account & settings"
              onPress={() => router.push("/account")}
              variant="secondary"
            />
            <StudioButton
              label="Return to sign in"
              onPress={() => void signOut()}
              variant="secondary"
            />
          </StudioStack>
        </StudioCard>
      </StudioScreen>
    );
  }

  function submit() {
    const normalizedEmail = email.trim();
    if (!normalizedEmail.includes("@")) {
      setValidationError("Enter a valid email address.");
      return;
    }
    if (password.length < 6) {
      setValidationError("Password must contain at least 6 characters.");
      return;
    }
    setValidationError(undefined);
    clearAuthCallbackError();
    void signIn(normalizedEmail, password);
  }

  const errorMessage =
    validationError ??
    authCallbackError ??
    signedOutMessage ??
    (state.status === "error" ? state.message : undefined);

  return (
    <StudioScreen>
      <StudioText variant="eyebrow">STUDYROOM</StudioText>
      <StudioText style={{ marginTop: 6 }} variant="title">
        Welcome back.
      </StudioText>
      <StudioText tone="muted" style={{ marginTop: 10 }}>
        Sign in to create a quiz room.
      </StudioText>

      <View style={{ marginTop: 24 }}>
        <StudioAppearanceSelector />
      </View>

      <StudioCard style={{ marginTop: 32 }}>
        <StudioStack>
          <StudioTextField
            autoCapitalize="none"
            autoComplete="email"
            autoCorrect={false}
            keyboardType="email-address"
            label="EMAIL"
            onChangeText={setEmail}
            placeholder="you@example.com"
            value={email}
          />
          <StudioTextField
            autoCapitalize="none"
            autoComplete="password"
            autoCorrect={false}
            label="PASSWORD"
            onChangeText={setPassword}
            placeholder="Your password"
            secureTextEntry
            value={password}
          />
          {errorMessage ? (
            <StudioText accessibilityRole="alert" tone="error">
              {errorMessage}
            </StudioText>
          ) : null}
          <StudioButton
            disabled={isSubmitting}
            label={isSubmitting ? "Signing in..." : "Sign in"}
            onPress={submit}
          />
          <StudioButton
            label="Create an account"
            onPress={() => router.push("/sign-up")}
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
