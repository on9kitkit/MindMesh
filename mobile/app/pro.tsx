import { router } from "expo-router";
import { StyleSheet, View } from "react-native";

import { useAuth } from "../src/auth/AuthContext";
import {
  StudioButton,
  StudioCard,
  StudioScreen,
  StudioStack,
  StudioText,
} from "../src/components/studio/StudioPrimitives";
import { useRevenueCat } from "../src/revenuecat/RevenueCatContext";
import { formatSubscriptionPeriod } from "../src/revenuecat/state";
import { revenueCatReadyData } from "../src/revenuecat/types";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import { spacing } from "../src/theme";

function entitlementStatusLabel(
  state: ReturnType<typeof useRevenueCat>["state"],
): string {
  if (state.capability.status === "preview-only") {
    return "Preview only";
  }
  if (
    state.capability.status ===
      "unsupported-with-current-web-configuration" ||
    state.capability.status === "unsupported-platform"
  ) {
    return "Unavailable on this platform";
  }
  const data = revenueCatReadyData(state);
  if (data !== null) {
    return data.isPro ? "Pro" : "Free";
  }
  if (state.status === "signed-out") {
    return "Signed out";
  }
  if (state.status === "unavailable") {
    return "Unavailable";
  }
  return "Loading";
}

function formattedExpirationDate(expirationDate: string | null): string | null {
  if (expirationDate === null) {
    return null;
  }
  const date = new Date(expirationDate);
  return Number.isNaN(date.valueOf()) ? expirationDate : date.toLocaleDateString();
}

