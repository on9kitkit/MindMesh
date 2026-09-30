import { StyleSheet, Text, View } from "react-native";

import { studioLightTheme } from "../../theme";
import { getCuratedLearningVisual } from "./curatedRegistry";
import { InteractiveScene3D } from "./InteractiveScene3D";
import type { VisualLearningCardProps } from "./types";
import { Visualization2D } from "./Visualization2D";

export function VisualLearningCard({
  subject,
  topic,
  isRevealed = false,
  theme,
  testID = "visual-learning-card",
}: VisualLearningCardProps) {
  // Strict Privacy Gating: Never expose visual models or topic explanations pre-reveal
  if (!isRevealed) {
    return null;
  }

  if (!subject || !topic) {
    return null;
  }

  // Closed curated registry lookup by actual subject and topic IDs
  const visual = getCuratedLearningVisual(subject, topic);
  if (!visual) {
    return null;
  }

  const activeTheme = theme ?? studioLightTheme;

  return (
    <View
      style={[
        styles.cardContainer,
        {
          backgroundColor: activeTheme.colors.surface,
          borderColor: activeTheme.colors.border,
        },
      ]}
      testID={testID}
    >
      {/* Header with explicit generic concept illustration notice */}
      <View style={styles.header}>
        <View
          style={[
            styles.badge,
            {
              backgroundColor: activeTheme.colors.primarySoft,
              borderColor: activeTheme.colors.primary,
            },
          ]}
        >
          <Text style={[styles.badgeText, { color: activeTheme.colors.primary }]}>
            Topic Concept Illustration
          </Text>
        </View>

        <Text
          style={[styles.disclaimerText, { color: activeTheme.colors.mutedText }]}
          testID={`${testID}-disclaimer`}
        >
          General topic concept illustration — not specific to this question's values or answer.
        </Text>

        <Text
          style={[styles.title, { color: activeTheme.colors.text }]}
          testID={`${testID}-title`}
        >
          {visual.title}
        </Text>
      </View>

      {/* Render appropriate 3D or 2D visualization */}
      {visual.type === "scene_3d" ? (
        <InteractiveScene3D
          descriptor={visual}
          theme={activeTheme}
          testID={`${testID}-3d`}
        />
      ) : (
        <Visualization2D
          descriptor={visual}
          theme={activeTheme}
          testID={`${testID}-2d`}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  cardContainer: {
    marginVertical: 12,
    padding: 14,
    borderWidth: 1,
    borderRadius: 12,
  },
  header: {
    marginBottom: 8,
  },
  badge: {
    alignSelf: "flex-start",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderWidth: 1,
    borderRadius: 6,
    marginBottom: 6,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  disclaimerText: {
    fontSize: 11,
    fontStyle: "italic",
    marginBottom: 4,
    lineHeight: 15,
  },
  title: {
    fontSize: 15,
    fontWeight: "700",
  },
});
