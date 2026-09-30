import assert from "node:assert/strict";
import test from "node:test";

import type { StudyRoomApiClient, JsonRequestOptions } from "./client";
import { MalformedResponseError } from "./errors";
import {
  acknowledgeDailyInvitation,
  chooseStarterPet,
  claimDailyInvitation,
  createPetPurchaseRequestId,
  dismissDailyInvitation,
  equipPetItems,
  getPetAccountState,
  getRewardOverview,
  getRewardSourceStatus,
  parsePetAccountState,
  parseRewardOverview,
  parseRewardSourceStatusResponse,
  petGallerySnapshot,
  purchasePetItem,
  selectHomeZone,
} from "./learningCompanions";

const REQUEST_ID = "11111111-1111-4111-8111-111111111111";
const PURCHASE_ID = "22222222-2222-4222-8222-222222222222";

function reward(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    home_timezone: "Europe/London",
    study_date: "2026-09-27",
    balance: 90,
    day_coins: 90,
    qualifying_count: 3,
    active_streak_days: 2,
    best_streak_days: 5,
    last_qualified_day: "2026-09-27",
    qualified_today: true,
    pending_receipt_count: 1,
    delayed_receipt_count: 0,
    ...overrides,
  };
}

function petState(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    catalog: [
      { id: "pet.owl", kind: "pet", coin_price: 120 },
      { id: "pet.tortoise", kind: "pet", coin_price: 120 },
      { id: "pet.fox", kind: "pet", coin_price: 120 },
      { id: "cosmetic.study_scarf", kind: "cosmetic", coin_price: 40 },
      { id: "animation.earned_celebration", kind: "animation", coin_price: 80 },
    ],
    owned_item_ids: ["pet.owl", "cosmetic.study_scarf"],
    starter_pet_id: "pet.owl",
    equipment: {
      pet_id: "pet.owl",
      cosmetic_id: "cosmetic.study_scarf",
      animation_id: null,
    },
    balance: 90,
    ...overrides,
  };
}

function clientWithReplies(replies: Readonly<Record<string, unknown>>) {
  const calls: Array<{ path: string; options: JsonRequestOptions | undefined }> = [];
  const client: StudyRoomApiClient = {
    baseUrl: "https://example.invalid",
    requestJson: async (path, options) => {
      calls.push({ path, options });
      assert.ok(Object.prototype.hasOwnProperty.call(replies, path), `Unexpected ${path}`);
      return replies[path];
    },
  };
  return { client, calls };
}

test("reward overview parses confirmed balance, day cap, pending and delayed receipts", () => {
  assert.deepEqual(parseRewardOverview(reward()), reward());
  assert.equal(parseRewardOverview(reward({ day_coins: 100 })).day_coins, 100);
  assert.equal(parseRewardOverview(reward({
    home_timezone: null, study_date: null, day_coins: 0, qualifying_count: 0,
    active_streak_days: 0, best_streak_days: 0, last_qualified_day: null,
    qualified_today: false,
  })).home_timezone, null);
  for (const invalid of [
    reward({ day_coins: 101 }),
    reward({ balance: -1 }),
    reward({ pending_receipt_count: 0.5 }),
    reward({ study_date: "2026-02-30" }),
    reward({ active_streak_days: 6 }),
    reward({ surprise: "extra" }),
  ]) {
    assert.throws(() => parseRewardOverview(invalid), MalformedResponseError);
  }
});

test("pet parser accepts only finite owned catalog and confirmed equipment", () => {
  const parsed = parsePetAccountState(petState());
  assert.equal(parsed.balance, 90);
  assert.deepEqual(parsed.owned_item_ids, ["pet.owl", "cosmetic.study_scarf"]);
  assert.deepEqual(parsed.equipment, {
    pet_id: "pet.owl", cosmetic_id: "cosmetic.study_scarf", animation_id: null,
  });
  assert.deepEqual(petGallerySnapshot(parsed), {
    balance: 90,
    ownedPetIds: ["pet.owl"],
    equippedPetId: "pet.owl",
    ownedCosmeticIds: ["cosmetic.study_scarf"],
    scarfEquipped: true,
    starterClaimAvailable: false,
    catalogPrices: {
      "pet.owl": 120,
      "pet.tortoise": 120,
      "pet.fox": 120,
      "cosmetic.study_scarf": 40,
      "animation.earned_celebration": 80,
    },
  });
  const unclaimed = petGallerySnapshot(parsePetAccountState(petState({
    owned_item_ids: [], starter_pet_id: null, equipment: null, balance: 0,
  })));
  assert.equal(unclaimed.starterClaimAvailable, true);
  assert.equal(unclaimed.equippedPetId, null);
});

