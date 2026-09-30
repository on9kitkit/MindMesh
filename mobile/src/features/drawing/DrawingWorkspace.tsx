import { useMemo, useState } from "react";
import {
  PanResponder,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type LayoutChangeEvent,
} from "react-native";
import Svg, {
  Circle,
  G,
  Line,
  Path,
  Rect,
  Text as SvgText,
} from "react-native-svg";

import { useStudioTheme } from "../../appearance/StudioThemeContext";
import { studioLightTheme, type ThemeTokens } from "../../theme";
import {
  angleBetweenPoints,
  distanceBetweenPoints,
  strokePath,
  toDrawingPoint,
} from "./model";
import {
  DRAWING_LIMITS,
  DRAWING_UNITS,
  type DrawingAction,
  type DrawingDocument,
  type DrawingInk,
  type DrawingPoint,
  type DrawingTool,
} from "./types";

export type DrawingWorkspaceProps = {
  document: DrawingDocument;
  dispatch: (action: DrawingAction) => void;
  editable: boolean;
  onClose?: () => void;
  theme?: ThemeTokens;
  initialTool?: DrawingTool;
  testID?: string;
};

const INK_OPTIONS: ReadonlyArray<{ ink: DrawingInk; label: string }> = [
  { ink: "ink", label: "Default text" },
  { ink: "primary", label: "Primary accent" },
  { ink: "success", label: "Success green" },
  { ink: "error", label: "Error red" },
];

const TOOL_OPTIONS: ReadonlyArray<{ tool: DrawingTool; label: string }> = [
  { tool: "pen", label: "Pen" },
  { tool: "ruler", label: "Ruler" },
  { tool: "protractor", label: "Protractor" },
  { tool: "eraser", label: "Eraser" },
];

export function resolveInkColor(ink: DrawingInk, theme: ThemeTokens): string {
  switch (ink) {
    case "ink":
      return theme.colors.text;
    case "primary":
      return theme.colors.primary;
    case "success":
      return theme.colors.success;
    case "error":
      return theme.colors.error;
    default:
      return theme.colors.text;
  }
}

