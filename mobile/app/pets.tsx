import { router } from "expo-router";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { StyleSheet } from "react-native";

import {
  chooseStarterPet,
  createPetPurchaseRequestId,
  equipPetItems,
  getPetAccountState,
  petGallerySnapshot,
  purchasePetItem,
  type PetAccountState,
  type PetEquipmentInput,
} from "../src/api/learningCompanions";
import { createApiClient, resolveApiBaseUrl } from "../src/api/client";
import { getUserFacingErrorMessage } from "../src/api/errors";
import { useAuth } from "../src/auth/AuthContext";
import type { AuthState } from "../src/auth/authFlow";
import { getSupabaseClient } from "../src/auth/supabase";
import { useStudioTheme } from "../src/appearance/StudioThemeContext";
import { secureAppearanceStorage } from "../src/appearance/appearancePreference";
import {
  StudioButton,
  StudioScreen,
  StudioText,
} from "../src/components/studio/StudioPrimitives";
import { PetGallery } from "../src/features/learningCompanions/PetGallery";
import {
  EARNED_CELEBRATION_ID,
  PRO_FLOURISH_ID,
  STUDY_SCARF_ID,
  getPurchaseOffer,
  type PetGalleryState,
  type PendingPetRequest,
  type ProAvailability,
  type PurchasablePetItemId,
} from "../src/features/learningCompanions/petGalleryPresentation";
import type {
  PetAnimationVariant,
  PetId,
} from "../src/features/learningCompanions/petPresentation";
import { useRevenueCat } from "../src/revenuecat/RevenueCatContext";
import type { RevenueCatState } from "../src/revenuecat/types";
import type { ThemeTokens } from "../src/theme";

export const PET_MOTION_STORAGE_KEY = "studyroom.pets.motion.v1";

export type PetsRouteState =
  | { status: "inactive" }
  | { status: "loading"; ownerKey: string }
  | { status: "error"; ownerKey: string; message: string }
  | {
      status: "ready";
      ownerKey: string;
      account: PetAccountState;
      pending: PendingPetRequest | null;
      operationError: string | null;
      proSelected: boolean;
    };

export type PetsRouteApi = {
  load: () => Promise<PetAccountState>;
  chooseStarter: (petId: PetId) => Promise<unknown>;
  purchase: (itemId: PurchasablePetItemId, requestId: string) => Promise<unknown>;
  equip: (input: PetEquipmentInput) => Promise<unknown>;
  createPurchaseRequestId: () => string;
};

export function createOwnerBoundPetsApi(visibleOwner: () => string | null): PetsRouteApi {
  const ownerClient = () => {
    const ownerKey = visibleOwner();
    const separator = ownerKey?.lastIndexOf(":") ?? -1;
    const expectedUserId = separator > 0 ? ownerKey?.slice(0, separator) : null;
    return createApiClient(resolveApiBaseUrl(process.env.EXPO_PUBLIC_API_BASE_URL), {
      getAccessToken: async () => {
        if (expectedUserId === null) return null;
        const { data, error } = await getSupabaseClient().auth.getSession();
        const session = data.session;
        if (
          error || visibleOwner() !== ownerKey || session === null ||
          session.user.id !== expectedUserId
        ) return null;
        return session.access_token;
      },
    });
  };
  return {
    load: () => getPetAccountState(ownerClient()),
    chooseStarter: (petId) => chooseStarterPet(petId, ownerClient()),
    purchase: (itemId, requestId) => purchasePetItem(itemId, requestId, ownerClient()),
    equip: (input) => equipPetItems(input, ownerClient()),
    createPurchaseRequestId: createPetPurchaseRequestId,
  };
}

export function petsOwnerKey(
  authState: AuthState,
  sessionRevision: number,
): string | null {
  if (
    authState.status !== "signed-in" ||
    (authState.profileBootstrap.status !== "ready" &&
      authState.profileBootstrap.status !== "not-required")
  ) {
    return null;
  }
  return `${authState.user.id}:${sessionRevision}`;
}

/** A cached or recoverable-error entitlement is not a current Pro grant. */
export function petProAvailability(
  userId: string | null,
  state: RevenueCatState,
  now = Date.now(),
): ProAvailability {
  if (
    userId === null ||
    state.status !== "ready" ||
    state.capability.status !== "native-purchase-supported" ||
    state.data.appUserId !== userId
  ) {
    return "unknown";
  }
  if (!state.data.isPro) return "inactive";
  if (state.data.expirationDate !== null) {
    const expiration = Date.parse(state.data.expirationDate);
    if (Number.isNaN(expiration)) return "unknown";
    if (expiration <= now) return "inactive";
  }
  return "active";
}

