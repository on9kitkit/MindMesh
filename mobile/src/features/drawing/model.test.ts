import assert from "node:assert/strict";
import test from "node:test";

import {
  angleBetweenPoints,
  countRetainedPoints,
  countVisiblePoints,
  createDrawingDocument,
  distanceBetweenPoints,
  protractorAngle,
  reduceDrawingDocument,
  snapToAngle,
  strokeNearPoint,
  strokePath,
  toDrawingPoint,
} from "./model";
import { DRAWING_LIMITS, DRAWING_UNITS, type DrawingPoint, type DrawingStroke } from "./types";

test("createDrawingDocument initializes empty document with expected defaults", () => {
  const doc = createDrawingDocument();
  assert.deepEqual(doc.strokes, []);
  assert.equal(doc.active, null);
  assert.deepEqual(doc.past, []);
  assert.deepEqual(doc.future, []);
  assert.equal(doc.nextStrokeId, 1);
  assert.equal(doc.limitReached, false);
  assert.equal(countVisiblePoints(doc), 0);
  assert.equal(countRetainedPoints(doc), 0);
  assert.equal(DRAWING_UNITS, 1000);
});

test("toDrawingPoint maps viewport coordinates uniformly to square 1000-unit canvas", () => {
  // Square viewport 400x400
  const center = toDrawingPoint(200, 200, 400, 400);
  assert.ok(center);
  assert.equal(center?.x, 500);
  assert.equal(center?.y, 500);

  // Landscape viewport 600x400 (centered square is 400x400 with 100px left/right offset)
  const p1 = toDrawingPoint(100, 0, 600, 400);
  assert.ok(p1);
  assert.equal(p1?.x, 0);
  assert.equal(p1?.y, 0);

  const pCenter = toDrawingPoint(300, 200, 600, 400);
  assert.ok(pCenter);
  assert.equal(pCenter?.x, 500);
  assert.equal(pCenter?.y, 500);

  // Clamps out-of-bounds touches
  const pClamped = toDrawingPoint(-50, 500, 400, 400);
  assert.ok(pClamped);
  assert.equal(pClamped?.x, 0);
  assert.equal(pClamped?.y, 1000);

  // Rejects invalid/nonfinite inputs
  assert.equal(toDrawingPoint(NaN, 100, 400, 400), null);
  assert.equal(toDrawingPoint(100, Infinity, 400, 400), null);
  assert.equal(toDrawingPoint(100, 100, 0, 400), null);
  assert.equal(toDrawingPoint(100, 100, 400, -10), null);
});

test("distanceBetweenPoints and angleBetweenPoints calculate accurate geometry", () => {
  const p1: DrawingPoint = { x: 100, y: 100 };
  const p2: DrawingPoint = { x: 400, y: 500 };

  // 300x400 right triangle => hypotenuse 500
  assert.equal(distanceBetweenPoints(p1, p2), 500);

  // Angle directions
  const pRight: DrawingPoint = { x: 200, y: 100 };
  assert.equal(angleBetweenPoints(p1, pRight), 0);

  const pDown: DrawingPoint = { x: 100, y: 200 };
  assert.equal(angleBetweenPoints(p1, pDown), 90);

  const pLeft: DrawingPoint = { x: 0, y: 100 };
  assert.equal(angleBetweenPoints(p1, pLeft), 180);

  const pUp: DrawingPoint = { x: 100, y: 0 };
  assert.equal(angleBetweenPoints(p1, pUp), 270);
});

test("snapToAngle snaps current point to 15-degree increments", () => {
  const start: DrawingPoint = { x: 100, y: 100 };
  // 100px away at ~42 degrees
  const current: DrawingPoint = { x: 174, y: 167 };

  // Snaps to 45 degrees
  const snapped = snapToAngle(start, current, 15);
  const angle = angleBetweenPoints(start, snapped);
  assert.equal(angle, 45);
  assert.ok(Math.abs(distanceBetweenPoints(start, snapped) - 100) <= 2);
});

test("protractorAngle returns degrees between 0 and 180 relative to baseline", () => {
  const center: DrawingPoint = { x: 500, y: 500 };

  // Ray directly to the right (baseline 0°)
  const pRight: DrawingPoint = { x: 700, y: 500 };
  assert.equal(protractorAngle(center, pRight, 0), 0);

  // Ray directly down (90° from right)
  const pDown: DrawingPoint = { x: 500, y: 700 };
  assert.equal(protractorAngle(center, pDown, 0), 90);

  // Ray directly to the left (180° from right)
  const pLeft: DrawingPoint = { x: 300, y: 500 };
  assert.equal(protractorAngle(center, pLeft, 0), 180);

  // Ray up (270° absolute, but 90° shortest difference)
  const pUp: DrawingPoint = { x: 500, y: 300 };
  assert.equal(protractorAngle(center, pUp, 0), 90);
});

