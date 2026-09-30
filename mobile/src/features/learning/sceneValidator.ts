import type {
  CameraConfig,
  Edge3D,
  LearningVisualDescriptor,
  Scene3DDescriptor,
  StudioThemeColorKey,
  Vector2D,
  Vertex3D,
  Visualization2DDescriptor,
  VisualTableData,
} from "./types";

export type ValidationResult<T> =
  | { success: true; data: T }
  | { success: false; errors: string[] };

const VALID_THEME_COLOR_KEYS: Record<string, true> = {
  background: true,
  surface: true,
  surfaceElevated: true,
  input: true,
  text: true,
  mutedText: true,
  border: true,
  primary: true,
  primaryPressed: true,
  primarySoft: true,
  primaryDisabled: true,
  onPrimary: true,
  selectedBackground: true,
  success: true,
  successBackground: true,
  error: true,
  errorBackground: true,
};

const MAX_VERTICES = 32;
const MAX_EDGES = 64;
const MAX_VECTORS = 8;
const MAX_COORDINATE = 500;
const MIN_COORDINATE = -500;
const MAX_RADIUS = 50;
const MAX_THICKNESS = 20;
const MAX_DISTANCE = 2000;
const MAX_FOCAL = 2000;
const MAX_ZOOM = 10.0;
const MIN_ZOOM = 0.1;
const MAX_SCALE = 100;
const MIN_SCALE = 0.1;
const MAX_MAGNITUDE = 500;
const MAX_TABLE_HEADERS = 8;
const MAX_TABLE_ROWS = 32;

function isFiniteNumber(val: unknown): val is number {
  return typeof val === "number" && Number.isFinite(val);
}

function isValidColorToken(token: unknown): token is StudioThemeColorKey {
  return typeof token === "string" && VALID_THEME_COLOR_KEYS[token] === true;
}

function isSafeString(val: unknown, maxLen = 200): val is string {
  if (typeof val !== "string") {
    return false;
  }
  if (val.length === 0 || val.length > maxLen) {
    return false;
  }
  // Reject scripts, HTML tags, and remote protocols
  if (/<[a-z]|javascript:|data:|https?:/i.test(val)) {
    return false;
  }
  return true;
}

export function validateTableData(tableData: unknown): ValidationResult<VisualTableData> {
  if (!tableData || typeof tableData !== "object") {
    return { success: false, errors: ["tableData must be an object"] };
  }
  const t = tableData as Record<string, unknown>;
  const errors: string[] = [];

  if (!Array.isArray(t.headers) || t.headers.length === 0 || t.headers.length > MAX_TABLE_HEADERS) {
    errors.push(`tableData.headers must be an array between 1 and ${MAX_TABLE_HEADERS} items`);
    return { success: false, errors };
  }

  const validHeaders: string[] = [];
  for (let i = 0; i < t.headers.length; i++) {
    const h = t.headers[i];
    if (!isSafeString(h, 50)) {
      errors.push(`tableData.headers[${i}] must be a safe non-empty string <= 50 chars`);
    } else {
      validHeaders.push(h);
    }
  }

  if (!Array.isArray(t.rows) || t.rows.length === 0 || t.rows.length > MAX_TABLE_ROWS) {
    errors.push(`tableData.rows must be an array between 1 and ${MAX_TABLE_ROWS} items`);
    return { success: false, errors };
  }

  const validRows: Array<Array<string | number>> = [];
  for (let r = 0; r < t.rows.length; r++) {
    const row = t.rows[r];
    if (!Array.isArray(row)) {
      errors.push(`tableData.rows[${r}] must be an array`);
      continue;
    }
    if (row.length !== t.headers.length) {
      errors.push(`tableData.rows[${r}] length (${row.length}) does not match headers count (${t.headers.length})`);
      continue;
    }
    const validRow: Array<string | number> = [];
    for (let c = 0; c < row.length; c++) {
      const cell = row[c];
      if (typeof cell === "number") {
        if (!Number.isFinite(cell)) {
          errors.push(`tableData.rows[${r}][${c}] must be a finite number`);
        } else {
          validRow.push(cell);
        }
      } else if (typeof cell === "string") {
        if (!isSafeString(cell, 100)) {
          errors.push(`tableData.rows[${r}][${c}] must be a safe string <= 100 chars`);
        } else {
          validRow.push(cell);
        }
      } else {
        errors.push(`tableData.rows[${r}][${c}] must be a string or number`);
      }
    }
    validRows.push(validRow);
  }

  if (errors.length > 0) {
    return { success: false, errors };
  }

  return {
    success: true,
    data: {
      headers: validHeaders,
      rows: validRows,
    },
  };
}