export function visiblePetsGalleryState(
  ownerKey: string | null,
  state: PetsRouteState,
): PetGalleryState {
  if (ownerKey === null || state.status === "inactive" || state.ownerKey !== ownerKey) {
    return { status: "loading" };
  }
  if (state.status === "loading") return { status: "loading" };
  if (state.status === "error") return { status: "error", message: state.message };
  return {
    status: "ready",
    snapshot: petGallerySnapshot(state.account),
    pending: state.pending,
    operationError: state.operationError,
  };
}

export function selectedPetAnimation(state: PetsRouteState): PetAnimationVariant {
  if (state.status !== "ready") return "basic";
  return state.proSelected
    ? PRO_FLOURISH_ID
    : state.account.equipment?.animation_id ?? "basic";
}

/** All loads and mutations are scoped to the visible authenticated session. */
export class PetsRouteController {
  private readonly listeners = new Set<() => void>();
  private readonly api: PetsRouteApi;
  private readonly visibleOwner: () => string | null;
  private ownerKey: string | null = null;
  private generation = 0;
  private state: PetsRouteState = { status: "inactive" };
  private disposed = false;

  constructor(api: PetsRouteApi, visibleOwner: () => string | null) {
    this.api = api;
    this.visibleOwner = visibleOwner;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): PetsRouteState => this.state;

  private publish(state: PetsRouteState): void {
    this.state = state;
    for (const listener of this.listeners) listener();
  }

  private isCurrent(ownerKey: string, generation: number): boolean {
    return !this.disposed && this.ownerKey === ownerKey &&
      this.visibleOwner() === ownerKey && this.generation === generation;
  }

  setOwner(ownerKey: string | null): Promise<void> {
    if (this.disposed || this.ownerKey === ownerKey) return Promise.resolve();
    this.generation += 1;
    this.ownerKey = ownerKey;
    if (ownerKey === null) {
      this.publish({ status: "inactive" });
      return Promise.resolve();
    }
    this.publish({ status: "loading", ownerKey });
    return this.load(ownerKey, this.generation);
  }

  retry(): Promise<void> {
    const ownerKey = this.ownerKey;
    if (
      this.disposed || ownerKey === null || this.visibleOwner() !== ownerKey ||
      (this.state.status === "ready" && this.state.pending !== null)
    ) {
      return Promise.resolve();
    }
    this.generation += 1;
    this.publish({ status: "loading", ownerKey });
    return this.load(ownerKey, this.generation);
  }

  private async load(ownerKey: string, generation: number): Promise<void> {
    try {
      const account = await this.api.load();
      if (this.isCurrent(ownerKey, generation)) {
        this.publish({
          status: "ready", ownerKey, account, pending: null,
          operationError: null, proSelected: false,
        });
      }
    } catch (error: unknown) {
      if (this.isCurrent(ownerKey, generation)) {
        this.publish({
          status: "error", ownerKey,
          message: getUserFacingErrorMessage(error),
        });
      }
    }
  }

  private async mutate(
    pending: PendingPetRequest,
    request: (account: PetAccountState) => Promise<unknown>,
    clearProSelection = false,
  ): Promise<void> {
    const state = this.state;
    if (
      this.disposed || state.status !== "ready" || state.pending !== null ||
      this.visibleOwner() !== state.ownerKey
    ) {
      return;
    }
    const { ownerKey, account, proSelected } = state;
    const generation = this.generation;
    this.publish({ ...state, pending, operationError: null });
    let failure: string | null = null;
    try {
      await request(account);
    } catch (error: unknown) {
      failure = getUserFacingErrorMessage(error);
    }
    if (!this.isCurrent(ownerKey, generation)) return;
    try {
      // Mutation acknowledgements are not a wallet/ownership snapshot.
      const confirmed = await this.api.load();
      if (this.isCurrent(ownerKey, generation)) {
        this.publish({
          status: "ready", ownerKey, account: confirmed, pending: null,
          operationError: failure,
          proSelected: failure === null && clearProSelection ? false : proSelected,
        });
      }
    } catch {
      if (this.isCurrent(ownerKey, generation)) {
        this.publish({
          status: "error", ownerKey,
          message: "Your request may have completed, but its result could not be confirmed. Reload companions before trying again.",
        });
      }
    }
  }

  requestStarter(petId: PetId): Promise<void> {
    const state = this.state;
    if (
      state.status !== "ready" || state.pending !== null ||
      getPurchaseOffer(petGallerySnapshot(state.account), petId).status !== "free-starter"
    ) return Promise.resolve();
    return this.mutate({ kind: "starter", petId }, () => this.api.chooseStarter(petId));
  }

