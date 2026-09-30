import type { ThemeColors, ThemeTokens } from "../../theme";
import type { AdaptiveSubject, AdaptiveTopic } from "../quiz/adaptiveQuiz";

/**
 * Valid theme color token keys from Studio theme palette.
 */
export type StudioThemeColorKey = keyof ThemeColors;

/**
 * 3D point in model coordinates.
 * Convention:
 *  +X: right
 *  +Y: up
 *  +Z: forward (out of screen towards viewer in model space)
 */
export type Point3D = {
  x: number;
  y: number;
  z: number;
};

/**
 * Projected 2D point on viewport.
 * zDepth: transformed camera-space depth where larger positive depth = farther away.
 */
export type ProjectedPoint2D = {
  x: number;
  y: number;
  zDepth: number;
  scale: number;
  visible: boolean;
};

/**
 * 3D vertex representing an atom, apex, corner, or joint.
 */
export type Vertex3D = {
  id: string;
  x: number;
  y: number;
  z: number;
  radius?: number;
  colorToken: StudioThemeColorKey;
  label?: string;
};

/**
 * 3D edge representing a bond, edge, or vector ray between two vertices.
 */
export type Edge3D = {
  id: string;
  from: string;
  to: string;
  thickness?: number;
  colorToken: StudioThemeColorKey;
  style?: "solid" | "dashed";
};

/**
 * Camera configuration for 3D perspective projection.
 */
export type CameraConfig = {
  initialYawDeg: number;
  initialPitchDeg: number;
  minPitchDeg: number;
  maxPitchDeg: number;
  initialZoom: number;
  minZoom: number;
  maxZoom: number;
  distance: number;
  focalLength: number;
  nearClip: number;
};

/**
 * Renderable 3D primitive sorted for Painter's algorithm.
 * Larger depth = farther away => rendered first (descending depth sort order).
 */
export type RenderPrimitive3D =
  | {
      kind: "vertex";
      id: string;
      depth: number;
      projected: ProjectedPoint2D;
      vertex: Vertex3D;
    }
  | {
      kind: "edge";
      id: string;
      depth: number;
      fromProjected: ProjectedPoint2D;
      toProjected: ProjectedPoint2D;
      edge: Edge3D;
      length: number;
      midpointX: number;
      midpointY: number;
      angleRad: number;
    };

/**
 * Structured tabular alternative for screen readers and reduced-motion modes.
 */
export type VisualTableData = {
  headers: string[];
  rows: Array<Array<string | number>>;
};

/**
 * Declarative 3D scene descriptor.
 */
export type Scene3DDescriptor = {
  type: "scene_3d";
  subject: AdaptiveSubject;
  topicId: AdaptiveTopic;
  title: string;
  description: string;
  educationalSummary: string;
  camera: CameraConfig;
  vertices: Vertex3D[];
  edges: Edge3D[];
  tableData: VisualTableData;
};

/**
 * 2D Vector representation for physics diagrams.
 */
export type Vector2D = {
  id: string;
  label: string;
  magnitude: number;
  angleDeg: number; // 0 = right, 90 = up, 180 = left, 270 = down
  colorToken: StudioThemeColorKey;
  xComp: number;
  yComp: number;
};

/**
 * Declarative 2D visualization descriptor.
 */
export type Visualization2DDescriptor = {
  type: "visualization_2d";
  subject: AdaptiveSubject;
  topicId: AdaptiveTopic;
  title: string;
  description: string;
  educationalSummary: string;
  origin: { x: number; y: number };
  scale: number;
  vectors: Vector2D[];
  resultant?: {
    magnitude: number;
    angleDeg: number;
    colorToken: StudioThemeColorKey;
    label: string;
  };
  tableData: VisualTableData;
};

export type LearningVisualDescriptor =
  | Scene3DDescriptor
  | Visualization2DDescriptor;

/**
 * Opt-in VisualLearningCard component props.
 * Strictly requires isRevealed=true to display visual learning content.
 */
export type VisualLearningCardProps = {
  subject: string;
  topic: string;
  isRevealed: boolean;
  theme?: ThemeTokens;
  testID?: string;
};