export function validateCameraConfig(config: unknown): ValidationResult<CameraConfig> {
  if (!config || typeof config !== "object") {
    return { success: false, errors: ["Camera config must be an object"] };
  }
  const c = config as Record<string, unknown>;
  const errors: string[] = [];

  if (!isFiniteNumber(c.initialYawDeg) || c.initialYawDeg < -360 || c.initialYawDeg > 360) {
    errors.push("initialYawDeg must be between -360 and 360");
  }
  if (!isFiniteNumber(c.initialPitchDeg) || c.initialPitchDeg < -85 || c.initialPitchDeg > 85) {
    errors.push("initialPitchDeg must be between -85 and 85");
  }
  if (!isFiniteNumber(c.minPitchDeg) || c.minPitchDeg < -85 || c.minPitchDeg > 0) {
    errors.push("minPitchDeg must be between -85 and 0");
  }
  if (!isFiniteNumber(c.maxPitchDeg) || c.maxPitchDeg < 0 || c.maxPitchDeg > 85) {
    errors.push("maxPitchDeg must be between 0 and 85");
  }
  if (isFiniteNumber(c.minPitchDeg) && isFiniteNumber(c.maxPitchDeg) && c.minPitchDeg > c.maxPitchDeg) {
    errors.push("minPitchDeg must be <= maxPitchDeg");
  }
  if (
    isFiniteNumber(c.initialPitchDeg) &&
    isFiniteNumber(c.minPitchDeg) &&
    isFiniteNumber(c.maxPitchDeg) &&
    (c.initialPitchDeg < c.minPitchDeg || c.initialPitchDeg > c.maxPitchDeg)
  ) {
    errors.push("initialPitchDeg must be inside the pitch range");
  }

  if (!isFiniteNumber(c.initialZoom) || c.initialZoom <= 0 || c.initialZoom > MAX_ZOOM) {
    errors.push(`initialZoom must be between 0 and ${MAX_ZOOM}`);
  }
  if (!isFiniteNumber(c.minZoom) || c.minZoom < MIN_ZOOM || c.minZoom > 5.0) {
    errors.push(`minZoom must be between ${MIN_ZOOM} and 5.0`);
  }
  if (!isFiniteNumber(c.maxZoom) || c.maxZoom > MAX_ZOOM || (isFiniteNumber(c.minZoom) && c.maxZoom < c.minZoom)) {
    errors.push(`maxZoom must be between minZoom and ${MAX_ZOOM}`);
  }
  if (
    isFiniteNumber(c.initialZoom) &&
    isFiniteNumber(c.minZoom) &&
    isFiniteNumber(c.maxZoom) &&
    (c.initialZoom < c.minZoom || c.initialZoom > c.maxZoom)
  ) {
    errors.push("initialZoom must be inside the zoom range");
  }

  if (!isFiniteNumber(c.distance) || c.distance <= 0 || c.distance > MAX_DISTANCE) {
    errors.push(`distance must be between 0 and ${MAX_DISTANCE}`);
  }
  if (!isFiniteNumber(c.focalLength) || c.focalLength <= 0 || c.focalLength > MAX_FOCAL) {
    errors.push(`focalLength must be between 0 and ${MAX_FOCAL}`);
  }
  if (!isFiniteNumber(c.nearClip) || c.nearClip < 0 || (isFiniteNumber(c.distance) && c.nearClip >= c.distance)) {
    errors.push("nearClip must be non-negative and strictly less than distance");
  }

  if (errors.length > 0) {
    return { success: false, errors };
  }

  return {
    success: true,
    data: {
      initialYawDeg: c.initialYawDeg as number,
      initialPitchDeg: c.initialPitchDeg as number,
      minPitchDeg: c.minPitchDeg as number,
      maxPitchDeg: c.maxPitchDeg as number,
      initialZoom: c.initialZoom as number,
      minZoom: c.minZoom as number,
      maxZoom: c.maxZoom as number,
      distance: c.distance as number,
      focalLength: c.focalLength as number,
      nearClip: c.nearClip as number,
    },
  };
}