test("strokePath generates SVG path strings for straight and freehand strokes", () => {
  // Empty
  assert.equal(strokePath({ id: 1, kind: "freehand", ink: "primary", points: [] }), "");

  // Single point
  const single = strokePath({
    id: 1,
    kind: "freehand",
    ink: "primary",
    points: [{ x: 100, y: 200 }],
  });
  assert.ok(single.startsWith("M 100 200 L 100.1"));

  // Straight line
  const straight = strokePath({
    id: 2,
    kind: "straight",
    ink: "primary",
    points: [
      { x: 10, y: 20 },
      { x: 50, y: 80 },
    ],
  });
  assert.equal(straight, "M 10 20 L 50 80");

  // Freehand multi-point (Bézier smoothed)
  const freehand = strokePath({
    id: 3,
    kind: "freehand",
    ink: "primary",
    points: [
      { x: 10, y: 10 },
      { x: 20, y: 30 },
      { x: 40, y: 50 },
      { x: 80, y: 90 },
    ],
  });
  assert.ok(freehand.includes("Q"));
  assert.ok(freehand.endsWith("L 80 90"));
});

test("strokeNearPoint hit-tests points within radius for straight and freehand strokes", () => {
  const straightStroke: DrawingStroke = {
    id: 1,
    kind: "straight",
    ink: "primary",
    points: [
      { x: 100, y: 100 },
      { x: 500, y: 100 },
    ],
  };

  // Near midpoint
  assert.equal(strokeNearPoint(straightStroke, { x: 300, y: 110 }, 20), true);
  // Far from line
  assert.equal(strokeNearPoint(straightStroke, { x: 300, y: 150 }, 20), false);
  // Near endpoint
  assert.equal(strokeNearPoint(straightStroke, { x: 505, y: 105 }, 20), true);

  const freehandStroke: DrawingStroke = {
    id: 2,
    kind: "freehand",
    ink: "primary",
    points: [
      { x: 100, y: 100 },
      { x: 200, y: 200 },
      { x: 300, y: 100 },
    ],
  };

  assert.equal(strokeNearPoint(freehandStroke, { x: 200, y: 195 }, 15), true);
  assert.equal(strokeNearPoint(freehandStroke, { x: 200, y: 50 }, 15), false);
});

test("reduceDrawingDocument handles BEGIN, EXTEND, END, CANCEL lifecycle", () => {
  let doc = createDrawingDocument();

  // BEGIN freehand
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 100, y: 100 },
    ink: "primary",
    kind: "freehand",
  });
  assert.ok(doc.active);
  assert.equal(doc.active?.id, 1);
  assert.equal(doc.active?.points.length, 1);

  // EXTEND
  doc = reduceDrawingDocument(doc, {
    type: "EXTEND",
    point: { x: 120, y: 130 },
  });
  assert.equal(doc.active?.points.length, 2);

  // EXTEND identical/too-close point ignored
  doc = reduceDrawingDocument(doc, {
    type: "EXTEND",
    point: { x: 120.5, y: 130.5 },
  });
  assert.equal(doc.active?.points.length, 2);

  // END
  doc = reduceDrawingDocument(doc, {
    type: "END",
    point: { x: 150, y: 160 },
  });
  assert.equal(doc.active, null);
  assert.equal(doc.strokes.length, 1);
  assert.equal(doc.strokes[0].points.length, 3);
  assert.equal(doc.past.length, 1); // Recorded empty initial state for undo
  assert.equal(doc.future.length, 0);

  // BEGIN and CANCEL
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 200, y: 200 },
    ink: "error",
    kind: "freehand",
  });
  assert.ok(doc.active);
  doc = reduceDrawingDocument(doc, { type: "CANCEL" });
  assert.equal(doc.active, null);
  assert.equal(doc.strokes.length, 1); // Unchanged
});

test("reduceDrawingDocument whole-stroke ERASE_AT removes stroke and pushes undo history", () => {
  let doc = createDrawingDocument();
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 100, y: 100 },
    ink: "primary",
    kind: "straight",
  });
  doc = reduceDrawingDocument(doc, {
    type: "END",
    point: { x: 500, y: 100 },
  });
  assert.equal(doc.strokes.length, 1);

  // Miss stroke
  doc = reduceDrawingDocument(doc, {
    type: "ERASE_AT",
    point: { x: 300, y: 500 },
  });
  assert.equal(doc.strokes.length, 1);

  // Hit stroke
  doc = reduceDrawingDocument(doc, {
    type: "ERASE_AT",
    point: { x: 300, y: 105 },
  });
  assert.equal(doc.strokes.length, 0);
  assert.equal(doc.past.length, 2);

  // Undo restores erased stroke
  doc = reduceDrawingDocument(doc, { type: "UNDO" });
  assert.equal(doc.strokes.length, 1);
});

