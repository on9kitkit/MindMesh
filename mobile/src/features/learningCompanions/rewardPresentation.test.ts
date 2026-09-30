import assert from "node:assert/strict";
import test from "node:test";

import { rewardStatusCopy, type RewardDisplayStatus } from "./rewardPresentation";

test("every source status has truthful non-optimistic copy", () => {
  const statuses: RewardDisplayStatus[] = [
    "not_eligible", "awaiting_marking", "reward_pending", "credited", "reward_delayed",
  ];
  for (const status of statuses) {
    assert.ok(rewardStatusCopy(status).length > 20);
  }
  assert.match(rewardStatusCopy("reward_pending"), /pending server confirmation/);
  assert.match(rewardStatusCopy("credited"), /daily cap.*zero coins/);
  assert.match(rewardStatusCopy("reward_delayed"), /not a wallet repair/);
});