  requestPurchase(itemId: PurchasablePetItemId): Promise<void> {
    const state = this.state;
    if (
      state.status !== "ready" || state.pending !== null ||
      getPurchaseOffer(petGallerySnapshot(state.account), itemId).status !== "available"
    ) return Promise.resolve();
    const requestId = this.api.createPurchaseRequestId();
    return this.mutate(
      { kind: "purchase", itemId },
      () => this.api.purchase(itemId, requestId),
    );
  }

  requestEquipPet(petId: PetId): Promise<void> {
    const state = this.state;
    if (state.status !== "ready" || state.pending !== null ||
      !state.account.owned_item_ids.includes(petId)) {
      return Promise.resolve();
    }
    return this.mutate({ kind: "equip-pet", petId }, (account) => this.api.equip({
      pet_id: petId,
      cosmetic_id: account.equipment?.cosmetic_id ?? null,
      animation_id: account.equipment?.animation_id ?? null,
    }));
  }

  requestScarfEquipped(equipped: boolean): Promise<void> {
    const state = this.state;
    if (
      state.status !== "ready" || state.pending !== null ||
      state.account.equipment === null ||
      !state.account.owned_item_ids.includes(STUDY_SCARF_ID) ||
      (state.account.equipment.cosmetic_id === STUDY_SCARF_ID) === equipped
    ) return Promise.resolve();
    return this.mutate({ kind: "equip-scarf", equipped }, (account) => {
      const equipment = account.equipment;
      if (equipment === null) return Promise.resolve();
      return this.api.equip({
        pet_id: equipment.pet_id,
        cosmetic_id: equipped ? STUDY_SCARF_ID : null,
        animation_id: equipment.animation_id,
      });
    });
  }

  requestEarnedAnimation(variant: "basic" | typeof EARNED_CELEBRATION_ID): Promise<void> {
    const state = this.state;
    if (
      state.status !== "ready" || state.pending !== null ||
      state.account.equipment === null ||
      (variant === EARNED_CELEBRATION_ID &&
        !state.account.owned_item_ids.includes(EARNED_CELEBRATION_ID))
    ) return Promise.resolve();
    return this.mutate({ kind: "select-animation", variant }, (account) => {
      const equipment = account.equipment;
      if (equipment === null) return Promise.resolve();
      return this.api.equip({
        pet_id: equipment.pet_id,
        cosmetic_id: equipment.cosmetic_id,
        animation_id: variant === EARNED_CELEBRATION_ID ? EARNED_CELEBRATION_ID : null,
      });
    }, true);
  }

  selectPro(proAvailability: ProAvailability): void {
    const state = this.state;
    if (
      this.disposed || state.status !== "ready" || state.pending !== null ||
      this.visibleOwner() !== state.ownerKey || state.account.equipment === null ||
      proAvailability !== "active"
    ) return;
    this.publish({ ...state, proSelected: true });
  }

  dispose(): void {
    this.disposed = true;
    this.generation += 1;
    this.ownerKey = null;
    this.listeners.clear();
  }
}

export type PetsScreenProps = {
  theme: ThemeTokens;
  galleryState: PetGalleryState;
  proAvailability: ProAvailability;
  selectedAnimationVariant: PetAnimationVariant;
  animationsEnabled: boolean;
  motionPreferenceError: string | null;
  waitingMessage: string | null;
  onRetry: () => void;
  onRequestStarterClaim: (petId: PetId) => void | Promise<void>;
  onRequestPurchase: (itemId: PurchasablePetItemId) => void | Promise<void>;
  onRequestEquipPet: (petId: PetId) => void | Promise<void>;
  onRequestScarfEquipped: (equipped: boolean) => void | Promise<void>;
  onRequestAnimationVariant: (variant: PetAnimationVariant) => void | Promise<void>;
  onRequestAnimationsEnabled: (enabled: boolean) => void;
  onReturnHome: () => void;
};

