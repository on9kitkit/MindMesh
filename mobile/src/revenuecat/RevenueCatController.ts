import type { RevenueCatConfigurationResult } from "./config";
import {
  deriveRevenueCatReadyData,
  safeRevenueCatError,
  updateRevenueCatEntitlement,
} from "./state";
import {
  revenueCatReadyData,
  type RevenueCatActionResult,
  type RevenueCatAdapter,
  type RevenueCatAdapterFailureCode,
  type RevenueCatCustomerInfo,
  type RevenueCatReadyData,
  type RevenueCatState,
} from "./types";

type RevenueCatControllerDependencies = {
  adapter: RevenueCatAdapter;
  configuration: RevenueCatConfigurationResult;
};

type StateListener = () => void;

function failureMessage(
  code: RevenueCatAdapterFailureCode,
  operation: "purchase" | "restore",
): string {
  switch (code) {
    case "network-failure":
      return "RevenueCat could not be reached. Check your connection and try again.";
    case "store-unavailable":
      return "The store is unavailable right now. Please try again later.";
    case "purchase-pending":
      return "The purchase is pending store approval. Pro will update when confirmed.";
    case "configuration-failure":
      return "RevenueCat is not configured correctly for this build.";
    case "purchase-failed":
      return operation === "restore"
        ? "Purchases could not be restored. Please try again."
        : "The purchase could not be completed. Please try again.";
  }
}

export class RevenueCatController {
  private state: RevenueCatState;
  private readonly listeners = new Set<StateListener>();
  private initializationPromise: Promise<void> | null = null;
  private reconciliationQueue: Promise<void> = Promise.resolve();
  private purchasePromise: Promise<RevenueCatActionResult> | null = null;
  private restorePromise: Promise<RevenueCatActionResult> | null = null;
  private removeCustomerInfoListener: (() => void) | null = null;
  private desiredUserId: string | null = null;
  private sdkUserId: string | null = null;
  private identityGeneration = 0;
  private configured = false;
  private disposed = false;

  constructor(private readonly dependencies: RevenueCatControllerDependencies) {
    this.state = {
      status: "unconfigured",
      capability: dependencies.adapter.capability,
    };
  }

