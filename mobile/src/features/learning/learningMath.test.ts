import assert from "node:assert/strict";
import test from "node:test";

import {
  buildRenderPrimitives,
  calculateDragRotation,
  clamp,
  DEG_TO_RAD,
  deriveLineSegment,
  normalizeAngleDeg,
  projectPoint,
  rotatePoint,
  sortPrimitivesFarToNear,
} from "./math3d";
import type { CameraConfig, RenderPrimitive3D } from "./types";

const mockCamera: CameraConfig = {
  initialYawDeg: 0,
  initialPitchDeg: 0,
  minPitchDeg: -85,
  maxPitchDeg: 85,
  initialZoom: 1.0,
  minZoom: 0.5,
  maxZoom: 3.0,
  distance: 300,
  focalLength: 200,
  nearClip: 50,
};

test("clamp keeps values within [min, max] and handles non-finite input", () => {
  assert.equal(clamp(5, 0, 10), 5);
  assert.equal(clamp(-5, 0, 10), 0);
  assert.equal(clamp(15, 0, 10), 10);
  assert.equal(clamp(NaN, 0, 10), 0);
  assert.equal(clamp(Infinity, 0, 10), 0);
});

test("normalizeAngleDeg normalizes angles into [-180, 180) range", () => {
  assert.equal(normalizeAngleDeg(0), 0);
  assert.equal(normalizeAngleDeg(180), -180);
  assert.equal(normalizeAngleDeg(360), 0);
  assert.equal(normalizeAngleDeg(450), 90);
  assert.equal(normalizeAngleDeg(-270), 90);
  assert.equal(normalizeAngleDeg(NaN), 0);
});

test("rotatePoint correctly executes yaw and pitch rotations", () => {
  // Identity at (0, 0, 0) angles
  const p0 = { x: 10, y: 20, z: 30 };
  const r0 = rotatePoint(p0, 0, 0);
  assert.ok(Math.abs(r0.x - 10) < 1e-5);
  assert.ok(Math.abs(r0.y - 20) < 1e-5);
  assert.ok(Math.abs(r0.z - 30) < 1e-5);

  // Yaw 90 deg: X maps to -Z, Z maps to +X
  const px = { x: 10, y: 0, z: 0 };
  const rx90 = rotatePoint(px, 90, 0);
  assert.ok(Math.abs(rx90.x - 0) < 1e-5);
  assert.ok(Math.abs(rx90.y - 0) < 1e-5);
  assert.ok(Math.abs(rx90.z - 10) < 1e-5);

  // Pitch 90 deg (clamped to 85 deg): Y maps to +Z, Z maps to -Y
  const py = { x: 0, y: 10, z: 0 };
  const ry45 = rotatePoint(py, 0, 45);
  const expectedY = 10 * Math.cos(45 * DEG_TO_RAD);
  const expectedZ = 10 * Math.sin(45 * DEG_TO_RAD);
  assert.ok(Math.abs(ry45.y - expectedY) < 1e-5);
  assert.ok(Math.abs(ry45.z - expectedZ) < 1e-5);

  // Non-finite coordinates fail safely to (0, 0, 0)
  const pNan = { x: NaN, y: 0, z: 0 };
  assert.deepEqual(rotatePoint(pNan, 0, 0), { x: 0, y: 0, z: 0 });
});

test("projectPoint maps origin (0, 0, 0) to viewport center", () => {
  const proj = projectPoint(
    { x: 0, y: 0, z: 0 },
    0,
    0,
    1.0,
    mockCamera,
    300,
    200,
  );
  assert.equal(proj.visible, true);
  assert.equal(proj.x, 150); // W / 2
  assert.equal(proj.y, 100); // H / 2
  assert.equal(proj.zDepth, 300); // distance - 0
});

test("projectPoint exhibits perspective foreshortening (further point has smaller scale)", () => {
  // Near point (closer in model space, z = +50 => camera depth = 250)
  const nearPoint = projectPoint(
    { x: 20, y: 20, z: 50 },
    0,
    0,
    1.0,
    mockCamera,
    300,
    200,
  );

  // Far point (further in model space, z = -50 => camera depth = 350)
  const farPoint = projectPoint(
    { x: 20, y: 20, z: -50 },
    0,
    0,
    1.0,
    mockCamera,
    300,
    200,
  );

  assert.ok(nearPoint.zDepth < farPoint.zDepth, "Near point has smaller depth than far point");
  assert.ok(nearPoint.scale > farPoint.scale, "Near point has larger perspective scale");
  assert.ok(nearPoint.x > farPoint.x, "Near point projects further outward from center");
});

test("projectPoint clips points behind or inside the near-plane", () => {
  // Point too close to camera: z = 280 => depth = 300 - 280 = 20 <= nearClip (50)
  const clippedPoint = projectPoint(
    { x: 0, y: 0, z: 280 },
    0,
    0,
    1.0,
    mockCamera,
    300,
    200,
  );
  assert.equal(clippedPoint.visible, false);
});

test("deriveLineSegment calculates accurate length, midpoint, and angle", () => {
  const from = { x: 0, y: 0, zDepth: 100, scale: 1, visible: true };
  const to = { x: 30, y: 40, zDepth: 100, scale: 1, visible: true };

  const line = deriveLineSegment(from, to);
  assert.equal(line.length, 50); // 3-4-5 right triangle
  assert.equal(line.midpointX, 15);
  assert.equal(line.midpointY, 20);
  assert.ok(Math.abs(line.angleRad - Math.atan2(40, 30)) < 1e-5);
});