test("malformed, unknown and unowned pet state fails closed", () => {
  const validCatalog = petState().catalog as Array<Record<string, unknown>>;
  for (const invalid of [
    petState({ catalog: validCatalog.slice(1) }),
    petState({ catalog: [...validCatalog.slice(0, 4), { id: "animation.pro_flourish", kind: "animation", coin_price: 80 }] }),
    petState({ catalog: [...validCatalog.slice(0, 4), { ...validCatalog[4], coin_price: -1 }] }),
    petState({ owned_item_ids: ["pet.owl", "pet.owl"] }),
    petState({ owned_item_ids: ["pet.owl", "animation.pro_flourish"] }),
    petState({ equipment: { pet_id: "pet.fox", cosmetic_id: "cosmetic.study_scarf", animation_id: null } }),
    petState({ equipment: { pet_id: "pet.owl", cosmetic_id: null, animation_id: "animation.earned_celebration" } }),
    petState({ starter_pet_id: "pet.fox" }),
    petState({ balance: Number.MAX_SAFE_INTEGER + 1 }),
  ]) {
    assert.throws(() => parsePetAccountState(invalid), MalformedResponseError);
  }
});

test("read APIs and daily settings call exact authenticated /me paths", async () => {
  const { client, calls } = clientWithReplies({
    "/me/rewards": reward(),
    "/me/pets": petState(),
    "/me/learning-settings/home-zone": {
      home_timezone: "Europe/London", home_zone_version: 1,
      selected_at: "2026-09-27T12:00:00+00:00",
    },
    "/me/daily-invitation": {
      study_date: "2026-09-27", should_open: true, reason: "first_entry",
    },
    "/me/daily-invitation/dismiss": {
      study_date: "2026-09-27", should_open: false, reason: "dismissed",
    },
    "/me/daily-invitation/acknowledge": {
      study_date: "2026-09-27", should_open: false, reason: "already_invited",
    },
  });
  assert.equal((await getRewardOverview(client)).balance, 90);
  assert.equal((await getPetAccountState(client)).starter_pet_id, "pet.owl");
  assert.equal((await selectHomeZone("Europe/London", client)).home_zone_version, 1);
  assert.equal((await claimDailyInvitation(client)).should_open, true);
  assert.equal((await acknowledgeDailyInvitation("2026-09-27", client)).reason, "already_invited");
  assert.equal((await dismissDailyInvitation("2026-09-27", client)).reason, "dismissed");
  assert.deepEqual(calls, [
    { path: "/me/rewards", options: undefined },
    { path: "/me/pets", options: undefined },
    { path: "/me/learning-settings/home-zone", options: {
      method: "POST", body: { home_timezone: "Europe/London" },
    } },
    { path: "/me/daily-invitation", options: { method: "POST" } },
    { path: "/me/daily-invitation/acknowledge", options: {
      method: "POST", body: { study_date: "2026-09-27" },
    } },
    { path: "/me/daily-invitation/dismiss", options: {
      method: "POST", body: { study_date: "2026-09-27" },
    } },
  ]);
});

test("daily and home-zone parsers reject invented grants or invalid responses", async () => {
  const { client } = clientWithReplies({
    "/me/learning-settings/home-zone": {
      home_timezone: "Europe/London", home_zone_version: 0,
      selected_at: "2026-09-27T12:00:00Z",
    },
    "/me/daily-invitation": {
      study_date: "2026-09-27", should_open: true, reason: "unknown",
    },
  });
  await assert.rejects(selectHomeZone("Europe/London", client), MalformedResponseError);
  await assert.rejects(claimDailyInvitation(client), MalformedResponseError);
  const mismatch = clientWithReplies({
    "/me/daily-invitation": {
      study_date: "2026-09-27", should_open: true, reason: "already_invited",
    },
  });
  await assert.rejects(claimDailyInvitation(mismatch.client), MalformedResponseError);
});

