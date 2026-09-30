import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, spacing } from "../theme";

type QuizSelectionOptionProps = {
  title: string;
  description?: string;
  selected: boolean;
  disabled: boolean;
  onPress(): void;
};

export function QuizSelectionOption({
  title,
  description,
  selected,
  disabled,
  onPress,
}: QuizSelectionOptionProps) {
  return (
    <Pressable
      accessibilityLabel={
        description === undefined ? title : `${title}, ${description}`
      }
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.option,
        selected && styles.selectedOption,
        disabled && styles.disabledOption,
        pressed && !disabled && styles.pressedOption,
      ]}
    >
      <View style={styles.copy}>
        <Text style={styles.title}>{title}</Text>
        {description === undefined ? null : (
          <Text style={styles.description}>{description}</Text>
        )}
      </View>
      {selected ? <Text style={styles.selected}>Selected</Text> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  option: {
    alignItems: "center",
    borderColor: colors.border,
    borderRadius: 10,
    borderWidth: 1,
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: spacing.sm,
    minHeight: 52,
    padding: spacing.sm,
  },
  selectedOption: {
    backgroundColor: colors.selectedBackground,
    borderColor: colors.primary,
    borderWidth: 2,
  },
  disabledOption: {
    opacity: 0.55,
  },
  pressedOption: {
    opacity: 0.85,
  },
  copy: {
    flex: 1,
  },
  title: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
  },
  description: {
    color: colors.mutedText,
    fontSize: 14,
    marginTop: spacing.xs,
  },
  selected: {
    color: colors.text,
    fontSize: 12,
    paddingLeft: spacing.sm,
  },
});
