import {
  ApiConfigurationError,
  AuthenticationApiError,
  BackendApiError,
  MalformedResponseError,
  NetworkApiError,
  parseBackendErrorPayload,
  StudyRoomApiError,
  TimeoutApiError,
} from "./errors";

export const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
export const DEFAULT_REQUEST_TIMEOUT_MS = 8_000;

export type JsonRequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  timeoutMs?: number;
};

export type AccessTokenProvider = () => Promise<string | null>;

export type ApiClientDependencies = {
  getAccessToken?: AccessTokenProvider;
  requireAuthentication?: boolean;
};

export type StudyRoomApiClient = {
  readonly baseUrl: string;
  requestJson(path: string, options?: JsonRequestOptions): Promise<unknown>;
};

const defaultAccessTokenProvider: AccessTokenProvider = async () => {
  const session = await import("../auth/session");
  return session.getCurrentAccessToken();
};

export function normalizeApiBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) {
    throw new ApiConfigurationError("The API base URL must not be empty.");
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new ApiConfigurationError("The API base URL is invalid.");
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new ApiConfigurationError("The API base URL must use HTTP or HTTPS.");
  }

  if (!parsed.hostname) {
    throw new ApiConfigurationError("The API base URL must include a host.");
  }

  return trimmed;
}

export function resolveApiBaseUrl(value?: string): string {
  return normalizeApiBaseUrl(value ?? DEFAULT_API_BASE_URL);
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function getPathUrl(baseUrl: string, path: string): string {
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

function parseJsonText(text: string, responseOk: boolean, status: number): unknown {
  if (!text.trim()) {
    return undefined;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    if (responseOk) {
      throw new MalformedResponseError();
    }

    throw new BackendApiError(
      "request_failed",
      "The StudyRoom server returned an unexpected error.",
      status,
    );
  }
}

function throwBackendError(status: number, payload: unknown): never {
  const backendError = parseBackendErrorPayload(payload);
  if (backendError) {
    throw new BackendApiError(
      backendError.code,
      backendError.message,
      status,
    );
  }

  throw new BackendApiError(
    "request_failed",
    "The StudyRoom server could not complete that request.",
    status,
  );
}

export function createApiClient(
  baseUrl = resolveApiBaseUrl(process.env.EXPO_PUBLIC_API_BASE_URL),
  dependencies: ApiClientDependencies = {},
): StudyRoomApiClient {
  const normalizedBaseUrl = normalizeApiBaseUrl(baseUrl);
  const accessTokenProvider =
    dependencies.getAccessToken ?? defaultAccessTokenProvider;
  const requireAuthentication = dependencies.requireAuthentication ?? true;

  return {
    baseUrl: normalizedBaseUrl,
    async requestJson(path, options = {}) {
      let accessToken: string | null = null;
      if (requireAuthentication) {
        accessToken = await accessTokenProvider();
        if (!accessToken) {
          throw new AuthenticationApiError();
        }
      }

      const controller = new AbortController();
      const timeoutMs = options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      try {
        const headers = new Headers({
          Accept: "application/json",
          "Content-Type": "application/json",
        });
        if (accessToken) {
          headers.set("Authorization", `Bearer ${accessToken}`);
        }

        const response = await fetch(getPathUrl(normalizedBaseUrl, path), {
          method: options.method ?? "GET",
          headers,
          body:
            options.body === undefined
              ? undefined
              : JSON.stringify(options.body),
          signal: controller.signal,
        });
        const payload = parseJsonText(
          await response.text(),
          response.ok,
          response.status,
        );

        if (!response.ok) {
          // A 401 rejects this request; it cannot safely sign out a mutable
          // Supabase session that may have changed while the SDK awaits.
          throwBackendError(response.status, payload);
        }

        return payload;
      } catch (error: unknown) {
        if (error instanceof StudyRoomApiError) {
          throw error;
        }
        if (isAbortError(error)) {
          throw new TimeoutApiError();
        }
        throw new NetworkApiError();
      } finally {
        clearTimeout(timeoutId);
      }
    },
  };
}

export const apiClient = createApiClient();