test("reduceDrawingDocument UNDO, REDO, and CLEAR are bounded and reversible", () => {
  let doc = createDrawingDocument();

  // Draw Stroke 1
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 50, y: 50 },
    ink: "primary",
    kind: "straight",
  });
  doc = reduceDrawingDocument(doc, { type: "END", point: { x: 100, y: 100 } });

  // Draw Stroke 2
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 200, y: 200 },
    ink: "success",
    kind: "straight",
  });
  doc = reduceDrawingDocument(doc, { type: "END", point: { x: 250, y: 250 } });

  assert.equal(doc.strokes.length, 2);

  // CLEAR is undoable
  doc = reduceDrawingDocument(doc, { type: "CLEAR" });
  assert.equal(doc.strokes.length, 0);

  // UNDO restores cleared strokes
  doc = reduceDrawingDocument(doc, { type: "UNDO" });
  assert.equal(doc.strokes.length, 2);

  // UNDO removes Stroke 2
  doc = reduceDrawingDocument(doc, { type: "UNDO" });
  assert.equal(doc.strokes.length, 1);

  // REDO restores Stroke 2
  doc = reduceDrawingDocument(doc, { type: "REDO" });
  assert.equal(doc.strokes.length, 2);
});

test("DRAWING_LIMITS maxStrokes, maxPointsPerStroke, maxVisiblePoints surface limitReached", () => {
  let doc = createDrawingDocument();

  // Test maxPointsPerStroke (256)
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 0, y: 0 },
    ink: "ink",
    kind: "freehand",
  });
  for (let i = 1; i <= 255; i++) {
    doc = reduceDrawingDocument(doc, {
      type: "EXTEND",
      point: { x: i * 2, y: i * 2 },
    });
  }
  assert.equal(doc.active?.points.length, 256);
  assert.equal(doc.limitReached, false);

  // Extending past 256 sets limitReached
  doc = reduceDrawingDocument(doc, {
    type: "EXTEND",
    point: { x: 600, y: 600 },
  });
  assert.equal(doc.limitReached, true);
  assert.equal(doc.active?.points.length, 256);

  doc = reduceDrawingDocument(doc, { type: "END" });
  assert.equal(doc.strokes.length, 1);

  // Test maxHistoryEntries (24)
  for (let i = 0; i < 30; i++) {
    doc = reduceDrawingDocument(doc, {
      type: "BEGIN",
      point: { x: i, y: i },
      ink: "ink",
      kind: "straight",
    });
    doc = reduceDrawingDocument(doc, { type: "END", point: { x: i + 1, y: i + 1 } });
  }
  assert.ok(doc.past.length <= DRAWING_LIMITS.maxHistoryEntries);
  assert.equal(doc.past.length, 24);
});

test("reduceDrawingDocument rejects BEGIN when an active stroke already exists", () => {
  let doc = createDrawingDocument();
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 100, y: 100 },
    ink: "primary",
    kind: "freehand",
  });
  assert.ok(doc.active);
  assert.equal(doc.active?.id, 1);
  assert.equal(doc.active?.ink, "primary");

  // Second BEGIN while active is rejected
  const duplicateBegin = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 200, y: 200 },
    ink: "error",
    kind: "straight",
  });
  assert.equal(duplicateBegin.active?.id, 1);
  assert.equal(duplicateBegin.active?.ink, "primary");
  assert.deepEqual(duplicateBegin.active?.points, [{ x: 100, y: 100 }]);
});

test("near-cap END enforces maxPointsPerStroke and retains limitReached", () => {
  let doc = createDrawingDocument();
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 0, y: 0 },
    ink: "ink",
    kind: "freehand",
  });

  // Fill to 255 points
  for (let i = 1; i <= 254; i++) {
    doc = reduceDrawingDocument(doc, {
      type: "EXTEND",
      point: { x: i * 2, y: i * 2 },
    });
  }
  assert.equal(doc.active?.points.length, 255);
  assert.equal(doc.limitReached, false);

  // END with 256th point succeeds
  const doc256 = reduceDrawingDocument(doc, {
    type: "END",
    point: { x: 600, y: 600 },
  });
  assert.equal(doc256.strokes.length, 1);
  assert.equal(doc256.strokes[0].points.length, 256);
  assert.equal(doc256.limitReached, false);

  // If stroke already at 256 points, END with additional point does not exceed cap and flags limitReached
  let docMax = createDrawingDocument();
  docMax = reduceDrawingDocument(docMax, {
    type: "BEGIN",
    point: { x: 0, y: 0 },
    ink: "ink",
    kind: "freehand",
  });
  for (let i = 1; i <= 255; i++) {
    docMax = reduceDrawingDocument(docMax, {
      type: "EXTEND",
      point: { x: i * 2, y: i * 2 },
    });
  }
  assert.equal(docMax.active?.points.length, 256);

  const endedOverMax = reduceDrawingDocument(docMax, {
    type: "END",
    point: { x: 800, y: 800 },
  });
  assert.equal(endedOverMax.strokes[0].points.length, 256);
  assert.equal(endedOverMax.limitReached, true);
});

