export type RevenueCatEnvironment = {
  EXPO_PUBLIC_REVENUECAT_TEST_API_KEY?: string;
  EXPO_PUBLIC_REVENUECAT_ENTITLEMENT_ID?: string;
  EXPO_PUBLIC_REVENUECAT_OFFERING_ID?: string;
  EXPO_PUBLIC_REVENUECAT_MODE?: string;
};

export type RevenueCatConfiguration = {
  mode: "test";
  apiKey: string;
  entitlementId: string;
  offeringId: string;
};

export type RevenueCatConfigurationResult =
  | { status: "configured"; configuration: RevenueCatConfiguration }
  | { status: "unavailable"; message: string };

function requiredValue(
  environment: RevenueCatEnvironment,
  name: keyof RevenueCatEnvironment,
): string | null {
  const value = environment[name]?.trim();
  return value ? value : null;
}

export function resolveRevenueCatConfiguration(
  environment: RevenueCatEnvironment,
): RevenueCatConfigurationResult {
  const mode = requiredValue(environment, "EXPO_PUBLIC_REVENUECAT_MODE");
  const apiKey = requiredValue(
    environment,
    "EXPO_PUBLIC_REVENUECAT_TEST_API_KEY",
  );
  const entitlementId = requiredValue(
    environment,
    "EXPO_PUBLIC_REVENUECAT_ENTITLEMENT_ID",
  );
  const offeringId = requiredValue(
    environment,
    "EXPO_PUBLIC_REVENUECAT_OFFERING_ID",
  );

  if (!mode) {
    return {
      status: "unavailable",
      message: "RevenueCat mode is not configured for this build.",
    };
  }
  if (!apiKey) {
    return {
      status: "unavailable",
      message: "The RevenueCat Test Store public SDK key is not configured.",
    };
  }
  if (!entitlementId) {
    return {
      status: "unavailable",
      message: "The RevenueCat entitlement identifier is not configured.",
    };
  }
  if (!offeringId) {
    return {
      status: "unavailable",
      message: "The RevenueCat offering identifier is not configured.",
    };
  }

  if (mode === "production") {
    return {
      status: "unavailable",
      message: apiKey.startsWith("test_")
        ? "A RevenueCat Test Store key cannot be used in production mode."
        : "Production RevenueCat platform keys are not implemented yet.",
    };
  }
  if (mode !== "test") {
    return {
      status: "unavailable",
      message: "RevenueCat mode must be explicitly set to test for this build.",
    };
  }
  if (!apiKey.startsWith("test_")) {
    return {
      status: "unavailable",
      message: "RevenueCat test mode requires a Test Store public SDK key.",
    };
  }

  return {
    status: "configured",
    configuration: {
      mode: "test",
      apiKey,
      entitlementId,
      offeringId,
    },
  };
}

export function loadRevenueCatConfiguration(): RevenueCatConfigurationResult {
  return resolveRevenueCatConfiguration({
    EXPO_PUBLIC_REVENUECAT_TEST_API_KEY:
      process.env.EXPO_PUBLIC_REVENUECAT_TEST_API_KEY,
    EXPO_PUBLIC_REVENUECAT_ENTITLEMENT_ID:
      process.env.EXPO_PUBLIC_REVENUECAT_ENTITLEMENT_ID,
    EXPO_PUBLIC_REVENUECAT_OFFERING_ID:
      process.env.EXPO_PUBLIC_REVENUECAT_OFFERING_ID,
    EXPO_PUBLIC_REVENUECAT_MODE: process.env.EXPO_PUBLIC_REVENUECAT_MODE,
  });
}