export function validateScene3D(descriptor: unknown): ValidationResult<Scene3DDescriptor> {
  if (!descriptor || typeof descriptor !== "object") {
    return { success: false, errors: ["Scene3D descriptor must be an object"] };
  }
  const d = descriptor as Record<string, unknown>;
  const errors: string[] = [];

  if (d.type !== "scene_3d") errors.push("type must be 'scene_3d'");
  if (!isSafeString(d.subject, 32)) errors.push("subject must be a valid string");
  if (!isSafeString(d.topicId, 32)) errors.push("topicId must be a valid string");
  if (!isSafeString(d.title, 100)) errors.push("title must be a valid string");
  if (!isSafeString(d.description, 300)) errors.push("description must be a valid string");
  if (!isSafeString(d.educationalSummary, 1000)) errors.push("educationalSummary must be a valid string");

  const cameraRes = validateCameraConfig(d.camera);
  if (!cameraRes.success) {
    errors.push(...cameraRes.errors);
  }

  if (!Array.isArray(d.vertices) || d.vertices.length === 0 || d.vertices.length > MAX_VERTICES) {
    errors.push(`vertices must be an array between 1 and ${MAX_VERTICES} items`);
  }

  const validVertices: Vertex3D[] = [];
  const vertexIdMap: Record<string, true> = {};

  if (Array.isArray(d.vertices)) {
    for (let i = 0; i < d.vertices.length; i++) {
      const v = d.vertices[i];
      if (!v || typeof v !== "object") {
        errors.push(`Vertex at index ${i} is not an object`);
        continue;
      }
      const vObj = v as Record<string, unknown>;
      if (!isSafeString(vObj.id, 32)) {
        errors.push(`Vertex at index ${i} has invalid id`);
      } else if (vertexIdMap[vObj.id as string]) {
        errors.push(`Duplicate vertex id: ${vObj.id}`);
      } else {
        vertexIdMap[vObj.id as string] = true;
      }

      if (!isFiniteNumber(vObj.x) || vObj.x < MIN_COORDINATE || vObj.x > MAX_COORDINATE) {
        errors.push(`Vertex ${vObj.id} x coordinate out of bounds`);
      }
      if (!isFiniteNumber(vObj.y) || vObj.y < MIN_COORDINATE || vObj.y > MAX_COORDINATE) {
        errors.push(`Vertex ${vObj.id} y coordinate out of bounds`);
      }
      if (!isFiniteNumber(vObj.z) || vObj.z < MIN_COORDINATE || vObj.z > MAX_COORDINATE) {
        errors.push(`Vertex ${vObj.id} z coordinate out of bounds`);
      }
      if (vObj.radius !== undefined) {
        if (!isFiniteNumber(vObj.radius) || vObj.radius <= 0 || vObj.radius > MAX_RADIUS) {
          errors.push(`Vertex ${vObj.id} radius must be between 0 and ${MAX_RADIUS}`);
        }
      }
      if (!isValidColorToken(vObj.colorToken)) {
        errors.push(`Vertex ${vObj.id} has invalid colorToken`);
      }

      if (errors.length === 0) {
        validVertices.push({
          id: vObj.id as string,
          x: vObj.x as number,
          y: vObj.y as number,
          z: vObj.z as number,
          radius: isFiniteNumber(vObj.radius) ? (vObj.radius as number) : undefined,
          colorToken: vObj.colorToken as StudioThemeColorKey,
          label: isSafeString(vObj.label, 32) ? (vObj.label as string) : undefined,
        });
      }
    }
  }

  if (!Array.isArray(d.edges) || d.edges.length > MAX_EDGES) {
    errors.push(`edges must be an array with at most ${MAX_EDGES} items`);
  }

  const validEdges: Edge3D[] = [];
  if (Array.isArray(d.edges)) {
    for (let i = 0; i < d.edges.length; i++) {
      const e = d.edges[i];
      if (!e || typeof e !== "object") {
        errors.push(`Edge at index ${i} is not an object`);
        continue;
      }
      const eObj = e as Record<string, unknown>;
      if (!isSafeString(eObj.id, 32)) {
        errors.push(`Edge at index ${i} has invalid id`);
      }
      if (typeof eObj.from !== "string" || !vertexIdMap[eObj.from]) {
        errors.push(`Edge ${eObj.id} references missing 'from' vertex: ${eObj.from}`);
      }
      if (typeof eObj.to !== "string" || !vertexIdMap[eObj.to]) {
        errors.push(`Edge ${eObj.id} references missing 'to' vertex: ${eObj.to}`);
      }
      if (eObj.thickness !== undefined) {
        if (!isFiniteNumber(eObj.thickness) || eObj.thickness <= 0 || eObj.thickness > MAX_THICKNESS) {
          errors.push(`Edge ${eObj.id} thickness must be between 0 and ${MAX_THICKNESS}`);
        }
      }
      if (!isValidColorToken(eObj.colorToken)) {
        errors.push(`Edge ${eObj.id} has invalid colorToken`);
      }

      if (errors.length === 0) {
        validEdges.push({
          id: eObj.id as string,
          from: eObj.from as string,
          to: eObj.to as string,
          thickness: isFiniteNumber(eObj.thickness) ? (eObj.thickness as number) : undefined,
          colorToken: eObj.colorToken as StudioThemeColorKey,
          style: eObj.style === "dashed" ? "dashed" : "solid",
        });
      }
    }
  }

  const tableRes = validateTableData(d.tableData);
  if (!tableRes.success) {
    errors.push(...tableRes.errors);
  }

  if (errors.length > 0 || !cameraRes.success || !tableRes.success) {
    return { success: false, errors };
  }

  return {
    success: true,
    data: {
      type: "scene_3d",
      subject: d.subject as Scene3DDescriptor["subject"],
      topicId: d.topicId as Scene3DDescriptor["topicId"],
      title: d.title as string,
      description: d.description as string,
      educationalSummary: d.educationalSummary as string,
      camera: cameraRes.data,
      vertices: validVertices,
      edges: validEdges,
      tableData: tableRes.data,
    },
  };
}