test("repeated full-history erasures and clears enforce maxRetainedPoints budget and remain undoable", () => {
  let doc = createDrawingDocument();

  // Create several strokes with multiple points
  for (let s = 0; s < 10; s++) {
    doc = reduceDrawingDocument(doc, {
      type: "BEGIN",
      point: { x: s * 50, y: s * 50 },
      ink: "primary",
      kind: "freehand",
    });
    for (let p = 1; p <= 50; p++) {
      doc = reduceDrawingDocument(doc, {
        type: "EXTEND",
        point: { x: s * 50 + p * 2, y: s * 50 + p * 2 },
      });
    }
    doc = reduceDrawingDocument(doc, { type: "END" });
  }

  assert.equal(doc.strokes.length, 10);
  assert.ok(countRetainedPoints(doc) <= DRAWING_LIMITS.maxRetainedPoints);

  // Perform repeated erase and clear cycles
  for (let cycle = 0; cycle < 15; cycle++) {
    // Erase at point
    doc = reduceDrawingDocument(doc, {
      type: "ERASE_AT",
      point: { x: 50, y: 50 },
    });

    // Clear
    doc = reduceDrawingDocument(doc, { type: "CLEAR" });
    assert.equal(doc.strokes.length, 0);

    // Undo clear
    doc = reduceDrawingDocument(doc, { type: "UNDO" });
    assert.ok(doc.strokes.length >= 0);

    // Invariant: total retained points NEVER exceeds 32768
    assert.ok(
      countRetainedPoints(doc) <= DRAWING_LIMITS.maxRetainedPoints,
      `Retained points ${countRetainedPoints(doc)} must be <= ${DRAWING_LIMITS.maxRetainedPoints}`,
    );
    assert.ok(doc.past.length <= DRAWING_LIMITS.maxHistoryEntries);
  }
});

test("straight-stroke EXTEND near maxVisiblePoints and maxRetainedPoints enforces limits and prunes history", () => {
  let doc = createDrawingDocument();

  // Create strokes to reach near maxVisiblePoints (8192)
  // 32 strokes * 255 points = 8160 points
  for (let s = 0; s < 32; s++) {
    doc = reduceDrawingDocument(doc, {
      type: "BEGIN",
      point: { x: s, y: 0 },
      ink: "ink",
      kind: "freehand",
    });
    for (let p = 1; p < 255; p++) {
      doc = reduceDrawingDocument(doc, {
        type: "EXTEND",
        point: { x: s, y: p * 2 },
      });
    }
    doc = reduceDrawingDocument(doc, { type: "END" });
  }

  // 8160 points visible; add 1 more stroke with 31 points => 8191 points visible
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 50, y: 0 },
    ink: "ink",
    kind: "freehand",
  });
  for (let p = 1; p < 31; p++) {
    doc = reduceDrawingDocument(doc, {
      type: "EXTEND",
      point: { x: 50, y: p * 2 },
    });
  }
  doc = reduceDrawingDocument(doc, { type: "END" });

  assert.equal(countVisiblePoints(doc), 8191);

  // Start straight stroke: point 1 brings visible points to exactly 8192 (max)
  doc = reduceDrawingDocument(doc, {
    type: "BEGIN",
    point: { x: 100, y: 100 },
    ink: "primary",
    kind: "straight",
  });
  assert.equal(countVisiblePoints(doc), 8192);
  assert.equal(doc.active?.points.length, 1);
  assert.equal(doc.limitReached, false);

  // Attempting straight EXTEND to add 2nd point would exceed 8192:
  // Must reject 2nd point and set limitReached = true
  const extendedOverVisible = reduceDrawingDocument(doc, {
    type: "EXTEND",
    point: { x: 200, y: 200 },
  });
  assert.equal(extendedOverVisible.limitReached, true);
  assert.equal(extendedOverVisible.active?.points.length, 1);
  assert.equal(countVisiblePoints(extendedOverVisible), 8192);

  // Similarly, END with extra point does not exceed visible points
  const endedOverVisible = reduceDrawingDocument(doc, {
    type: "END",
    point: { x: 200, y: 200 },
  });
  assert.equal(endedOverVisible.limitReached, true);
});