export function PetsScreen({
  theme,
  galleryState,
  proAvailability,
  selectedAnimationVariant,
  animationsEnabled,
  motionPreferenceError,
  waitingMessage,
  onRetry,
  onRequestStarterClaim,
  onRequestPurchase,
  onRequestEquipPet,
  onRequestScarfEquipped,
  onRequestAnimationVariant,
  onRequestAnimationsEnabled,
  onReturnHome,
}: PetsScreenProps) {
  return (
    <StudioScreen>
      <StudioText variant="eyebrow">STUDYROOM</StudioText>
      <StudioText variant="title" style={styles.title}>Your companions</StudioText>
      {waitingMessage !== null ? (
        <StudioText tone="muted" style={styles.description}>{waitingMessage}</StudioText>
      ) : (
        <PetGallery
          animationsEnabled={animationsEnabled}
          onRequestAnimationVariant={onRequestAnimationVariant}
          onRequestAnimationsEnabled={onRequestAnimationsEnabled}
          onRequestEquipPet={onRequestEquipPet}
          onRequestPurchase={onRequestPurchase}
          onRequestScarfEquipped={onRequestScarfEquipped}
          onRequestStarterClaim={onRequestStarterClaim}
          onRetryLoad={onRetry}
          proAvailability={proAvailability}
          selectedAnimationVariant={selectedAnimationVariant}
          state={galleryState}
          theme={theme}
        />
      )}
      {motionPreferenceError !== null ? (
        <StudioText accessibilityRole="alert" tone="error" style={styles.notice}>
          {motionPreferenceError}
        </StudioText>
      ) : null}
      <StudioButton label="Return Home" onPress={onReturnHome} variant="secondary" />
    </StudioScreen>
  );
}

export default function PetsRoute() {
  const auth = useAuth();
  const revenueCat = useRevenueCat();
  const theme = useStudioTheme();
  const ownerKey = petsOwnerKey(auth.state, auth.sessionRevision);
  const ownerRef = useRef(ownerKey);
  ownerRef.current = ownerKey;
  const controllerRef = useRef<PetsRouteController | null>(null);
  if (controllerRef.current === null) {
    controllerRef.current = new PetsRouteController(
      createOwnerBoundPetsApi(() => ownerRef.current),
      () => ownerRef.current,
    );
  }
  const controller = controllerRef.current;
  const stored = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => { void controller.setOwner(ownerKey); }, [controller, ownerKey]);
  useEffect(() => () => controller.dispose(), [controller]);

  const [motion, setMotion] = useState({ enabled: false, error: null as string | null });
  const motionSelectedRef = useRef(false);
  const motionSelectionVersion = useRef(0);
  const motionWriteChain = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => {
    let active = true;
    void secureAppearanceStorage.getItem(PET_MOTION_STORAGE_KEY).then(
      (storedValue) => {
        if (active && !motionSelectedRef.current) {
          setMotion({ enabled: storedValue !== "off", error: null });
        }
      },
      () => {
        if (active && !motionSelectedRef.current) {
          setMotion({ enabled: false, error: "Pet motion preference could not be loaded." });
        }
      },
    );
    return () => { active = false; };
  }, []);
  const setAnimationsEnabled = (enabled: boolean) => {
    motionSelectedRef.current = true;
    const version = ++motionSelectionVersion.current;
    setMotion({ enabled, error: null });
    motionWriteChain.current = motionWriteChain.current
      .catch(() => undefined)
      .then(() => secureAppearanceStorage.setItem(PET_MOTION_STORAGE_KEY, enabled ? "on" : "off"))
      .catch(() => {
        if (motionSelectionVersion.current === version) {
          setMotion((current) => ({
            ...current, error: "Pet motion preference could not be saved on this device.",
          }));
        }
      });
  };

  const userId = auth.state.status === "signed-in" ? auth.state.user.id : null;
  const proAvailability = petProAvailability(userId, revenueCat.state);
  const waitingMessage = ownerKey !== null
    ? null
    : auth.state.status === "signed-in"
      ? "Preparing your account before loading companions…"
      : "Returning to sign in…";
  return (
    <PetsScreen
      animationsEnabled={motion.enabled}
      galleryState={visiblePetsGalleryState(ownerKey, stored)}
      motionPreferenceError={motion.error}
      onRequestAnimationVariant={(variant) => {
        if (variant === PRO_FLOURISH_ID) controller.selectPro(proAvailability);
        else return controller.requestEarnedAnimation(variant);
      }}
      onRequestAnimationsEnabled={setAnimationsEnabled}
      onRequestEquipPet={(petId) => controller.requestEquipPet(petId)}
      onRequestPurchase={(itemId) => controller.requestPurchase(itemId)}
      onRequestScarfEquipped={(equipped) => controller.requestScarfEquipped(equipped)}
      onRequestStarterClaim={(petId) => controller.requestStarter(petId)}
      onRetry={() => { void controller.retry(); }}
      onReturnHome={() => router.replace("/")}
      proAvailability={proAvailability}
      selectedAnimationVariant={selectedPetAnimation(stored)}
      theme={theme}
      waitingMessage={waitingMessage}
    />
  );
}

const styles = StyleSheet.create({
  title: { marginTop: 6, marginBottom: 16 },
  description: { marginBottom: 16 },
  notice: { marginTop: 16 },
});