test("sortPrimitivesFarToNear sorts in strictly descending depth order (Painter's algorithm)", () => {
  const primitives: RenderPrimitive3D[] = [
    {
      kind: "vertex",
      id: "v1",
      depth: 120, // Middle
      projected: { x: 0, y: 0, zDepth: 120, scale: 1, visible: true },
      vertex: { id: "v1", x: 0, y: 0, z: 0, colorToken: "primary" },
    },
    {
      kind: "vertex",
      id: "v2",
      depth: 250, // Farthest (largest positive depth)
      projected: { x: 0, y: 0, zDepth: 250, scale: 1, visible: true },
      vertex: { id: "v2", x: 0, y: 0, z: 0, colorToken: "primary" },
    },
    {
      kind: "vertex",
      id: "v3",
      depth: 60, // Closest (smallest positive depth)
      projected: { x: 0, y: 0, zDepth: 60, scale: 1, visible: true },
      vertex: { id: "v3", x: 0, y: 0, z: 0, colorToken: "primary" },
    },
    {
      kind: "vertex",
      id: "v4",
      depth: 180, // Second farthest
      projected: { x: 0, y: 0, zDepth: 180, scale: 1, visible: true },
      vertex: { id: "v4", x: 0, y: 0, z: 0, colorToken: "primary" },
    },
  ];

  const sorted = sortPrimitivesFarToNear(primitives);

  // Painter's algorithm order: Farthest (250) -> Middle-Far (180) -> Middle-Near (120) -> Closest (60)
  assert.equal(sorted[0].id, "v2");
  assert.equal(sorted[1].id, "v4");
  assert.equal(sorted[2].id, "v1");
  assert.equal(sorted[3].id, "v3");

  assert.equal(sorted[0].depth, 250);
  assert.equal(sorted[1].depth, 180);
  assert.equal(sorted[2].depth, 120);
  assert.equal(sorted[3].depth, 60);
});

test("buildRenderPrimitives produces sorted vertex and edge primitives", () => {
  const vertices = [
    { id: "a", x: 0, y: 20, z: 0, colorToken: "primary" as const },
    { id: "b", x: 0, y: -20, z: -50, colorToken: "border" as const },
  ];
  const edges = [
    { id: "e1", from: "a", to: "b", colorToken: "border" as const },
  ];

  const prims = buildRenderPrimitives(
    vertices,
    edges,
    0,
    0,
    1.0,
    mockCamera,
    200,
    200,
  );

  assert.equal(prims.length, 3); // 2 vertices + 1 edge
  // Ensure every depth is finite
  for (const p of prims) {
    assert.ok(Number.isFinite(p.depth));
  }
  // Ensure sorted descending
  for (let i = 0; i < prims.length - 1; i++) {
    assert.ok(prims[i].depth >= prims[i + 1].depth);
  }
});

test("calculateDragRotation with sequential move events applies delta to fixed origin without compounding", () => {
  const originYaw = 30;
  const originPitch = 20;

  // First move event: user moved +10px horizontally, +5px vertically
  const move1 = calculateDragRotation(originYaw, originPitch, 10, 5);
  assert.equal(move1.yaw, 34); // 30 + 10 * 0.4
  assert.equal(move1.pitch, 18); // 20 - 5 * 0.4

  // Second move event: user's cumulative drag from origin is now +25px horizontally, -10px vertically
  const move2 = calculateDragRotation(originYaw, originPitch, 25, -10);
  assert.equal(move2.yaw, 40); // 30 + 25 * 0.4 = 40 (NOT 34 + 25 * 0.4 = 44)
  assert.equal(move2.pitch, 24); // 20 - (-10) * 0.4 = 24 (NOT 18 + 4 = 22)
});

test("sortPrimitivesFarToNear tie-breaker places edges before vertices at equal depth", () => {
  const vertex: RenderPrimitive3D = {
    kind: "vertex",
    id: "v_point",
    depth: 100,
    projected: { x: 0, y: 0, zDepth: 100, scale: 1, visible: true },
    vertex: { id: "v_point", x: 0, y: 0, z: 0, colorToken: "primary" },
  };
  const edge: RenderPrimitive3D = {
    kind: "edge",
    id: "e_line",
    depth: 100, // Exact same depth as vertex
    fromProjected: { x: 0, y: 0, zDepth: 100, scale: 1, visible: true },
    toProjected: { x: 10, y: 10, zDepth: 100, scale: 1, visible: true },
    edge: { id: "e_line", from: "v1", to: "v2", colorToken: "border" },
    length: 14.14,
    midpointX: 5,
    midpointY: 5,
    angleRad: 0.785,
  };

  // Test with vertex first in input
  const sorted1 = sortPrimitivesFarToNear([vertex, edge]);
  assert.equal(sorted1[0].kind, "edge", "Edge must be sorted before vertex at equal depth");
  assert.equal(sorted1[1].kind, "vertex", "Vertex must be sorted after edge at equal depth");

  // Test with edge first in input
  const sorted2 = sortPrimitivesFarToNear([edge, vertex]);
  assert.equal(sorted2[0].kind, "edge");
  assert.equal(sorted2[1].kind, "vertex");
});
