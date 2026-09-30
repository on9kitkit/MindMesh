import assert from "node:assert/strict";
import test from "node:test";

import {
  FORCES_VECTOR_2D,
  GEOMETRY_PYRAMID_3D,
  getCuratedLearningVisual,
} from "./curatedRegistry";
import {
  validateCameraConfig,
  validateLearningDescriptor,
  validateScene3D,
  validateTableData,
  validateVisualization2D,
} from "./sceneValidator";
import type { Scene3DDescriptor, Visualization2DDescriptor } from "./types";

test("curated descriptors pass schema validation", () => {
  const pyramidRes = validateLearningDescriptor(GEOMETRY_PYRAMID_3D);
  assert.equal(pyramidRes.success, true, "Pyramid 3D must be valid");

  const forcesRes = validateLearningDescriptor(FORCES_VECTOR_2D);
  assert.equal(forcesRes.success, true, "Forces 2D must be valid");
});

test("curated registry returns exact matches and null for uncurated topics", () => {
  const mathVisual = getCuratedLearningVisual("mathematics", "geometry");
  assert.ok(mathVisual !== null);
  assert.equal(mathVisual?.type, "scene_3d");

  const physicsVisual = getCuratedLearningVisual("physics", "forces");
  assert.ok(physicsVisual !== null);
  assert.equal(physicsVisual?.type, "visualization_2d");

  // Other topics gracefully return null
  assert.equal(getCuratedLearningVisual("biology", "cells"), null);
  assert.equal(getCuratedLearningVisual("english_language", "writing_techniques"), null);
  assert.equal(getCuratedLearningVisual("mathematics", "algebra"), null);
});

test("validateCameraConfig enforces valid numbers and bounds", () => {
  // Valid camera
  const valid = validateCameraConfig(GEOMETRY_PYRAMID_3D.camera);
  assert.equal(valid.success, true);

  // Invalid: maxZoom < minZoom
  const invalidZoom = validateCameraConfig({
    ...GEOMETRY_PYRAMID_3D.camera,
    minZoom: 2.0,
    maxZoom: 1.0,
  });
  assert.equal(invalidZoom.success, false);

  // Invalid: distance <= 0
  const invalidDist = validateCameraConfig({
    ...GEOMETRY_PYRAMID_3D.camera,
    distance: -10,
  });
  assert.equal(invalidDist.success, false);

  const initialZoomOutsideRange = validateCameraConfig({
    ...GEOMETRY_PYRAMID_3D.camera,
    initialZoom: 0.2,
  });
  assert.equal(initialZoomOutsideRange.success, false);

  const initialPitchOutsideRange = validateCameraConfig({
    ...GEOMETRY_PYRAMID_3D.camera,
    maxPitchDeg: 10,
    initialPitchDeg: 22,
  });
  assert.equal(initialPitchOutsideRange.success, false);
  assert.ok(
    initialPitchOutsideRange.errors.some((error) => error.includes("initialPitchDeg must be inside")),
  );
});

test("validateScene3D rejects oversized vertex and edge counts", () => {
  // Exceeding 32 vertices
  const manyVertices = Array.from({ length: 33 }, (_, i) => ({
    id: `v_${i}`,
    x: 0,
    y: 0,
    z: 0,
    colorToken: "primary" as const,
  }));

  const invalidScene: Scene3DDescriptor = {
    ...GEOMETRY_PYRAMID_3D,
    vertices: manyVertices,
  };

  const res = validateScene3D(invalidScene);
  assert.equal(res.success, false);
  assert.ok(res.errors.some((e) => e.includes("vertices must be an array between 1 and 32 items")));
});

test("validateScene3D rejects dangling edge references", () => {
  const danglingEdgeScene: Scene3DDescriptor = {
    ...GEOMETRY_PYRAMID_3D,
    edges: [
      {
        id: "e_bad",
        from: "v_apex",
        to: "v_nonexistent",
        colorToken: "primary",
      },
    ],
  };

  const res = validateScene3D(danglingEdgeScene);
  assert.equal(res.success, false);
  assert.ok(res.errors.some((e) => e.includes("references missing 'to' vertex")));
});

test("validateScene3D rejects coordinates outside bounded range", () => {
  const outOfBoundsScene: Scene3DDescriptor = {
    ...GEOMETRY_PYRAMID_3D,
    vertices: [
      { id: "v1", x: 9999, y: 0, z: 0, colorToken: "primary" },
    ],
    edges: [],
  };

  const res = validateScene3D(outOfBoundsScene);
  assert.equal(res.success, false);
  assert.ok(res.errors.some((e) => e.includes("out of bounds")));
});

