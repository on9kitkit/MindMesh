import { NativeModules, Platform } from "react-native";
import { mindMeshProductCopy } from "./brandCopy";
import type {
  CustomerInfo,
  PurchasesEntitlementInfo,
  PurchasesOffering,
} from "react-native-purchases";

import {
  adapterFailureCodeFromError,
  revenueCatErrorIsCancellation,
} from "./state";
import type {
  NativePurchasePlatform,
  RevenueCatAdapter,
  RevenueCatCustomerInfo,
  RevenueCatEntitlementInfo,
  RevenueCatOffering,
  RevenueCatPaywallResult,
  RevenueCatPlatformCapability,
} from "./types";

type PurchasesModule = typeof import("react-native-purchases");

function sanitizeEntitlement(
  entitlement: PurchasesEntitlementInfo,
): RevenueCatEntitlementInfo {
  return {
    identifier: entitlement.identifier,
    isActive: entitlement.isActive,
    expirationDate: entitlement.expirationDate,
    willRenew: entitlement.willRenew,
    isSandbox: entitlement.isSandbox,
  };
}

function sanitizeEntitlements(
  entitlements: Readonly<Record<string, PurchasesEntitlementInfo>>,
): Readonly<Record<string, RevenueCatEntitlementInfo>> {
  return Object.fromEntries(
    Object.entries(entitlements).map(([identifier, entitlement]) => [
      identifier,
      sanitizeEntitlement(entitlement),
    ]),
  );
}

function sanitizeCustomerInfo(
  customerInfo: CustomerInfo,
): RevenueCatCustomerInfo {
  return {
    entitlements: {
      active: sanitizeEntitlements(customerInfo.entitlements.active),
      all: sanitizeEntitlements(customerInfo.entitlements.all),
    },
    managementUrl: customerInfo.managementURL,
  };
}

function sanitizeOffering(offering: PurchasesOffering): RevenueCatOffering {
  return {
    identifier: offering.identifier,
    packages: offering.availablePackages.map((availablePackage) => ({
      identifier: availablePackage.identifier,
      productIdentifier: availablePackage.product.identifier,
      title: mindMeshProductCopy(availablePackage.product.title),
      description: mindMeshProductCopy(availablePackage.product.description),
      price: availablePackage.product.priceString,
      period: availablePackage.product.subscriptionPeriod,
    })),
  };
}

function expoGoIsActive(): boolean {
  const runtime = globalThis as typeof globalThis & {
    expo?: { modules?: { ExpoGo?: boolean } };
  };
  return runtime.expo?.modules?.ExpoGo === true;
}

export function resolveRevenueCatPlatformCapability(
  platform: string,
  nativeModulesAvailable: boolean,
  isExpoGo: boolean,
): RevenueCatPlatformCapability {
  if (platform === "web") {
    return {
      status: "unsupported-with-current-web-configuration",
      platform: "web",
      message:
        "Purchases are unavailable on Web until RevenueCat Billing is configured. Use a native development build.",
    };
  }
  if (platform !== "ios" && platform !== "android") {
    return {
      status: "unsupported-platform",
      platform,
      message: "RevenueCat purchases are unavailable on this platform.",
    };
  }
  if (!nativeModulesAvailable) {
    return {
      status: "preview-only",
      platform: platform as NativePurchasePlatform,
      message: isExpoGo
        ? "Expo Go is preview-only. Use a native development build to test purchases."
        : "This build does not include the RevenueCat native modules. Use a development build.",
    };
  }
  return {
    status: "native-purchase-supported",
    platform: platform as NativePurchasePlatform,
  };
}

function currentCapability(): RevenueCatPlatformCapability {
  const nativeModulesAvailable =
    NativeModules.RNPurchases !== undefined &&
    NativeModules.RNPaywalls !== undefined;
  return resolveRevenueCatPlatformCapability(
    Platform.OS,
    nativeModulesAvailable,
    expoGoIsActive(),
  );
}

class ProductionRevenueCatAdapter implements RevenueCatAdapter {
  readonly capability = currentCapability();

