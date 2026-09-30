/**
 * Presentation-only design tokens for the Studio surfaces.
 *
 * The legacy exports at the bottom intentionally retain the existing light
 * palette. Untouched routes still consume those exports until they opt into
 * StudioThemeProvider; this prevents a theme foundation from changing shared
 * cards or text across the rest of the app.
 */

export type ThemeMode = "light" | "dark" | "system";
export type ThemeScheme = "light" | "dark";

export type ThemeColors = {
  background: string;
  surface: string;
  surfaceElevated: string;
  input: string;
  text: string;
  mutedText: string;
  border: string;
  primary: string;
  primaryPressed: string;
  primarySoft: string;
  primaryDisabled: string;
  onPrimary: string;
  selectedBackground: string;
  success: string;
  successBackground: string;
  error: string;
  errorBackground: string;
};

export type ThemeSpacing = {
  xs: number;
  sm: number;
  md: number;
  lg: number;
  xl: number;
  xxl: number;
};

export type ThemeRadii = {
  sm: number;
  md: number;
  lg: number;
  pill: number;
};

export type ThemeFontWeight = "400" | "500" | "600" | "700" | "800";

export type ThemeTypeStyle = {
  fontSize: number;
  lineHeight: number;
  fontWeight: ThemeFontWeight;
  letterSpacing?: number;
};

export type ThemeTypography = {
  eyebrow: ThemeTypeStyle;
  title: ThemeTypeStyle;
  heading: ThemeTypeStyle;
  body: ThemeTypeStyle;
  label: ThemeTypeStyle;
  caption: ThemeTypeStyle;
};

export type ThemeTokens = {
  scheme: ThemeScheme;
  colors: ThemeColors;
  spacing: ThemeSpacing;
  radii: ThemeRadii;
  typography: ThemeTypography;
};

const baseSpacing: ThemeSpacing = {
  xs: 6,
  sm: 10,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
};

const baseRadii: ThemeRadii = {
  sm: 12,
  md: 18,
  lg: 26,
  pill: 999,
};
export const woodRadii: ThemeRadii = {
  sm: 10,
  md: 16,
  lg: 22,
  pill: 999,
};

export const glassRadii: ThemeRadii = {
  sm: 14,
  md: 20,
  lg: 28,
  pill: 999,
};

export const paperRadii: ThemeRadii = {
  sm: 8,
  md: 14,
  lg: 20,
  pill: 999,
};


const baseTypography: ThemeTypography = {
  eyebrow: {
    fontSize: 12,
    lineHeight: 16,
    fontWeight: "800",
    letterSpacing: 1.8,
  },
  title: {
    fontSize: 34,
    lineHeight: 40,
    fontWeight: "800",
  },
  heading: {
    fontSize: 21,
    lineHeight: 28,
    fontWeight: "800",
  },
  body: {
    fontSize: 16,
    lineHeight: 24,
    fontWeight: "400",
  },
  label: {
    fontSize: 12,
    lineHeight: 16,
    fontWeight: "800",
    letterSpacing: 1.2,
  },
  caption: {
    fontSize: 14,
    lineHeight: 20,
    fontWeight: "500",
  },
};

export const studioLightTheme: ThemeTokens = {
  scheme: "light",
  colors: {
    background: "#F5F6FB",
    surface: "#FFFFFF",
    surfaceElevated: "#F0F1FA",
    input: "#FBFBFE",
    text: "#16182A",
    mutedText: "#60677D",
    border: "#D9DCEA",
    primary: "#5146E5",
    primaryPressed: "#3F36B7",
    primarySoft: "#EAE8FF",
    primaryDisabled: "#BDBBE0",
    onPrimary: "#FFFFFF",
    selectedBackground: "#EAE8FF",
    success: "#19724A",
    successBackground: "#E8F6EE",
    error: "#B42318",
    errorBackground: "#FDECEB",
  },
  spacing: baseSpacing,
  radii: baseRadii,
  typography: baseTypography,
};

