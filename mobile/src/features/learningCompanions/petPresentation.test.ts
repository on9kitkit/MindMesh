import assert from "node:assert/strict";
import test from "node:test";

import { THEME_PALETTES } from "../../theme";
import {
  PET_IDS,
  effectivePetMotion,
  getPetCopy,
  getPetPaint,
  getPetReaction,
  type PetAnimationVariant,
  type PetId,
} from "./petPresentation";

function luminance(hex: string): number {
  const channels = hex.match(/[0-9a-f]{2}/gi);
  assert.ok(channels && channels.length === 3, `Expected a six-digit colour: ${hex}`);
  const [red, green, blue] = channels.map((channel) => {
    const value = Number.parseInt(channel, 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return red * 0.2126 + green * 0.7152 + blue * 0.0722;
}

function contrast(first: string, second: string): number {
  const higher = Math.max(luminance(first), luminance(second));
  const lower = Math.min(luminance(first), luminance(second));
  return (higher + 0.05) / (lower + 0.05);
}

test("pet registry stays at the approved three finite companions", () => {
  assert.deepEqual(PET_IDS, ["pet.owl", "pet.tortoise", "pet.fox"]);
  assert.deepEqual(
    PET_IDS.map((petId) => getPetCopy(petId).personality),
    ["Curious", "Calm", "Playful"],
  );
  for (const petId of PET_IDS) {
    const copy = getPetCopy(petId);
    for (const line of [copy.idleLine, copy.tapLine, copy.finishLine]) {
      assert.ok(line.trim().length > 0);
      assert.ok(!line.includes("{score}"));
    }
  }
});

test("tap and result reactions remain visible authored text at every motion tier", () => {
  const tiers: PetAnimationVariant[] = [
    "basic",
    "animation.earned_celebration",
    "animation.pro_flourish",
  ];
  for (const petId of PET_IDS) {
    const copy = getPetCopy(petId);
    for (const tier of tiers) {
      assert.equal(getPetReaction(petId, "home", false, tier).message, copy.idleLine);
      assert.equal(getPetReaction(petId, "result", false, tier).message, copy.finishLine);
      assert.equal(getPetReaction(petId, "home", true, tier).message, copy.tapLine);
      assert.ok(getPetReaction(petId, "result", true, tier).action.length > 0);
    }
  }
});

test("reduced motion and user animation choice always yield a still equivalent", () => {
  const tiers: PetAnimationVariant[] = [
    "basic",
    "animation.earned_celebration",
    "animation.pro_flourish",
  ];
  for (const tier of tiers) {
    assert.equal(effectivePetMotion(tier, false, false), "still");
    assert.equal(effectivePetMotion(tier, true, true), "still");
    assert.equal(effectivePetMotion(tier, true, false), tier);
  }
});

test("original pet silhouettes remain distinct on all eight native themes", () => {
  const seen: Record<PetId, Set<string>> = {
    "pet.owl": new Set(),
    "pet.tortoise": new Set(),
    "pet.fox": new Set(),
  };
  for (const themes of Object.values(THEME_PALETTES)) {
    for (const theme of Object.values(themes)) {
      for (const petId of PET_IDS) {
        const paint = getPetPaint(petId, theme);
        seen[petId].add(paint.body);
        assert.equal(paint.frame, theme.colors.surfaceElevated);
        assert.equal(paint.frameBorder, theme.colors.border);
        assert.equal(paint.outline, theme.colors.text);
        assert.ok(
          contrast(paint.body, paint.frame) >= 3,
          `${petId} body lacks 3:1 frame contrast in ${theme.scheme}: ${paint.body} / ${paint.frame}`,
        );
        assert.ok(contrast(paint.eye, paint.face) >= 3);
      }
    }
  }
  for (const colors of Object.values(seen)) assert.equal(colors.size, 2);
});
