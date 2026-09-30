import { apiClient, type StudyRoomApiClient } from "./client";
import { MalformedResponseError } from "./errors";
import {
  EARNED_CELEBRATION_ID,
  STUDY_SCARF_ID,
  type ConfirmedPetGallery,
  type PurchasablePetItemId,
} from "../features/learningCompanions/petGalleryPresentation";
import { PET_IDS, type PetId } from "../features/learningCompanions/petPresentation";
import {
  createPreparationRequestId,
  isUuidV4,
} from "../features/quiz/adaptiveQuiz";

export type RewardOverview = {
  home_timezone: string | null;
  study_date: string | null;
  balance: number;
  day_coins: number;
  qualifying_count: number;
  active_streak_days: number;
  best_streak_days: number;
  last_qualified_day: string | null;
  qualified_today: boolean;
  pending_receipt_count: number;
  delayed_receipt_count: number;
};
export type RewardSourceKind = "room" | "solo";
export type RewardSourceDisplayStatus =
  | "not_eligible"
  | "awaiting_marking"
  | "reward_pending"
  | "credited"
  | "reward_delayed";
export type RewardSourceStatusResponse = {
  source_kind: RewardSourceKind;
  source_id: string;
  status: RewardSourceDisplayStatus;
};

export type HomeZoneSelection = {
  home_timezone: string;
  home_zone_version: number;
  selected_at: string;
};
export type DailyInvitationReason =
  | "first_entry"
  | "already_invited"
  | "already_qualified"
  | "dismissed";
export type DailyInvitation = {
  study_date: string;
  should_open: boolean;
  reason: DailyInvitationReason;
};

export type PetCatalogKind = "pet" | "cosmetic" | "animation";
export type PetCatalogEntry = {
  id: PurchasablePetItemId;
  kind: PetCatalogKind;
  coin_price: number;
};
export type PetEquipment = {
  pet_id: PetId;
  cosmetic_id: typeof STUDY_SCARF_ID | null;
  animation_id: typeof EARNED_CELEBRATION_ID | null;
};
export type PetEquipmentInput = PetEquipment;
export type PetAccountState = {
  catalog: ReadonlyArray<PetCatalogEntry>;
  owned_item_ids: ReadonlyArray<PurchasablePetItemId>;
  starter_pet_id: PetId | null;
  equipment: PetEquipment | null;
  balance: number;
};
export type StarterPetChoice = { item_id: PetId; created: boolean };
export type PetPurchaseResult = {
  purchase_id: string;
  request_id: string;
  item_id: PurchasablePetItemId;
  price_charged: number;
  balance_after: number;
  replayed: boolean;
};

const CATALOG_KIND: Readonly<Record<PurchasablePetItemId, PetCatalogKind>> = {
  "pet.owl": "pet",
  "pet.tortoise": "pet",
  "pet.fox": "pet",
  [STUDY_SCARF_ID]: "cosmetic",
  [EARNED_CELEBRATION_ID]: "animation",
};
const ITEM_IDS = Object.keys(CATALOG_KIND) as PurchasablePetItemId[];
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function malformed(): never {
  throw new MalformedResponseError(
    "The StudyRoom server returned an invalid learning companions response.",
  );
}

function exactObject(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return malformed();
  }
  const record = value as Record<string, unknown>;
  if (
    Object.keys(record).length !== keys.length ||
    keys.some((key) => !Object.prototype.hasOwnProperty.call(record, key)) ||
    Object.keys(record).some((key) => !keys.includes(key))
  ) {
    return malformed();
  }
  return record;
}

function nonnegativeCount(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    return malformed();
  }
  return value;
}

function dateOrNull(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return malformed();
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
    return malformed();
  }
  return value;
}

function parseHomeZoneSelection(value: unknown): HomeZoneSelection {
  const record = exactObject(value, ["home_timezone", "home_zone_version", "selected_at"]);
  if (
    typeof record.home_timezone !== "string" || !record.home_timezone.trim() ||
    typeof record.selected_at !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(record.selected_at) ||
    Number.isNaN(Date.parse(record.selected_at))
  ) {
    return malformed();
  }
  const version = nonnegativeCount(record.home_zone_version);
  if (version === 0) return malformed();
  return {
    home_timezone: record.home_timezone,
    home_zone_version: version,
    selected_at: record.selected_at,
  };
}

function parseDailyInvitation(value: unknown): DailyInvitation {
  const record = exactObject(value, ["study_date", "should_open", "reason"]);
  const reason = record.reason;
  if (
    typeof record.should_open !== "boolean" ||
    (reason !== "first_entry" && reason !== "already_invited" &&
      reason !== "already_qualified" && reason !== "dismissed") ||
    record.should_open !== (reason === "first_entry")
  ) {
    return malformed();
  }
  const studyDate = dateOrNull(record.study_date);
  if (studyDate === null) return malformed();
  return {
    study_date: studyDate,
    should_open: record.should_open,
    reason,
  };
}

function petId(value: unknown): PetId {
  if (typeof value !== "string" || !PET_IDS.some((id) => id === value)) {
    return malformed();
  }
  return value as PetId;
}

