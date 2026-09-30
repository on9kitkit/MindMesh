export type SupportContact =
  | { status: "configured"; email: string }
  | { status: "unavailable" };

const SUPPORT_EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function resolveSupportContact(
  value: string | undefined = process.env.EXPO_PUBLIC_SUPPORT_EMAIL,
): SupportContact {
  const email = value?.trim() ?? "";
  if (!email || !SUPPORT_EMAIL_PATTERN.test(email)) {
    return { status: "unavailable" };
  }
  return { status: "configured", email };
}

export function supportMailto(contact: SupportContact): string | null {
  return contact.status === "configured" ? `mailto:${contact.email}` : null;
}