  private configurationPromise: Promise<void> | null = null;
  private modulePromise: Promise<PurchasesModule> | null = null;
  private readonly nativeOfferings = new Map<string, PurchasesOffering>();

  private getModule(): Promise<PurchasesModule> {
    if (this.modulePromise === null) {
      this.modulePromise = import("react-native-purchases");
    }
    return this.modulePromise;
  }

  configure(apiKey: string): Promise<void> {
    if (this.configurationPromise !== null) {
      return this.configurationPromise;
    }
    this.configurationPromise = this.configureOnce(apiKey);
    return this.configurationPromise;
  }

  private async configureOnce(apiKey: string): Promise<void> {
    const { default: Purchases } = await this.getModule();
    if (!(await Purchases.isConfigured())) {
      Purchases.configure({ apiKey });
    }
  }

  async logIn(appUserId: string): Promise<RevenueCatCustomerInfo> {
    const { default: Purchases } = await this.getModule();
    const result = await Purchases.logIn(appUserId);
    return sanitizeCustomerInfo(result.customerInfo);
  }

  async logOut(): Promise<RevenueCatCustomerInfo> {
    const { default: Purchases } = await this.getModule();
    return sanitizeCustomerInfo(await Purchases.logOut());
  }

  async getCustomerInfo(): Promise<RevenueCatCustomerInfo> {
    const { default: Purchases } = await this.getModule();
    return sanitizeCustomerInfo(await Purchases.getCustomerInfo());
  }

  async getOfferings() {
    const { default: Purchases } = await this.getModule();
    const offerings = await Purchases.getOfferings();
    this.nativeOfferings.clear();
    for (const offering of Object.values(offerings.all)) {
      this.nativeOfferings.set(offering.identifier, offering);
    }
    return {
      currentOfferingId: offerings.current?.identifier ?? null,
      offerings: Object.values(offerings.all).map(sanitizeOffering),
    };
  }

  async presentPaywall(offeringId: string): Promise<RevenueCatPaywallResult> {
    const offering = this.nativeOfferings.get(offeringId);
    if (!offering) {
      return { status: "offering-unavailable" };
    }
    try {
      const { default: RevenueCatUI, PAYWALL_RESULT } = await import(
        "react-native-purchases-ui"
      );
      const result = await RevenueCatUI.presentPaywall({ offering });
      switch (result) {
        case PAYWALL_RESULT.PURCHASED:
          return { status: "purchased" };
        case PAYWALL_RESULT.RESTORED:
          return { status: "restored" };
        case PAYWALL_RESULT.CANCELLED:
          return { status: "cancelled" };
        case PAYWALL_RESULT.NOT_PRESENTED:
          return { status: "not-presented" };
        case PAYWALL_RESULT.ERROR:
          return { status: "failed", code: "purchase-failed" };
      }
    } catch (error: unknown) {
      if (revenueCatErrorIsCancellation(error)) {
        return { status: "cancelled" };
      }
      const code = adapterFailureCodeFromError(error);
      if (code === "purchase-pending") {
        return { status: "pending" };
      }
      return { status: "failed", code };
    }
  }

  async restorePurchases(): Promise<RevenueCatCustomerInfo> {
    const { default: Purchases } = await this.getModule();
    return sanitizeCustomerInfo(await Purchases.restorePurchases());
  }

  async addCustomerInfoUpdateListener(
    listener: (customerInfo: RevenueCatCustomerInfo) => void,
  ): Promise<() => void> {
    const { default: Purchases } = await this.getModule();
    const nativeListener = (customerInfo: CustomerInfo) => {
      listener(sanitizeCustomerInfo(customerInfo));
    };
    Purchases.addCustomerInfoUpdateListener(nativeListener);
    return () => {
      Purchases.removeCustomerInfoUpdateListener(nativeListener);
    };
  }
}

let productionAdapter: RevenueCatAdapter | null = null;

export function getProductionRevenueCatAdapter(): RevenueCatAdapter {
  if (productionAdapter === null) {
    productionAdapter = new ProductionRevenueCatAdapter();
  }
  return productionAdapter;
}