export const studioDarkTheme: ThemeTokens = {
  scheme: "dark",
  colors: {
    background: "#101326",
    surface: "#181D36",
    surfaceElevated: "#222846",
    input: "#141A31",
    text: "#F5F6FF",
    mutedText: "#B9BFDA",
    border: "#3A4265",
    primary: "#9B95FF",
    primaryPressed: "#B7B2FF",
    primarySoft: "#2F2B5C",
    primaryDisabled: "#5E6090",
    onPrimary: "#15172A",
    selectedBackground: "#2F2B5C",
    success: "#7FE0AE",
    successBackground: "#183D31",
    error: "#FF9B91",
    errorBackground: "#49242B",
  },
  spacing: baseSpacing,
  radii: baseRadii,
  typography: baseTypography,
};

export const woodLightTheme: ThemeTokens = {
  scheme: "light",
  colors: {
    background: "#EEE3D0",
    surface: "#FFF9ED",
    surfaceElevated: "#E6D7C0",
    input: "#FDF6EA",
    text: "#302B24",
    mutedText: "#6B5B48",
    border: "#D5C4AA",
    primary: "#2F5C43",
    primaryPressed: "#234733",
    primarySoft: "#DDECE2",
    primaryDisabled: "#BAC9BF",
    onPrimary: "#FFFFFF",
    selectedBackground: "#E4EDE6",
    success: "#1F6B43",
    successBackground: "#E2F2E8",
    error: "#A82E2E",
    errorBackground: "#FBE8E8",
  },
  spacing: baseSpacing,
  radii: woodRadii,
  typography: baseTypography,
};

export const woodDarkTheme: ThemeTokens = {
  scheme: "dark",
  colors: {
    background: "#201A16",
    surface: "#2D241F",
    surfaceElevated: "#3B3029",
    input: "#271F1A",
    text: "#F7ECE0",
    mutedText: "#C4B29E",
    border: "#544537",
    primary: "#92CAA1",
    primaryPressed: "#B0DEBC",
    primarySoft: "#253D2E",
    primaryDisabled: "#4E6655",
    onPrimary: "#14241A",
    selectedBackground: "#283E30",
    success: "#85DCA8",
    successBackground: "#1B3B2B",
    error: "#FF9B9B",
    errorBackground: "#472424",
  },
  spacing: baseSpacing,
  radii: woodRadii,
  typography: baseTypography,
};

export const glassLightTheme: ThemeTokens = {
  scheme: "light",
  colors: {
    background: "#E8EEF8",
    surface: "#F8FAFF",
    surfaceElevated: "#DDE6F5",
    input: "#F4F7FD",
    text: "#1D2842",
    mutedText: "#4F5D7C",
    border: "#CAD6E8",
    primary: "#4B44C7",
    primaryPressed: "#3A33A8",
    primarySoft: "#E3E7FC",
    primaryDisabled: "#B8C0E6",
    onPrimary: "#FFFFFF",
    selectedBackground: "#E6EAFA",
    success: "#137255",
    successBackground: "#E2F4EE",
    error: "#B52942",
    errorBackground: "#FCE7EC",
  },
  spacing: baseSpacing,
  radii: glassRadii,
  typography: baseTypography,
};

export const glassDarkTheme: ThemeTokens = {
  scheme: "dark",
  colors: {
    background: "#0E1828",
    surface: "#1A283E",
    surfaceElevated: "#243754",
    input: "#152134",
    text: "#F0F5FF",
    mutedText: "#A6BAD8",
    border: "#3F5374",
    primary: "#A29DFF",
    primaryPressed: "#BFBCFF",
    primarySoft: "#222552",
    primaryDisabled: "#575B8A",
    onPrimary: "#10132A",
    selectedBackground: "#222D4F",
    success: "#76DEB4",
    successBackground: "#13382C",
    error: "#FFA0B2",
    errorBackground: "#48222B",
  },
  spacing: baseSpacing,
  radii: glassRadii,
  typography: baseTypography,
};

