import type { DrawingDataPoint, SavedDrawing } from "./drawingTypes.js";
import type { DrawingStylePatch } from "./drawingInteractionController.js";

export interface DrawingCoordinate {
  readonly time: number;
  readonly price: number;
}

export interface CoordinateDraft { time: string; price: string }
export function coordinateDraft(points: readonly DrawingCoordinate[]): CoordinateDraft[] {
  return points.map((point) => ({ time: formatCoordinateTime(point.time), price: String(point.price) }));
}
export function parseCoordinateDraft(draft: readonly CoordinateDraft[], original?: readonly DrawingCoordinate[]): DrawingCoordinate[] | null {
  const points: DrawingCoordinate[] = [];
  for (const [index, item] of draft.entries()) {
    const base = original?.[index];
    const time = base && item.time === formatCoordinateTime(base.time) ? base.time : parseCoordinateTime(item.time);
    if (time === null || !item.price.trim() || !Number.isFinite(Number(item.price))) return null;
    points.push({ time, price: Number(item.price) });
  }
  return points;
}

/** Only ordinary time anchors are editable here. Never reinterpret a lineage
 * ordinal or a legacy logical index as a timestamp. */
export function drawingCoordinates(saved: SavedDrawing): readonly DrawingCoordinate[] | null {
  let points: readonly DrawingDataPoint[];
  if (saved.type === "axis-line") points = saved.dataPoint ? [saved.dataPoint] : [];
  else if (saved.type === "line" || saved.type === "shape" || saved.type === "fibonacci" || saved.type === "angle-measure") points = saved.dataPoints ?? [];
  else return null;
  if (!points.length || points.length > 3 || points.some((point) =>
    typeof point.time !== "number" || !Number.isFinite(point.time) || !Number.isFinite(point.price)
    || point.logical !== undefined || point.sourceOrdinal !== undefined
    || point.sourceProjection !== undefined || point.sourceProjectionConfig !== undefined
    || !formatCoordinateTime(point.time))) return null;
  return points.map(({ time, price }) => ({ time: time as number, price }));
}

export function formatCoordinateTime(time: number): string {
  const date = new Date(time * 1000);
  if (!Number.isFinite(date.getTime()) || date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) return "";
  return date.toISOString().slice(0, -1);
}

export function parseCoordinateTime(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?$/.test(value)) return null;
  const normalized = value.length === 16 ? `${value}:00.000` : value.includes(".") ? value.padEnd(23, "0") : `${value}.000`;
  const time = Date.parse(`${normalized}Z`) / 1000;
  return Number.isFinite(time) && formatCoordinateTime(time) === normalized ? time : null;
}

export function sameCoordinates(left: readonly DrawingCoordinate[], right: readonly DrawingCoordinate[]): boolean {
  return left.length === right.length && left.every((point, index) => point.time === right[index]?.time && point.price === right[index]?.price);
}

/** Apply only supported properties to a copy; the codec validates the complete
 * candidate before any renderer or persistent document is changed. */
export function drawingPropertiesCandidate(
  saved: SavedDrawing,
  patch: DrawingStylePatch,
  coordinates?: readonly DrawingCoordinate[],
  expectedCoordinates?: readonly DrawingCoordinate[],
): SavedDrawing | null {
  const candidate = { ...saved } as SavedDrawing & DrawingStylePatch;
  if (patch.visibleIntervals !== undefined) candidate.visibleIntervals = patch.visibleIntervals;
  if (typeof patch.hidden === "boolean") candidate.hidden = patch.hidden;
  if (typeof patch.locked === "boolean") candidate.locked = patch.locked;
  if (typeof patch.color === "string" && "color" in saved) candidate.color = patch.color;
  if (typeof patch.lineWidth === "number" && "lineWidth" in saved) candidate.lineWidth = patch.lineWidth;
  if (saved.type === "highlighter" && typeof patch.opacity === "number") candidate.opacity = patch.opacity;
  if (saved.type === "shape") {
    if (typeof patch.fillColor === "string") candidate.fillColor = patch.fillColor;
    if (typeof patch.fillOpacity === "number") candidate.fillOpacity = patch.fillOpacity;
    if (patch.lineStyle) candidate.lineStyle = patch.lineStyle;
  }
  if (saved.type === "fibonacci" && patch.levels) candidate.levels = patch.levels;
  if (saved.type === "position" && typeof patch.positionSize === "number") candidate.positionSize = patch.positionSize;
  if (coordinates) {
    if (saved.locked) return null;
    const current = drawingCoordinates(saved);
    if (!current || coordinates.length !== current.length
      || (expectedCoordinates && !sameCoordinates(current, expectedCoordinates))
      || coordinates.some((point) => !Number.isFinite(point.price) || !formatCoordinateTime(point.time))) return null;
    if (candidate.type === "axis-line" && candidate.dataPoint && coordinates[0]) {
      candidate.dataPoint = { ...candidate.dataPoint, ...coordinates[0] };
    } else if (candidate.type === "line" || candidate.type === "shape" || candidate.type === "fibonacci" || candidate.type === "angle-measure") {
      candidate.dataPoints = (candidate.dataPoints ?? []).map((point, index) => ({ ...point, ...coordinates[index] }));
    } else return null;
  }
  return candidate;
}
