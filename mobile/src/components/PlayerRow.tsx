import { Pressable, StyleSheet, Text, View } from "react-native";

import { useStudioTheme } from "../appearance/StudioThemeContext";
import { colors, spacing } from "../theme";

export type PlayerRowProps = {
  participant: {
    user_id: string;
    display_name: string;
    roleLabel: "Host" | "Member";
    readinessLabel: "Ready automatically" | "Ready" | "Not ready";
    online: boolean;
    presenceLabel: "Online" | "Offline";
  };
  onReport?: () => void;
};

export function PlayerRow({ participant, onReport }: PlayerRowProps) {
  const initial = participant.display_name.charAt(0).toUpperCase();

  return (
    <View style={styles.row}>
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>{initial}</Text>
      </View>
      <View style={styles.details}>
        <Text style={styles.name}>{participant.display_name}</Text>
        <Text style={styles.role}>
          {participant.roleLabel} — {participant.readinessLabel}
        </Text>
        <Text style={participant.online ? styles.online : styles.offline}>
          {participant.presenceLabel}
        </Text>
      </View>
      {onReport ? (
        <Pressable
          accessibilityLabel={`Report ${participant.display_name}`}
          accessibilityRole="button"
          onPress={onReport}
          style={styles.reportAction}
        >
          <Text style={styles.reportLabel}>Report</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/**
 * Opt-in themed presentation for the Waiting Room. The legacy PlayerRow
 * remains unchanged for routes that have not adopted Studio tokens yet.
 */
export function StudioPlayerRow({ participant, onReport }: PlayerRowProps) {
  const theme = useStudioTheme();
  const initial = participant.display_name.charAt(0).toUpperCase();

  return (
    <View
      style={[
        studioStyles.row,
        { paddingVertical: theme.spacing.sm },
      ]}
    >
      <View
        style={[
          studioStyles.avatar,
          {
            backgroundColor: theme.colors.selectedBackground,
            marginRight: theme.spacing.sm,
          },
        ]}
      >
        <Text
          style={[
            theme.typography.caption,
            studioStyles.avatarText,
            { color: theme.colors.primary },
          ]}
        >
          {initial}
        </Text>
      </View>
      <View style={studioStyles.details}>
        <Text
          style={[
            theme.typography.body,
            studioStyles.name,
            { color: theme.colors.text },
          ]}
        >
          {participant.display_name}
        </Text>
        <Text
          style={[
            theme.typography.caption,
            studioStyles.role,
            { color: theme.colors.mutedText },
          ]}
        >
          {participant.roleLabel} — {participant.readinessLabel}
        </Text>
        <Text
          style={[
            theme.typography.caption,
            studioStyles.presence,
            {
              color: participant.online
                ? theme.colors.success
                : theme.colors.mutedText,
            },
          ]}
        >
          {participant.presenceLabel}
        </Text>
      </View>
      {onReport ? (
        <Pressable
          accessibilityLabel={`Report ${participant.display_name}`}
          accessibilityRole="button"
          onPress={onReport}
          style={[
            studioStyles.reportAction,
            {
              minHeight: 44,
              minWidth: 64,
              paddingLeft: theme.spacing.xs,
            },
          ]}
        >
          <Text
            style={[
              theme.typography.caption,
              studioStyles.reportLabel,
              { color: theme.colors.primary },
            ]}
          >
            Report
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const studioStyles = StyleSheet.create({
  row: {
    alignItems: "center",
    flexDirection: "row",
  },
  avatar: {
    alignItems: "center",
    borderRadius: 18,
    height: 36,
    justifyContent: "center",
    width: 36,
  },
  avatarText: {
    fontWeight: "700",
  },
  details: {
    flex: 1,
  },
  name: {
    fontWeight: "600",
  },
  role: {
    marginTop: 2,
  },
  presence: {
    marginTop: 2,
  },
  reportAction: {
    alignItems: "center",
    justifyContent: "center",
  },
  reportLabel: {
    fontWeight: "700",
  },
});

const styles = StyleSheet.create({
  row: {
    alignItems: "center",
    flexDirection: "row",
    paddingVertical: spacing.sm,
  },
  avatar: {
    alignItems: "center",
    backgroundColor: colors.selectedBackground,
    borderRadius: 18,
    height: 36,
    justifyContent: "center",
    marginRight: spacing.sm,
    width: 36,
  },
  avatarText: {
    color: colors.primary,
    fontSize: 15,
    fontWeight: "700",
  },
  details: {
    flex: 1,
  },
  name: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "600",
  },
  role: {
    color: colors.mutedText,
    fontSize: 13,
    marginTop: 2,
  },
  online: {
    color: colors.success,
    fontSize: 13,
    marginTop: 2,
  },
  offline: {
    color: colors.mutedText,
    fontSize: 13,
    marginTop: 2,
  },
  reportAction: {
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
    minWidth: 64,
    paddingLeft: spacing.xs,
  },
  reportLabel: {
    color: colors.primary,
    fontSize: 13,
    fontWeight: "700",
  },
});