export function DrawingWorkspace({
  document,
  dispatch,
  editable,
  onClose,
  theme: explicitTheme,
  initialTool = "pen",
  testID = "drawing-workspace",
}: DrawingWorkspaceProps) {
  let contextTheme: ThemeTokens | undefined;
  try {
    contextTheme = useStudioTheme();
  } catch {
    // Graceful fallback for isolated test environments outside provider
    contextTheme = undefined;
  }
  const theme = explicitTheme ?? contextTheme ?? studioLightTheme;

  const [tool, setTool] = useState<DrawingTool>(initialTool);
  const [selectedInk, setSelectedInk] = useState<DrawingInk>("ink");
  const [canvasSize, setCanvasSize] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0,
  });

  // Protractor state: center position and rotation angle in drawing units/degrees
  const [protractorCenter, setProtractorCenter] = useState<DrawingPoint>({
    x: DRAWING_UNITS / 2,
    y: DRAWING_UNITS / 2,
  });
  const [protractorAngleDeg, setProtractorAngleDeg] = useState<number>(0);

  const handleLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    if (width > 0 && height > 0) {
      setCanvasSize({ width, height });
    }
  };

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => editable,
        onMoveShouldSetPanResponder: () => editable,
        onPanResponderGrant: (evt) => {
          if (!editable) return;
          const { locationX, locationY } = evt.nativeEvent;
          const pt = toDrawingPoint(
            locationX,
            locationY,
            canvasSize.width,
            canvasSize.height,
          );
          if (!pt) return;

          if (tool === "pen") {
            dispatch({
              type: "BEGIN",
              point: pt,
              ink: selectedInk,
              kind: "freehand",
            });
          } else if (tool === "ruler") {
            dispatch({
              type: "BEGIN",
              point: pt,
              ink: selectedInk,
              kind: "straight",
            });
          } else if (tool === "eraser") {
            dispatch({ type: "ERASE_AT", point: pt });
          } else if (tool === "protractor") {
            // Drag protractor center without drawing ink
            setProtractorCenter(pt);
          }
        },
        onPanResponderMove: (evt) => {
          if (!editable) return;
          const { locationX, locationY } = evt.nativeEvent;
          const pt = toDrawingPoint(
            locationX,
            locationY,
            canvasSize.width,
            canvasSize.height,
          );
          if (!pt) return;

          if (tool === "pen" || tool === "ruler") {
            dispatch({ type: "EXTEND", point: pt });
          } else if (tool === "eraser") {
            dispatch({ type: "ERASE_AT", point: pt });
          } else if (tool === "protractor") {
            setProtractorCenter(pt);
          }
        },
        onPanResponderRelease: (evt) => {
          if (!editable) return;
          const { locationX, locationY } = evt.nativeEvent;
          const pt = toDrawingPoint(
            locationX,
            locationY,
            canvasSize.width,
            canvasSize.height,
          );

          if (tool === "pen" || tool === "ruler") {
            dispatch({ type: "END", point: pt ?? undefined });
          }
        },
        onPanResponderTerminate: () => {
          if (!editable) return;
          if (tool === "pen" || tool === "ruler") {
            dispatch({ type: "CANCEL" });
          }
        },
      }),
    [canvasSize.height, canvasSize.width, dispatch, editable, selectedInk, tool],
  );

  // Ruler measurement readout when ruler tool is actively drawing a straight line
  const rulerMeasurement = useMemo(() => {
    if (
      tool !== "ruler" ||
      !document.active ||
      document.active.kind !== "straight" ||
      document.active.points.length < 2
    ) {
      return null;
    }
    const p0 = document.active.points[0];
    const p1 = document.active.points[document.active.points.length - 1];
    const distance = Math.round(distanceBetweenPoints(p0, p1));
    const angle = Math.round(angleBetweenPoints(p0, p1));
    return {
      distance,
      angle,
      endX: p1.x,
      endY: p1.y,
    };
  }, [document.active, tool]);

  // Protractor SVG geometry
  const protractorGeometry = useMemo(() => {
    if (tool !== "protractor") return null;
    const radius = 240;
    const cx = protractorCenter.x;
    const cy = protractorCenter.y;
    const rotRad = (protractorAngleDeg * Math.PI) / 180;

    // Baseline endpoints (left to right along diameter)
    const baseLeftX = cx - radius * Math.cos(rotRad);
    const baseLeftY = cy - radius * Math.sin(rotRad);
    const baseRightX = cx + radius * Math.cos(rotRad);
    const baseRightY = cy + radius * Math.sin(rotRad);

    // 180-degree semi-circle arc (upper half relative to rotation)
    const arcPath = `M ${baseLeftX.toFixed(1)} ${baseLeftY.toFixed(1)} A ${radius} ${radius} 0 0 1 ${baseRightX.toFixed(1)} ${baseRightY.toFixed(1)} Z`;

    // Ticks at major degree angles (0 to 180 in 15-degree steps)
    const ticks: Array<{ x1: number; y1: number; x2: number; y2: number; deg: number }> = [];
    for (let d = 0; d <= 180; d += 15) {
      const tickAngleRad = ((protractorAngleDeg + 180 - d) * Math.PI) / 180;
      const isMajor = d % 45 === 0;
      const tickLength = isMajor ? 20 : 10;
      const x1 = cx + radius * Math.cos(tickAngleRad);
      const y1 = cy + radius * Math.sin(tickAngleRad);
      const x2 = cx + (radius - tickLength) * Math.cos(tickAngleRad);
      const y2 = cy + (radius - tickLength) * Math.sin(tickAngleRad);
      ticks.push({ x1, y1, x2, y2, deg: d });
    }

    return { cx, cy, radius, arcPath, ticks };
  }, [protractorAngleDeg, protractorCenter.x, protractorCenter.y, tool]);

  return (
    <View
      style={[styles.container, { backgroundColor: theme.colors.surface }]}
      testID={testID}
    >
      {/* Top Header Row */}
      <View style={[styles.headerRow, { borderBottomColor: theme.colors.border }]}>
        <View style={styles.headerInfo}>
          <Text style={[styles.title, { color: theme.colors.text }]}>
            Maths Scratchpad
          </Text>
          <Text style={[styles.strokeCount, { color: theme.colors.mutedText }]}>
            {document.strokes.length} / {DRAWING_LIMITS.maxStrokes} strokes
          </Text>
        </View>

        {onClose ? (
          <Pressable
            accessibilityLabel="Return to answer and close drawing workspace"
            accessibilityRole="button"
            onPress={onClose}
            style={[
              styles.closeButton,
              {
                backgroundColor: theme.colors.surfaceElevated,
                borderColor: theme.colors.border,
              },
            ]}
            testID={`${testID}-close`}
          >
            <Text style={[styles.closeButtonText, { color: theme.colors.text }]}>
              Return to answer
            </Text>
          </Pressable>
        ) : null}
      </View>

      {/* Read-Only Status Banner */}
      {!editable ? (
        <View
          style={[
            styles.statusBanner,
            { backgroundColor: theme.colors.surfaceElevated },
          ]}
          testID={`${testID}-read-only-banner`}
        >
          <Text style={[styles.statusBannerText, { color: theme.colors.mutedText }]}>
            Viewing saved working (read-only)
          </Text>
        </View>
      ) : null}

      {/* Limit Reached Warning Banner */}
      {document.limitReached ? (
        <View
          accessibilityRole="alert"
          style={[
            styles.statusBanner,
            { backgroundColor: theme.colors.errorBackground },
          ]}
          testID={`${testID}-limit-banner`}
        >
          <Text style={[styles.statusBannerText, { color: theme.colors.error }]}>
            Drawing limit reached. Delete strokes or clear to continue.
          </Text>
        </View>
      ) : null}

      {/* Interactive Themed Drawing Canvas */}
      <View style={styles.canvasWrapper}>
        <View
          style={[
            styles.canvasContainer,
            {
              backgroundColor: theme.colors.surfaceElevated,
              borderColor: theme.colors.border,
            },
          ]}
          onLayout={handleLayout}
          {...panResponder.panHandlers}
          accessibilityLabel="Drawing canvas. Use touch gestures to draw or erase working notes."
          accessibilityRole="image"
          testID={`${testID}-canvas`}
        >
          <Svg
            viewBox={`0 0 ${DRAWING_UNITS} ${DRAWING_UNITS}`}
            style={styles.svgCanvas}
          >
            {/* Background touch target grid */}
            <Rect
              width={DRAWING_UNITS}
              height={DRAWING_UNITS}
              fill="transparent"
            />

            {/* Committed Strokes */}
            {document.strokes.map((stroke) => (
              <Path
                key={stroke.id}
                d={strokePath(stroke)}
                stroke={resolveInkColor(stroke.ink, theme)}
                strokeWidth={stroke.kind === "straight" ? 4 : 3}
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            ))}

            {/* Active Drawing Stroke */}
            {document.active ? (
              <Path
                d={strokePath(document.active)}
                stroke={resolveInkColor(document.active.ink, theme)}
                strokeWidth={document.active.kind === "straight" ? 4 : 3}
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            ) : null}

            {/* Ruler Straightedge Active Measurement Guide */}
            {rulerMeasurement ? (
              <G>
                <Circle
                  cx={rulerMeasurement.endX}
                  cy={rulerMeasurement.endY}
                  r={8}
                  fill={theme.colors.primary}
                />
                <SvgText
                  x={Math.min(DRAWING_UNITS - 120, Math.max(20, rulerMeasurement.endX + 15))}
                  y={Math.min(DRAWING_UNITS - 20, Math.max(30, rulerMeasurement.endY - 15))}
                  fill={theme.colors.text}
                  fontSize="28"
                  fontWeight="bold"
                >
                  {`${rulerMeasurement.distance} units (${rulerMeasurement.angle}°)`}
                </SvgText>
              </G>
            ) : null}

            {/* Protractor Tool Visual Overlay */}
            {protractorGeometry ? (
              <G testID={`${testID}-protractor-overlay`}>
                <Path
                  d={protractorGeometry.arcPath}
                  fill={theme.colors.surface}
                  fillOpacity={0.7}
                  stroke={theme.colors.primary}
                  strokeWidth={3}
                />
                <Circle
                  cx={protractorGeometry.cx}
                  cy={protractorGeometry.cy}
                  r={6}
                  fill={theme.colors.primary}
                />
                {protractorGeometry.ticks.map((t, idx) => (
                  <Line
                    key={idx}
                    x1={t.x1}
                    y1={t.y1}
                    x2={t.x2}
                    y2={t.y2}
                    stroke={theme.colors.text}
                    strokeWidth={t.deg % 45 === 0 ? 2.5 : 1.5}
                  />
                ))}
                <SvgText
                  x={protractorGeometry.cx}
                  y={protractorGeometry.cy - 30}
                  textAnchor="middle"
                  fill={theme.colors.text}
                  fontSize="24"
                  fontWeight="600"
                >
                  {`${protractorAngleDeg}° Protractor`}
                </SvgText>
              </G>
            ) : null}
          </Svg>
        </View>
      </View>

      {/* Accessible Controls Panel */}
      <ScrollView
        contentContainerStyle={styles.controlsScroll}
        style={styles.controlsContainer}
        horizontal={false}
      >
        {/* Tool Selectors */}
        <View style={styles.controlSection}>
          <Text style={[styles.sectionLabel, { color: theme.colors.mutedText }]}>
            Tools
          </Text>
          <View style={styles.buttonRow}>
            {TOOL_OPTIONS.map((opt) => {
              const active = tool === opt.tool;
              return (
                <Pressable
                  key={opt.tool}
                  accessibilityLabel={`Tool: ${opt.label}`}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active, disabled: !editable }}
                  disabled={!editable}
                  onPress={() => setTool(opt.tool)}
                  style={[
                    styles.controlButton,
                    {
                      backgroundColor: active
                        ? theme.colors.primary
                        : theme.colors.surfaceElevated,
                      borderColor: active
                        ? theme.colors.primary
                        : theme.colors.border,
                      opacity: editable ? 1 : 0.5,
                    },
                  ]}
                  testID={`${testID}-tool-${opt.tool}`}
                >
                  <Text
                    style={[
                      styles.controlButtonText,
                      {
                        color: active
                          ? theme.colors.onPrimary
                          : theme.colors.text,
                      },
                    ]}
                  >
                    {opt.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        {/* Ink Colors (Active for Pen and Ruler) */}
        {tool === "pen" || tool === "ruler" ? (
          <View style={styles.controlSection}>
            <Text style={[styles.sectionLabel, { color: theme.colors.mutedText }]}>
              Ink Colour
            </Text>
            <View style={styles.buttonRow}>
              {INK_OPTIONS.map((opt) => {
                const active = selectedInk === opt.ink;
                const inkColor = resolveInkColor(opt.ink, theme);
                return (
                  <Pressable
                    key={opt.ink}
                    accessibilityLabel={`Ink colour: ${opt.label}`}
                    accessibilityRole="button"
                    accessibilityState={{ selected: active, disabled: !editable }}
                    disabled={!editable}
                    onPress={() => setSelectedInk(opt.ink)}
                    style={[
                      styles.controlButton,
                      styles.inkButton,
                      {
                        backgroundColor: theme.colors.surfaceElevated,
                        borderColor: active
                          ? theme.colors.primary
                          : theme.colors.border,
                        borderWidth: active ? 2.5 : 1,
                        opacity: editable ? 1 : 0.5,
                      },
                    ]}
                    testID={`${testID}-ink-${opt.ink}`}
                  >
                    <View
                      style={[styles.colorSwatch, { backgroundColor: inkColor }]}
                    />
                    <Text
                      style={[
                        styles.controlButtonText,
                        { color: theme.colors.text },
                      ]}
                    >
                      {opt.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        ) : null}

        {/* Protractor Rotation Controls */}
        {tool === "protractor" ? (
          <View style={styles.controlSection}>
            <Text style={[styles.sectionLabel, { color: theme.colors.mutedText }]}>
              Protractor Angle ({protractorAngleDeg}°)
            </Text>
            <View style={styles.buttonRow}>
              <Pressable
                accessibilityLabel="Rotate protractor counter-clockwise by 15 degrees"
                accessibilityRole="button"
                onPress={() =>
                  setProtractorAngleDeg((prev) => (prev - 15 + 360) % 360)
                }
                style={[
                  styles.controlButton,
                  {
                    backgroundColor: theme.colors.surfaceElevated,
                    borderColor: theme.colors.border,
                  },
                ]}
                testID={`${testID}-protractor-rotate-ccw`}
              >
                <Text style={[styles.controlButtonText, { color: theme.colors.text }]}>
                  -15°
                </Text>
              </Pressable>
              <Pressable
                accessibilityLabel="Rotate protractor clockwise by 15 degrees"
                accessibilityRole="button"
                onPress={() =>
                  setProtractorAngleDeg((prev) => (prev + 15) % 360)
                }
                style={[
                  styles.controlButton,
                  {
                    backgroundColor: theme.colors.surfaceElevated,
                    borderColor: theme.colors.border,
                  },
                ]}
                testID={`${testID}-protractor-rotate-cw`}
              >
                <Text style={[styles.controlButtonText, { color: theme.colors.text }]}>
                  +15°
                </Text>
              </Pressable>
              <Pressable
                accessibilityLabel="Reset protractor angle to 0 degrees"
                accessibilityRole="button"
                onPress={() => setProtractorAngleDeg(0)}
                style={[
                  styles.controlButton,
                  {
                    backgroundColor: theme.colors.surfaceElevated,
                    borderColor: theme.colors.border,
                  },
                ]}
                testID={`${testID}-protractor-reset`}
              >
                <Text style={[styles.controlButtonText, { color: theme.colors.text }]}>
                  Reset 0°
                </Text>
              </Pressable>
            </View>
          </View>
        ) : null}

        {/* History Actions */}
        <View style={styles.controlSection}>
          <Text style={[styles.sectionLabel, { color: theme.colors.mutedText }]}>
            Actions
          </Text>
          <View style={styles.buttonRow}>
            <Pressable
              accessibilityLabel="Undo last stroke"
              accessibilityRole="button"
              accessibilityState={{
                disabled: !editable || document.past.length === 0,
              }}
              disabled={!editable || document.past.length === 0}
              onPress={() => dispatch({ type: "UNDO" })}
              style={[
                styles.controlButton,
                {
                  backgroundColor: theme.colors.surfaceElevated,
                  borderColor: theme.colors.border,
                  opacity: editable && document.past.length > 0 ? 1 : 0.4,
                },
              ]}
              testID={`${testID}-action-undo`}
            >
              <Text style={[styles.controlButtonText, { color: theme.colors.text }]}>
                Undo
              </Text>
            </Pressable>
            <Pressable
              accessibilityLabel="Redo last undone stroke"
              accessibilityRole="button"
              accessibilityState={{
                disabled: !editable || document.future.length === 0,
              }}
              disabled={!editable || document.future.length === 0}
              onPress={() => dispatch({ type: "REDO" })}
              style={[
                styles.controlButton,
                {
                  backgroundColor: theme.colors.surfaceElevated,
                  borderColor: theme.colors.border,
                  opacity: editable && document.future.length > 0 ? 1 : 0.4,
                },
              ]}
              testID={`${testID}-action-redo`}
            >
              <Text style={[styles.controlButtonText, { color: theme.colors.text }]}>
                Redo
              </Text>
            </Pressable>
            <Pressable
              accessibilityLabel="Clear all strokes"
              accessibilityRole="button"
              accessibilityState={{
                disabled: !editable || document.strokes.length === 0,
              }}
              disabled={!editable || document.strokes.length === 0}
              onPress={() => dispatch({ type: "CLEAR" })}
              style={[
                styles.controlButton,
                {
                  backgroundColor: theme.colors.surfaceElevated,
                  borderColor: theme.colors.error,
                  opacity: editable && document.strokes.length > 0 ? 1 : 0.4,
                },
              ]}
              testID={`${testID}-action-clear`}
            >
              <Text style={[styles.controlButtonText, { color: theme.colors.error }]}>
                Clear
              </Text>
            </Pressable>
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    flexDirection: "column",
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  headerInfo: {
    flexDirection: "column",
  },
  title: {
    fontSize: 18,
    fontWeight: "700",
  },
  strokeCount: {
    fontSize: 12,
    marginTop: 2,
  },
  closeButton: {
    minHeight: 44,
    minWidth: 72,
    paddingHorizontal: 14,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    borderWidth: 1,
  },
  closeButtonText: {
    fontSize: 14,
    fontWeight: "600",
  },
  statusBanner: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  statusBannerText: {
    fontSize: 13,
    fontWeight: "600",
    textAlign: "center",
  },
  canvasWrapper: {
    alignItems: "center",
    justifyContent: "center",
    padding: 12,
  },
  canvasContainer: {
    width: "100%",
    maxWidth: 420,
    aspectRatio: 1,
    borderRadius: 16,
    borderWidth: 1.5,
    overflow: "hidden",
  },
  svgCanvas: {
    width: "100%",
    height: "100%",
  },
  controlsContainer: {
    flex: 1,
  },
  controlsScroll: {
    paddingHorizontal: 16,
    paddingBottom: 24,
  },
  controlSection: {
    marginTop: 12,
  },
  sectionLabel: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: 6,
  },
  buttonRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  controlButton: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 6,
  },
  controlButtonText: {
    fontSize: 13,
    fontWeight: "600",
  },
  inkButton: {
    minWidth: 80,
  },
  colorSwatch: {
    width: 14,
    height: 14,
    borderRadius: 7,
  },
});
