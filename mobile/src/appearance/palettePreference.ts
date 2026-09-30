import {
  DEFAULT_THEME_PALETTE,
  type ThemePalette,
} from "../theme";
import {
  secureAppearanceStorage,
  type AppearanceStorage,
} from "./appearancePreference";

export const PALETTE_STORAGE_KEY = "studyroom.appearance.palette.v1";

export type PalettePreferenceSnapshot = {
  palette: ThemePalette;
  hydrated: boolean;
  error: string | undefined;
};

const LOAD_ERROR = "Could not load palette on this device.";
const SAVE_ERROR = "Could not save palette on this device.";

export function isThemePalette(value: unknown): value is ThemePalette {
  return (
    value === "studio" ||
    value === "wood" ||
    value === "glass" ||
    value === "paper"
  );
}

export function parseStoredThemePalette(value: string | null): ThemePalette {
  return isThemePalette(value) ? value : DEFAULT_THEME_PALETTE;
}

/**
 * Device-local palette preference owner. It deliberately knows nothing about auth,
 * accounts, sessions, mode, or server state.
 */
export class PalettePreferenceController {
  private readonly listeners = new Set<() => void>();
  private readonly storage: AppearanceStorage;
  private palette: ThemePalette = DEFAULT_THEME_PALETTE;
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

  public getSnapshot(): PalettePreferenceSnapshot {
    return { palette: this.palette, hydrated: this.hydrated, error: this.error };
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

  public select(palette: ThemePalette): void {
    if (!isThemePalette(palette)) {
      return;
    }
    this.userSelected = true;
    this.palette = palette;
    this.error = undefined;
    this.selectionVersion += 1;
    const version = this.selectionVersion;
    this.emit();
    this.enqueueWrite(palette, version);
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
    this.enqueueWrite(this.palette, version);
  }

  private startRead(): Promise<void> {
    const read = this.loadStoredPalette();
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

  private async loadStoredPalette(): Promise<void> {
    const selectionVersionAtReadStart = this.selectionVersion;
    try {
      const stored = await this.storage.getItem(PALETTE_STORAGE_KEY);
      const readStillOwnsPublication =
        !this.userSelected &&
        this.selectionVersion === selectionVersionAtReadStart;
      if (readStillOwnsPublication) {
        this.palette = parseStoredThemePalette(stored);
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

  private enqueueWrite(palette: ThemePalette, version: number): void {
    this.writeChain = this.writeChain
      .then(async () => {
        try {
          await this.storage.setItem(PALETTE_STORAGE_KEY, palette);
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

export { LOAD_ERROR as PALETTE_LOAD_ERROR, SAVE_ERROR as PALETTE_SAVE_ERROR };
