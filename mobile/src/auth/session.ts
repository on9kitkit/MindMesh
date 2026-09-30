import { getSupabaseClient } from "./supabase";

export class AuthSessionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthSessionError";
  }
}

export async function getCurrentAccessToken(): Promise<string | null> {
  const { data, error } = await getSupabaseClient().auth.getSession();
  if (error) {
    throw new AuthSessionError("The authentication session is unavailable.");
  }
  return data.session?.access_token ?? null;
}

export async function refreshCurrentSession(): Promise<boolean> {
  const { data, error } = await getSupabaseClient().auth.refreshSession();
  if (error) {
    throw new AuthSessionError("The authentication session could not refresh.");
  }
  return data.session !== null;
}

export async function clearSessionAfterUnauthorized(): Promise<void> {
  try {
    await getSupabaseClient().auth.signOut({ scope: "local" });
  } catch {
    // The realtime authentication failure has already been reported. The
    // next auth-state restoration attempt will surface any remaining issue.
  }
}
