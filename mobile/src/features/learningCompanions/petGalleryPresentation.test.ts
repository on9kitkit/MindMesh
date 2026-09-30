import assert from "node:assert/strict";
import test from "node:test";

import {
  EARNED_CELEBRATION_ID,
  PRO_FLOURISH_ID,
  STUDY_SCARF_ID,
  confirmedBalance,
  getAvailableAnimationVariant,
  getPetReviewPrompt,
  getPreviewPet,
  getPurchaseOffer,
  ownsPetItem,
  type ConfirmedPetGallery,
} from "./petGalleryPresentation";

const catalogPrices = {
  "pet.owl": 120,
  "pet.tortoise": 120,
  "pet.fox": 120,
  [STUDY_SCARF_ID]: 40,
  [EARNED_CELEBRATION_ID]: 80,
} as const;

function confirmed(overrides: Partial<ConfirmedPetGallery> = {}): ConfirmedPetGallery {
  return {
    balance: 0,
    ownedPetIds: [],
    equippedPetId: null,
    ownedCosmeticIds: [],
    scarfEquipped: false,
    starterClaimAvailable: true,
    catalogPrices,
    ...overrides,
  };
}

test("one free starter stays available at zero coins, paid catalog stays blocked", () => {
  const snapshot = confirmed();
  for (const petId of ["pet.owl", "pet.tortoise", "pet.fox"] as const) {
    assert.deepEqual(getPurchaseOffer(snapshot, petId), { status: "free-starter" });
  }
  assert.deepEqual(getPurchaseOffer(snapshot, STUDY_SCARF_ID), {
    status: "insufficient",
    price: 40,
    shortfall: 40,
  });
  assert.deepEqual(getPurchaseOffer(snapshot, EARNED_CELEBRATION_ID), {
    status: "insufficient",
    price: 80,
    shortfall: 80,
  });
  assert.deepEqual(getPreviewPet(snapshot), { petId: "pet.owl", status: "preview-only" });
});

test("claimed starter removes the free choice; 40 and 80 do not buy a 120-coin pet", () => {
  const starter = confirmed({
    ownedPetIds: ["pet.tortoise"],
    equippedPetId: "pet.tortoise",
    starterClaimAvailable: false,
  });
  assert.deepEqual(getPurchaseOffer(starter, "pet.tortoise"), { status: "owned" });
  assert.deepEqual(getPurchaseOffer(starter, "pet.owl"), {
    status: "insufficient",
    price: 120,
    shortfall: 120,
  });
  const forty = { ...starter, balance: 40 };
  assert.deepEqual(getPurchaseOffer(forty, STUDY_SCARF_ID), {
    status: "available",
    price: 40,
  });
  assert.deepEqual(getPurchaseOffer(forty, "pet.fox"), {
    status: "insufficient",
    price: 120,
    shortfall: 80,
  });
  const eighty = { ...starter, balance: 80 };
  assert.deepEqual(getPurchaseOffer(eighty, EARNED_CELEBRATION_ID), {
    status: "available",
    price: 80,
  });
  assert.equal(getPurchaseOffer(eighty, "pet.fox").status, "insufficient");
});

test("invalid confirmed arithmetic fails closed without a fake affordable offer", () => {
  const snapshot = confirmed({
    balance: Number.NaN,
    starterClaimAvailable: false,
  });
  assert.equal(confirmedBalance(snapshot), null);
  assert.deepEqual(getPurchaseOffer(snapshot, "pet.fox"), { status: "unavailable" });
  assert.deepEqual(
    getPurchaseOffer(confirmed({
      starterClaimAvailable: false,
      catalogPrices: { ...catalogPrices, "pet.fox": -1 },
    }), "pet.fox"),
    { status: "unavailable" },
  );
  assert.deepEqual(
    getPurchaseOffer(confirmed({
      starterClaimAvailable: false,
      catalogPrices: { "pet.owl": 120 },
    }), "pet.fox"),
    { status: "unavailable" },
  );
});

test("unknown or lapsed Pro pauses only the presentation variant, never earned ownership", () => {
  const owned = confirmed({
    ownedPetIds: ["pet.fox"],
    equippedPetId: "pet.fox",
    ownedCosmeticIds: [STUDY_SCARF_ID, EARNED_CELEBRATION_ID],
    scarfEquipped: true,
    starterClaimAvailable: false,
  });
  assert.equal(getAvailableAnimationVariant(owned, PRO_FLOURISH_ID, "active"), PRO_FLOURISH_ID);
  assert.equal(getAvailableAnimationVariant(owned, PRO_FLOURISH_ID, "unknown"), EARNED_CELEBRATION_ID);
  assert.equal(getAvailableAnimationVariant(owned, PRO_FLOURISH_ID, "inactive"), EARNED_CELEBRATION_ID);
  assert.equal(ownsPetItem(owned, "pet.fox"), true);
  assert.equal(ownsPetItem(owned, STUDY_SCARF_ID), true);
  assert.equal(ownsPetItem(owned, EARNED_CELEBRATION_ID), true);
  assert.deepEqual(getPurchaseOffer(owned, STUDY_SCARF_ID), { status: "owned" });
  assert.equal(
    getAvailableAnimationVariant(
      { ...owned, ownedCosmeticIds: [STUDY_SCARF_ID] },
      PRO_FLOURISH_ID,
      "unknown",
    ),
    "basic",
  );
});

test("unowned equipped IDs never masquerade as the learner's companion", () => {
  const snapshot = confirmed({
    ownedPetIds: ["pet.tortoise"],
    equippedPetId: "pet.fox",
    starterClaimAvailable: false,
  });
  assert.deepEqual(getPreviewPet(snapshot), { petId: "pet.tortoise", status: "owned" });
});

test("confirmation names the exact free choice or affordable quoted purchase", () => {
  assert.equal(Object.keys(catalogPrices).length, 5);
  assert.equal(PRO_FLOURISH_ID in catalogPrices, false);
  assert.equal(
    getPetReviewPrompt(confirmed(), { kind: "starter", petId: "pet.fox" }),
    "Choose Fox as your one free starter? Other pets can be earned later.",
  );
  const buyer = confirmed({
    balance: 120,
    ownedPetIds: ["pet.owl"],
    equippedPetId: "pet.owl",
    starterClaimAvailable: false,
  });
  assert.equal(
    getPetReviewPrompt(buyer, {
      kind: "purchase",
      itemId: "pet.fox",
      quotedPrice: 120,
    }),
    "Buy Fox for 120 coins? Your confirmed balance is 120 coins. Your balance and ownership update only after server confirmation.",
  );
  assert.equal(getPetReviewPrompt(buyer, { kind: "starter", petId: "pet.fox" }), null);
});

test("review closes when quote, ownership, or affordability changes", () => {
  const buyer = confirmed({
    balance: 120,
    ownedPetIds: ["pet.owl"],
    starterClaimAvailable: false,
  });
  const choice = { kind: "purchase", itemId: "pet.fox", quotedPrice: 120 } as const;
  assert.equal(getPetReviewPrompt({ ...buyer, balance: 119 }, choice), null);
  assert.equal(
    getPetReviewPrompt({
      ...buyer,
      catalogPrices: { ...catalogPrices, "pet.fox": 100 },
    }, choice),
    null,
  );
  assert.equal(getPetReviewPrompt({ ...buyer, ownedPetIds: ["pet.owl", "pet.fox"] }, choice), null);
  assert.equal(getPetReviewPrompt(buyer, null), null);
});
