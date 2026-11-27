import { CALCULATED_ANCHOR_COUNT, isCalculatedToolId, nextDrawingId } from "../drawingModel.js";
import { normalizeSavedDrawingItemStrict } from "../drawingPersistence.js";
import type {
  CalculatedToolId,
  ChannelToolId,
  DrawingDataPoint,
  DrawingDataToScreen,
  DrawingToolId,
  SavedCalculatedDrawing,
  ScreenPoint,
} from "../drawingTypes.js";
import {
  anchoredVwap,
  calculationBars,
  fibExtensionLevels,
  fixedRangeVolumeProfile,
  regressionChannel,
  DEFAULT_REGRESSION_DEVIATION,
  DEFAULT_VOLUME_PROFILE_ROWS,
} from "../geometry/calculatedDrawingMath.js";
import type { DynamicOverlayDecoration } from "./dynamicOverlayController.js";

export interface CalculatedSelectionHandle {
  readonly point: ScreenPoint;
  readonly hit: Readonly<{ pointIndex: number }>;
  readonly radius: number;
}

/**
 * Selection handles from the scene projection. Range drawings put their start
 * handle on the earlier bar, which may be the second stored anchor.
 */
export function calculatedSelectionHandles(
  saved: SavedCalculatedDrawing,
  sceneHandles: readonly ScreenPoint[] | null,
): readonly CalculatedSelectionHandle[] {
  if (!sceneHandles || sceneHandles.length !== saved.dataPoints.length) return [];
  const [first, second] = saved.dataPoints;
  const swapped = sceneHandles.length === 2 && Number(first?.time) > Number(second?.time);
  return Object.freeze(sceneHandles.map((point, index) => Object.freeze({
    point: Object.freeze({ x: point.x, y: point.y }),
    hit: Object.freeze({ pointIndex: swapped ? 1 - index : index }),
    radius: 10,
  })));
}

/** Tools whose creation takes a third click after the first two anchors. */
export function isThreeClickCreationTool(
  tool: DrawingToolId | null | undefined,
): tool is ChannelToolId | "fib-extension" {
  return tool === "channel-parallel" || tool === "fib-extension";
}

export { isCalculatedToolId };

export interface CalculatedSavedDrawingOptions {
  readonly tool: CalculatedToolId;
  readonly dataPoints: readonly DrawingDataPoint[];
  readonly color: string;
  readonly lineWidth: number;
}

/**
 * Build a calculated drawing from creation clicks. Missing trailing anchors
 * repeat the last one, so a two-click preview of a fib extension is valid.
 */
export function createCalculatedSavedDrawing({
  tool,
  dataPoints,
  color,
  lineWidth,
}: CalculatedSavedDrawingOptions): (SavedCalculatedDrawing & { id: string }) | null {
  if (!isCalculatedToolId(tool) || !Array.isArray(dataPoints as unknown) || dataPoints.length === 0) return null;
  const wanted = CALCULATED_ANCHOR_COUNT[tool];
  const points = dataPoints.slice(0, wanted).map((point) => ({ ...point }));
  while (points.length < wanted) points.push({ ...points[points.length - 1]! });
  const candidate: SavedCalculatedDrawing = { type: "calculated", calcType: tool, dataPoints: points, color, lineWidth };
  const normalized = normalizeSavedDrawingItemStrict(candidate);
  if (!normalized || normalized.type !== "calculated") return null;
  const id = nextDrawingId("calc");
  const created = normalizeSavedDrawingItemStrict({ ...normalized, id });
  return created?.type === "calculated" && created.id === id
    ? created as SavedCalculatedDrawing & { id: string }
    : null;
}

const finitePoint = (point: ScreenPoint | null): point is ScreenPoint =>
  !!point && Number.isFinite(point.x) && Number.isFinite(point.y);

function line(from: ScreenPoint, to: ScreenPoint, color: string, lineWidth: number, dashed = false): DynamicOverlayDecoration {
  return Object.freeze({ type: "line", from: Object.freeze({ ...from }), to: Object.freeze({ ...to }), color, lineWidth, dashed });
}

/**
 * Dynamic-canvas preview while a calculated drawing is placed or dragged.
 * With the chart's bars it previews the real values; without them it falls
 * back to the anchors so the gesture still has feedback.
 */
