import {
  DRAWING_LIMITS,
  DRAWING_UNITS,
  type DrawingAction,
  type DrawingDocument,
  type DrawingPoint,
  type DrawingStroke,
} from "./types";

/**
 * Creates a fresh, empty drawing document.
 */
export function createDrawingDocument(): DrawingDocument {
  return {
    strokes: [],
    active: null,
    past: [],
    future: [],
    nextStrokeId: 1,
    limitReached: false,
  };
}

/**
 * Maps screen/touch coordinates (locationX, locationY) within a layout viewport (width, height)
 * into uniform, square logical drawing coordinates [0, DRAWING_UNITS].
 *
 * Uses isotropic (1:1 aspect) scaling based on min(width, height) and centers the drawing area,
 * guaranteeing angles and geometric shapes (triangles, protractor) are preserved without distortion.
 */
export function toDrawingPoint(
  locationX: number,
  locationY: number,
  width: number,
  height: number,
): DrawingPoint | null {
  if (
    !Number.isFinite(locationX) ||
    !Number.isFinite(locationY) ||
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0
  ) {
    return null;
  }

  const side = Math.min(width, height);
  if (side <= 0) {
    return null;
  }

  const offsetX = (width - side) / 2;
  const offsetY = (height - side) / 2;

  // Relative position within the centered square
  const relX = locationX - offsetX;
  const relY = locationY - offsetY;

  // Clamp within square bounds [0, side]
  const clampedX = Math.max(0, Math.min(side, relX));
  const clampedY = Math.max(0, Math.min(side, relY));

  const x = Math.round((clampedX / side) * DRAWING_UNITS);
  const y = Math.round((clampedY / side) * DRAWING_UNITS);

  return { x, y };
}

/**
 * Calculates Euclidean distance between two points.
 */
export function distanceBetweenPoints(p1: DrawingPoint, p2: DrawingPoint): number {
  if (
    !Number.isFinite(p1.x) ||
    !Number.isFinite(p1.y) ||
    !Number.isFinite(p2.x) ||
    !Number.isFinite(p2.y)
  ) {
    return 0;
  }
  return Math.hypot(p2.x - p1.x, p2.y - p1.y);
}

/**
 * Calculates angle from p1 to p2 in degrees [0, 360).
 * 0° = right, 90° = down (screen coords), 180° = left, 270° = up.
 */
export function angleBetweenPoints(p1: DrawingPoint, p2: DrawingPoint): number {
  if (
    !Number.isFinite(p1.x) ||
    !Number.isFinite(p1.y) ||
    !Number.isFinite(p2.x) ||
    !Number.isFinite(p2.y)
  ) {
    return 0;
  }
  const rad = Math.atan2(p2.y - p1.y, p2.x - p1.x);
  let deg = (rad * 180) / Math.PI;
  if (deg < 0) {
    deg += 360;
  }
  return deg;
}

/**
 * Snaps current point to nearest angle step (default 15°) relative to start point.
 */
export function snapToAngle(
  start: DrawingPoint,
  current: DrawingPoint,
  snapStepDeg = 15,
): DrawingPoint {
  const dist = distanceBetweenPoints(start, current);
  if (dist === 0 || snapStepDeg <= 0) {
    return current;
  }

  const rawAngle = angleBetweenPoints(start, current);
  const snappedAngle = Math.round(rawAngle / snapStepDeg) * snapStepDeg;
  const rad = (snappedAngle * Math.PI) / 180;

  const snappedX = Math.round(start.x + Math.cos(rad) * dist);
  const snappedY = Math.round(start.y + Math.sin(rad) * dist);

  return {
    x: Math.max(0, Math.min(DRAWING_UNITS, snappedX)),
    y: Math.max(0, Math.min(DRAWING_UNITS, snappedY)),
  };
}

/**
 * Calculates protractor angle in degrees [0, 180] relative to a baseline angle.
 */
export function protractorAngle(
  center: DrawingPoint,
  point: DrawingPoint,
  baselineDeg = 0,
): number {
  const angle = angleBetweenPoints(center, point);
  let diff = Math.abs(angle - baselineDeg) % 360;
  if (diff > 180) {
    diff = 360 - diff;
  }
  return Math.round(diff);
}

/**
 * Derives an SVG path string from a stroke's points.
 * Uses midpoint quadratic Bézier curve smoothing for freehand strokes.
 */
