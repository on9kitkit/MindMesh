import type {
  CameraConfig,
  Edge3D,
  Point3D,
  ProjectedPoint2D,
  RenderPrimitive3D,
  Vertex3D,
} from "./types";

/**
 * Degrees to radians conversion factor.
 */
export const DEG_TO_RAD = Math.PI / 180;

/**
 * Clamp a number to an inclusive range [min, max].
 * Ensures deterministic, finite results.
 */
export function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.max(min, Math.min(max, value));
}

/**
 * Normalize an angle in degrees to the [-180, 180) range.
 */
export function normalizeAngleDeg(degrees: number): number {
  if (!Number.isFinite(degrees)) {
    return 0;
  }
  let normalized = (degrees + 180) % 360;
  if (normalized < 0) {
    normalized += 360;
  }
  return normalized - 180;
}

/**
 * Rotate a 3D point by yaw (around Y axis) and pitch (around X axis).
 * Yaw: horizontal rotation (positive turns right).
 * Pitch: vertical tilt (positive pitches up).
 */
export function rotatePoint(
  point: Point3D,
  yawDeg: number,
  pitchDeg: number,
): Point3D {
  const { x, y, z } = point;
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
    return { x: 0, y: 0, z: 0 };
  }

  const yawRad = normalizeAngleDeg(yawDeg) * DEG_TO_RAD;
  const pitchRad = clamp(pitchDeg, -85, 85) * DEG_TO_RAD;

  const cosY = Math.cos(yawRad);
  const sinY = Math.sin(yawRad);
  const cosP = Math.cos(pitchRad);
  const sinP = Math.sin(pitchRad);

  // 1. Yaw rotation around Y axis
  const x1 = x * cosY - z * sinY;
  const z1 = x * sinY + z * cosY;
  const y1 = y;

  // 2. Pitch rotation around X axis
  const y2 = y1 * cosP - z1 * sinP;
  const z2 = y1 * sinP + z1 * cosP;
  const x2 = x1;

  return { x: x2, y: y2, z: z2 };
}

/**
 * Calculate rotation angles from an initial gesture origin and cumulative touch deltas.
 * Prevents quadratic stacking of move events.
 */
export function calculateDragRotation(
  originYaw: number,
  originPitch: number,
  dx: number,
  dy: number,
  minPitch = -85,
  maxPitch = 85,
): { yaw: number; pitch: number } {
  const nextYaw = originYaw + dx * 0.4;
  const nextPitch = originPitch - dy * 0.4;
  return {
    yaw: normalizeAngleDeg(nextYaw),
    pitch: clamp(nextPitch, minPitch, maxPitch),
  };
}

/**
 * Project a 3D point onto a 2D viewport using perspective projection.
 *
 * Depth convention:
 *  - Camera is at distance D along the view axis looking at (0, 0, 0).
 *  - Model space +Z is towards the camera, -Z is away from the camera.
 *  - Camera depth = distance - rotated.z.
 *  - Therefore: larger positive depth means FARTHER from the camera.
 *  - Smaller positive depth means CLOSER to the camera.
 *
 * Near-clipping:
 *  - If depth <= nearClip, the point is clipped/invisible to avoid division by zero
 *    or inversion behind the camera.
 */
export function projectPoint(
  point: Point3D,
  yawDeg: number,
  pitchDeg: number,
  zoom: number,
  camera: CameraConfig,
  viewportWidth: number,
  viewportHeight: number,
): ProjectedPoint2D {
  const rotated = rotatePoint(point, yawDeg, pitchDeg);
  const clampedZoom = clamp(zoom, camera.minZoom, camera.maxZoom);

  // Larger positive depth = farther away
  const zDepth = camera.distance - rotated.z;

  if (zDepth <= camera.nearClip) {
    return {
      x: viewportWidth / 2,
      y: viewportHeight / 2,
      zDepth,
      scale: 0,
      visible: false,
    };
  }

  const scale = (camera.focalLength / zDepth) * clampedZoom;

  // Canvas y-axis points down, while model y-axis points up
  const xProj = rotated.x * scale + viewportWidth / 2;
  const yProj = -rotated.y * scale + viewportHeight / 2;

  return {
    x: xProj,
    y: yProj,
    zDepth,
    scale,
    visible: true,
  };
}

/**
 * Derive 2D line segment rendering parameters between two projected points.
 */
export function deriveLineSegment(
  from: ProjectedPoint2D,
  to: ProjectedPoint2D,
): {
  length: number;
  midpointX: number;
  midpointY: number;
  angleRad: number;
} {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy);
  const midpointX = (from.x + to.x) / 2;
  const midpointY = (from.y + to.y) / 2;
  const angleRad = Math.atan2(dy, dx);

  return {
    length,
    midpointX,
    midpointY,
    angleRad,
  };
}

/**
 * Deterministic Painter's algorithm sorting:
 * Larger positive depth is farther away => far-to-near descending order.
 * First element in returned array has largest depth (rendered first / at bottom).
 * Last element in returned array has smallest depth (rendered last / in front).
 */
export function sortPrimitivesFarToNear(
  primitives: RenderPrimitive3D[],
): RenderPrimitive3D[] {
  return [...primitives].sort((a, b) => {
    // Descending order of depth
    const diff = b.depth - a.depth;
    if (Math.abs(diff) > 1e-6) {
      return diff;
    }
    // Tie-breaker: deterministic order by kind then id
    if (a.kind !== b.kind) {
      // Draw edges before vertices when depths are identical (edges first in array, vertices on top)
      return a.kind === "edge" ? -1 : 1;
    }
    return a.id.localeCompare(b.id);
  });
}

/**
 * Build sorted renderable 3D primitives from vertices and edges.
 */
export function buildRenderPrimitives(
  vertices: Vertex3D[],
  edges: Edge3D[],
  yawDeg: number,
  pitchDeg: number,
  zoom: number,
  camera: CameraConfig,
  viewportWidth: number,
  viewportHeight: number,
): RenderPrimitive3D[] {
  const projectedMap: Record<string, ProjectedPoint2D> = {};

  for (const v of vertices) {
    projectedMap[v.id] = projectPoint(
      { x: v.x, y: v.y, z: v.z },
      yawDeg,
      pitchDeg,
      zoom,
      camera,
      viewportWidth,
      viewportHeight,
    );
  }

  const primitives: RenderPrimitive3D[] = [];

  // 1. Vertices
  for (const v of vertices) {
    const proj = projectedMap[v.id];
    if (!proj || !proj.visible) {
      continue;
    }
    primitives.push({
      kind: "vertex",
      id: v.id,
      depth: proj.zDepth,
      projected: proj,
      vertex: v,
    });
  }

  // 2. Edges
  for (const e of edges) {
    const pFrom = projectedMap[e.from];
    const pTo = projectedMap[e.to];
    if (!pFrom || !pTo || !pFrom.visible || !pTo.visible) {
      continue;
    }
    const line = deriveLineSegment(pFrom, pTo);
    const averageDepth = (pFrom.zDepth + pTo.zDepth) / 2;

    primitives.push({
      kind: "edge",
      id: e.id,
      depth: averageDepth,
      fromProjected: pFrom,
      toProjected: pTo,
      edge: e,
      length: line.length,
      midpointX: line.midpointX,
      midpointY: line.midpointY,
      angleRad: line.angleRad,
    });
  }

  // Deterministic far-to-near sort (descending depth)
  return sortPrimitivesFarToNear(primitives);
}