export default function ProRoute() {
  const { state: authState } = useAuth();
  const theme = useStudioTheme();
  const {
    presentPaywall,
    refreshCustomerInfo,
    restorePurchases,
    state,
  } = useRevenueCat();
  const data = revenueCatReadyData(state);
  const nativePurchasesSupported =
    state.capability.status === "native-purchase-supported";
  const operationPending =
    state.status === "purchasing" || state.status === "restoring";
  const purchaseAvailable =
    nativePurchasesSupported &&
    data !== null &&
    !data.isPro &&
    data.offeringStatus === "available" &&
    !operationPending;
  const restoreAvailable =
    nativePurchasesSupported && data !== null && !operationPending;
  const refreshAvailable =
    !operationPending &&
    state.status !== "unconfigured" &&
    state.status !== "initializing" &&
    state.status !== "signed-out" &&
    state.status !== "loading-customer" &&
    state.status !== "unavailable";

  if (authState.status !== "signed-in") {
    return (
      <StudioScreen>
        <StudioText variant="eyebrow">MINDMESH PRO</StudioText>
        <StudioText variant="title" style={styles.title}>Returning to sign in...</StudioText>
      </StudioScreen>
    );
  }

  const statusMessage =
    state.status === "recoverable-error"
      ? state.message
      : state.status === "unavailable"
        ? state.message
        : state.status === "ready"
          ? state.notice?.message ?? null
          : state.status === "purchasing"
            ? "The RevenueCat paywall is open."
            : state.status === "restoring"
              ? "Restoring purchases..."
              : null;
  const statusIsError =
    state.status === "recoverable-error" || state.status === "unavailable";
  const expirationDate = formattedExpirationDate(
    data?.expirationDate ?? null,
  );

  return (
    <StudioScreen>
      <StudioText variant="eyebrow">MINDMESH PRO</StudioText>
      <StudioText variant="title" style={styles.title}>MindMesh Pro</StudioText>
      <StudioText tone="muted" style={styles.description}>
        Advanced MindMesh Pro features are being introduced progressively.
      </StudioText>

      <StudioCard style={styles.card}>
        <StudioText tone="muted" style={styles.cardLabel}>CURRENT ACCESS</StudioText>
        <StudioText style={styles.accessStatus}>{entitlementStatusLabel(state)}</StudioText>
        {data?.isPro ? (
          <View>
            {expirationDate ? (
              <StudioText tone="muted" style={styles.detail}>Active until {expirationDate}</StudioText>
            ) : (
              <StudioText tone="muted" style={styles.detail}>Active without an expiry date</StudioText>
            )}
            {data.willRenew !== null ? (
              <StudioText tone="muted" style={styles.detail}>
                {data.willRenew ? "Renews automatically" : "Will not renew"}
              </StudioText>
            ) : null}
            {data.isSandbox ? (
              <StudioText tone="muted" style={styles.detail}>Test Store / sandbox entitlement</StudioText>
            ) : null}
            {data.managementUrl ? (
              <StudioText tone="muted" style={styles.detail}>
                Subscription management is available from the store account.
              </StudioText>
            ) : null}
          </View>
        ) : null}
        {state.capability.status !== "native-purchase-supported" ? (
          <StudioText tone="muted" style={styles.platformMessage}>
            {state.capability.message}
          </StudioText>
        ) : null}
      </StudioCard>

      {data?.offering ? (
        <StudioCard style={styles.card}>
          <StudioText tone="muted" style={styles.cardLabel}>AVAILABLE PACKAGES</StudioText>
          {data.offering.packages.map((availablePackage) => {
            const period = formatSubscriptionPeriod(availablePackage.period);
            return (
              <View key={availablePackage.identifier} style={[styles.packageRow, { borderTopColor: theme.colors.border }]}>
                <View style={styles.packageCopy}>
                  <StudioText style={styles.packageTitle}>{availablePackage.title}</StudioText>
                  {availablePackage.description ? (
                    <StudioText tone="muted" style={styles.packageDescription}>
                      {availablePackage.description}
                    </StudioText>
                  ) : null}
                  {period ? <StudioText tone="muted" style={styles.detail}>{period}</StudioText> : null}
                </View>
                <StudioText style={styles.packagePrice}>{availablePackage.price}</StudioText>
              </View>
            );
          })}
          {data.offeringStatus === "empty" ? (
            <StudioText tone="muted" style={styles.platformMessage}>
              This offering has no available packages.
            </StudioText>
          ) : null}
        </StudioCard>
      ) : data?.offeringStatus === "missing" ? (
        <StudioCard style={styles.card}>
          <StudioText tone="muted" style={styles.platformMessage}>
            The configured MindMesh Pro offering is unavailable.
          </StudioText>
        </StudioCard>
      ) : null}

      {statusMessage ? (
        <StudioText
          accessibilityLiveRegion="polite"
          {...(statusIsError ? { accessibilityRole: "alert" as const } : {})}
          tone={statusIsError ? "error" : "success"}
          style={[statusIsError ? styles.error : styles.notice, {
            backgroundColor: statusIsError
              ? theme.colors.errorBackground
              : theme.colors.successBackground,
          }]}
        >
          {statusMessage}
        </StudioText>
      ) : null}

      <StudioStack>
        <View style={styles.actions}>
        <StudioButton
          disabled={!purchaseAvailable}
          label={state.status === "purchasing" ? "Opening Paywall..." : "Open RevenueCat Paywall"}
          onPress={() => void presentPaywall()}
        />
        <StudioButton
          disabled={!restoreAvailable}
          label={state.status === "restoring" ? "Restoring Purchases..." : "Restore Purchases"}
          onPress={() => void restorePurchases()}
          variant="secondary"
        />
        <StudioButton
          disabled={!refreshAvailable}
          label={
            state.status === "loading-customer"
              ? "Refreshing Pro Status..."
              : "Refresh Pro Status"
          }
          onPress={() => void refreshCustomerInfo()}
          variant="secondary"
        />
        <StudioButton
          disabled={operationPending}
          label="Return Home"
          onPress={() => router.replace("/")}
          variant="secondary"
        />
        </View>
      </StudioStack>
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  title: {
    marginTop: spacing.xs,
  },
  description: {
    lineHeight: 23,
    marginTop: spacing.sm,
  },
  card: {
    marginTop: spacing.lg,
  },
  cardLabel: {
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 1,
  },
  accessStatus: {
    fontSize: 24,
    fontWeight: "800",
    lineHeight: 30,
    marginTop: spacing.xs,
  },
  detail: {
    fontSize: 14,
    lineHeight: 20,
    marginTop: spacing.xs,
  },
  platformMessage: {
    fontSize: 15,
    lineHeight: 21,
    marginTop: spacing.sm,
  },
  packageRow: {
    alignItems: "flex-start",
    borderTopWidth: 1,
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
  },
  packageCopy: {
    flex: 1,
    minWidth: 0,
    paddingRight: spacing.sm,
  },
  packageTitle: {
    fontSize: 16,
    fontWeight: "700",
  },
  packageDescription: {
    fontSize: 14,
    lineHeight: 20,
    marginTop: spacing.xs,
  },
  packagePrice: {
    flexShrink: 1,
    fontSize: 16,
    fontWeight: "800",
    textAlign: "right",
  },
  notice: {
    fontSize: 14,
    lineHeight: 20,
    marginTop: spacing.md,
    padding: spacing.sm,
  },
  error: {
    fontSize: 14,
    lineHeight: 20,
    marginTop: spacing.md,
    padding: spacing.sm,
  },
  actions: {
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
});
