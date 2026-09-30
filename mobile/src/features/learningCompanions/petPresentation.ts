import type { ThemeTokens } from "../../theme";

export const PET_IDS = ["pet.owl", "pet.tortoise", "pet.fox"] as const;

export type PetId = (typeof PET_IDS)[number];
export type PetOccasion = "home" | "result";

/** The caller supplies an already-authorized tier. This module owns no wallet or Pro decision. */
export type PetAnimationVariant =
  | "basic"
  | "animation.earned_celebration"
  | "animation.pro_flourish";

export type EffectivePetMotion = PetAnimationVariant | "still";

export type PetCopy = {
  name: string;
  personality: string;
  idleLine: string;
  tapLine: string;
  finishLine: string;
  basicAction: string;
  earnedAction: string;
  proAction: string;
};

const PET_COPY: Readonly<Record<PetId, PetCopy>> = {
  "pet.owl": {
    name: "Owl",
    personality: "Curious",
    idleLine: "Owl is ready to explore.",
    tapLine: "Let's look closer.",
    finishLine: "Every question taught us something.",
    basicAction: "Owl tilts its head.",
    earnedAction: "Owl lifts its wings in celebration.",
    proAction: "Owl gives a gentle wing flourish.",
  },
  "pet.tortoise": {
    name: "Tortoise",
    personality: "Calm",
    idleLine: "Tortoise is here to take it steady.",
    tapLine: "One step at a time.",
    finishLine: "You kept going.",
    basicAction: "Tortoise gives a small nod.",
    earnedAction: "Tortoise takes a cheerful little step.",
    proAction: "Tortoise gives a slow, happy shell sway.",
  },
  "pet.fox": {
    name: "Fox",
    personality: "Playful",
    idleLine: "Fox is ready to study with you.",
    tapLine: "Ready for a challenge?",
    finishLine: "That was a lively finish!",
    basicAction: "Fox flicks its tail.",
    earnedAction: "Fox makes a small celebratory hop.",
    proAction: "Fox gives a playful two-step flourish.",
  },
};

export function getPetCopy(petId: PetId): PetCopy {
  return PET_COPY[petId];
}

export function effectivePetMotion(
  variant: PetAnimationVariant,
  animationsEnabled: boolean,
  reduceMotion: boolean,
): EffectivePetMotion {
  return animationsEnabled && !reduceMotion ? variant : "still";
}

export function getPetReaction(
  petId: PetId,
  occasion: PetOccasion,
  interacted: boolean,
  variant: PetAnimationVariant,
): { message: string; action: string } {
  const copy = getPetCopy(petId);
  const message = interacted
    ? copy.tapLine
    : occasion === "result"
      ? copy.finishLine
      : copy.idleLine;
  const action =
    variant === "animation.pro_flourish"
      ? copy.proAction
      : variant === "animation.earned_celebration"
        ? copy.earnedAction
        : copy.basicAction;
  return { message, action };
}

export type PetPaint = {
  body: string;
  detail: string;
  face: string;
  eye: string;
  outline: string;
  frame: string;
  frameBorder: string;
};

const PET_PAINT: Readonly<
  Record<PetId, Record<ThemeTokens["scheme"], Pick<PetPaint, "body" | "detail" | "face">>>
> = {
  "pet.owl": {
    light: { body: "#71568E", detail: "#584271", face: "#FFF1D9" },
    dark: { body: "#BBA1DD", detail: "#8E73B7", face: "#FFF1D9" },
  },
  "pet.tortoise": {
    light: { body: "#317958", detail: "#245A41", face: "#E8F3D9" },
    dark: { body: "#83C79D", detail: "#55A778", face: "#E8F3D9" },
  },
  "pet.fox": {
    light: { body: "#B95C2D", detail: "#8F4325", face: "#FFF0D9" },
    dark: { body: "#F0AB72", detail: "#CE7848", face: "#FFF0D9" },
  },
};

export function getPetPaint(petId: PetId, theme: ThemeTokens): PetPaint {
  return {
    ...PET_PAINT[petId][theme.scheme],
    eye: "#17202A",
    outline: theme.colors.text,
    frame: theme.colors.surfaceElevated,
    frameBorder: theme.colors.border,
  };
}
