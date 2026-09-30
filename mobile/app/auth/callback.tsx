import { router, useLocalSearchParams } from "expo-router";
import { useEffect } from "react";
import { StyleSheet } from "react-native";

import {
  StudioButton,
  StudioScreen,
  StudioText,
} from "../../src/components/studio/StudioPrimitives";
import {
  authCallbackUrlFromRouteParams,
  processAuthCallbackRoute,
  type AuthCallbackRouteParams,
} from "../../src/auth/authCallbackRoute";
import { useAuth } from "../../src/auth/AuthContext";
import { useStudioTheme } from "../../src/appearance/StudioThemeContext";
import { spacing } from "../../src/theme";

export default function AuthCallbackRoute() {
  const params = useLocalSearchParams<AuthCallbackRouteParams>();
  const {
    authCallbackError,
    authCallbackStatus,
    clearAuthCallbackError,
    processAuthCallback,
    state,
  } = useAuth();
  const callbackUrl = authCallbackUrlFromRouteParams(params);
  const theme = useStudioTheme();

  useEffect(() => {
    void processAuthCallbackRoute(params, processAuthCallback);
  }, [callbackUrl, processAuthCallback]);

  useEffect(() => {
    if (
      authCallbackStatus === "authenticated" &&
      state.status === "signed-in" &&
      authCallbackError === null
    ) {
      router.replace("/");
    }
  }, [authCallbackError, authCallbackStatus, state.status]);

  if (authCallbackError !== null) {
    const hasValidSession = state.status === "signed-in";
    return (
      <StudioScreen>
        <StudioText variant="eyebrow">MINDMESH</StudioText>
        <StudioText variant="title" style={styles.title}>
          Confirmation needs attention.
        </StudioText>
        <StudioText
          accessibilityRole="alert"
          tone="error"
          style={[styles.error, { backgroundColor: theme.colors.errorBackground }]}
        >
          {authCallbackError}
        </StudioText>
        <StudioButton
          label={hasValidSession ? "Continue to MindMesh" : "Return to sign in"}
          onPress={() => {
            clearAuthCallbackError();
            router.replace(hasValidSession ? "/" : "/sign-in");
          }}
        />
      </StudioScreen>
    );
  }

  return (
    <StudioScreen>
      <StudioText variant="eyebrow">MINDMESH</StudioText>
      <StudioText accessibilityLiveRegion="polite" variant="title" style={styles.title}>
        Confirming your account...
      </StudioText>
      <StudioText tone="muted" style={styles.description}>
        Please wait while MindMesh completes secure sign-in.
      </StudioText>
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
  error: {
    fontSize: 14,
    lineHeight: 20,
    marginBottom: spacing.md,
    marginTop: spacing.lg,
    padding: spacing.sm,
  },
});
