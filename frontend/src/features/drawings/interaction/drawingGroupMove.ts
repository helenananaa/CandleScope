import { applyDrawingEntityDrag } from "./drawingEntityDrag.js";
import type { CaptureStroke } from "./freehandDrag.js";
import { parsePositionTimeRange } from "../drawingContracts.js";
import type { DrawingDragDescriptor } from "../drawingDragResizeController.js";
import type {
  DrawingDataPoint,
  DrawingDataToScreen,
  SavedDrawing,
  ScreenPoint,
  ScreenToDrawingData,
} from "../drawingTypes.js";

/**
 * Moving several drawings together (PL-4). Every member gets its ordinary
 * body-drag descriptor and the same screen delta, so a group keeps its shape
 * on any price scale and each kind keeps its own move rules. Members are
 * moved by the delta exactly; only the primary drawing decides snapping.
 */
export interface GroupMoveContext {
  readonly dataToScreen: DrawingDataToScreen;
  readonly screenToData: ScreenToDrawingData;
  readonly screenToDrawingData: ScreenToDrawingData;
  /** Freehand body drags need the overlay's capture identity. */
  readonly freehandDescriptor?: (saved: SavedDrawing, startMouse: ScreenPoint) => DrawingDragDescriptor | null;
  readonly captureStroke?: CaptureStroke;
}

export interface GroupMoveMember {
  readonly original: SavedDrawing;
  readonly descriptor: DrawingDragDescriptor;
}

export interface ScreenDelta {
  readonly dx: number;
  readonly dy: number;
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function points(saved: SavedDrawing): DrawingDataPoint[] | null {
  return "dataPoints" in saved && Array.isArray(saved.dataPoints) ? saved.dataPoints.map((point) => ({ ...point })) : null;
}

/** The body-drag descriptor this drawing's own drag would use, or null for a locked or unsupported drawing. */
export function groupMoveDescriptor(
  saved: SavedDrawing,
  startMouse: ScreenPoint,
  context: GroupMoveContext,
): DrawingDragDescriptor | null {
  if (!saved.id || saved.locked) return null;
  const id = saved.id;
  switch (saved.type) {
    case "line":
    case "fibonacci":
    case "range-measure":
    case "channel":
    case "path": {
      const origPoints = points(saved);
      return origPoints && origPoints.length > 0 ? { id, type: saved.type, pointIndex: -1, startMouse, origPoints } : null;
    }
    case "angle-measure": {
      const origPoints = points(saved);
      return origPoints && origPoints.length > 0 ? { id, type: "angle", pointIndex: -1, startMouse, origPoints } : null;
    }
    case "shape": {
      const origPoints = points(saved);
      return origPoints && origPoints.length >= 2 ? { id, type: "shape", zone: "body", startMouse, origPoints, origBox: null } : null;
    }
    case "text":
      return saved.dataPoint ? { id, type: "text", startMouse, origDataPoint: { ...saved.dataPoint } } : null;
    case "axis-line":
      return saved.dataPoint ? { id, type: "axis-line", zone: "center", startMouse, origDataPoint: { ...saved.dataPoint } } : null;
    case "position": {
      const origTimeRange = parsePositionTimeRange(saved.timeRange);
      if (!origTimeRange || !finite(saved.entryPrice)) return null;
      return {
        id,
        type: "position-move",
        startMouse,
        origEntry: saved.entryPrice,
        origTp: finite(saved.tpPrice) ? saved.tpPrice : null,
        origSl: finite(saved.slPrice) ? saved.slPrice : null,
        origTimeRange,
      };
    }
    case "freehand":
    case "highlighter":
      return context.freehandDescriptor?.(saved, startMouse) ?? null;
  }
  return null;
}

/** First anchor of a drawing in data space, used to snap the group. */
function snapAnchor(saved: SavedDrawing): DrawingDataPoint | null {
  if ("dataPoints" in saved && Array.isArray(saved.dataPoints) && saved.dataPoints[0]) return saved.dataPoints[0];
  if ((saved.type === "text" || saved.type === "axis-line") && saved.dataPoint) return saved.dataPoint;
  if (saved.type === "position" && finite(saved.entryPrice)) {
    const range = parsePositionTimeRange(saved.timeRange);
    const start = range?.start;
    if (start === undefined || start === null) return null;
    return typeof start === "number" ? { time: start, price: saved.entryPrice } : { ...start, price: saved.entryPrice } as DrawingDataPoint;
  }
  return null;
}

/**
 * Group snapping: with the magnet on, the primary drawing's first anchor
 * snaps to the nearest bar value and every member moves by that same
 * corrected delta, so the group keeps its shape and other drawings stay put.
 */
export function snappedGroupDelta(
  primary: SavedDrawing,
  raw: ScreenDelta,
  context: GroupMoveContext,
  snap: boolean,
): ScreenDelta {
  if (!snap) return raw;
  const anchor = snapAnchor(primary);
  const origin = anchor ? context.dataToScreen(anchor) : null;
  if (!origin || !finite(origin.x) || !finite(origin.y)) return raw;
  const snapped = context.screenToDrawingData(origin.x + raw.dx, origin.y + raw.dy, { snap: true });
  const target = snapped ? context.dataToScreen(snapped) : null;
  return target && finite(target.x) && finite(target.y)
    ? { dx: target.x - origin.x, dy: target.y - origin.y }
    : raw;
}

/** Every member moved by `delta`; null when any member cannot move, so a group never splits. */
export function groupMoveDrafts(
  members: readonly GroupMoveMember[],
  delta: ScreenDelta,
  context: GroupMoveContext,
): readonly SavedDrawing[] | null {
  if (!finite(delta.dx) || !finite(delta.dy)) return null;
  const drafts: SavedDrawing[] = [];
  for (const { original, descriptor } of members) {
    let pos: ScreenPoint = { x: descriptor.startMouse.x + delta.dx, y: descriptor.startMouse.y + delta.dy };
    if (descriptor.type === "axis-line") {
      // Axis lines follow the pointer position rather than a delta.
      const origin = context.dataToScreen(descriptor.origDataPoint);
      if (!origin) return null;
      pos = { x: origin.x + delta.dx, y: origin.y + delta.dy };
    }
    const draft = applyDrawingEntityDrag({
      descriptor,
      drawing: original,
      pos,
      screenToData: context.screenToData,
      screenToDrawingData: context.screenToDrawingData,
      dataToScreen: context.dataToScreen,
      snap: false,
      ...(context.captureStroke ? { captureStroke: context.captureStroke } : {}),
    });
    if (!draft) return null;
    drafts.push(draft);
  }
  return Object.freeze(drafts);
}