function itemId(value: unknown): PurchasablePetItemId {
  if (typeof value !== "string" || !Object.prototype.hasOwnProperty.call(CATALOG_KIND, value)) {
    return malformed();
  }
  return value as PurchasablePetItemId;
}

function equipment(value: unknown): PetEquipment | null {
  if (value === null) return null;
  const record = exactObject(value, ["pet_id", "cosmetic_id", "animation_id"]);
  if (record.cosmetic_id !== null && record.cosmetic_id !== STUDY_SCARF_ID) {
    return malformed();
  }
  if (record.animation_id !== null && record.animation_id !== EARNED_CELEBRATION_ID) {
    return malformed();
  }
  return {
    pet_id: petId(record.pet_id),
    cosmetic_id: record.cosmetic_id,
    animation_id: record.animation_id,
  } as PetEquipment;
}

export function parseRewardOverview(value: unknown): RewardOverview {
  const record = exactObject(value, [
    "home_timezone", "study_date", "balance", "day_coins", "qualifying_count",
    "active_streak_days", "best_streak_days", "last_qualified_day",
    "qualified_today", "pending_receipt_count", "delayed_receipt_count",
  ]);
  if (
    (record.home_timezone !== null &&
      (typeof record.home_timezone !== "string" || !record.home_timezone.trim())) ||
    typeof record.qualified_today !== "boolean"
  ) {
    return malformed();
  }
  const overview: RewardOverview = {
    home_timezone: record.home_timezone as string | null,
    study_date: dateOrNull(record.study_date),
    balance: nonnegativeCount(record.balance),
    day_coins: nonnegativeCount(record.day_coins),
    qualifying_count: nonnegativeCount(record.qualifying_count),
    active_streak_days: nonnegativeCount(record.active_streak_days),
    best_streak_days: nonnegativeCount(record.best_streak_days),
    last_qualified_day: dateOrNull(record.last_qualified_day),
    qualified_today: record.qualified_today,
    pending_receipt_count: nonnegativeCount(record.pending_receipt_count),
    delayed_receipt_count: nonnegativeCount(record.delayed_receipt_count),
  };
  if (
    overview.day_coins > 100 ||
    overview.active_streak_days > overview.best_streak_days ||
    (overview.home_timezone === null) !== (overview.study_date === null)
  ) {
    return malformed();
  }
  return overview;
}

export function parseRewardSourceStatusResponse(
  value: unknown,
  expectedKind: RewardSourceKind,
  expectedId: string,
): RewardSourceStatusResponse {
  const record = exactObject(value, ["source_kind", "source_id", "status"]);
  const status = record.status;
  if (
    record.source_kind !== expectedKind ||
    typeof record.source_id !== "string" ||
    !UUID_PATTERN.test(record.source_id) ||
    record.source_id.toLowerCase() !== expectedId.toLowerCase() ||
    (status !== "not_eligible" && status !== "awaiting_marking" &&
      status !== "reward_pending" && status !== "credited" &&
      status !== "reward_delayed")
  ) {
    return malformed();
  }
  return {
    source_kind: expectedKind,
    source_id: record.source_id.toLowerCase(),
    status,
  };
}

export function parsePetAccountState(value: unknown): PetAccountState {
  const record = exactObject(value, [
    "catalog", "owned_item_ids", "starter_pet_id", "equipment", "balance",
  ]);
  if (!Array.isArray(record.catalog) || !Array.isArray(record.owned_item_ids)) {
    return malformed();
  }
  const catalog: PetCatalogEntry[] = record.catalog.map((entry: unknown) => {
    const row = exactObject(entry, ["id", "kind", "coin_price"]);
    const id = itemId(row.id);
    if (row.kind !== CATALOG_KIND[id]) return malformed();
    const coinPrice = nonnegativeCount(row.coin_price);
    if (coinPrice === 0) return malformed();
    return { id, kind: CATALOG_KIND[id], coin_price: coinPrice };
  });
  if (
    catalog.length !== ITEM_IDS.length ||
    new Set(catalog.map((entry) => entry.id)).size !== ITEM_IDS.length
  ) {
    return malformed();
  }
  const ownedItemIds = record.owned_item_ids.map(itemId);
  if (new Set(ownedItemIds).size !== ownedItemIds.length) return malformed();
  const starterPetId = record.starter_pet_id === null
    ? null
    : petId(record.starter_pet_id);
  const selectedEquipment = equipment(record.equipment);
  if (
    (starterPetId !== null && !ownedItemIds.includes(starterPetId)) ||
    (selectedEquipment !== null && (
      !ownedItemIds.includes(selectedEquipment.pet_id) ||
      (selectedEquipment.cosmetic_id !== null &&
        !ownedItemIds.includes(selectedEquipment.cosmetic_id)) ||
      (selectedEquipment.animation_id !== null &&
        !ownedItemIds.includes(selectedEquipment.animation_id))
    ))
  ) {
    return malformed();
  }
  return {
    catalog,
    owned_item_ids: ownedItemIds,
    starter_pet_id: starterPetId,
    equipment: selectedEquipment,
    balance: nonnegativeCount(record.balance),
  };
}

