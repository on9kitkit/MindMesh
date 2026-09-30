import { Pressable, StyleSheet, Text, View } from "react-native";

import { useStudioTheme } from "../appearance/StudioThemeContext";
import type { LeaderboardEntryPayload } from "../realtime/protocol";
import { colors, spacing } from "../theme";

export type LeaderboardRowProps = {
  entry: LeaderboardEntryPayload;
  position: number;
  isCurrentUser: boolean;
  marksText?: string | null;
  correctAnswersLabel?: string | null;
  onReport?: () => void;
};

export function LeaderboardRow({
  entry,
  position,
  isCurrentUser,
  marksText,
  correctAnswersLabel,
  onReport,
}: LeaderboardRowProps) {
  return (
    <View style={[styles.row, isCurrentUser && styles.currentUserRow]}>
      <Text style={styles.position}>{position}</Text>
      <View style={styles.details}>
        <Text style={styles.name}>{entry.display_name}</Text>
        <Text style={styles.role}>
          {isCurrentUser ? "You · " : ""}
          {correctAnswersLabel ?? `${entry.correct_answers} correct`}
        </Text>
      </View>
      <Text style={styles.score}>
        {marksText ?? `${entry.total_points} pts`}
      </Text>
      {onReport ? (
        <Pressable
          accessibilityLabel={`Report ${entry.display_name}`}
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
 * Opt-in themed presentation for Quiz reveal. Results continues to consume
 * the legacy LeaderboardRow until that route is explicitly mapped.
 */
export function StudioLeaderboardRow({
  entry,
  position,
  isCurrentUser,
  marksText,
  correctAnswersLabel,
  onReport,
}: LeaderboardRowProps) {
  const theme = useStudioTheme();
  return (
    <View
      style={[
        studioStyles.row,
        isCurrentUser && { backgroundColor: theme.colors.selectedBackground },
      ]}
    >
      <Text style={[theme.typography.body, studioStyles.position, { color: theme.colors.mutedText }]}>
        {position}
      </Text>
      <View style={studioStyles.details}>
        <Text style={[theme.typography.body, studioStyles.name, { color: theme.colors.text }]}>
          {entry.display_name}
        </Text>
        <Text style={[theme.typography.caption, studioStyles.role, { color: theme.colors.mutedText }]}>
          {isCurrentUser ? "You · " : ""}
          {correctAnswersLabel ?? `${entry.correct_answers} correct`}
        </Text>
      </View>
      <Text style={[theme.typography.heading, studioStyles.score, { color: theme.colors.text }]}>
        {marksText ?? `${entry.total_points} pts`}
      </Text>
      {onReport ? (
        <Pressable
          accessibilityLabel={`Report ${entry.display_name}`}
          accessibilityRole="button"
          onPress={onReport}
          style={studioStyles.reportAction}
        >
          <Text style={[theme.typography.caption, studioStyles.reportLabel, { color: theme.colors.primary }]}>
            Report
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    alignItems: "center",
    flexDirection: "row",
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  currentUserRow: {
    backgroundColor: colors.selectedBackground,
    borderRadius: 8,
  },
  position: {
    color: colors.mutedText,
    fontSize: 16,
    fontWeight: "700",
    width: 30,
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
  score: {
    color: colors.text,
    fontSize: 18,
    fontWeight: "800",
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

const studioStyles = StyleSheet.create({
  row: {
    alignItems: "center",
    borderRadius: 18,
    flexDirection: "row",
    paddingHorizontal: 6,
    paddingVertical: 10,
  },
  position: {
    fontWeight: "700",
    width: 30,
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
  score: {
    fontWeight: "800",
  },
  reportAction: {
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
    minWidth: 64,
    paddingLeft: 6,
  },
  reportLabel: {
    fontWeight: "700",
  },
});
