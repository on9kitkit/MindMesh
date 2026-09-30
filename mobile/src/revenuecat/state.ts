import type {
  RevenueCatAdapterFailureCode,
  RevenueCatCustomerInfo,
  RevenueCatOffering,
  RevenueCatOfferings,
  RevenueCatReadyData,
  RevenueCatRecoverableErrorCode,
} from "./types";

type RevenueCatOperation =
  | "configuration"
  | "identity"
  | "customer-info"
  | "offering"
  | "purchase"
  | "restore";

export type SafeRevenueCatError = {
  code: RevenueCatRecoverableErrorCode;
  message: string;
};

function structuredErrorCode(error: unknown): string | null {
  if (typeof error !== "object" || error === null || !("code" in error)) {
    return null;
  }
  return typeof error.code === "string" ? error.code : null;
}

export function revenueCatErrorIsCancellation(error: unknown): boolean {
  return structuredErrorCode(error) === "1";
}

export function adapterFailureCodeFromError(
  error: unknown,
): RevenueCatAdapterFailureCode {
  switch (structuredErrorCode(error)) {
    case "10":
    case "32":
    case "33":
    case "35":
      return "network-failure";
    case "2":
    case "3":
    case "5":
    case "24":
      return "store-unavailable";
    case "20":
      return "purchase-pending";
    case "11":
    case "14":
    case "23":
      return "configuration-failure";
    default:
      return "purchase-failed";
  }
}

export function safeRevenueCatError(
  error: unknown,
  operation: RevenueCatOperation,
): SafeRevenueCatError {
  const code = adapterFailureCodeFromError(error);
  if (code === "network-failure") {
    return {
      code,
      message: "RevenueCat could not be reached. Check your connection and try again.",
    };
  }
  if (code === "store-unavailable") {
    return {
      code,
      message: "The store is unavailable for this purchase right now.",
    };
  }
  if (code === "purchase-pending") {
    return {
      code,
      message: "The purchase is pending store approval. Pro will update when confirmed.",
    };
  }
  if (code === "configuration-failure" || operation === "configuration") {
    return {
      code: "configuration-failure",
      message: "RevenueCat could not be configured for this build.",
    };
  }
  if (operation === "offering") {
    return {
      code: "offering-unavailable",
      message: "The MindMesh Pro offering could not be loaded. Please try again.",
    };
  }
  if (operation === "customer-info" || operation === "identity") {
    return {
      code: "customer-info-unavailable",
      message: "Your MindMesh Pro status could not be loaded. Please try again.",
    };
  }
  if (operation === "restore") {
    return {
      code: "purchase-failed",
      message: "Purchases could not be restored. Please try again.",
    };
  }
  return {
    code: "purchase-failed",
    message: "The purchase could not be completed. Please try again.",
  };
}

function configuredOffering(
  offerings: RevenueCatOfferings,
  offeringId: string,
): RevenueCatOffering | null {
  return (
    offerings.offerings.find((offering) => offering.identifier === offeringId) ??
    null
  );
}

export function deriveRevenueCatReadyData(
  appUserId: string,
  entitlementId: string,
  offeringId: string,
  customerInfo: RevenueCatCustomerInfo,
  offerings: RevenueCatOfferings | null,
): RevenueCatReadyData {
  const entitlement = customerInfo.entitlements.active[entitlementId];
  const offering = offerings
    ? configuredOffering(offerings, offeringId)
    : null;
  const offeringStatus =
    offerings === null
      ? "load-failed"
      : offering === null
        ? "missing"
        : offering.packages.length === 0
          ? "empty"
          : "available";

  return {
    appUserId,
    isPro: entitlement !== undefined,
    entitlementIdentifier: entitlementId,
    expirationDate: entitlement?.expirationDate ?? null,
    willRenew: entitlement?.willRenew ?? null,
    managementUrl: customerInfo.managementUrl,
    isSandbox: entitlement?.isSandbox ?? null,
    offering,
    offeringStatus,
  };
}

export function updateRevenueCatEntitlement(
  data: RevenueCatReadyData,
  customerInfo: RevenueCatCustomerInfo,
): RevenueCatReadyData {
  const entitlement =
    customerInfo.entitlements.active[data.entitlementIdentifier];
  return {
    ...data,
    isPro: entitlement !== undefined,
    expirationDate: entitlement?.expirationDate ?? null,
    willRenew: entitlement?.willRenew ?? null,
    managementUrl: customerInfo.managementUrl,
    isSandbox: entitlement?.isSandbox ?? null,
  };
}

const PERIOD_UNITS: Readonly<Record<string, string>> = {
  D: "day",
  W: "week",
  M: "month",
  Y: "year",
};

export function formatSubscriptionPeriod(period: string | null): string | null {
  if (period === null) {
    return null;
  }
  const match = /^P(\d+)([DWMY])$/.exec(period);
  if (!match) {
    return period;
  }
  const count = Number(match[1]);
  const unit = PERIOD_UNITS[match[2]];
  if (!unit || !Number.isSafeInteger(count) || count <= 0) {
    return period;
  }
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}
