import {
  createContext,
  useEffect,
  useContext,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";
import { useColorScheme } from "react-native";

import {
  AppearancePreferenceController,
  type AppearancePreferenceSnapshot,
  type AppearanceStorage,
} from "./appearancePreference";
import {
  PalettePreferenceController,
  type PalettePreferenceSnapshot,
} from "./palettePreference";
import {
  DEFAULT_THEME_MODE,
  DEFAULT_THEME_PALETTE,
  resolveThemeScheme,
  themeForPaletteAndScheme,
  type ThemeMode,
  type ThemePalette,
  type ThemeScheme,
  type ThemeTokens,
} from "../theme";

export type StudioThemeContextValue = ThemeTokens & {
  mode: ThemeMode;
  selectedMode: ThemeMode;
  preferenceHydrated: boolean;
  preferenceError: string | undefined;
  setMode: (mode: ThemeMode) => void;
  retryModeSave: () => void;
  palette: ThemePalette;
  selectedPalette: ThemePalette;
  paletteHydrated: boolean;
  paletteError: string | undefined;
  setPalette: (palette: ThemePalette) => void;
  retryPaletteSave: () => void;
};

const StudioThemeContext = createContext<StudioThemeContextValue | undefined>(
  undefined,
);

type StudioThemeProviderProps = PropsWithChildren<{
  mode?: ThemeMode;
  palette?: ThemePalette;
  preferenceEnabled?: boolean;
  storage?: AppearanceStorage;
  systemScheme?: ThemeScheme | null;
}>;

/**
 * Presentation-only context. It owns only the device-local appearance
 * preference, not auth, RevenueCat, session, or server state, so changing the
 * mode cannot remount those providers.
 */
export function StudioThemeProvider({
  children,
  mode,
  palette,
  preferenceEnabled = true,
  storage,
  systemScheme,
}: StudioThemeProviderProps) {
  const [controller] = useState(
    () => new AppearancePreferenceController(storage),
  );
  const [paletteController] = useState(
    () => new PalettePreferenceController(storage),
  );
  const [snapshot, setSnapshot] = useState<AppearancePreferenceSnapshot>(() =>
    controller.getSnapshot(),
  );
  const [paletteSnapshot, setPaletteSnapshot] = useState<PalettePreferenceSnapshot>(() =>
    paletteController.getSnapshot(),
  );

  useEffect(() => controller.subscribe(() => setSnapshot(controller.getSnapshot())), [controller]);
  useEffect(
    () => paletteController.subscribe(() => setPaletteSnapshot(paletteController.getSnapshot())),
    [paletteController],
  );
  useEffect(() => {
    if (preferenceEnabled && mode === undefined) {
      void controller.hydrate();
    }
  }, [controller, mode, preferenceEnabled]);
  useEffect(() => {
    if (preferenceEnabled && palette === undefined) {
      void paletteController.hydrate();
    }
  }, [paletteController, palette, preferenceEnabled]);

  const nativeSystemScheme = useColorScheme();
  const resolvedSystemScheme = systemScheme ?? (nativeSystemScheme === "unspecified" ? null : nativeSystemScheme);
  const selectedMode = snapshot.mode;
  const effectiveMode =
    preferenceEnabled && mode === undefined ? selectedMode : (mode ?? DEFAULT_THEME_MODE);
  const scheme = resolveThemeScheme(effectiveMode, resolvedSystemScheme);

  const selectedPalette = paletteSnapshot.palette;
  const effectivePalette =
    preferenceEnabled && palette === undefined
      ? selectedPalette
      : (palette ?? DEFAULT_THEME_PALETTE);

  const value = useMemo<StudioThemeContextValue>(() => {
    const theme = themeForPaletteAndScheme(effectivePalette, scheme);
    return {
      ...theme,
      mode: effectiveMode,
      selectedMode,
      preferenceHydrated: snapshot.hydrated,
      preferenceError: snapshot.error,
      setMode: (nextMode) => {
        if (preferenceEnabled && mode === undefined) {
          controller.select(nextMode);
        }
      },
      retryModeSave: () => controller.retry(),
      palette: effectivePalette,
      selectedPalette,
      paletteHydrated: paletteSnapshot.hydrated,
      paletteError: paletteSnapshot.error,
      setPalette: (nextPalette) => {
        if (preferenceEnabled && palette === undefined) {
          paletteController.select(nextPalette);
        }
      },
      retryPaletteSave: () => paletteController.retry(),
    };
  }, [
    controller,
    effectiveMode,
    effectivePalette,
    mode,
    palette,
    paletteController,
    paletteSnapshot.error,
    paletteSnapshot.hydrated,
    preferenceEnabled,
    scheme,
    selectedMode,
    selectedPalette,
    snapshot.error,
    snapshot.hydrated,
  ]);

  return (
    <StudioThemeContext.Provider value={value}>
      {children}
    </StudioThemeContext.Provider>
  );
}

export function useStudioTheme(): StudioThemeContextValue {
  const theme = useContext(StudioThemeContext);
  if (theme === undefined) {
    throw new Error("useStudioTheme must be used inside StudioThemeProvider");
  }
  return theme;
}
