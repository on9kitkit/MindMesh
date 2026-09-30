import type { Session } from "@supabase/supabase-js";

export const NATIVE_AUTH_REDIRECT_URL = "studyroom-preview://auth/callback";

export type AuthCallbackClient = {
  auth: {
    exchangeCodeForSession(
      code: string,
    ): Promise<{
      data: { session: Session | null };
      error: { message: string } | null;
    }>;
  };
};

export type ParsedAuthCallback =
  | { status: "not-auth-callback" }
  | { status: "error"; message: string }
  | { status: "code"; code: string };

export type AuthCallbackResult =
  | {
      status: "ignored";
      reason: "not-auth-callback" | "duplicate" | "busy";
    }
  | { status: "failed"; message: string }
  | { status: "authenticated"; session: Session };

function callbackErrorMessage(error: string, errorCode: string | null): string {
  const normalizedError = `${error} ${errorCode ?? ""}`.toLowerCase();
  if (
    normalizedError.includes("expired") ||
    normalizedError.includes("already") ||
    normalizedError.includes("invalid") ||
    normalizedError.includes("otp_expired")
  ) {
    return "This confirmation link has expired or was already used. Request a new confirmation email and try again.";
  }
  if (
    normalizedError.includes("network") ||
    normalizedError.includes("fetch") ||
    normalizedError.includes("timeout")
  ) {
    return "StudyRoom could not reach Supabase to complete confirmation. Check your connection and try again.";
  }
  return "StudyRoom could not complete this confirmation link. Request a new confirmation email and try again.";
}

export function getAuthCallbackErrorMessage(error: unknown): string {
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "object" &&
          error !== null &&
          "message" in error &&
          typeof error.message === "string"
        ? error.message
        : "";
  return callbackErrorMessage(message, null);
}

export function parseAuthCallbackUrl(url: string): ParsedAuthCallback {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { status: "not-auth-callback" };
  }

  if (
    parsed.protocol !== "studyroom-preview:" ||
    !(
      (parsed.hostname === "auth" && parsed.pathname === "/callback") ||
      (parsed.hostname === "" && parsed.pathname === "/auth/callback")
    )
  ) {
    return { status: "not-auth-callback" };
  }

  const error = parsed.searchParams.get("error");
  const errorCode = parsed.searchParams.get("error_code");
  const errorDescription = parsed.searchParams.get("error_description");
  if (error || errorCode || errorDescription) {
    return {
      status: "error",
      message: callbackErrorMessage(error ?? errorDescription ?? "", errorCode),
    };
  }

  const code = parsed.searchParams.get("code");
  if (!code) {
    return {
      status: "error",
      message: "This confirmation link is incomplete. Request a new confirmation email and try again.",
    };
  }

  return { status: "code", code };
}

export function createSignUpOptions(displayName: string): {
  data: { display_name: string };
  emailRedirectTo: string;
} {
  return {
    data: { display_name: displayName },
    emailRedirectTo: NATIVE_AUTH_REDIRECT_URL,
  };
}

export class AuthCallbackHandler {
  private readonly handledCallbackKeys = new Set<string>();
  private processing = false;

  constructor(private readonly client: AuthCallbackClient) {}

  async process(url: string): Promise<AuthCallbackResult> {
    const parsed = parseAuthCallbackUrl(url);
    if (parsed.status === "not-auth-callback") {
      return { status: "ignored", reason: "not-auth-callback" };
    }
    const callbackKey =
      parsed.status === "code" ? `code:${parsed.code}` : `error:${parsed.message}`;
    if (this.handledCallbackKeys.has(callbackKey)) {
      return { status: "ignored", reason: "duplicate" };
    }
    if (this.processing) {
      return { status: "ignored", reason: "busy" };
    }

    this.processing = true;
    try {
      if (parsed.status === "error") {
        this.handledCallbackKeys.add(callbackKey);
        return { status: "failed", message: parsed.message };
      }

      const { data, error } = await this.client.auth.exchangeCodeForSession(
        parsed.code,
      );
      if (error) {
        return {
          status: "failed",
          message: getAuthCallbackErrorMessage(error),
        };
      }
      if (!data.session) {
        return {
          status: "failed",
          message: "StudyRoom did not receive a session from this confirmation link. Request a new confirmation email and try again.",
        };
      }
      this.handledCallbackKeys.add(callbackKey);
      return { status: "authenticated", session: data.session };
    } catch (error: unknown) {
      return {
        status: "failed",
        message: getAuthCallbackErrorMessage(error),
      };
    } finally {
      this.processing = false;
    }
  }
}