/** Do not turn the purchase response into local ownership; refresh /me/pets. */
export function petGallerySnapshot(state: PetAccountState): ConfirmedPetGallery {
  const prices: Partial<Record<PurchasablePetItemId, number>> = {};
  for (const entry of state.catalog) prices[entry.id] = entry.coin_price;
  const ownedPetIds = PET_IDS.filter((id) => state.owned_item_ids.includes(id));
  return {
    balance: state.balance,
    ownedPetIds,
    equippedPetId: state.equipment?.pet_id ?? null,
    ownedCosmeticIds: [STUDY_SCARF_ID, EARNED_CELEBRATION_ID].filter((id) =>
      state.owned_item_ids.includes(id),
    ),
    scarfEquipped: state.equipment?.cosmetic_id === STUDY_SCARF_ID,
    starterClaimAvailable: state.starter_pet_id === null && ownedPetIds.length === 0,
    catalogPrices: prices,
  };
}

export async function getRewardOverview(
  client: StudyRoomApiClient = apiClient,
): Promise<RewardOverview> {
  return parseRewardOverview(await client.requestJson("/me/rewards"));
}

export async function getRewardSourceStatus(
  kind: RewardSourceKind,
  id: string,
  client: StudyRoomApiClient = apiClient,
): Promise<RewardSourceStatusResponse> {
  if (!UUID_PATTERN.test(id)) return malformed();
  const response = await client.requestJson(
    `/me/rewards/sources/${kind}/${encodeURIComponent(id)}`,
  );
  return parseRewardSourceStatusResponse(response, kind, id);
}

export async function selectHomeZone(
  timeZone: string,
  client: StudyRoomApiClient = apiClient,
): Promise<HomeZoneSelection> {
  const normalized = timeZone.trim();
  if (!normalized) return malformed();
  return parseHomeZoneSelection(await client.requestJson("/me/learning-settings/home-zone", {
    method: "POST", body: { home_timezone: normalized },
  }));
}

export async function claimDailyInvitation(
  client: StudyRoomApiClient = apiClient,
): Promise<DailyInvitation> {
  return parseDailyInvitation(await client.requestJson("/me/daily-invitation", {
    method: "POST",
  }));
}

export async function dismissDailyInvitation(
  studyDate: string,
  client: StudyRoomApiClient = apiClient,
): Promise<DailyInvitation> {
  return parseDailyInvitation(await client.requestJson("/me/daily-invitation/dismiss", {
    method: "POST", body: { study_date: studyDate },
  }));
}

export async function acknowledgeDailyInvitation(
  studyDate: string,
  client: StudyRoomApiClient = apiClient,
): Promise<DailyInvitation> {
  return parseDailyInvitation(await client.requestJson("/me/daily-invitation/acknowledge", {
    method: "POST", body: { study_date: studyDate },
  }));
}

export async function getPetAccountState(
  client: StudyRoomApiClient = apiClient,
): Promise<PetAccountState> {
  return parsePetAccountState(await client.requestJson("/me/pets"));
}

export async function chooseStarterPet(
  selectedPetId: PetId,
  client: StudyRoomApiClient = apiClient,
): Promise<StarterPetChoice> {
  const record = exactObject(await client.requestJson("/me/pets/starter", {
    method: "POST", body: { item_id: selectedPetId },
  }), ["item_id", "created"]);
  if (record.item_id !== selectedPetId || typeof record.created !== "boolean") {
    return malformed();
  }
  return { item_id: selectedPetId, created: record.created };
}

export const createPetPurchaseRequestId = createPreparationRequestId;

export async function purchasePetItem(
  selectedItemId: PurchasablePetItemId,
  requestId: string,
  client: StudyRoomApiClient = apiClient,
): Promise<PetPurchaseResult> {
  if (!isUuidV4(requestId)) return malformed();
  const record = exactObject(await client.requestJson("/me/pets/purchases", {
    method: "POST", body: { request_id: requestId, item_id: selectedItemId },
  }), ["purchase_id", "request_id", "item_id", "price_charged", "balance_after", "replayed"]);
  if (
    typeof record.purchase_id !== "string" || !isUuidV4(record.purchase_id) ||
    record.request_id !== requestId || record.item_id !== selectedItemId ||
    typeof record.replayed !== "boolean"
  ) {
    return malformed();
  }
  const charged = nonnegativeCount(record.price_charged);
  if (charged === 0) return malformed();
  return {
    purchase_id: record.purchase_id,
    request_id: requestId,
    item_id: selectedItemId,
    price_charged: charged,
    balance_after: nonnegativeCount(record.balance_after),
    replayed: record.replayed,
  };
}

export async function equipPetItems(
  input: PetEquipmentInput,
  client: StudyRoomApiClient = apiClient,
): Promise<PetEquipment> {
  const response = equipment(await client.requestJson("/me/pets/equipment", {
    method: "PUT", body: input,
  }));
  if (
    response === null ||
    response.pet_id !== input.pet_id ||
    response.cosmetic_id !== input.cosmetic_id ||
    response.animation_id !== input.animation_id
  ) {
    return malformed();
  }
  return response;
}
