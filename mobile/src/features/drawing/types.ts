/** Temporary drawing coordinates use a square, uniform 1000-unit canvas. */
export const DRAWING_UNITS = 1000;

export const DRAWING_LIMITS = {
  maxStrokes: 96,
  maxPointsPerStroke: 256,
  maxVisiblePoints: 8192,
  maxRetainedPoints: 32768,
  maxHistoryEntries: 24,
} as const;

export type DrawingPoint = Readonly<{ x: number; y: number }>;
export type DrawingInk = "ink" | "primary" | "success" | "error";
export type DrawingTool = "pen" | "eraser" | "ruler" | "protractor";

export type DrawingStroke = Readonly<{
  id: number;
  kind: "freehand" | "straight";
  ink: DrawingInk;
  points: readonly DrawingPoint[];
}>;

export type DrawingDocument = Readonly<{
  strokes: readonly DrawingStroke[];
  active: DrawingStroke | null;
  past: readonly (readonly DrawingStroke[])[];
  future: readonly (readonly DrawingStroke[])[];
  nextStrokeId: number;
  limitReached: boolean;
}>;

export type DrawingAction =
  | { type: "BEGIN"; point: DrawingPoint; ink: DrawingInk; kind: "freehand" | "straight" }
  | { type: "EXTEND"; point: DrawingPoint }
  | { type: "END"; point?: DrawingPoint }
  | { type: "CANCEL" }
  | { type: "ERASE_AT"; point: DrawingPoint }
  | { type: "UNDO" }
  | { type: "REDO" }
  | { type: "CLEAR" };

export type DrawingScope = Readonly<{
  userId: string;
  mode: "room" | "solo";
  sessionId: string;
  questionId: string;
}>;

export type DrawingPhase = "answer-open" | "read-only" | "closed";