export function calculatedDraftDecorations(
  saved: SavedCalculatedDrawing,
  dataToScreen: DrawingDataToScreen,
  seriesData: readonly unknown[] | null | undefined,
): readonly DynamicOverlayDecoration[] {
  const color = saved.color ?? "#3b82f6";
  const width = saved.lineWidth ?? 2;
  const anchors = saved.dataPoints.map((point) => dataToScreen(point));
  if (!anchors.every(finitePoint)) return [];
  const handles = Object.freeze(anchors.map((point) => Object.freeze({ ...point })));
  const decorations: DynamicOverlayDecoration[] = [Object.freeze({ type: "handles", handles, color })];
  const bars = Array.isArray(seriesData) ? calculationBars(seriesData as readonly Record<string, unknown>[]) : [];
  const project = (time: number, price: number) => dataToScreen({ time, price } as DrawingDataPoint);
  switch (saved.calcType) {
    case "fib-extension": {
      const [a, b, c] = anchors as [ScreenPoint, ScreenPoint, ScreenPoint];
      decorations.push(line(a, b, color, 1, true), line(b, c, color, 1, true));
      const [pa, pb, pc] = saved.dataPoints as [DrawingDataPoint, DrawingDataPoint, DrawingDataPoint];
      const length = Math.max(48, Math.abs(b.x - a.x));
      for (const level of fibExtensionLevels(pa.price, pb.price, pc.price)) {
        const point = typeof pc.time === "number" ? project(pc.time, level.price) : null;
        if (finitePoint(point)) decorations.push(line({ x: c.x, y: point.y }, { x: c.x + length, y: point.y }, color, width, level.ratio === 0));
      }
      break;
    }
    case "anchored-vwap": {
      const anchor = saved.dataPoints[0]!;
      const points = typeof anchor.time === "number"
        ? anchoredVwap(bars, anchor.time).map((point) => project(point.time, point.price)).filter(finitePoint)
        : [];
      if (points.length >= 2) {
        decorations.push(Object.freeze({
          type: "freehand", points: Object.freeze(points), color, lineWidth: width,
          opacity: 1, compositeOperation: "source-over", squareBrush: false, quadratic: false,
        }));
      }
      break;
    }
    case "volume-profile": {
      const [first, second] = saved.dataPoints as [DrawingDataPoint, DrawingDataPoint];
      const profile = typeof first.time === "number" && typeof second.time === "number"
        ? fixedRangeVolumeProfile(bars, first.time, second.time, saved.rows ?? DEFAULT_VOLUME_PROFILE_ROWS)
        : null;
      const left = Math.min(anchors[0]!.x, anchors[1]!.x);
      const right = Math.max(anchors[0]!.x, anchors[1]!.x);
      if (!profile) {
        decorations.push(line(anchors[0]!, anchors[1]!, color, 1, true));
        break;
      }
      const top = project(profile.startTime, profile.high);
      const bottom = project(profile.startTime, profile.low);
      if (finitePoint(top) && finitePoint(bottom)) {
        decorations.push(Object.freeze({ type: "box", box: Object.freeze({ x: left, y: top.y, width: right - left, height: bottom.y - top.y }), color, dashed: true }));
      }
      const maxVolume = Math.max(...profile.rows.map((row) => row.volume));
      for (const row of profile.rows) {
        if (!(row.volume > 0) || !(maxVolume > 0)) continue;
        const high = project(profile.startTime, row.high);
        const low = project(profile.startTime, row.low);
        if (!finitePoint(high) || !finitePoint(low)) continue;
        decorations.push(Object.freeze({
          type: "shape", shapeType: "rectangle", color, lineWidth: 0.5, fillColor: color, fillOpacity: row.inValueArea ? 0.35 : 0.15,
          box: Object.freeze({ x: left, y: high.y, width: (row.volume / maxVolume) * Math.max(24, (right - left) * 0.7), height: low.y - high.y }),
        }));
      }
      break;
    }
    case "regression-channel": {
      const [first, second] = saved.dataPoints as [DrawingDataPoint, DrawingDataPoint];
      const channel = typeof first.time === "number" && typeof second.time === "number"
        ? regressionChannel(bars, first.time, second.time, saved.deviation ?? DEFAULT_REGRESSION_DEVIATION)
        : null;
      if (!channel) {
        decorations.push(line(anchors[0]!, anchors[1]!, color, 1, true));
        break;
      }
      for (const [offset, dashed] of [[0, true], [channel.offset, false], [-channel.offset, false]] as const) {
        const from = project(channel.startTime, channel.startPrice + offset);
        const to = project(channel.endTime, channel.endPrice + offset);
        if (finitePoint(from) && finitePoint(to)) decorations.push(line(from, to, color, width, dashed));
      }
      break;
    }
  }
  return Object.freeze(decorations);
}