export function validateVisualization2D(descriptor: unknown): ValidationResult<Visualization2DDescriptor> {
  if (!descriptor || typeof descriptor !== "object") {
    return { success: false, errors: ["Visualization2D descriptor must be an object"] };
  }
  const d = descriptor as Record<string, unknown>;
  const errors: string[] = [];

  if (d.type !== "visualization_2d") errors.push("type must be 'visualization_2d'");
  if (!isSafeString(d.subject, 32)) errors.push("subject must be a valid string");
  if (!isSafeString(d.topicId, 32)) errors.push("topicId must be a valid string");
  if (!isSafeString(d.title, 100)) errors.push("title must be a valid string");
  if (!isSafeString(d.description, 300)) errors.push("description must be a valid string");
  if (!isSafeString(d.educationalSummary, 1000)) errors.push("educationalSummary must be a valid string");

  if (!d.origin || typeof d.origin !== "object") {
    errors.push("origin must be an object with finite x and y");
  } else {
    const o = d.origin as Record<string, unknown>;
    if (!isFiniteNumber(o.x) || o.x < MIN_COORDINATE || o.x > MAX_COORDINATE) {
      errors.push("origin.x must be a finite number within bounds");
    }
    if (!isFiniteNumber(o.y) || o.y < MIN_COORDINATE || o.y > MAX_COORDINATE) {
      errors.push("origin.y must be a finite number within bounds");
    }
  }

  if (!isFiniteNumber(d.scale) || d.scale < MIN_SCALE || d.scale > MAX_SCALE) {
    errors.push(`scale must be between ${MIN_SCALE} and ${MAX_SCALE}`);
  }

  if (!Array.isArray(d.vectors) || d.vectors.length === 0 || d.vectors.length > MAX_VECTORS) {
    errors.push(`vectors must be an array between 1 and ${MAX_VECTORS} items`);
  }

  const validVectors: Vector2D[] = [];
  let sumX = 0;
  let sumY = 0;

  if (Array.isArray(d.vectors)) {
    for (let i = 0; i < d.vectors.length; i++) {
      const v = d.vectors[i];
      if (!v || typeof v !== "object") {
        errors.push(`Vector at index ${i} is not an object`);
        continue;
      }
      const vObj = v as Record<string, unknown>;
      if (!isSafeString(vObj.id, 32)) errors.push(`Vector at index ${i} has invalid id`);
      if (!isSafeString(vObj.label, 64)) errors.push(`Vector ${vObj.id} has invalid label`);
      if (!isFiniteNumber(vObj.magnitude) || vObj.magnitude < 0 || vObj.magnitude > MAX_MAGNITUDE) {
        errors.push(`Vector ${vObj.id} magnitude must be between 0 and ${MAX_MAGNITUDE}`);
      }
      if (!isFiniteNumber(vObj.angleDeg) || vObj.angleDeg < -360 || vObj.angleDeg > 360) {
        errors.push(`Vector ${vObj.id} angleDeg must be between -360 and 360`);
      }
      if (!isValidColorToken(vObj.colorToken)) errors.push(`Vector ${vObj.id} has invalid colorToken`);
      if (!isFiniteNumber(vObj.xComp) || vObj.xComp < -MAX_MAGNITUDE || vObj.xComp > MAX_MAGNITUDE) {
        errors.push(`Vector ${vObj.id} xComp must be between -${MAX_MAGNITUDE} and ${MAX_MAGNITUDE}`);
      }
      if (!isFiniteNumber(vObj.yComp) || vObj.yComp < -MAX_MAGNITUDE || vObj.yComp > MAX_MAGNITUDE) {
        errors.push(`Vector ${vObj.id} yComp must be between -${MAX_MAGNITUDE} and ${MAX_MAGNITUDE}`);
      }

      // Check component consistency with magnitude and angle
      if (
        isFiniteNumber(vObj.magnitude) &&
        isFiniteNumber(vObj.angleDeg) &&
        isFiniteNumber(vObj.xComp) &&
        isFiniteNumber(vObj.yComp)
      ) {
        const rad = ((vObj.angleDeg as number) * Math.PI) / 180;
        const expX = (vObj.magnitude as number) * Math.cos(rad);
        const expY = (vObj.magnitude as number) * Math.sin(rad);
        if (Math.abs((vObj.xComp as number) - expX) > 1.0) {
          errors.push(`Vector ${vObj.id} xComp is inconsistent with magnitude and angleDeg`);
        }
        if (Math.abs((vObj.yComp as number) - expY) > 1.0) {
          errors.push(`Vector ${vObj.id} yComp is inconsistent with magnitude and angleDeg`);
        }
        sumX += vObj.xComp as number;
        sumY += vObj.yComp as number;
      }

      if (errors.length === 0) {
        validVectors.push({
          id: vObj.id as string,
          label: vObj.label as string,
          magnitude: vObj.magnitude as number,
          angleDeg: vObj.angleDeg as number,
          colorToken: vObj.colorToken as StudioThemeColorKey,
          xComp: vObj.xComp as number,
          yComp: vObj.yComp as number,
        });
      }
    }
  }

  // Validate optional resultant
  let validResultant: Visualization2DDescriptor["resultant"] | undefined;
  if (d.resultant !== undefined) {
    if (!d.resultant || typeof d.resultant !== "object") {
      errors.push("resultant must be an object");
    } else {
      const rObj = d.resultant as Record<string, unknown>;
      if (!isFiniteNumber(rObj.magnitude) || rObj.magnitude < 0 || rObj.magnitude > MAX_MAGNITUDE) {
        errors.push(`resultant.magnitude must be between 0 and ${MAX_MAGNITUDE}`);
      }
      if (!isFiniteNumber(rObj.angleDeg) || rObj.angleDeg < -360 || rObj.angleDeg > 360) {
        errors.push("resultant.angleDeg must be between -360 and 360");
      }
      if (!isValidColorToken(rObj.colorToken)) {
        errors.push("resultant.colorToken has invalid theme color key");
      }
      if (!isSafeString(rObj.label, 64)) {
        errors.push("resultant.label must be a safe string <= 64 chars");
      }

      // Check consistency with vector component sums
      if (isFiniteNumber(rObj.magnitude) && isFiniteNumber(rObj.angleDeg)) {
        const expectedNetMag = Math.hypot(sumX, sumY);
        if (Math.abs((rObj.magnitude as number) - expectedNetMag) > 1.5) {
          errors.push(`resultant.magnitude (${rObj.magnitude}) does not match vector component sum (${expectedNetMag.toFixed(1)})`);
        }
        const resultAngle = ((rObj.angleDeg as number) * Math.PI) / 180;
        const resultX = (rObj.magnitude as number) * Math.cos(resultAngle);
        const resultY = (rObj.magnitude as number) * Math.sin(resultAngle);
        if (Math.hypot(resultX - sumX, resultY - sumY) > 1.5) {
          errors.push("resultant direction does not match vector component sum");
        }
      }

      if (errors.length === 0) {
        validResultant = {
          magnitude: rObj.magnitude as number,
          angleDeg: rObj.angleDeg as number,
          colorToken: rObj.colorToken as StudioThemeColorKey,
          label: rObj.label as string,
        };
      }
    }
  }

  const tableRes = validateTableData(d.tableData);
  if (!tableRes.success) {
    errors.push(...tableRes.errors);
  }

  if (errors.length > 0 || !tableRes.success) {
    return { success: false, errors };
  }

  return {
    success: true,
    data: {
      type: "visualization_2d",
      subject: d.subject as Visualization2DDescriptor["subject"],
      topicId: d.topicId as Visualization2DDescriptor["topicId"],
      title: d.title as string,
      description: d.description as string,
      educationalSummary: d.educationalSummary as string,
      origin: d.origin as Visualization2DDescriptor["origin"],
      scale: d.scale as number,
      vectors: validVectors,
      resultant: validResultant,
      tableData: tableRes.data,
    },
  };
}

export function validateLearningDescriptor(
  descriptor: unknown,
): ValidationResult<LearningVisualDescriptor> {
  if (!descriptor || typeof descriptor !== "object") {
    return { success: false, errors: ["Descriptor must be an object"] };
  }
  const type = (descriptor as Record<string, unknown>).type;
  if (type === "scene_3d") {
    return validateScene3D(descriptor);
  }
  if (type === "visualization_2d") {
    return validateVisualization2D(descriptor);
  }
  return { success: false, errors: [`Unsupported descriptor type: '${type}'`] };
}
