export type NativePurchasePlatform = "ios" | "android";

export type RevenueCatPlatformCapability =
  | {
      status: "native-purchase-supported";
      platform: NativePurchasePlatform;
    }
  | {
      status: "preview-only";
      platform: NativePurchasePlatform;
      message: string;
    }
  | {
      status: "unsupported-with-current-web-configuration";
      platform: "web";
      message: string;
    }
  | {
      status: "unsupported-platform";
      platform: string;
      message: string;
    };

export type RevenueCatEntitlementInfo = {
  identifier: string;
  isActive: boolean;
  expirationDate: string | null;
  willRenew: boolean;
  isSandbox: boolean;
};

export type RevenueCatCustomerInfo = {
  entitlements: {
    active: Readonly<Record<string, RevenueCatEntitlementInfo>>;
    all: Readonly<Record<string, RevenueCatEntitlementInfo>>;
  };
  managementUrl: string | null;
};

export type RevenueCatPackage = {
  identifier: string;
  productIdentifier: string;
  title: string;
  description: string;
  price: string;
  period: string | null;
};

export type RevenueCatOffering = {
  identifier: string;
  packages: readonly RevenueCatPackage[];
};

export type RevenueCatOfferings = {
  currentOfferingId: string | null;
  offerings: readonly RevenueCatOffering[];
};

export type RevenueCatAdapterFailureCode =
  | "configuration-failure"
  | "network-failure"
  | "store-unavailable"
  | "purchase-pending"
  | "purchase-failed";

export type RevenueCatPaywallResult =
  | { status: "purchased" }
  | { status: "restored" }
  | { status: "cancelled" }
  | { status: "not-presented" }
  | { status: "pending" }
  | {
      status: "failed";
      code: RevenueCatAdapterFailureCode;
    }
  | { status: "offering-unavailable" };

export type RevenueCatAdapter = {
  readonly capability: RevenueCatPlatformCapability;
  configure(apiKey: string): Promise<void>;
  logIn(appUserId: string): Promise<RevenueCatCustomerInfo>;
  logOut(): Promise<RevenueCatCustomerInfo>;
  getCustomerInfo(): Promise<RevenueCatCustomerInfo>;
  getOfferings(): Promise<RevenueCatOfferings>;
  presentPaywall(offeringId: string): Promise<RevenueCatPaywallResult>;
  restorePurchases(): Promise<RevenueCatCustomerInfo>;
  addCustomerInfoUpdateListener(
    listener: (customerInfo: RevenueCatCustomerInfo) => void,
  ): Promise<() => void>;
};

export type RevenueCatOfferingStatus =
  | "available"
  | "missing"
  | "empty"
  | "load-failed";

export type RevenueCatReadyData = {
  appUserId: string;
  isPro: boolean;
  entitlementIdentifier: string;
  expirationDate: string | null;
  willRenew: boolean | null;
  managementUrl: string | null;
  isSandbox: boolean | null;
  offering: RevenueCatOffering | null;
  offeringStatus: RevenueCatOfferingStatus;
};

export type RevenueCatNotice = {
  tone: "neutral" | "success";
  message: string;
};

export type RevenueCatRecoverableErrorCode =
  | RevenueCatAdapterFailureCode
  | "offering-unavailable"
  | "package-unavailable"
  | "entitlement-not-active"
  | "customer-info-unavailable";

export type RevenueCatState =
  | {
      status: "unconfigured";
      capability: RevenueCatPlatformCapability;
    }
  | {
      status: "initializing";
      capability: RevenueCatPlatformCapability;
    }
  | {
      status: "signed-out";
      capability: RevenueCatPlatformCapability;
    }
  | {
      status: "loading-customer";
      capability: RevenueCatPlatformCapability;
      appUserId: string;
    }
  | {
      status: "ready";
      capability: RevenueCatPlatformCapability;
      data: RevenueCatReadyData;
      notice: RevenueCatNotice | null;
    }
  | {
      status: "purchasing";
      capability: RevenueCatPlatformCapability;
      data: RevenueCatReadyData;
    }
  | {
      status: "restoring";
      capability: RevenueCatPlatformCapability;
      data: RevenueCatReadyData;
    }
  | {
      status: "unavailable";
      capability: RevenueCatPlatformCapability;
      reason: "configuration" | "platform" | "sdk";
      message: string;
    }
  | {
      status: "recoverable-error";
      capability: RevenueCatPlatformCapability;
      appUserId: string;
      data: RevenueCatReadyData | null;
      code: RevenueCatRecoverableErrorCode;
      message: string;
    };

export type RevenueCatActionResult =
  | { status: "completed"; isPro: boolean }
  | { status: "cancelled" }
  | { status: "pending" }
  | { status: "blocked"; message: string }
  | { status: "failed" };

export function revenueCatReadyData(
  state: RevenueCatState,
): RevenueCatReadyData | null {
  switch (state.status) {
    case "ready":
    case "purchasing":
    case "restoring":
      return state.data;
    case "recoverable-error":
      return state.data;
    case "unconfigured":
    case "initializing":
    case "signed-out":
    case "loading-customer":
    case "unavailable":
      return null;
  }
}
