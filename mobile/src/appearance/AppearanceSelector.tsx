import { useState } from "react";

import {
  StudioButton,
  StudioCard,
  StudioChoiceRow,
  StudioStack,
  StudioText,
} from "../components/studio/StudioPrimitives";
import { useStudioTheme } from "./StudioThemeContext";
import {
  THEME_PALETTE_INFO,
  type ThemeMode,
  type ThemePalette,
} from "../theme";

const MODE_OPTIONS: ReadonlyArray<{
  mode: ThemeMode;
  title: string;
  description: string;
}> = [
  { mode: "light", title: "Light", description: "A bright appearance." },
  { mode: "dark", title: "Dark", description: "A focused dark appearance." },
  { mode: "system", title: "System", description: "Follow this device's appearance." },
];

const MODE_LABELS: Record<ThemeMode, string> = {
  light: "Light",
  dark: "Dark",
  system: "System",
};

const PALETTE_OPTIONS: ReadonlyArray<{
  palette: ThemePalette;
  title: string;
  description: string;
}> = [
  {
    palette: "studio",
    title: THEME_PALETTE_INFO.studio.name,
    description: THEME_PALETTE_INFO.studio.description,
  },
  {
    palette: "wood",
    title: THEME_PALETTE_INFO.wood.name,
    description: THEME_PALETTE_INFO.wood.description,
  },
  {
    palette: "glass",
    title: THEME_PALETTE_INFO.glass.name,
    description: THEME_PALETTE_INFO.glass.description,
  },
  {
    palette: "paper",
    title: THEME_PALETTE_INFO.paper.name,
    description: THEME_PALETTE_INFO.paper.description,
  },
];

export function StudioAppearanceSelector() {
  const {
    preferenceError,
    selectedMode,
    setMode,
    retryModeSave,
    paletteError,
    selectedPalette,
    setPalette,
    retryPaletteSave,
  } = useStudioTheme();
  const [expandedMode, setExpandedMode] = useState(false);
  const [expandedPalette, setExpandedPalette] = useState(false);
  return (
    <StudioCard>
      <StudioStack>
        <StudioText variant="heading">Appearance</StudioText>
        <StudioText tone="muted">
          Choose Light, Dark, or System for this device, and pick a design theme.
          This setting is not linked to your account.
        </StudioText>
        <StudioButton
          label={`${expandedMode ? "Hide" : "Choose"} appearance: ${MODE_LABELS[selectedMode]}`}
          onPress={() => setExpandedMode((current) => !current)}
          variant="secondary"
        />
        {expandedMode ? (
          <StudioStack>
            {MODE_OPTIONS.map((option) => (
              <StudioChoiceRow
                key={option.mode}
                accessibilityLabel={`${option.title} appearance`}
                description={option.description}
                onPress={() => setMode(option.mode)}
                selected={selectedMode === option.mode}
                title={option.title}
              />
            ))}
          </StudioStack>
        ) : null}
        {preferenceError ? (
          <StudioStack>
            <StudioText accessibilityRole="alert" tone="error">
              {preferenceError}
            </StudioText>
            <StudioButton
              label="Retry appearance storage"
              onPress={retryModeSave}
              variant="secondary"
            />
          </StudioStack>
        ) : null}
        <StudioButton
          label={`${expandedPalette ? "Hide" : "Choose"} theme: ${THEME_PALETTE_INFO[selectedPalette]?.name ?? "Studio"}`}
          onPress={() => setExpandedPalette((current) => !current)}
          variant="secondary"
        />
        {expandedPalette ? (
          <StudioStack>
            {PALETTE_OPTIONS.map((option) => (
              <StudioChoiceRow
                key={option.palette}
                accessibilityLabel={`${option.title} theme`}
                description={option.description}
                onPress={() => setPalette(option.palette)}
                selected={selectedPalette === option.palette}
                title={option.title}
              />
            ))}
          </StudioStack>
        ) : null}
        {paletteError ? (
          <StudioStack>
            <StudioText accessibilityRole="alert" tone="error">
              {paletteError}
            </StudioText>
            <StudioButton
              label="Retry palette storage"
              onPress={retryPaletteSave}
              variant="secondary"
            />
          </StudioStack>
        ) : null}
        <StudioText tone="muted" variant="caption">
          Changes apply immediately; this setting is device-local.
        </StudioText>
      </StudioStack>
    </StudioCard>
  );
}
