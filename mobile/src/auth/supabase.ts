import { AppState, Platform } from "react-native";
import * as SecureStore from "expo-secure-store";
import "react-native-url-polyfill/auto";
import {
  createClient,
  processLock,
  type SupabaseClient,
} from "@supabase/supabase-js";

export class AuthConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthConfigurationError";
  }
}

const nativeStorage = {
  getItem: (key: string) => SecureStore.getItemAsync(key),
  removeItem: (key: string) => SecureStore.deleteItemAsync(key),
  setItem: (key: string, value: string) => SecureStore.setItemAsync(key, value),
};

let client: SupabaseClient | undefined;
let autoRefreshListenerRegistered = false;

function readRequiredEnvironmentVariable(name: string, rawValue: string | undefined): string {
  const value = rawValue?.trim();
  if (!value) {
    throw new AuthConfigurationError(`${name} is required for authentication.`);
  }
  return value;
}

function getSessionStorage() {
  if (Platform.OS === "web") {
    return globalThis.localStorage;
  }
  return nativeStorage;
}

function registerNativeAutoRefresh() {
  if (Platform.OS === "web" || autoRefreshListenerRegistered) {
    return;
  }

  autoRefreshListenerRegistered = true;
  AppState.addEventListener("change", (state) => {
    if (state === "active") {
      void getSupabaseClient().auth.startAutoRefresh();
    } else {
      void getSupabaseClient().auth.stopAutoRefresh();
    }
  });
}

export function getSupabaseClient(): SupabaseClient {
  if (client) {
    return client;
  }

  const supabaseUrl = readRequiredEnvironmentVariable(
    "EXPO_PUBLIC_SUPABASE_URL",
    process.env.EXPO_PUBLIC_SUPABASE_URL,
  );
  const supabasePublishableKey = readRequiredEnvironmentVariable(
    "EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
    process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
  );

  client = createClient(supabaseUrl, supabasePublishableKey, {
    auth: {
      storage: getSessionStorage(),
      autoRefreshToken: true,
      flowType: "pkce",
      persistSession: true,
      detectSessionInUrl: false,
      lock: processLock,
    },
  });
  registerNativeAutoRefresh();
  return client;
}