export function strokePath(stroke: DrawingStroke): string {
  const pts = stroke.points;
  if (!pts || pts.length === 0) {
    return "";
  }

  const p0 = pts[0];
  if (pts.length === 1) {
    // Single point tap: short stub
    return `M ${p0.x} ${p0.y} L ${p0.x + 0.1} ${p0.y + 0.1}`;
  }

  if (stroke.kind === "straight") {
    const plast = pts[pts.length - 1];
    return `M ${p0.x} ${p0.y} L ${plast.x} ${plast.y}`;
  }

  // Freehand smoothing
  if (pts.length === 2) {
    return `M ${p0.x} ${p0.y} L ${pts[1].x} ${pts[1].y}`;
  }

  let path = `M ${p0.x} ${p0.y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const current = pts[i];
    const next = pts[i + 1];
    const midX = (current.x + next.x) / 2;
    const midY = (current.y + next.y) / 2;
    path += ` Q ${current.x} ${current.y} ${midX.toFixed(1)} ${midY.toFixed(1)}`;
  }

  const last = pts[pts.length - 1];
  path += ` L ${last.x} ${last.y}`;
  return path;
}

/**
 * Minimum distance between point P and line segment AB.
 */
function distanceToSegment(
  p: DrawingPoint,
  a: DrawingPoint,
  b: DrawingPoint,
): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lenSq = dx * dx + dy * dy;

  if (lenSq === 0) {
    return distanceBetweenPoints(p, a);
  }

  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq));
  const projX = a.x + t * dx;
  const projY = a.y + t * dy;

  return Math.hypot(p.x - projX, p.y - projY);
}

/**
 * Hit-test whether a point is within radius distance of any segment of a stroke.
 */
export function strokeNearPoint(
  stroke: DrawingStroke,
  point: DrawingPoint,
  radius = 25,
): boolean {
  const pts = stroke.points;
  if (!pts || pts.length === 0) {
    return false;
  }

  if (pts.length === 1) {
    return distanceBetweenPoints(point, pts[0]) <= radius;
  }

  if (stroke.kind === "straight") {
    return distanceToSegment(point, pts[0], pts[pts.length - 1]) <= radius;
  }

  for (let i = 0; i < pts.length - 1; i++) {
    if (distanceToSegment(point, pts[i], pts[i + 1]) <= radius) {
      return true;
    }
  }

  return false;
}

/**
 * Counts total points across an array of strokes.
 */
export function countPointsInStrokes(strokes: readonly DrawingStroke[]): number {
  let count = 0;
  for (const s of strokes) {
    count += s.points.length;
  }
  return count;
}

/**
 * Counts total points across a history array of stroke snapshots.
 */
export function countPointsInHistory(
  history: readonly (readonly DrawingStroke[])[],
): number {
  let count = 0;
  for (const entry of history) {
    for (const s of entry) {
      count += s.points.length;
    }
  }
  return count;
}

/**
 * Counts total points currently visible (committed strokes + active stroke).
 */
export function countVisiblePoints(doc: DrawingDocument): number {
  let count = countPointsInStrokes(doc.strokes);
  if (doc.active) {
    count += doc.active.points.length;
  }
  return count;
}

/**
 * Counts all points retained across current strokes, active stroke, and all past/future history.
 */
export function countRetainedPoints(doc: DrawingDocument): number {
  return (
    countVisiblePoints(doc) +
    countPointsInHistory(doc.past) +
    countPointsInHistory(doc.future)
  );
}

/**
 * Prunes past history array to satisfy maxHistoryEntries and maxRetainedPoints.
 */
function pruneHistoryToRetainedLimit(
  strokes: readonly DrawingStroke[],
  active: DrawingStroke | null,
  past: readonly (readonly DrawingStroke[])[],
  future: readonly (readonly DrawingStroke[])[],
): readonly (readonly DrawingStroke[])[] {
  let prunedPast = past;
  if (prunedPast.length > DRAWING_LIMITS.maxHistoryEntries) {
    prunedPast = prunedPast.slice(prunedPast.length - DRAWING_LIMITS.maxHistoryEntries);
  }

  const basePoints =
    countPointsInStrokes(strokes) +
    (active ? active.points.length : 0) +
    countPointsInHistory(future);

  while (
    basePoints + countPointsInHistory(prunedPast) > DRAWING_LIMITS.maxRetainedPoints &&
    prunedPast.length > 0
  ) {
    prunedPast = prunedPast.slice(1);
  }

  return prunedPast;
}

/**
 * Pure state reducer for drawing document actions.
 * Enforces all 5 DRAWING_LIMITS and budget invariants.
 */
export function reduceDrawingDocument(
  doc: DrawingDocument,
  action: DrawingAction,
): DrawingDocument {
  switch (action.type) {
    case "BEGIN": {
      // Reject BEGIN when an active stroke already exists
      if (doc.active) {
        return doc;
      }

      if (!Number.isFinite(action.point.x) || !Number.isFinite(action.point.y)) {
        return doc;
      }

      // Check max strokes limit
      if (doc.strokes.length >= DRAWING_LIMITS.maxStrokes) {
        return { ...doc, limitReached: true };
      }

      // Check visible points limit
      if (countVisiblePoints(doc) + 1 > DRAWING_LIMITS.maxVisiblePoints) {
        return { ...doc, limitReached: true };
      }

      // Check total retained budget
      if (countRetainedPoints(doc) + 1 > DRAWING_LIMITS.maxRetainedPoints) {
        if (doc.past.length > 0) {
          const trimmedPast = doc.past.slice(1);
          return reduceDrawingDocument(
            { ...doc, past: trimmedPast },
            action,
          );
        }
        return { ...doc, limitReached: true };
      }

      const point: DrawingPoint = {
        x: Math.max(0, Math.min(DRAWING_UNITS, action.point.x)),
        y: Math.max(0, Math.min(DRAWING_UNITS, action.point.y)),
      };

      const newStroke: DrawingStroke = {
        id: doc.nextStrokeId,
        kind: action.kind,
        ink: action.ink,
        points: [point],
      };

      return {
        ...doc,
        active: newStroke,
        nextStrokeId: doc.nextStrokeId + 1,
        limitReached: false,
      };
    }

    case "EXTEND": {
      if (!doc.active) {
        return doc;
      }
      if (!Number.isFinite(action.point.x) || !Number.isFinite(action.point.y)) {
        return doc;
      }

      const point: DrawingPoint = {
        x: Math.max(0, Math.min(DRAWING_UNITS, action.point.x)),
        y: Math.max(0, Math.min(DRAWING_UNITS, action.point.y)),
      };

      if (doc.active.kind === "straight") {
        const isAddingPoint = doc.active.points.length === 1;
        if (isAddingPoint) {
          // Check visible points limit
          if (countVisiblePoints(doc) + 1 > DRAWING_LIMITS.maxVisiblePoints) {
            return { ...doc, limitReached: true };
          }

          // Check total retained budget
          if (countRetainedPoints(doc) + 1 > DRAWING_LIMITS.maxRetainedPoints) {
            if (doc.past.length > 0) {
              const trimmedPast = doc.past.slice(1);
              return reduceDrawingDocument(
                { ...doc, past: trimmedPast },
                action,
              );
            }
            return { ...doc, limitReached: true };
          }
        }

        // Straight line only maintains start and current point
        const p0 = doc.active.points[0];
        return {
          ...doc,
          active: {
            ...doc.active,
            points: [p0, point],
          },
        };
      }

      // Freehand: check minimum distance to prevent duplicate clutter
      const last = doc.active.points[doc.active.points.length - 1];
      if (distanceBetweenPoints(last, point) < 2) {
        return doc;
      }

      // Check points per stroke limit
      if (doc.active.points.length >= DRAWING_LIMITS.maxPointsPerStroke) {
        return { ...doc, limitReached: true };
      }

      // Check visible points limit
      if (countVisiblePoints(doc) + 1 > DRAWING_LIMITS.maxVisiblePoints) {
        return { ...doc, limitReached: true };
      }

      // Check total retained budget
      if (countRetainedPoints(doc) + 1 > DRAWING_LIMITS.maxRetainedPoints) {
        if (doc.past.length > 0) {
          const trimmedPast = doc.past.slice(1);
          return reduceDrawingDocument(
            { ...doc, past: trimmedPast },
            action,
          );
        }
        return { ...doc, limitReached: true };
      }

      return {
        ...doc,
        active: {
          ...doc.active,
          points: [...doc.active.points, point],
        },
      };
    }

    case "END": {
      if (!doc.active) {
        return doc;
      }

      let finalActive = doc.active;
      let limitHit = doc.limitReached;

      if (
        action.point &&
        Number.isFinite(action.point.x) &&
        Number.isFinite(action.point.y)
      ) {
        const point: DrawingPoint = {
          x: Math.max(0, Math.min(DRAWING_UNITS, action.point.x)),
          y: Math.max(0, Math.min(DRAWING_UNITS, action.point.y)),
        };

        if (doc.active.kind === "straight") {
          const isAddingPoint = doc.active.points.length === 1;
          if (isAddingPoint) {
            if (countVisiblePoints(doc) + 1 > DRAWING_LIMITS.maxVisiblePoints) {
              limitHit = true;
            } else {
              finalActive = {
                ...doc.active,
                points: [doc.active.points[0], point],
              };
            }
          } else {
            finalActive = {
              ...doc.active,
              points: [doc.active.points[0], point],
            };
          }
        } else {
          // Freehand: check minimum distance and point limits before appending
          const last = doc.active.points[doc.active.points.length - 1];
          if (distanceBetweenPoints(last, point) >= 2) {
            if (
              doc.active.points.length < DRAWING_LIMITS.maxPointsPerStroke &&
              countVisiblePoints(doc) + 1 <= DRAWING_LIMITS.maxVisiblePoints
            ) {
              finalActive = {
                ...doc.active,
                points: [...doc.active.points, point],
              };
            } else {
              limitHit = true;
            }
          }
        }
      }

      if (finalActive.points.length === 0) {
        return { ...doc, active: null, limitReached: limitHit };
      }

      // Check maxStrokes limit
      if (doc.strokes.length >= DRAWING_LIMITS.maxStrokes) {
        return { ...doc, active: null, limitReached: true };
      }

      // Check visible points limit with finalActive
      const visibleAfter = countPointsInStrokes(doc.strokes) + finalActive.points.length;
      if (visibleAfter > DRAWING_LIMITS.maxVisiblePoints) {
        return { ...doc, active: null, limitReached: true };
      }

      const candidateStrokes = [...doc.strokes, finalActive];

      // Prune past history to stay within budget
      const prunedPast = pruneHistoryToRetainedLimit(
        candidateStrokes,
        null,
        [...doc.past, doc.strokes],
        [],
      );

      // If cannot fit within retained budget even with empty past, do not append stroke and flag limitReached
      if (
        countPointsInStrokes(candidateStrokes) + countPointsInHistory(prunedPast) >
        DRAWING_LIMITS.maxRetainedPoints
      ) {
        return { ...doc, active: null, limitReached: true };
      }

      return {
        ...doc,
        strokes: candidateStrokes,
        active: null,
        past: prunedPast,
        future: [],
        limitReached: limitHit,
      };
    }

    case "CANCEL": {
      return {
        ...doc,
        active: null,
        limitReached: false,
      };
    }

    case "ERASE_AT": {
      if (!Number.isFinite(action.point.x) || !Number.isFinite(action.point.y)) {
        return doc;
      }

      const remainingStrokes = doc.strokes.filter(
        (s) => !strokeNearPoint(s, action.point, 25),
      );

      // If nothing erased, no-op
      if (remainingStrokes.length === doc.strokes.length) {
        return doc;
      }

      // Prune past history to stay within budget
      const prunedPast = pruneHistoryToRetainedLimit(
        remainingStrokes,
        doc.active,
        [...doc.past, doc.strokes],
        [],
      );

      return {
        ...doc,
        strokes: remainingStrokes,
        past: prunedPast,
        future: [],
        limitReached: doc.limitReached,
      };
    }

    case "UNDO": {
      if (doc.past.length === 0) {
        return doc;
      }

      const previousStrokes = doc.past[doc.past.length - 1];
      const newPast = doc.past.slice(0, -1);
      const newFuture = [doc.strokes, ...doc.future];

      return {
        ...doc,
        strokes: previousStrokes,
        active: null,
        past: newPast,
        future: newFuture,
        limitReached: false,
      };
    }

    case "REDO": {
      if (doc.future.length === 0) {
        return doc;
      }

      const nextStrokes = doc.future[0];
      const newFuture = doc.future.slice(1);

      // Prune past history to stay within budget
      const prunedPast = pruneHistoryToRetainedLimit(
        nextStrokes,
        null,
        [...doc.past, doc.strokes],
        newFuture,
      );

      return {
        ...doc,
        strokes: nextStrokes,
        active: null,
        past: prunedPast,
        future: newFuture,
        limitReached: false,
      };
    }

    case "CLEAR": {
      if (doc.strokes.length === 0 && !doc.active) {
        return doc;
      }

      // Clear is undoable: preserve current strokes in past history
      const prunedPast = pruneHistoryToRetainedLimit(
        [],
        null,
        [...doc.past, doc.strokes],
        [],
      );

      return {
        ...doc,
        strokes: [],
        active: null,
        past: prunedPast,
        future: [],
        limitReached: false,
      };
    }

    default:
      return doc;
  }
}