export const paperLightTheme: ThemeTokens = {
  scheme: "light",
  colors: {
    background: "#F2EFE8",
    surface: "#FFFCF5",
    surfaceElevated: "#E7E2D7",
    input: "#FBF8F0",
    text: "#2E2A27",
    mutedText: "#6B645B",
    border: "#D8D0C2",
    primary: "#943053",
    primaryPressed: "#782240",
    primarySoft: "#FCE5ED",
    primaryDisabled: "#D9B6C2",
    onPrimary: "#FFFFFF",
    selectedBackground: "#FAE8EE",
    success: "#1E6E49",
    successBackground: "#E3F3EA",
    error: "#AD2727",
    errorBackground: "#FBE6E6",
  },
  spacing: baseSpacing,
  radii: paperRadii,
  typography: baseTypography,
};

export const paperDarkTheme: ThemeTokens = {
  scheme: "dark",
  colors: {
    background: "#1E1D1B",
    surface: "#2B2927",
    surfaceElevated: "#383532",
    input: "#242220",
    text: "#F5F0E6",
    mutedText: "#BCB3A4",
    border: "#4E4942",
    primary: "#F29FBD",
    primaryPressed: "#F8BDD3",
    primarySoft: "#40232E",
    primaryDisabled: "#6E4D58",
    onPrimary: "#291019",
    selectedBackground: "#3D2B32",
    success: "#82DCAB",
    successBackground: "#1B3B2B",
    error: "#FFA2A2",
    errorBackground: "#472424",
  },
  spacing: baseSpacing,
  radii: paperRadii,
  typography: baseTypography,
};

export type ThemePalette = "studio" | "wood" | "glass" | "paper";

export const DEFAULT_THEME_PALETTE: ThemePalette = "studio";

export const THEME_PALETTE_INFO: Record<
  ThemePalette,
  { name: string; description: string }
> = {
  studio: { name: "Studio", description: "Clean & considered" },
  wood: { name: "Wood", description: "Warm & tactile" },
  glass: { name: "Glass", description: "Frosted & luminous" },
  paper: { name: "Paper", description: "Quiet & editorial" },
};

export const THEME_PALETTES: Record<
  ThemePalette,
  Record<ThemeScheme, ThemeTokens>
> = {
  studio: {
    light: studioLightTheme,
    dark: studioDarkTheme,
  },
  wood: {
    light: woodLightTheme,
    dark: woodDarkTheme,
  },
  glass: {
    light: glassLightTheme,
    dark: glassDarkTheme,
  },
  paper: {
    light: paperLightTheme,
    dark: paperDarkTheme,
  },
};

export function themeForPaletteAndScheme(
  palette: ThemePalette,
  scheme: ThemeScheme,
): ThemeTokens {
  return THEME_PALETTES[palette]?.[scheme] ?? THEME_PALETTES.studio[scheme];
}


export const DEFAULT_THEME_MODE: ThemeMode = "light";

export function resolveThemeScheme(
  mode: ThemeMode,
  systemScheme: ThemeScheme | null | undefined,
): ThemeScheme {
  if (mode === "system") {
    return systemScheme === "dark" ? "dark" : "light";
  }
  return mode;
}

export function themeForScheme(scheme: ThemeScheme): ThemeTokens {
  return scheme === "dark" ? studioDarkTheme : studioLightTheme;
}

export function themeForMode(
  mode: ThemeMode,
  systemScheme: ThemeScheme | null | undefined,
): ThemeTokens {
  return themeForScheme(resolveThemeScheme(mode, systemScheme));
}

// Legacy light exports. These values intentionally match the inherited
// palette so routes not yet migrated do not change appearance.
export const colors = {
  background: "#F6F8FB",
  surface: "#FFFFFF",
  text: "#17202A",
  mutedText: "#667383",
  border: "#D9E0E8",
  primary: "#2F6FED",
  primaryPressed: "#2459C8",
  primaryDisabled: "#B8C5DA",
  selectedBackground: "#EAF1FF",
  success: "#1F7A4D",
  successBackground: "#EAF7EF",
  error: "#B42318",
  errorBackground: "#FFF0EE",
};

export const spacing = {
  xs: 6,
  sm: 12,
  md: 20,
  lg: 28,
  xl: 40,
};
