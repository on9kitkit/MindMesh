export const DISPLAY_NAME_MIN_LENGTH = 1;
export const DISPLAY_NAME_MAX_LENGTH = 40;

const RESERVED_DISPLAY_NAMES = new Set([
  "studyroom",
  "studyroom support",
  "studyroom admin",
  "administrator",
  "moderator",
  "support",
]);
const PROHIBITED_DISPLAY_NAME_TERMS = new Set(["official", "staff"]);
const DANGEROUS_FORMAT_CHARACTERS =
  /[\u0000-\u001f\u007f-\u009f\u00ad\u061c\u200b-\u200f\u2028\u2029\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff]/u;

export type DisplayNameValidation =
  | { valid: true; value: string }
  | { valid: false; message: string };

export function validateDisplayName(raw: string): DisplayNameValidation {
  const normalized = raw.normalize("NFKC");
  if (DANGEROUS_FORMAT_CHARACTERS.test(normalized)) {
    return { valid: false, message: "Choose a different display name." };
  }
  const value = normalized.trim().split(/\s+/u).join(" ");
  if (!value) {
    return { valid: false, message: "Enter a display name." };
  }
  const length = Array.from(value).length;
  if (
    length < DISPLAY_NAME_MIN_LENGTH ||
    length > DISPLAY_NAME_MAX_LENGTH
  ) {
    return {
      valid: false,
      message: `Display names must contain ${DISPLAY_NAME_MIN_LENGTH}–${DISPLAY_NAME_MAX_LENGTH} characters.`,
    };
  }

  const folded = value.toLowerCase();
  if (RESERVED_DISPLAY_NAMES.has(folded)) {
    return { valid: false, message: "Choose a different display name." };
  }
  const tokens = value
    .split(/[^\p{L}\p{N}]+/u)
    .map((token) => token.toLowerCase())
    .filter(Boolean);
  if (tokens.some((token) => PROHIBITED_DISPLAY_NAME_TERMS.has(token))) {
    return { valid: false, message: "Choose a different display name." };
  }
  return { valid: true, value };
}
