import { Pressable, StyleSheet, Text } from "react-native";

import { colors, spacing } from "../theme";

type AppButtonProps = {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "destructive";
};

export function AppButton({
  label,
  onPress,
  disabled = false,
  variant = "primary",
}: AppButtonProps) {
  const isSecondary = variant === "secondary";
  const isDestructive = variant === "destructive";

  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        isSecondary
          ? styles.secondaryButton
          : isDestructive
            ? styles.destructiveButton
            : styles.primaryButton,
        disabled && styles.disabledButton,
        pressed && !disabled && styles.pressedButton,
      ]}
    >
      <Text
        style={[
          styles.label,
          isSecondary ? styles.secondaryLabel : styles.primaryLabel,
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: "center",
    borderRadius: 10,
    minHeight: 50,
    justifyContent: "center",
    paddingHorizontal: spacing.md,
  },
  primaryButton: {
    backgroundColor: colors.primary,
  },
  destructiveButton: {
    backgroundColor: colors.error,
  },
  secondaryButton: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
  },
  disabledButton: {
    backgroundColor: colors.primaryDisabled,
  },
  pressedButton: {
    opacity: 0.85,
  },
  label: {
    fontSize: 16,
    fontWeight: "700",
  },
  primaryLabel: {
    color: colors.surface,
  },
  secondaryLabel: {
    color: colors.text,
  },
});
