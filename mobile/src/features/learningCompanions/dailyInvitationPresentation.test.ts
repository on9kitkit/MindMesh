import assert from "node:assert/strict";
import test from "node:test";

import { dailyOfferIsOpen } from "./dailyInvitationPresentation";

const offer = {
  study_date: "2026-09-27",
  should_open: true,
  reason: "first_entry" as const,
};

test("daily offer opens automatically only after a safe room-free offer", () => {
  assert.equal(dailyOfferIsOpen(offer, true, null), true);
  assert.equal(dailyOfferIsOpen(offer, false, null), false);
  assert.equal(dailyOfferIsOpen(null, true, null), false);
  assert.equal(dailyOfferIsOpen({ ...offer, should_open: false }, true, null), false);
});

test("leaving the offered day closed does not hide tomorrow's offer", () => {
  assert.equal(dailyOfferIsOpen(offer, true, offer.study_date), false);
  assert.equal(dailyOfferIsOpen({ ...offer, study_date: "2026-09-28" }, true, offer.study_date), true);
});
