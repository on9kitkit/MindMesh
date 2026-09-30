import {
  DEFAULT_THEME_MODE,
  type ThemeMode,
} from "../theme";

export const APPEARANCE_STORAGE_KEY = "studyroom.appearance.mode.v1";

export type AppearanceStorage = {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
};

export const secureAppearanceStorage: AppearanceStorage = {
  getItem: async (key) => {
    const SecureStore = await import("expo-secure-store");
    return SecureStore.getItemAsync(key);
  },
  setItem: async (key, value) => {
    const SecureStore = await import("expo-secure-store");
    await SecureStore.setItemAsync(key, value);
  },
};

export type AppearancePreferenceSnapshot = {
  mode: ThemeMode;
  hydrated: boolean;
  error: string | undefined;
};

const LOAD_ERROR = "Could not load appearance on this device.";
const SAVE_ERROR = "Could not save appearance on this device.";

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === "light" || value === "dark" || value === "system";
}

export function parseStoredThemeMode(value: string | null): ThemeMode {
  return isThemeMode(value) ? value : DEFAULT_THEME_MODE;
}

/**
 * Device-local preference owner. It deliberately knows nothing about auth,
 * accounts, sessions, or server state.
 */
export class AppearancePreferenceController {
  private readonly listeners = new Set<() => void>();
  private readonly storage: AppearanceStorage;
  private mode: ThemeMode = DEFAULT_THEME_MODE;
  private hydrated = false;
  private error: string | undefined;
  private readStarted = false;
  private readPromise: Promise<void> | undefined;
  private writeChain: Promise<void> = Promise.resolve();
  private selectionVersion = 0;
  private userSelected = false;

  public constructor(storage: AppearanceStorage = secureAppearanceStorage) {
    this.storage = storage;
  }

  public getSnapshot(): AppearancePreferenceSnapshot {
    return { mode: this.mode, hydrated: this.hydrated, error: this.error };
  }

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  public hydrate(): Promise<void> {
    if (this.readStarted) {
      return this.readPromise ?? Promise.resolve();
    }
    this.readStarted = true;
    return this.startRead();
  }

  public select(mode: ThemeMode): void {
    if (!isThemeMode(mode)) {
      return;
    }
    this.userSelected = true;
    this.mode = mode;
    this.error = undefined;
    this.selectionVersion += 1;
    const version = this.selectionVersion;
    this.emit();
    this.enqueueWrite(mode, version);
  }

  public retry(): void {
    if (this.error === LOAD_ERROR && !this.userSelected) {
      if (this.readPromise === undefined) {
        void this.startRead();
      }
      return;
    }
    this.error = undefined;
    this.selectionVersion += 1;
    const version = this.selectionVersion;
    this.emit();
    this.enqueueWrite(this.mode, version);
  }

  private startRead(): Promise<void> {
    const read = this.loadStoredMode();
    this.readPromise = read;
    void read.then(
      () => {
        if (this.readPromise === read) {
          this.readPromise = undefined;
        }
      },
      () => {
        if (this.readPromise === read) {
          this.readPromise = undefined;
        }
      },
    );
    return read;
  }

  private async loadStoredMode(): Promise<void> {
    const selectionVersionAtReadStart = this.selectionVersion;
    try {
      const stored = await this.storage.getItem(APPEARANCE_STORAGE_KEY);
      const readStillOwnsPublication =
        !this.userSelected &&
        this.selectionVersion === selectionVersionAtReadStart;
      if (readStillOwnsPublication) {
        this.mode = parseStoredThemeMode(stored);
        this.error = undefined;
      }
    } catch {
      if (
        !this.userSelected &&
        this.selectionVersion === selectionVersionAtReadStart
      ) {
        this.error = LOAD_ERROR;
      }
    } finally {
      this.hydrated = true;
      this.emit();
    }
  }

  private enqueueWrite(mode: ThemeMode, version: number): void {
    this.writeChain = this.writeChain
      .then(async () => {
        try {
          await this.storage.setItem(APPEARANCE_STORAGE_KEY, mode);
          if (version === this.selectionVersion) {
            this.error = undefined;
            this.emit();
          }
        } catch {
          if (version === this.selectionVersion) {
            this.error = SAVE_ERROR;
            this.emit();
          }
        }
      })
      .catch(() => {
        // Keep the queue usable even if a storage implementation violates its
        // Promise contract by throwing outside the awaited operation.
      });
  }

  private emit(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }
}

export { LOAD_ERROR as APPEARANCE_LOAD_ERROR, SAVE_ERROR as APPEARANCE_SAVE_ERROR };