  readonly subscribe = (listener: StateListener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getState = (): RevenueCatState => this.state;

  private setState(state: RevenueCatState): void {
    if (this.disposed) {
      return;
    }
    this.state = state;
    for (const listener of this.listeners) {
      listener();
    }
  }

  initialize(): Promise<void> {
    if (this.initializationPromise !== null) {
      return this.initializationPromise;
    }
    this.initializationPromise = this.performInitialization();
    return this.initializationPromise;
  }

  private async performInitialization(): Promise<void> {
    const { adapter, configuration } = this.dependencies;
    if (configuration.status === "unavailable") {
      this.setState({
        status: "unavailable",
        capability: adapter.capability,
        reason: "configuration",
        message: configuration.message,
      });
      return;
    }
    if (
      adapter.capability.status ===
        "unsupported-with-current-web-configuration" ||
      adapter.capability.status === "unsupported-platform"
    ) {
      this.setState({
        status: "unavailable",
        capability: adapter.capability,
        reason: "platform",
        message: adapter.capability.message,
      });
      return;
    }

    this.setState({
      status: "initializing",
      capability: adapter.capability,
    });
    try {
      await adapter.configure(configuration.configuration.apiKey);
      if (this.disposed) {
        return;
      }
      const removeCustomerInfoListener =
        await adapter.addCustomerInfoUpdateListener((customerInfo) => {
          this.applyCustomerInfoUpdate(customerInfo);
        });
      if (this.disposed) {
        removeCustomerInfoListener();
        return;
      }
      this.removeCustomerInfoListener = removeCustomerInfoListener;
      this.configured = true;
    } catch (error: unknown) {
      const failure = safeRevenueCatError(error, "configuration");
      this.setState({
        status: "unavailable",
        capability: adapter.capability,
        reason: "sdk",
        message: failure.message,
      });
      return;
    }

    if (this.desiredUserId === null) {
      this.setState({
        status: "signed-out",
        capability: adapter.capability,
      });
      return;
    }
    this.setLoadingCustomer(this.desiredUserId);
    await this.queueReconciliation();
  }

  setAuthenticated(appUserId: string): Promise<void> {
    const normalizedUserId = appUserId.trim();
    if (!normalizedUserId || this.desiredUserId === normalizedUserId) {
      return this.reconciliationQueue;
    }
    this.desiredUserId = normalizedUserId;
    this.identityGeneration += 1;
    if (this.configured) {
      this.setLoadingCustomer(normalizedUserId);
      return this.queueReconciliation();
    }
    return this.reconciliationQueue;
  }

  setSignedOut(): Promise<void> {
    if (this.desiredUserId === null && this.sdkUserId === null) {
      if (this.configured && this.state.status !== "signed-out") {
        this.setState({
          status: "signed-out",
          capability: this.dependencies.adapter.capability,
        });
      }
      return this.reconciliationQueue;
    }
    this.desiredUserId = null;
    this.identityGeneration += 1;
    if (this.configured) {
      this.setState({
        status: "signed-out",
        capability: this.dependencies.adapter.capability,
      });
      return this.queueReconciliation();
    }
    return this.reconciliationQueue;
  }

  private setLoadingCustomer(appUserId: string): void {
    this.setState({
      status: "loading-customer",
      capability: this.dependencies.adapter.capability,
      appUserId,
    });
  }

  private queueReconciliation(): Promise<void> {
    if (!this.configured || this.disposed) {
      return this.reconciliationQueue;
    }
    const queued = this.reconciliationQueue.then(() =>
      this.reconcileCurrentIdentity(),
    );
    this.reconciliationQueue = queued.catch(() => undefined);
    return queued;
  }

  private identityIsCurrent(generation: number, userId: string): boolean {
    return (
      !this.disposed &&
      this.identityGeneration === generation &&
      this.desiredUserId === userId
    );
  }

  private async reconcileCurrentIdentity(): Promise<void> {
    if (!this.configured || this.disposed) {
      return;
    }
    const targetUserId = this.desiredUserId;
    const generation = this.identityGeneration;
    const { adapter, configuration } = this.dependencies;
    if (configuration.status !== "configured") {
      return;
    }

    if (targetUserId === null) {
      if (this.sdkUserId !== null) {
        try {
          await adapter.logOut();
          this.sdkUserId = null;
        } catch {
          // Auth state is already cleared. A later login will explicitly replace
          // the RevenueCat identity if the SDK could not log out here.
        }
      }
      if (
        !this.disposed &&
        this.identityGeneration === generation &&
        this.desiredUserId === null
      ) {
        this.setState({
          status: "signed-out",
          capability: adapter.capability,
        });
      }
      return;
    }

    this.setLoadingCustomer(targetUserId);
    if (this.sdkUserId !== targetUserId) {
      try {
        await adapter.logIn(targetUserId);
        this.sdkUserId = targetUserId;
      } catch (error: unknown) {
        if (this.identityIsCurrent(generation, targetUserId)) {
          const failure = safeRevenueCatError(error, "identity");
          this.setState({
            status: "recoverable-error",
            capability: adapter.capability,
            appUserId: targetUserId,
            data: null,
            code: failure.code,
            message: failure.message,
          });
        }
        return;
      }
    }
    if (!this.identityIsCurrent(generation, targetUserId)) {
      return;
    }

    let customerInfo: RevenueCatCustomerInfo;
    try {
      customerInfo = await adapter.getCustomerInfo();
    } catch (error: unknown) {
      if (this.identityIsCurrent(generation, targetUserId)) {
        const failure = safeRevenueCatError(error, "customer-info");
        this.setState({
          status: "recoverable-error",
          capability: adapter.capability,
          appUserId: targetUserId,
          data: null,
          code: failure.code,
          message: failure.message,
        });
      }
      return;
    }
    if (!this.identityIsCurrent(generation, targetUserId)) {
      return;
    }

    try {
      const offerings = await adapter.getOfferings();
      if (!this.identityIsCurrent(generation, targetUserId)) {
        return;
      }
      this.setState({
        status: "ready",
        capability: adapter.capability,
        data: deriveRevenueCatReadyData(
          targetUserId,
          configuration.configuration.entitlementId,
          configuration.configuration.offeringId,
          customerInfo,
          offerings,
        ),
        notice: null,
      });
    } catch (error: unknown) {
      if (!this.identityIsCurrent(generation, targetUserId)) {
        return;
      }
      const failure = safeRevenueCatError(error, "offering");
      this.setState({
        status: "recoverable-error",
        capability: adapter.capability,
        appUserId: targetUserId,
        data: deriveRevenueCatReadyData(
          targetUserId,
          configuration.configuration.entitlementId,
          configuration.configuration.offeringId,
          customerInfo,
          null,
        ),
        code: failure.code,
        message: failure.message,
      });
    }
  }

  refreshCustomerInfo(): Promise<void> {
    const userId = this.desiredUserId;
    if (
      !this.configured ||
      userId === null ||
      this.state.status === "purchasing" ||
      this.state.status === "restoring" ||
      this.state.status === "loading-customer"
    ) {
      return this.reconciliationQueue;
    }
    this.setLoadingCustomer(userId);
    return this.queueReconciliation();
  }

  private applyCustomerInfoUpdate(customerInfo: RevenueCatCustomerInfo): void {
    const userId = this.desiredUserId;
    if (userId === null || this.sdkUserId !== userId || this.disposed) {
      return;
    }
    const data = revenueCatReadyData(this.state);
    if (data === null || data.appUserId !== userId) {
      return;
    }
    const updatedData = updateRevenueCatEntitlement(data, customerInfo);
    switch (this.state.status) {
      case "ready":
        this.setState({
          ...this.state,
          data: updatedData,
          notice: null,
        });
        return;
      case "purchasing":
      case "restoring":
        this.setState({ ...this.state, data: updatedData });
        return;
      case "recoverable-error":
        this.setState({ ...this.state, data: updatedData });
        return;
      case "unconfigured":
      case "initializing":
      case "signed-out":
      case "loading-customer":
      case "unavailable":
        return;
    }
  }

  presentPaywall(): Promise<RevenueCatActionResult> {
    if (this.purchasePromise !== null) {
      return Promise.resolve({
        status: "blocked",
        message: "A purchase is already in progress.",
      });
    }
    if (
      this.dependencies.adapter.capability.status !==
      "native-purchase-supported"
    ) {
      return Promise.resolve({
        status: "blocked",
        message: this.dependencies.adapter.capability.message,
      });
    }
    if (this.restorePromise !== null) {
      return Promise.resolve({
        status: "blocked",
        message: "Wait for purchase restoration to finish.",
      });
    }
    const data = revenueCatReadyData(this.state);
    if (data === null || this.desiredUserId !== data.appUserId) {
      return Promise.resolve({
        status: "blocked",
        message: "MindMesh Pro is still loading.",
      });
    }
    if (data.isPro) {
      return Promise.resolve({
        status: "blocked",
        message: "MindMesh Pro is already active.",
      });
    }
    if (data.offering === null || data.offeringStatus === "missing") {
      this.setState({
        status: "recoverable-error",
        capability: this.dependencies.adapter.capability,
        appUserId: data.appUserId,
        data,
        code: "offering-unavailable",
        message: "The configured MindMesh Pro offering is unavailable.",
      });
      return Promise.resolve({ status: "failed" });
    }
    if (data.offeringStatus === "empty") {
      this.setState({
        status: "recoverable-error",
        capability: this.dependencies.adapter.capability,
        appUserId: data.appUserId,
        data,
        code: "package-unavailable",
        message: "The MindMesh Pro offering has no available packages.",
      });
      return Promise.resolve({ status: "failed" });
    }

    this.setState({
      status: "purchasing",
      capability: this.dependencies.adapter.capability,
      data,
    });
    const operation = this.performPaywallPresentation(data);
    this.purchasePromise = operation;
    void operation.finally(() => {
      if (this.purchasePromise === operation) {
        this.purchasePromise = null;
      }
    });
    return operation;
  }

  private async performPaywallPresentation(
    startingData: RevenueCatReadyData,
  ): Promise<RevenueCatActionResult> {
    const generation = this.identityGeneration;
    const userId = startingData.appUserId;
    try {
      const result = await this.dependencies.adapter.presentPaywall(
        startingData.offering?.identifier ?? "",
      );
      if (!this.identityIsCurrent(generation, userId)) {
        return { status: "blocked", message: "The signed-in user changed." };
      }
      const latestData = revenueCatReadyData(this.state) ?? startingData;
      switch (result.status) {
        case "cancelled":
          this.setState({
            status: "ready",
            capability: this.dependencies.adapter.capability,
            data: latestData,
            notice: {
              tone: "neutral",
              message: "Purchase cancelled. No changes were made.",
            },
          });
          return { status: "cancelled" };
        case "not-presented":
          this.setState({
            status: "ready",
            capability: this.dependencies.adapter.capability,
            data: latestData,
            notice: {
              tone: "neutral",
              message: "The paywall closed without a purchase.",
            },
          });
          return { status: "cancelled" };
        case "pending":
          this.setState({
            status: "ready",
            capability: this.dependencies.adapter.capability,
            data: latestData,
            notice: {
              tone: "neutral",
              message:
                "The purchase is pending store approval. Pro will update when confirmed.",
            },
          });
          return { status: "pending" };
        case "failed":
          this.setState({
            status: "recoverable-error",
            capability: this.dependencies.adapter.capability,
            appUserId: userId,
            data: latestData,
            code: result.code,
            message: failureMessage(result.code, "purchase"),
          });
          return { status: "failed" };
        case "offering-unavailable":
          this.setState({
            status: "recoverable-error",
            capability: this.dependencies.adapter.capability,
            appUserId: userId,
            data: latestData,
            code: "offering-unavailable",
            message: "The configured MindMesh Pro offering is unavailable.",
          });
          return { status: "failed" };
        case "purchased":
        case "restored":
          return await this.confirmPaywallEntitlement(
            latestData,
            generation,
            result.status,
          );
      }
    } catch (error: unknown) {
      if (!this.identityIsCurrent(generation, userId)) {
        return { status: "blocked", message: "The signed-in user changed." };
      }
      const failure = safeRevenueCatError(error, "purchase");
      this.setState({
        status: "recoverable-error",
        capability: this.dependencies.adapter.capability,
        appUserId: userId,
        data: revenueCatReadyData(this.state) ?? startingData,
        code: failure.code,
        message: failure.message,
      });
      return { status: "failed" };
    }
  }

  private async confirmPaywallEntitlement(
    data: RevenueCatReadyData,
    generation: number,
    outcome: "purchased" | "restored",
  ): Promise<RevenueCatActionResult> {
    const customerInfo = await this.dependencies.adapter.getCustomerInfo();
    if (!this.identityIsCurrent(generation, data.appUserId)) {
      return { status: "blocked", message: "The signed-in user changed." };
    }
    const updatedData = updateRevenueCatEntitlement(data, customerInfo);
    if (!updatedData.isPro) {
      if (outcome === "restored") {
        this.setState({
          status: "ready",
          capability: this.dependencies.adapter.capability,
          data: updatedData,
          notice: {
            tone: "neutral",
            message: "No MindMesh Pro purchase was found to restore.",
          },
        });
        return { status: "completed", isPro: false };
      }
      this.setState({
        status: "recoverable-error",
        capability: this.dependencies.adapter.capability,
        appUserId: data.appUserId,
        data: updatedData,
        code: "entitlement-not-active",
        message:
          "The purchase finished, but the MindMesh Pro entitlement is not active yet.",
      });
      return { status: "failed" };
    }
    this.setState({
      status: "ready",
      capability: this.dependencies.adapter.capability,
      data: updatedData,
      notice: {
        tone: "success",
        message: "MindMesh Pro is active.",
      },
    });
    return { status: "completed", isPro: true };
  }

  restorePurchases(): Promise<RevenueCatActionResult> {
    if (this.restorePromise !== null) {
      return this.restorePromise;
    }
    if (
      this.dependencies.adapter.capability.status !==
      "native-purchase-supported"
    ) {
      return Promise.resolve({
        status: "blocked",
        message: this.dependencies.adapter.capability.message,
      });
    }
    if (this.purchasePromise !== null) {
      return Promise.resolve({
        status: "blocked",
        message: "Wait for the current purchase to finish.",
      });
    }
    const data = revenueCatReadyData(this.state);
    if (data === null || this.desiredUserId !== data.appUserId) {
      return Promise.resolve({
        status: "blocked",
        message: "MindMesh Pro is still loading.",
      });
    }

    this.setState({
      status: "restoring",
      capability: this.dependencies.adapter.capability,
      data,
    });
    const operation = this.performRestore(data);
    this.restorePromise = operation;
    void operation.finally(() => {
      if (this.restorePromise === operation) {
        this.restorePromise = null;
      }
    });
    return operation;
  }

  private async performRestore(
    startingData: RevenueCatReadyData,
  ): Promise<RevenueCatActionResult> {
    const generation = this.identityGeneration;
    try {
      const customerInfo = await this.dependencies.adapter.restorePurchases();
      if (!this.identityIsCurrent(generation, startingData.appUserId)) {
        return { status: "blocked", message: "The signed-in user changed." };
      }
      const latestData = revenueCatReadyData(this.state) ?? startingData;
      const updatedData = updateRevenueCatEntitlement(
        latestData,
        customerInfo,
      );
      this.setState({
        status: "ready",
        capability: this.dependencies.adapter.capability,
        data: updatedData,
        notice: updatedData.isPro
          ? { tone: "success", message: "MindMesh Pro was restored." }
          : {
              tone: "neutral",
              message: "No MindMesh Pro purchase was found to restore.",
            },
      });
      return { status: "completed", isPro: updatedData.isPro };
    } catch (error: unknown) {
      if (!this.identityIsCurrent(generation, startingData.appUserId)) {
        return { status: "blocked", message: "The signed-in user changed." };
      }
      const failure = safeRevenueCatError(error, "restore");
      this.setState({
        status: "recoverable-error",
        capability: this.dependencies.adapter.capability,
        appUserId: startingData.appUserId,
        data: revenueCatReadyData(this.state) ?? startingData,
        code: failure.code,
        message: failure.message,
      });
      return { status: "failed" };
    }
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.identityGeneration += 1;
    this.removeCustomerInfoListener?.();
    this.removeCustomerInfoListener = null;
    this.listeners.clear();
  }
}
