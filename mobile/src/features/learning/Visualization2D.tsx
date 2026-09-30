import React, { useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { ThemeTokens } from "../../theme";
import type { Visualization2DDescriptor } from "./types";

export type Visualization2DProps = {
  descriptor: Visualization2DDescriptor;
  theme: ThemeTokens;
  testID?: string;
};

const VIEWPORT_WIDTH = 260;
const VIEWPORT_HEIGHT = 200;

export function Visualization2D({
  descriptor,
  theme,
  testID = "visualization-2d",
}: Visualization2DProps) {
  const [showTable, setShowTable] = useState(false);

  const originX = descriptor.origin.x;
  const originY = descriptor.origin.y;
  const scale = descriptor.scale;

  return (
    <View style={styles.container} testID={testID}>
      {/* 2D Canvas */}
      <View
        style={[
          styles.canvas,
          {
            width: VIEWPORT_WIDTH,
            height: VIEWPORT_HEIGHT,
            backgroundColor: theme.colors.surfaceElevated,
            borderColor: theme.colors.border,
          },
        ]}
        accessibilityLabel={`2D Vector Diagram: ${descriptor.title}`}
        accessibilityRole="image"
        testID={`${testID}-canvas`}
      >
        {/* Horizontal Axis */}
        <View
          style={[
            styles.axisLine,
            {
              left: 10,
              top: originY,
              width: VIEWPORT_WIDTH - 20,
              height: 1,
              backgroundColor: theme.colors.border,
            },
          ]}
        />

        {/* Vertical Axis */}
        <View
          style={[
            styles.axisLine,
            {
              left: originX,
              top: 10,
              width: 1,
              height: VIEWPORT_HEIGHT - 20,
              backgroundColor: theme.colors.border,
            },
          ]}
        />

        {/* Center Object Box */}
        <View
          style={[
            styles.centerBox,
            {
              left: originX - 16,
              top: originY - 16,
              width: 32,
              height: 32,
              backgroundColor: theme.colors.surface,
              borderColor: theme.colors.primary,
            },
          ]}
          testID={`${testID}-center-box`}
        >
          <Text style={[styles.centerBoxText, { color: theme.colors.primary }]}>M</Text>
        </View>

        {/* Vectors */}
        {descriptor.vectors.map((vec) => {
          const length = vec.magnitude * scale;
          const rad = (vec.angleDeg * Math.PI) / 180;
          // Canvas Y is downward, so sin is subtracted
          const endX = originX + Math.cos(rad) * length;
          const endY = originY - Math.sin(rad) * length;

          const midX = (originX + endX) / 2;
          const midY = (originY + endY) / 2;
          const angleRad = Math.atan2(endY - originY, endX - originX);
          const color = theme.colors[vec.colorToken];

          // Text placement offset
          const labelOffsetX = Math.cos(rad) * 16;
          const labelOffsetY = -Math.sin(rad) * 16;

          return (
            <React.Fragment key={`vec-${vec.id}`}>
              {/* Vector Shaft */}
              <View
                style={[
                  styles.vectorLine,
                  {
                    left: midX - length / 2,
                    top: midY - 1,
                    width: length,
                    height: 2.5,
                    backgroundColor: color,
                    transform: [{ rotate: `${angleRad}rad` }],
                  },
                ]}
                testID={`${testID}-vector-${vec.id}`}
              />

              {/* Directional Vector Arrowhead (two angled wings) */}
              <View
                style={[
                  styles.arrowHeadContainer,
                  {
                    left: endX - 8,
                    top: endY - 8,
                    transform: [{ rotate: `${angleRad}rad` }],
                  },
                ]}
                testID={`${testID}-arrowhead-${vec.id}`}
              >
                <View
                  style={[
                    styles.arrowBarb,
                    {
                      backgroundColor: color,
                      transform: [{ rotate: "145deg" }],
                    },
                  ]}
                />
                <View
                  style={[
                    styles.arrowBarb,
                    {
                      backgroundColor: color,
                      transform: [{ rotate: "-145deg" }],
                    },
                  ]}
                />
              </View>

              {/* Vector Label */}
              <Text
                style={[
                  styles.vectorLabel,
                  {
                    left: endX + labelOffsetX - 30,
                    top: endY + labelOffsetY - 8,
                    color: theme.colors.text,
                  },
                ]}
              >
                {vec.label}
              </Text>
            </React.Fragment>
          );
        })}

        {/* Resultant Summary Tag in Top-Right */}
        {descriptor.resultant ? (
          <View
            style={[
              styles.resultantBadge,
              {
                backgroundColor: theme.colors.successBackground,
                borderColor: theme.colors.success,
              },
            ]}
          >
            <Text style={[styles.resultantText, { color: theme.colors.success }]}>
              {descriptor.resultant.label}
            </Text>
          </View>
        ) : null}
      </View>

      {/* Screen-reader summary */}
      <Text
        style={[styles.statusText, { color: theme.colors.mutedText }]}
        accessibilityLiveRegion="polite"
      >
        {descriptor.educationalSummary}
      </Text>

      {/* Toggle Table Button */}
      <Pressable
        accessibilityLabel={showTable ? "Hide data table" : "Show data table"}
        accessibilityRole="button"
        onPress={() => setShowTable((prev) => !prev)}
        style={[
          styles.toggleButton,
          {
            borderColor: theme.colors.primary,
            backgroundColor: showTable ? theme.colors.primarySoft : "transparent",
          },
        ]}
        testID={`${testID}-btn-toggle-table`}
      >
        <Text style={[styles.buttonText, { color: theme.colors.primary }]}>
          {showTable ? "Hide Forces Table" : "View Forces Table"}
        </Text>
      </Pressable>

      {/* Accessible Data Table */}
      {showTable ? (
        <View
          style={[
            styles.tableContainer,
            { backgroundColor: theme.colors.surface, borderColor: theme.colors.border },
          ]}
          testID={`${testID}-table-alternative`}
        >
          <Text style={[styles.tableHeading, { color: theme.colors.text }]}>
            Forces Breakdown Table
          </Text>

          {/* Table Header */}
          <View style={[styles.tableRow, { borderBottomColor: theme.colors.border }]}>
            {descriptor.tableData.headers.map((h, i) => (
              <Text
                key={`th-${i}`}
                style={[styles.tableCellHeader, { color: theme.colors.text }]}
              >
                {h}
              </Text>
            ))}
          </View>

          {/* Table Rows */}
          {descriptor.tableData.rows.map((row, rIdx) => (
            <View
              key={`tr-${rIdx}`}
              style={[styles.tableRow, { borderBottomColor: theme.colors.border }]}
            >
              {row.map((cell, cIdx) => (
                <Text
                  key={`td-${rIdx}-${cIdx}`}
                  style={[styles.tableCell, { color: theme.colors.mutedText }]}
                >
                  {String(cell)}
                </Text>
              ))}
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    paddingVertical: 8,
  },
  canvas: {
    position: "relative",
    borderWidth: 1,
    borderRadius: 12,
    overflow: "hidden",
  },
  axisLine: {
    position: "absolute",
  },
  centerBox: {
    position: "absolute",
    borderWidth: 1.5,
    borderRadius: 4,
    alignItems: "center",
    justifyContent: "center",
    zIndex: 2,
  },
  centerBoxText: {
    fontSize: 10,
    fontWeight: "700",
  },
  vectorLine: {
    position: "absolute",
    zIndex: 3,
  },
  arrowHeadContainer: {
    position: "absolute",
    width: 16,
    height: 16,
    alignItems: "center",
    justifyContent: "center",
    zIndex: 4,
  },
  arrowBarb: {
    position: "absolute",
    width: 8,
    height: 2,
    borderRadius: 1,
    left: 4,
    top: 7,
  },
  vectorLabel: {
    position: "absolute",
    fontSize: 9,
    fontWeight: "600",
    width: 70,
    textAlign: "center",
    zIndex: 5,
  },
  resultantBadge: {
    position: "absolute",
    top: 6,
    right: 6,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderWidth: 1,
    borderRadius: 6,
    zIndex: 10,
  },
  resultantText: {
    fontSize: 10,
    fontWeight: "700",
  },
  statusText: {
    fontSize: 12,
    marginTop: 6,
    textAlign: "center",
    paddingHorizontal: 12,
    lineHeight: 16,
  },
  toggleButton: {
    marginTop: 8,
    minHeight: 44,
    minWidth: 44,
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderWidth: 1,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonText: {
    fontSize: 11,
    fontWeight: "600",
  },
  tableContainer: {
    width: "100%",
    marginTop: 10,
    padding: 10,
    borderWidth: 1,
    borderRadius: 8,
  },
  tableHeading: {
    fontSize: 13,
    fontWeight: "700",
    marginBottom: 6,
  },
  tableRow: {
    flexDirection: "row",
    borderBottomWidth: 1,
    paddingVertical: 4,
  },
  tableCellHeader: {
    flex: 1,
    fontSize: 10,
    fontWeight: "700",
  },
  tableCell: {
    flex: 1,
    fontSize: 10,
  },
});
