import type { TextStyle, ViewStyle } from "react-native";

import type { ThemeTokens } from "../theme";

export type StudioButtonVariant =
  | "primary"
  | "secondary"
  | "quiet"
  | "destructive";

export type StudioButtonPresentation = {
  button: ViewStyle;
  label: TextStyle;
};

export function studioButtonPresentation(
  theme: ThemeTokens,
  variant: StudioButtonVariant,
  disabled: boolean,
): StudioButtonPresentation {
  const isPrimary = variant === "primary";
  const isDestructive = variant === "destructive";
  const isQuiet = variant === "quiet";
  const backgroundColor = isPrimary
    ? theme.colors.primary
    : isDestructive
      ? theme.colors.error
      : isQuiet
        ? "transparent"
        : theme.colors.surface;
  const labelColor = isPrimary || isDestructive
    ? theme.colors.onPrimary
    : theme.colors.text;

  return {
    button: {
      alignItems: "center",
      backgroundColor,
      borderColor: isQuiet ? "transparent" : theme.colors.border,
      borderRadius: theme.radii.md,
      borderWidth: isPrimary || isDestructive || isQuiet ? 0 : 1,
      justifyContent: "center",
      minHeight: 48,
      opacity: disabled ? 0.55 : 1,
      paddingHorizontal: theme.spacing.lg,
      paddingVertical: theme.spacing.sm,
    },
    label: {
      color: labelColor,
      fontSize: 16,
      fontWeight: "800",
      lineHeight: 22,
    },
  };
}

export type StudioChoicePresentation = {
  row: ViewStyle;
  title: TextStyle;
  description: TextStyle;
  indicator: ViewStyle;
  indicatorMark: ViewStyle;
};

export function studioChoicePresentation(
  theme: ThemeTokens,
  selected: boolean,
  disabled: boolean,
): StudioChoicePresentation {
  return {
    row: {
      alignItems: "center",
      backgroundColor: selected
        ? theme.colors.selectedBackground
        : theme.colors.surface,
      borderColor: selected ? theme.colors.primary : theme.colors.border,
      borderRadius: theme.radii.md,
      borderWidth: 1,
      flexDirection: "row",
      minHeight: 64,
      opacity: disabled ? 0.55 : 1,
      paddingHorizontal: theme.spacing.md,
      paddingVertical: theme.spacing.sm,
    },
    title: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: "700",
      lineHeight: 22,
    },
    description: {
      color: theme.colors.mutedText,
      fontSize: 14,
      lineHeight: 20,
      marginTop: 2,
    },
    indicator: {
      alignItems: "center",
      borderColor: selected ? theme.colors.primary : theme.colors.border,
      borderRadius: theme.radii.pill,
      borderWidth: 2,
      height: 22,
      justifyContent: "center",
      marginRight: theme.spacing.sm,
      width: 22,
    },
    indicatorMark: {
      backgroundColor: theme.colors.primary,
      borderRadius: theme.radii.pill,
      height: 10,
      width: 10,
    },
  };
}
