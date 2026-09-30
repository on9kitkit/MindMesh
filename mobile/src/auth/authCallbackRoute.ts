import { NATIVE_AUTH_REDIRECT_URL } from "./authCallback";

export type AuthCallbackRouteParams = Readonly<
  Record<string, string | string[]>
>;

const callbackQueryKeys = [
  "code",
  "error",
  "error_code",
  "error_description",
] as const;

function firstRouteParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function authCallbackUrlFromRouteParams(
  params: AuthCallbackRouteParams,
): string {
  const callbackUrl = new URL(NATIVE_AUTH_REDIRECT_URL);
  for (const key of callbackQueryKeys) {
    const value = firstRouteParam(params[key]);
    if (value !== undefined) {
      callbackUrl.searchParams.set(key, value);
    }
  }
  return callbackUrl.toString();
}

export async function processAuthCallbackRoute(
  params: AuthCallbackRouteParams,
  processCallback: (url: string) => Promise<void>,
): Promise<void> {
  await processCallback(authCallbackUrlFromRouteParams(params));
}
