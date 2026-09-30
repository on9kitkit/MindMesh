import type {
  LearningVisualDescriptor,
  Scene3DDescriptor,
  Visualization2DDescriptor,
} from "./types";

/**
 * 3D Square-Based Pyramid for Mathematics / Geometry.
 * Models a classic geometric solid with 5 vertices, 8 edges, and square base.
 */
export const GEOMETRY_PYRAMID_3D: Scene3DDescriptor = {
  type: "scene_3d",
  subject: "mathematics",
  topicId: "geometry",
  title: "Square-Based Pyramid",
  description: "3D wireframe solid with a square horizontal base and four triangular faces meeting at the apex.",
  educationalSummary:
    "Right square-based pyramid: base side = 80 units, vertical height = 80 units. Drag to rotate yaw and pitch to inspect 3D perspective foreshortening, base corners, and slant edges.",
  camera: {
    initialYawDeg: 35,
    initialPitchDeg: 22,
    minPitchDeg: -85,
    maxPitchDeg: 85,
    initialZoom: 1.0,
    minZoom: 0.6,
    maxZoom: 2.2,
    distance: 280,
    focalLength: 220,
    nearClip: 30,
  },
  vertices: [
    { id: "v_apex", x: 0, y: 45, z: 0, radius: 8, colorToken: "primary", label: "Apex" },
    { id: "v_b1", x: -40, y: -35, z: -40, radius: 7, colorToken: "mutedText", label: "A" },
    { id: "v_b2", x: 40, y: -35, z: -40, radius: 7, colorToken: "mutedText", label: "B" },
    { id: "v_b3", x: 40, y: -35, z: 40, radius: 7, colorToken: "mutedText", label: "C" },
    { id: "v_b4", x: -40, y: -35, z: 40, radius: 7, colorToken: "mutedText", label: "D" },
  ],
  edges: [
    // Square base edges
    { id: "e_b1_b2", from: "v_b1", to: "v_b2", thickness: 2, colorToken: "mutedText", style: "solid" },
    { id: "e_b2_b3", from: "v_b2", to: "v_b3", thickness: 2, colorToken: "mutedText", style: "solid" },
    { id: "e_b3_b4", from: "v_b3", to: "v_b4", thickness: 2, colorToken: "mutedText", style: "solid" },
    { id: "e_b4_b1", from: "v_b4", to: "v_b1", thickness: 2, colorToken: "mutedText", style: "solid" },
    // Slant edges from base corners to apex
    { id: "e_apex_b1", from: "v_apex", to: "v_b1", thickness: 2.5, colorToken: "primary", style: "solid" },
    { id: "e_apex_b2", from: "v_apex", to: "v_b2", thickness: 2.5, colorToken: "primary", style: "solid" },
    { id: "e_apex_b3", from: "v_apex", to: "v_b3", thickness: 2.5, colorToken: "primary", style: "solid" },
    { id: "e_apex_b4", from: "v_apex", to: "v_b4", thickness: 2.5, colorToken: "primary", style: "solid" },
  ],
  tableData: {
    headers: ["Element", "ID", "Model Position (X, Y, Z)", "Role"],
    rows: [
      ["Apex", "v_apex", "(0, +45, 0)", "Top apex vertex"],
      ["Base Corner A", "v_b1", "(-40, -35, -40)", "Back-left base"],
      ["Base Corner B", "v_b2", "(+40, -35, -40)", "Back-right base"],
      ["Base Corner C", "v_b3", "(+40, -35, +40)", "Front-right base"],
      ["Base Corner D", "v_b4", "(-40, -35, +40)", "Front-left base"],
      ["Base Edges", "4 edges", "40 units from center", "Square perimeter (80x80)"],
      ["Slant Edges", "4 edges", "Corner to apex", "Pyramid faces"],
    ],
  },
};

/**
 * 2D Free-body Forces Diagram for Physics / Forces.
 * Models an object experiencing four forces: forward thrust, friction, normal reaction, and weight.
 */
export const FORCES_VECTOR_2D: Visualization2DDescriptor = {
  type: "visualization_2d",
  subject: "physics",
  topicId: "forces",
  title: "Forces on a Surface",
  description: "Free-body force vector diagram showing balanced vertical forces and unbalanced horizontal forces.",
  educationalSummary:
    "Vertical forces are in equilibrium: Normal Reaction (8 N up) balances Weight (8 N down). Horizontal forces are unbalanced: Forward Thrust (12 N right) exceeds Friction (4 N left), giving a Net Resultant Force of 8 N to the right.",
  origin: { x: 120, y: 120 },
  scale: 6.5, // 6.5 pixels per Newton
  vectors: [
    {
      id: "f_thrust",
      label: "Forward Thrust (12 N)",
      magnitude: 12,
      angleDeg: 0,
      colorToken: "primary",
      xComp: 12,
      yComp: 0,
    },
    {
      id: "f_friction",
      label: "Friction (4 N)",
      magnitude: 4,
      angleDeg: 180,
      colorToken: "error",
      xComp: -4,
      yComp: 0,
    },
    {
      id: "f_normal",
      label: "Normal Reaction (8 N)",
      magnitude: 8,
      angleDeg: 90,
      colorToken: "mutedText",
      xComp: 0,
      yComp: 8,
    },
    {
      id: "f_weight",
      label: "Weight (8 N)",
      magnitude: 8,
      angleDeg: 270,
      colorToken: "mutedText",
      xComp: 0,
      yComp: -8,
    },
  ],
  resultant: {
    magnitude: 8,
    angleDeg: 0,
    colorToken: "success",
    label: "Resultant Force (8 N Forward)",
  },
  tableData: {
    headers: ["Force Name", "Direction", "Magnitude (N)", "X / Y Components"],
    rows: [
      ["Forward Thrust", "Right (0°)", 12, "+12 N, 0 N"],
      ["Friction Resistance", "Left (180°)", 4, "-4 N, 0 N"],
      ["Normal Reaction", "Up (90°)", 8, "0 N, +8 N"],
      ["Gravitational Weight", "Down (270°)", 8, "0 N, -8 N"],
      ["Net Resultant Force", "Right (0°)", 8, "+8 N, 0 N (Accelerating Right)"],
    ],
  },
};

/**
 * Accessor for curated visual learning descriptors.
 * Explicitly matches verified actual topic IDs from adaptiveQuiz.ts.
 * Returns null if topic does not have a curated visual.
 */
export function getCuratedLearningVisual(
  subject: string,
  topic: string,
): LearningVisualDescriptor | null {
  if (subject === "mathematics" && topic === "geometry") {
    return GEOMETRY_PYRAMID_3D;
  }
  if (subject === "physics" && topic === "forces") {
    return FORCES_VECTOR_2D;
  }
  return null;
}
