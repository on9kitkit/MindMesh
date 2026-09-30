import { Pressable, StyleSheet, Text } from "react-native";

import { useStudioTheme } from "../appearance/StudioThemeContext";
import type { QuestionOptionPayload } from "../realtime/protocol";
import type { QuizOptionAppearance } from "../features/quiz/quizPresentation";
import { colors, spacing } from "../theme";

export type QuizOptionProps = {
  option: QuestionOptionPayload;
  selected: boolean;
  appearance: QuizOptionAppearance;
  disabled: boolean;
  onPress: () => void;
};

export function QuizOption({
  option,
  selected,
  appearance,
  disabled,
  onPress,
}: QuizOptionProps) {
  return (
    <Pressable
      accessibilityLabel={option.label}
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.option,
        appearance === "selected" && styles.selectedOption,
        appearance === "correct" && styles.correctOption,
        appearance === "incorrect-selected" && styles.incorrectOption,
        pressed && !disabled && styles.pressedOption,
      ]}
    >
      <Text
        style={[
          styles.label,
          appearance === "selected" && styles.selectedLabel,
          appearance === "correct" && styles.correctLabel,
          appearance === "incorrect-selected" && styles.incorrectLabel,
        ]}
      >
        {option.label}
      </Text>
    </Pressable>
  );
}

/**
 * Opt-in themed presentation for the Quiz route. The legacy QuizOption stays
 * unchanged for any route that has not adopted the Studio palette.
 */
export function StudioQuizOption({
  option,
  selected,
  appearance,
  disabled,
  onPress,
}: QuizOptionProps) {
  const theme = useStudioTheme();
  const isCorrect = appearance === "correct";
  const isIncorrect = appearance === "incorrect-selected";
  const backgroundColor = isCorrect
    ? theme.colors.successBackground
    : isIncorrect
      ? theme.colors.errorBackground
      : appearance === "selected"
        ? theme.colors.selectedBackground
        : theme.colors.surface;
  const borderColor = isCorrect
    ? theme.colors.success
    : isIncorrect
      ? theme.colors.error
      : appearance === "selected"
        ? theme.colors.primary
        : theme.colors.border;
  const labelColor = isCorrect
    ? theme.colors.success
    : isIncorrect
      ? theme.colors.error
      : appearance === "selected"
        ? theme.colors.primary
        : theme.colors.text;

  return (
    <Pressable
      accessibilityLabel={option.label}
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        studioStyles.option,
        {
          backgroundColor,
          borderColor,
          opacity: disabled ? 0.55 : 1,
        },
        pressed && !disabled && { borderColor: theme.colors.primaryPressed },
      ]}
    >
      <Text
        style={[
          theme.typography.body,
          studioStyles.label,
          { color: labelColor, fontWeight: selected || isCorrect || isIncorrect ? "700" : "400" },
        ]}
      >
        {option.label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  option: {
    borderColor: colors.border,
    borderRadius: 10,
    borderWidth: 1,
    marginTop: spacing.sm,
    minHeight: 52,
    justifyContent: "center",
    paddingHorizontal: spacing.md,
  },
  selectedOption: {
    backgroundColor: colors.selectedBackground,
    borderColor: colors.primary,
  },
  correctOption: {
    backgroundColor: colors.successBackground,
    borderColor: colors.success,
  },
  incorrectOption: {
    backgroundColor: colors.errorBackground,
    borderColor: colors.error,
  },
  pressedOption: {
    opacity: 0.8,
  },
  label: {
    color: colors.text,
    fontSize: 16,
    lineHeight: 22,
  },
  selectedLabel: {
    color: colors.primary,
    fontWeight: "700",
  },
  correctLabel: {
    color: colors.success,
    fontWeight: "700",
  },
  incorrectLabel: {
    color: colors.error,
    fontWeight: "700",
  },
});

const studioStyles = StyleSheet.create({
  option: {
    borderRadius: 18,
    borderWidth: 1,
    justifyContent: "center",
    marginTop: 10,
    minHeight: 52,
    paddingHorizontal: 16,
  },
  label: {
    lineHeight: 22,
  },
});
