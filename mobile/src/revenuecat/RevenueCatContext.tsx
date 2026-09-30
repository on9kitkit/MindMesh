import {
  createContext,
  type PropsWithChildren,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from "react";
import { AppState, type AppStateStatus } from "react-native";

import { useAuth } from "../auth/AuthContext";
import { loadRevenueCatConfiguration } from "./config";
import { getProductionRevenueCatAdapter } from "./nativeAdapter";
import { RevenueCatController } from "./RevenueCatController";
import { synchronizeRevenueCatAuthentication } from "./authLifecycle";
import type {
  RevenueCatActionResult,
  RevenueCatState,
} from "./types";

export type RevenueCatContextValue = {
  state: RevenueCatState;
  presentPaywall(): Promise<RevenueCatActionResult>;
  restorePurchases(): Promise<RevenueCatActionResult>;
  refreshCustomerInfo(): Promise<void>;
  clearIdentity(): Promise<void>;
};

type RevenueCatProviderProps = PropsWithChildren<{
  controller?: RevenueCatController;
}>;

const RevenueCatContext = createContext<RevenueCatContextValue | undefined>(
  undefined,
);

function createProductionController(): RevenueCatController {
  return new RevenueCatController({
    adapter: getProductionRevenueCatAdapter(),
    configuration: loadRevenueCatConfiguration(),
  });
}

export function RevenueCatProvider({
  children,
  controller: providedController,
}: RevenueCatProviderProps) {
  const controllerRef = useRef<RevenueCatController | null>(null);
  const ownsControllerRef = useRef(providedController === undefined);
  if (controllerRef.current === null) {
    controllerRef.current = providedController ?? createProductionController();
  }
  const controller = controllerRef.current;
  const { state: authState } = useAuth();
  const authenticatedUserId =
    authState.status === "signed-in" ? authState.user.id : null;
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getState,
    controller.getState,
  );

  useLayoutEffect(() => {
    synchronizeRevenueCatAuthentication(controller, authState);
  }, [authState.status, authenticatedUserId, controller]);

  useEffect(() => {
    void controller.initialize();
  }, [controller]);

  useEffect(() => {
    let previousState: AppStateStatus = AppState.currentState;
    const subscription = AppState.addEventListener("change", (nextState) => {
      const becameActive = previousState !== "active" && nextState === "active";
      previousState = nextState;
      if (becameActive) {
        void controller.refreshCustomerInfo();
      }
    });
    return () => subscription.remove();
  }, [controller]);

  useEffect(
    () => () => {
      if (ownsControllerRef.current) {
        controller.dispose();
      }
    },
    [controller],
  );

  const value = useMemo<RevenueCatContextValue>(
    () => ({
      state,
      presentPaywall: () => controller.presentPaywall(),
      restorePurchases: () => controller.restorePurchases(),
      refreshCustomerInfo: () => controller.refreshCustomerInfo(),
      clearIdentity: () => controller.setSignedOut(),
    }),
    [controller, state],
  );

  return (
    <RevenueCatContext.Provider value={value}>
      {children}
    </RevenueCatContext.Provider>
  );
}

export function useRevenueCat(): RevenueCatContextValue {
  const context = useContext(RevenueCatContext);
  if (context === undefined) {
    throw new Error("useRevenueCat must be used inside RevenueCatProvider");
  }
  return context;
}
