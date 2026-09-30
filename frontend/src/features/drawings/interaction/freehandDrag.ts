import {
  appendFreehandStrokeCaptureBatch,
  cancelFreehandStrokeDraft,
  createFreehandStrokeDraft,
  finalizeFreehandStrokeDraft,
  resolveFreehandStrokePoints,
} from "../freehandStrokeModel.js";
import type {
  DrawingChartAdapter, DrawingDataToScreen, FreehandCaptureBatch,
  SavedFreehandDrawing, SavedHighlighterDrawing, ScreenPoint,
} from "../drawingTypes.js";

export type SavedStroke = SavedFreehandDrawing | SavedHighlighterDrawing;
export type CaptureStroke = (points: readonly ScreenPoint[]) => FreehandCaptureBatch | null;

/** Resolve every stored sample, never the decimated visible display list. */
export function projectStrokeForDrag(
  saved: SavedStroke,
  dataToScreen: DrawingDataToScreen,
  adapter: DrawingChartAdapter | null,
): readonly ScreenPoint[] | null {
  const stroke = saved.stroke;
  const frame = stroke && adapter?.captureDrawingFrame?.();
  const points = stroke
    ? resolveFreehandStrokePoints(stroke, {
        resolveTime: (time, _index, point) => dataToScreen({
          time, price: point.price,
          sourceProjection: stroke.sourceProjection,
          sourceProjectionConfig: stroke.sourceProjectionConfig,
        })?.x,
        resolveAnchor: (anchor, _index, point) => dataToScreen({
          time: anchor.time, sourceOrdinal: anchor.sourceOrdinal, price: point.price,
          sourceProjection: stroke.sourceProjection,
          sourceProjectionConfig: stroke.sourceProjectionConfig,
        })?.x,
        resolveSpan: (span) => frame && adapter?.projectDrawingFrameSourceLineageSpan?.(frame, {
          ...span, sourceProjection: stroke.sourceProjection,
          sourceProjectionConfig: stroke.sourceProjectionConfig,
        }),
      }).map((point) => {
        const y = point && adapter?.priceToCoordinate(point.price);
        return point && typeof y === "number" ? { x: point.x, y } : null;
      })
    : saved.dataPoints.map(dataToScreen);
  if (points.length < 2 || points.some((p) => !p || !Number.isFinite(p.x) || !Number.isFinite(p.y))) return null;
  return points as ScreenPoint[];
}

export function translateStroke(
  original: SavedStroke,
  points: readonly ScreenPoint[],
  delta: ScreenPoint,
  captureIdentity: unknown,
  capture: CaptureStroke,
): SavedStroke | null {
  if (original.locked || !Number.isFinite(delta.x) || !Number.isFinite(delta.y)) return null;
  if (delta.x === 0 && delta.y === 0) return original;
  const batch = capture(points.map((point) => ({ x: point.x + delta.x, y: point.y + delta.y })));
  if (!batch || batch.captureIdentity !== captureIdentity
    || !Array.isArray(batch.captures) || batch.captures.length !== points.length) return null;
  const draft = createFreehandStrokeDraft(batch);
  try {
    if (!appendFreehandStrokeCaptureBatch(draft, batch)) return null;
    const stroke = finalizeFreehandStrokeDraft(draft, { captureIdentity, preservePoints: true });
    if (!stroke || stroke.points.length !== points.length) return null;
    // Keep the legacy quadratic path contract; migration to linear stroke
    // rendering during a move would change the visible contour.
    if (original.dataPoints) {
      if (stroke.version !== 3 || stroke.points.some(point => "span" in point)) return null;
      const dataPoints = stroke.points.map(point => {
        if ("time" in point) return { time: point.time, price: point.price };
        if ("anchor" in point) return { ...point.anchor, price: point.price,
          sourceProjection: stroke.sourceProjection, sourceProjectionConfig: stroke.sourceProjectionConfig };
        return null;
      });
      if (dataPoints.some(point => point === null)) return null;
      return { ...original, dataPoints: dataPoints as NonNullable<SavedStroke["dataPoints"]> };
    }
    const { dataPoints: _oldPoints, ...rest } = original;
    return { ...rest, stroke } as SavedStroke;
  } finally {
    cancelFreehandStrokeDraft(draft);
  }
}
