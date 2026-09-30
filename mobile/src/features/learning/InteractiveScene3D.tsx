import { useMemo, useRef, useState } from "react";
import {
  PanResponder,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { ThemeTokens } from "../../theme";
import { buildRenderPrimitives, calculateDragRotation, clamp, normalizeAngleDeg } from "./math3d";
import type { Scene3DDescriptor } from "./types";

export type InteractiveScene3DProps = {
  descriptor: Scene3DDescriptor;
  theme: ThemeTokens;
  testID?: string;
};

const VIEWPORT_WIDTH = 260;
const VIEWPORT_HEIGHT = 200;

export function InteractiveScene3D({
  descriptor,
  theme,
  testID = "interactive-scene-3d",
}: InteractiveScene3DProps) {
  const [yaw, setYaw] = useState(descriptor.camera.initialYawDeg);
  const [pitch, setPitch] = useState(descriptor.camera.initialPitchDeg);
  const [zoom, setZoom] = useState(descriptor.camera.initialZoom);
  const [showTable, setShowTable] = useState(false);

  // Keep live refs for PanResponder to prevent stale closures
  const stateRef = useRef({ yaw, pitch, zoom });
  stateRef.current = { yaw, pitch, zoom };
  const dragOriginRef = useRef({ yaw, pitch });

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: () => {
          dragOriginRef.current = {
            yaw: stateRef.current.yaw,
            pitch: stateRef.current.pitch,
          };
        },
        onPanResponderMove: (_evt, gestureState) => {
          const next = calculateDragRotation(
            dragOriginRef.current.yaw,
            dragOriginRef.current.pitch,
            gestureState.dx,
            gestureState.dy,
            descriptor.camera.minPitchDeg,
            descriptor.camera.maxPitchDeg,
          );
          setYaw(next.yaw);
          setPitch(next.pitch);
        },
      }),
    [descriptor.camera.minPitchDeg, descriptor.camera.maxPitchDeg],
  );

  const primitives = useMemo(
    () =>
      buildRenderPrimitives(
        descriptor.vertices,
        descriptor.edges,
        yaw,
        pitch,
        zoom,
        descriptor.camera,
        VIEWPORT_WIDTH,
        VIEWPORT_HEIGHT,
      ),
    [descriptor.vertices, descriptor.edges, descriptor.camera, yaw, pitch, zoom],
  );

  const handleRotateLeft = () => setYaw((prev) => normalizeAngleDeg(prev - 15));
  const handleRotateRight = () => setYaw((prev) => normalizeAngleDeg(prev + 15));
  const handleRotateUp = () =>
    setPitch((prev) =>
      clamp(prev + 15, descriptor.camera.minPitchDeg, descriptor.camera.maxPitchDeg),
    );
  const handleRotateDown = () =>
    setPitch((prev) =>
      clamp(prev - 15, descriptor.camera.minPitchDeg, descriptor.camera.maxPitchDeg),
    );
  const handleZoomIn = () =>
    setZoom((prev) =>
      clamp(prev + 0.2, descriptor.camera.minZoom, descriptor.camera.maxZoom),
    );
  const handleZoomOut = () =>
    setZoom((prev) =>
      clamp(prev - 0.2, descriptor.camera.minZoom, descriptor.camera.maxZoom),
    );
  const handleReset = () => {
    setYaw(descriptor.camera.initialYawDeg);
    setPitch(descriptor.camera.initialPitchDeg);
    setZoom(descriptor.camera.initialZoom);
  };

  const statusAnnouncement = `3D view: ${descriptor.title}. Yaw: ${Math.round(
    yaw,
  )} degrees, Pitch: ${Math.round(pitch)} degrees, Zoom: ${zoom.toFixed(1)}x.`;

  return (
    <View style={styles.container} testID={testID}>
      {/* 3D Canvas Container */}
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
        {...panResponder.panHandlers}
        accessibilityLabel="Interactive 3D geometry canvas. Drag to rotate model."
        accessibilityRole="image"
        testID={`${testID}-canvas`}
      >
        {/* Render depth-sorted primitives (descending depth = far-to-near Painter order) */}
        {primitives.map((prim) => {
          if (prim.kind === "vertex") {
            const r = (prim.vertex.radius ?? 8) * prim.projected.scale;
            const radius = Math.max(3, Math.min(16, r));
            const color = theme.colors[prim.vertex.colorToken];

            return (
              <View
                key={`vertex-${prim.id}`}
                style={[
                  styles.vertex,
                  {
                    left: prim.projected.x - radius,
                    top: prim.projected.y - radius,
                    width: radius * 2,
                    height: radius * 2,
                    borderRadius: radius,
                    backgroundColor: color,
                  },
                ]}
                testID={`${testID}-vertex-${prim.id}`}
              >
                {prim.vertex.label ? (
                  <Text
                    style={[
                      styles.vertexLabel,
                      { color: theme.colors.text, bottom: radius + 2 },
                    ]}
                  >
                    {prim.vertex.label}
                  </Text>
                ) : null}
              </View>
            );
          }

          if (prim.kind === "edge") {
            const thickness = prim.edge.thickness ?? 2;
            const color = theme.colors[prim.edge.colorToken];

            return (
              <View
                key={`edge-${prim.id}`}
                style={[
                  styles.edge,
                  {
                    left: prim.midpointX - prim.length / 2,
                    top: prim.midpointY - thickness / 2,
                    width: prim.length,
                    height: thickness,
                    backgroundColor: color,
                    transform: [{ rotate: `${prim.angleRad}rad` }],
                  },
                ]}
                testID={`${testID}-edge-${prim.id}`}
              />
            );
          }

          return null;
        })}
      </View>

      {/* Screen-reader accessible status text */}
      <Text
        style={[styles.statusText, { color: theme.colors.mutedText }]}
        accessibilityLiveRegion="polite"
      >
        {statusAnnouncement}
      </Text>

      {/* Accessible Stepper Controls */}
      <View style={styles.controlsRow}>
        <Pressable
          accessibilityLabel="Rotate Left"
          accessibilityRole="button"
          onPress={handleRotateLeft}
          style={[styles.stepperButton, { borderColor: theme.colors.border }]}
          testID={`${testID}-btn-left`}
        >
          <Text style={[styles.buttonText, { color: theme.colors.text }]}>◀ Left</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Rotate Right"
          accessibilityRole="button"
          onPress={handleRotateRight}
          style={[styles.stepperButton, { borderColor: theme.colors.border }]}
          testID={`${testID}-btn-right`}
        >
          <Text style={[styles.buttonText, { color: theme.colors.text }]}>Right ▶</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Rotate Up"
          accessibilityRole="button"
          onPress={handleRotateUp}
          style={[styles.stepperButton, { borderColor: theme.colors.border }]}
          testID={`${testID}-btn-up`}
        >
          <Text style={[styles.buttonText, { color: theme.colors.text }]}>▲ Up</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Rotate Down"
          accessibilityRole="button"
          onPress={handleRotateDown}
          style={[styles.stepperButton, { borderColor: theme.colors.border }]}
          testID={`${testID}-btn-down`}
        >
          <Text style={[styles.buttonText, { color: theme.colors.text }]}>▼ Down</Text>
        </Pressable>
      </View>

      <View style={styles.controlsRow}>
        <Pressable
          accessibilityLabel="Zoom In"
          accessibilityRole="button"
          onPress={handleZoomIn}
          style={[styles.stepperButton, { borderColor: theme.colors.border }]}
          testID={`${testID}-btn-zoom-in`}
        >
          <Text style={[styles.buttonText, { color: theme.colors.text }]}>Zoom +</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Zoom Out"
          accessibilityRole="button"
          onPress={handleZoomOut}
          style={[styles.stepperButton, { borderColor: theme.colors.border }]}
          testID={`${testID}-btn-zoom-out`}
        >
          <Text style={[styles.buttonText, { color: theme.colors.text }]}>Zoom -</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Reset View"
          accessibilityRole="button"
          onPress={handleReset}
          style={[styles.stepperButton, { borderColor: theme.colors.border }]}
          testID={`${testID}-btn-reset`}
        >
          <Text style={[styles.buttonText, { color: theme.colors.text }]}>Reset</Text>
        </Pressable>
        <Pressable
          accessibilityLabel={showTable ? "Hide data table" : "Show data table"}
          accessibilityRole="button"
          onPress={() => setShowTable((prev) => !prev)}
          style={[
            styles.stepperButton,
            {
              borderColor: theme.colors.primary,
              backgroundColor: showTable ? theme.colors.primarySoft : "transparent",
            },
          ]}
          testID={`${testID}-btn-toggle-table`}
        >
          <Text style={[styles.buttonText, { color: theme.colors.primary }]}>
            {showTable ? "Hide Table" : "Data Table"}
          </Text>
        </Pressable>
      </View>

      {/* Accessible Text / Table Alternative */}
      {showTable ? (
        <View
          style={[
            styles.tableContainer,
            { backgroundColor: theme.colors.surface, borderColor: theme.colors.border },
          ]}
          testID={`${testID}-table-alternative`}
        >
          <Text style={[styles.tableHeading, { color: theme.colors.text }]}>
            Accessible Structural Table
          </Text>
          <Text style={[styles.tableSummary, { color: theme.colors.mutedText }]}>
            {descriptor.educationalSummary}
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
  vertex: {
    position: "absolute",
    alignItems: "center",
    justifyContent: "center",
  },
  vertexLabel: {
    position: "absolute",
    fontSize: 10,
    fontWeight: "600",
  },
  edge: {
    position: "absolute",
  },
  statusText: {
    fontSize: 12,
    marginTop: 6,
    textAlign: "center",
  },
  controlsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: 8,
    marginTop: 8,
  },
  stepperButton: {
    minHeight: 44,
    minWidth: 44,
    paddingVertical: 10,
    paddingHorizontal: 12,
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
    marginBottom: 4,
  },
  tableSummary: {
    fontSize: 12,
    marginBottom: 8,
    lineHeight: 16,
  },
  tableRow: {
    flexDirection: "row",
    borderBottomWidth: 1,
    paddingVertical: 4,
  },
  tableCellHeader: {
    flex: 1,
    fontSize: 11,
    fontWeight: "700",
  },
  tableCell: {
    flex: 1,
    fontSize: 11,
  },
});