test("owner reward source status carries only finite status and matching source identity", async () => {
  const roomId = "33333333-3333-4333-8333-333333333333";
  const soloId = "44444444-4444-4444-8444-444444444444";
  const { client, calls } = clientWithReplies({
    [`/me/rewards/sources/room/${roomId}`]: {
      source_kind: "room", source_id: roomId, status: "reward_pending",
    },
    [`/me/rewards/sources/solo/${soloId}`]: {
      source_kind: "solo", source_id: soloId, status: "awaiting_marking",
    },
  });
  assert.deepEqual(await getRewardSourceStatus("room", roomId, client), {
    source_kind: "room", source_id: roomId, status: "reward_pending",
  });
  assert.equal((await getRewardSourceStatus("solo", soloId, client)).status, "awaiting_marking");
  assert.deepEqual(calls.map((call) => call.path), [
    `/me/rewards/sources/room/${roomId}`,
    `/me/rewards/sources/solo/${soloId}`,
  ]);
  for (const invalid of [
    { source_kind: "solo", source_id: roomId, status: "credited" },
    { source_kind: "room", source_id: soloId, status: "credited" },
    { source_kind: "room", source_id: roomId, status: "coins:20" },
    { source_kind: "room", source_id: roomId, status: "credited", amount: 20 },
  ]) {
    assert.throws(
      () => parseRewardSourceStatusResponse(invalid, "room", roomId),
      MalformedResponseError,
    );
  }
  await assert.rejects(getRewardSourceStatus("room", "bad-id", client), MalformedResponseError);
});

test("starter, idempotent purchase and equipment write only exact request bodies", async () => {
  const { client, calls } = clientWithReplies({
    "/me/pets/starter": { item_id: "pet.fox", created: true },
    "/me/pets/purchases": {
      purchase_id: PURCHASE_ID, request_id: REQUEST_ID,
      item_id: "cosmetic.study_scarf", price_charged: 40,
      balance_after: 50, replayed: false,
    },
    "/me/pets/equipment": {
      pet_id: "pet.fox", cosmetic_id: "cosmetic.study_scarf", animation_id: null,
    },
  });
  assert.equal((await chooseStarterPet("pet.fox", client)).item_id, "pet.fox");
  const purchased = await purchasePetItem("cosmetic.study_scarf", REQUEST_ID, client);
  assert.equal(purchased.balance_after, 50);
  assert.equal(purchased.price_charged, 40);
  const input = {
    pet_id: "pet.fox" as const,
    cosmetic_id: "cosmetic.study_scarf" as const,
    animation_id: null,
  };
  assert.deepEqual(await equipPetItems(input, client), input);
  assert.deepEqual(calls, [
    { path: "/me/pets/starter", options: {
      method: "POST", body: { item_id: "pet.fox" },
    } },
    { path: "/me/pets/purchases", options: {
      method: "POST", body: {
        request_id: REQUEST_ID, item_id: "cosmetic.study_scarf",
      },
    } },
    { path: "/me/pets/equipment", options: { method: "PUT", body: input } },
  ]);
  assert.match(createPetPurchaseRequestId(() => 0.42), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

test("mutation response mismatch or invalid request ID cannot become ownership", async () => {
  const { client } = clientWithReplies({
    "/me/pets/starter": { item_id: "pet.owl", created: true },
    "/me/pets/purchases": {
      purchase_id: PURCHASE_ID, request_id: REQUEST_ID,
      item_id: "pet.fox", price_charged: 120,
      balance_after: 0, replayed: false,
    },
    "/me/pets/equipment": {
      pet_id: "pet.owl", cosmetic_id: null, animation_id: null,
    },
  });
  await assert.rejects(chooseStarterPet("pet.fox", client), MalformedResponseError);
  await assert.rejects(purchasePetItem("pet.owl", REQUEST_ID, client), MalformedResponseError);
  await assert.rejects(purchasePetItem("pet.owl", "not-a-uuid", client), MalformedResponseError);
  await assert.rejects(equipPetItems({
    pet_id: "pet.fox", cosmetic_id: null, animation_id: null,
  }, client), MalformedResponseError);
});
