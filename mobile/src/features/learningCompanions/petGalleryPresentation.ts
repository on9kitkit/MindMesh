import {
  PET_IDS,
  type PetAnimationVariant,
  type PetId,
} from "./petPresentation";

export const STUDY_SCARF_ID = "cosmetic.study_scarf" as const;
export const EARNED_CELEBRATION_ID = "animation.earned_celebration" as const;
export const PRO_FLOURISH_ID = "animation.pro_flourish" as const;

export type EarnedCosmeticId =
  | typeof STUDY_SCARF_ID
  | typeof EARNED_CELEBRATION_ID;
export type PurchasablePetItemId = PetId | EarnedCosmeticId;
export type ProAvailability = "active" | "inactive" | "unknown";

/** Values here must come from a confirmed server response, never a local estimate. */
export type ConfirmedPetGallery = {
  balance: number;
  ownedPetIds: ReadonlyArray<PetId>;
  equippedPetId: PetId | null;
  ownedCosmeticIds: ReadonlyArray<EarnedCosmeticId>;
  scarfEquipped: boolean;
  starterClaimAvailable: boolean;
  catalogPrices: Readonly<Partial<Record<PurchasablePetItemId, number>>>;
};

export type PendingPetRequest =
  | { kind: "starter"; petId: PetId }
  | { kind: "purchase"; itemId: PurchasablePetItemId }
  | { kind: "equip-pet"; petId: PetId }
  | { kind: "equip-scarf"; equipped: boolean }
  | { kind: "select-animation"; variant: PetAnimationVariant };

export type PetReviewChoice =
  | { kind: "starter"; petId: PetId }
  | { kind: "purchase"; itemId: PurchasablePetItemId; quotedPrice: number };

export type PetGalleryState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      snapshot: ConfirmedPetGallery;
      pending: PendingPetRequest | null;
      operationError: string | null;
    };

export type PurchaseOffer =
  | { status: "owned" }
  | { status: "free-starter" }
  | { status: "available"; price: number }
  | { status: "insufficient"; price: number; shortfall: number }
  | { status: "unavailable" };

export function isPetId(itemId: PurchasablePetItemId): itemId is PetId {
  return PET_IDS.some((petId) => petId === itemId);
}

export function ownsPetItem(
  snapshot: ConfirmedPetGallery,
  itemId: PurchasablePetItemId,
): boolean {
  return isPetId(itemId)
    ? snapshot.ownedPetIds.includes(itemId)
    : snapshot.ownedCosmeticIds.includes(itemId);
}

export function confirmedBalance(snapshot: ConfirmedPetGallery): number | null {
  return Number.isSafeInteger(snapshot.balance) && snapshot.balance >= 0
    ? snapshot.balance
    : null;
}

export function getPurchaseOffer(
  snapshot: ConfirmedPetGallery,
  itemId: PurchasablePetItemId,
): PurchaseOffer {
  if (ownsPetItem(snapshot, itemId)) return { status: "owned" };
  if (
    isPetId(itemId) &&
    snapshot.starterClaimAvailable &&
    snapshot.ownedPetIds.length === 0
  ) {
    return { status: "free-starter" };
  }
  const balance = confirmedBalance(snapshot);
  const price = snapshot.catalogPrices[itemId];
  if (balance === null || typeof price !== "number" || !Number.isSafeInteger(price) || price <= 0) {
    return { status: "unavailable" };
  }
  return balance >= price
    ? { status: "available", price }
    : { status: "insufficient", price, shortfall: price - balance };
}

export function getPreviewPet(snapshot: ConfirmedPetGallery): {
  petId: PetId;
  status: "equipped" | "owned" | "preview-only";
} {
  if (
    snapshot.equippedPetId !== null &&
    snapshot.ownedPetIds.includes(snapshot.equippedPetId)
  ) {
    return { petId: snapshot.equippedPetId, status: "equipped" };
  }
  const firstOwned = PET_IDS.find((petId) => snapshot.ownedPetIds.includes(petId));
  return firstOwned
    ? { petId: firstOwned, status: "owned" }
    : { petId: "pet.owl", status: "preview-only" };
}

/** Pro is a separate, current presentation entitlement, never wallet ownership. */
export function getAvailableAnimationVariant(
  snapshot: ConfirmedPetGallery,
  selectedAnimationVariant: PetAnimationVariant,
  proAvailability: ProAvailability,
): PetAnimationVariant {
  const earnedOwned = snapshot.ownedCosmeticIds.includes(EARNED_CELEBRATION_ID);
  if (selectedAnimationVariant === PRO_FLOURISH_ID) {
    if (proAvailability === "active") return PRO_FLOURISH_ID;
    return earnedOwned ? EARNED_CELEBRATION_ID : "basic";
  }
  if (selectedAnimationVariant === EARNED_CELEBRATION_ID && earnedOwned) {
    return EARNED_CELEBRATION_ID;
  }
  return "basic";
}

const REVIEW_NAMES: Readonly<Record<PurchasablePetItemId, string>> = {
  "pet.owl": "Owl",
  "pet.tortoise": "Tortoise",
  "pet.fox": "Fox",
  [STUDY_SCARF_ID]: "Study scarf",
  [EARNED_CELEBRATION_ID]: "Earned celebration",
};

/** Returns no prompt if ownership, quoted price, or affordability changed. */
export function getPetReviewPrompt(
  snapshot: ConfirmedPetGallery,
  choice: PetReviewChoice | null,
): string | null {
  if (choice === null) return null;
  const itemId = choice.kind === "starter" ? choice.petId : choice.itemId;
  const offer = getPurchaseOffer(snapshot, itemId);
  if (choice.kind === "starter") {
    return offer.status === "free-starter"
      ? `Choose ${REVIEW_NAMES[itemId]} as your one free starter? Other pets can be earned later.`
      : null;
  }
  const balance = confirmedBalance(snapshot);
  return offer.status === "available" &&
    offer.price === choice.quotedPrice &&
    balance !== null
    ? `Buy ${REVIEW_NAMES[itemId]} for ${offer.price} coins? Your confirmed balance is ${balance} coins. Your balance and ownership update only after server confirmation.`
    : null;
}
