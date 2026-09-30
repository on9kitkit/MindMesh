import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, spacing } from "../theme";

type RoomCapacityOptionProps = {
  title: string;
  capacityLabel: string;
  accessLabel: string;
  selected: boolean;
  disabled: boolean;
  onPress(): void;
};

export function RoomCapacityOption({
  title,
  capacityLabel,
  accessLabel,
  selected,
  disabled,
  onPress,
}: RoomCapacityOptionProps) {
  return (
    <Pressable
      accessibilityLabel={`${title}, ${capacityLabel}, ${accessLabel}`}
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
        <Text style={styles.description}>{capacityLabel}</Text>
      </View>
      <View style={styles.statusCopy}>
        <Text style={styles.access}>{accessLabel}</Text>
        {selected ? <Text style={styles.selected}>Selected</Text> : null}
      </View>
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
    minHeight: 72,
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
  statusCopy: {
    alignItems: "flex-end",
    paddingLeft: spacing.sm,
  },
  access: {
    color: colors.primary,
    fontSize: 13,
    fontWeight: "700",
  },
  selected: {
    color: colors.text,
    fontSize: 12,
    marginTop: spacing.xs,
  },
});