test("validateScene3D rejects unsafe strings and remote protocols", () => {
  const unsafeScene = {
    ...GEOMETRY_PYRAMID_3D,
    title: "<script>alert('hack')</script>",
  };

  const res = validateScene3D(unsafeScene);
  assert.equal(res.success, false);
  assert.ok(res.errors.some((e) => e.includes("title must be a valid string")));

  const urlScene = {
    ...GEOMETRY_PYRAMID_3D,
    description: "Inspect at https://evil.com/payload.png",
  };
  const urlRes = validateScene3D(urlScene);
  assert.equal(urlRes.success, false);
});

test("validateVisualization2D enforces vector count and bounds", () => {
  const validRes = validateVisualization2D(FORCES_VECTOR_2D);
  assert.equal(validRes.success, true);

  // Negative magnitude rejected
  const badVectorScene: Visualization2DDescriptor = {
    ...FORCES_VECTOR_2D,
    vectors: [
      {
        id: "v1",
        label: "Bad Vector",
        magnitude: -5,
        angleDeg: 0,
        colorToken: "primary",
        xComp: -5,
        yComp: 0,
      },
    ],
  };

  const badRes = validateVisualization2D(badVectorScene);
  assert.equal(badRes.success, false);
  assert.ok(badRes.errors.some((e) => e.includes("magnitude must be between 0 and 500")));
});

test("validateTableData rejects header/row mismatches, excessive counts, and unsafe cells", () => {
  // Valid table passes
  const valid = validateTableData({
    headers: ["Col A", "Col B"],
    rows: [
      ["Row 1", 42],
      ["Row 2", 99],
    ],
  });
  assert.equal(valid.success, true);

  // Length mismatch between headers and row cells
  const mismatch = validateTableData({
    headers: ["Col A", "Col B"],
    rows: [["Only One Cell"]],
  });
  assert.equal(mismatch.success, false);
  assert.ok(mismatch.errors.some((e) => e.includes("does not match headers count")));

  // Unsafe HTML in cell
  const unsafeCell = validateTableData({
    headers: ["Col A"],
    rows: [["<script>alert(1)</script>"]],
  });
  assert.equal(unsafeCell.success, false);

  // Excessive headers (> 8)
  const tooManyHeaders = validateTableData({
    headers: Array.from({ length: 9 }, (_, i) => `H${i}`),
    rows: [],
  });
  assert.equal(tooManyHeaders.success, false);
});

test("validateCameraConfig enforces nearClip strictly less than distance and upper bounds", () => {
  // NearClip >= distance rejected
  const badClip = validateCameraConfig({
    ...GEOMETRY_PYRAMID_3D.camera,
    distance: 100,
    nearClip: 100,
  });
  assert.equal(badClip.success, false);
  assert.ok(badClip.errors.some((e) => e.includes("nearClip must be non-negative and strictly less than distance")));

  // Excessive distance (> 2000) rejected
  const hugeDistance = validateCameraConfig({
    ...GEOMETRY_PYRAMID_3D.camera,
    distance: 5000,
  });
  assert.equal(hugeDistance.success, false);

  // Excessive zoom (> 10.0) rejected
  const hugeZoom = validateCameraConfig({
    ...GEOMETRY_PYRAMID_3D.camera,
    maxZoom: 20.0,
  });
  assert.equal(hugeZoom.success, false);
});

test("validateVisualization2D rejects inconsistent vector components and mismatched resultant", () => {
  // Inconsistent vector component: magnitude=10, angle=0 (should be x=10, y=0), but claims x=5, y=0
  const inconsistentVector: Visualization2DDescriptor = {
    ...FORCES_VECTOR_2D,
    vectors: [
      {
        id: "v_bad",
        label: "Inconsistent",
        magnitude: 10,
        angleDeg: 0,
        colorToken: "primary",
        xComp: 5, // Mismatch!
        yComp: 0,
      },
    ],
  };
  const vecRes = validateVisualization2D(inconsistentVector);
  assert.equal(vecRes.success, false);
  assert.ok(vecRes.errors.some((e) => e.includes("xComp is inconsistent with magnitude and angleDeg")));

  // Mismatched resultant magnitude: sum of vectors is 8N, but resultant claims 30N
  const mismatchedResultant: Visualization2DDescriptor = {
    ...FORCES_VECTOR_2D,
    resultant: {
      magnitude: 30, // Mismatch from 8N!
      angleDeg: 0,
      colorToken: "success",
      label: "Fake Resultant",
    },
  };
  const resRes = validateVisualization2D(mismatchedResultant);
  assert.equal(resRes.success, false);
  assert.ok(resRes.errors.some((e) => e.includes("does not match vector component sum")));

  const reversedResultant: Visualization2DDescriptor = {
    ...FORCES_VECTOR_2D,
    resultant: {
      magnitude: 8,
      angleDeg: 180,
      colorToken: "success",
      label: "Wrong Direction",
    },
  };
  const reversed = validateVisualization2D(reversedResultant);
  assert.equal(reversed.success, false);
  assert.ok(reversed.errors.some((error) => error.includes("resultant direction")));
});
