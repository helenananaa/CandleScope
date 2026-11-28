import { t } from "../../../i18n/index.js";
import type { DrawingHit, ScreenPoint } from "../drawingTypes.js";
import {
  anchoredVwap,
  calculationBars,
  fibExtensionLevels,
  fixedRangeVolumeProfile,
  regressionChannel,
  type CalculationBar,
} from "../geometry/calculatedDrawingMath.js";
import type {
  CalculatedDisplayRenderSpec,
  DrawingDisplayHitZone,
} from "../rendering/drawingDisplayList.js";
import type { CalculatedDrawingRenderEntity } from "../rendering/drawingRenderDefaults.js";

/**
 * Screen projection of calculated drawings. The scene projector supplies the
 * chart's bars and a time/price → screen projection; this module never reads
 * a chart directly, so a replay chart can only ever hand it revealed bars.
 */
export interface CalculatedProjectionContext {
  readonly seriesData: readonly unknown[];
  /** Null means the frame could not project; the caller retries later. */
  project(points: readonly Readonly<{ time: number; price: number }>[]): Float64Array | null;
  formatPrice(price: number): string;
  paintAlpha(color: string, alpha: number): string;
}

export interface CalculatedProjectionParts {
  readonly values: Float64Array;
  readonly handles: Float64Array;
  readonly handleNames: readonly string[];
  readonly handleResults: readonly (Readonly<DrawingHit> | null)[];
  readonly hitZones: readonly DrawingDisplayHitZone[];
  readonly renderSpec: CalculatedDisplayRenderSpec;
}

export const CALCULATED_PROJECTION_FAILED = "failed" as const;
export type CalculatedProjection = CalculatedProjectionParts | null | typeof CALCULATED_PROJECTION_FAILED;

const barsCache = new WeakMap<readonly unknown[], readonly CalculationBar[]>();

function barsFor(seriesData: readonly unknown[]): readonly CalculationBar[] {
  let bars = barsCache.get(seriesData);
  if (!bars) {
    bars = calculationBars(seriesData as readonly Record<string, unknown>[]);
    barsCache.set(seriesData, bars);
  }
  return bars;
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

class PointBuffer {
  readonly values: number[] = [];
  get count(): number {
    return this.values.length / 2;
  }
  push(...points: readonly ScreenPoint[]): number {
    const offset = this.count;
    for (const point of points) this.values.push(point.x, point.y);
    return offset;
  }
}

function pointAt(buffer: Float64Array, index: number): ScreenPoint | null {
  const x = buffer[index * 2];
  const y = buffer[index * 2 + 1];
  return finite(x) && finite(y) ? { x, y } : null;
}

interface Builder {
  readonly points: PointBuffer;
  readonly hitZones: DrawingDisplayHitZone[];
  readonly polygons: CalculatedDisplayRenderSpec["polygons"][number][];
  readonly boxes: CalculatedDisplayRenderSpec["boxes"][number][];
  readonly lines: CalculatedDisplayRenderSpec["lines"][number][];
  readonly labels: CalculatedDisplayRenderSpec["labels"][number][];
  handleOffset: number;
  handles: { point: ScreenPoint; name: string; pointIndex: number }[];
}

function createBuilder(): Builder {
  return { points: new PointBuffer(), hitZones: [], polygons: [], boxes: [], lines: [], labels: [], handleOffset: 0, handles: [] };
}

function bodyZone(kind: DrawingDisplayHitZone["kind"], name: string, pointOffset: number, pointCount: number, tolerance: number): DrawingDisplayHitZone {
  return Object.freeze({ kind, name, pointOffset, pointCount, tolerance, result: Object.freeze({ pointIndex: -1, zone: "body" }) });
}

function addLine(builder: Builder, entity: CalculatedDrawingRenderEntity, points: readonly ScreenPoint[], options: { dashed?: boolean; color?: string; width?: number; name: string; hit?: boolean }): number {
  const offset = builder.points.push(...points);
  builder.lines.push(Object.freeze({
    pointOffset: offset,
    pointCount: points.length,
    color: options.color ?? entity.style.color,
    widthCssPx: options.width ?? entity.style.lineWidth,
    dashed: options.dashed ?? false,
  }));
  if (options.hit !== false) {
    builder.hitZones.push(bodyZone("polyline", options.name, offset, points.length, 6 + entity.style.lineWidth / 2));
  }
  return offset;
}

function addLabel(builder: Builder, point: ScreenPoint, text: string, color: string, align: "left" | "right"): void {
  const offset = builder.points.push(point);
  builder.labels.push(Object.freeze({ pointOffset: offset, text, color, align }));
}

function finish(builder: Builder, entity: CalculatedDrawingRenderEntity, selected: boolean): CalculatedProjectionParts {
  // Handles go last and take priority over body zones in hit testing.
  const handleOffset = builder.points.push(...builder.handles.map((handle) => handle.point));
  const tolerance = 7 + entity.style.lineWidth;
  const handleZones = builder.handles.map((handle, index) => Object.freeze({
    kind: "point" as const,
    name: handle.name,
    pointOffset: handleOffset + index,
    pointCount: 1,
    tolerance,
    result: Object.freeze({ pointIndex: handle.pointIndex }),
  }));
  const values = new Float64Array(builder.points.values);
  return Object.freeze({
    values,
    handles: new Float64Array(builder.handles.flatMap((handle) => [handle.point.x, handle.point.y])),
    handleNames: Object.freeze(builder.handles.map((handle) => handle.name)),
    handleResults: Object.freeze(builder.handles.map(() => null)),
    hitZones: Object.freeze([...handleZones, ...builder.hitZones]),
    renderSpec: Object.freeze({
      op: "calculated" as const,
      calcType: entity.geometry.calcType,
      strokeColor: entity.style.color,
      lineWidthCssPx: entity.style.lineWidth,
      selected,
      handlePointOffset: handleOffset,
      handleCount: builder.handles.length,
      polygons: Object.freeze(builder.polygons),
      boxes: Object.freeze(builder.boxes),
      lines: Object.freeze(builder.lines),
      labels: Object.freeze(builder.labels),
    }),
  });
}

/** Anchors with a numeric time; calculated drawings live on ordinary time axes only. */
function timedAnchors(entity: CalculatedDrawingRenderEntity): readonly { time: number; price: number }[] | null {
  const anchors = entity.geometry.dataPoints.map((point) => ({ time: point.time, price: point.price }));
  return anchors.every((point) => finite(point.time) && finite(point.price))
    ? anchors as { time: number; price: number }[]
    : null;
}

function projectFibExtension(entity: CalculatedDrawingRenderEntity, context: CalculatedProjectionContext, selected: boolean): CalculatedProjection {
  const anchors = timedAnchors(entity);
  if (!anchors || anchors.length !== 3) return null;
  const [a, b, c] = anchors as [typeof anchors[0], typeof anchors[0], typeof anchors[0]];
  const levels = fibExtensionLevels(a.price, b.price, c.price);
  const projected = context.project([a, b, c, ...levels.map((level) => ({ time: c.time, price: level.price }))]);
  if (!projected) return CALCULATED_PROJECTION_FAILED;
  const screenA = pointAt(projected, 0);
  const screenB = pointAt(projected, 1);
  const screenC = pointAt(projected, 2);
  if (!screenA || !screenB || !screenC) return null;
  const builder = createBuilder();
  addLine(builder, entity, [screenA, screenB, screenC], { dashed: true, name: "trend", width: Math.max(1, entity.style.lineWidth / 2) });
  // Levels run right from C for as far as A→B spans on screen.
  const length = Math.max(48, Math.abs(screenB.x - screenA.x));
  levels.forEach((level, index) => {
    const y = projected[(3 + index) * 2 + 1];
    if (!finite(y)) return;
    const end = { x: screenC.x + length, y };
    addLine(builder, entity, [{ x: screenC.x, y }, end], { name: `level-${level.ratio}`, dashed: level.ratio === 0 });
    // Above the line's right end, so the label shows whenever the level does.
    addLabel(builder, end, `${level.ratio} (${context.formatPrice(level.price)})`, entity.style.color, "right");
  });
  builder.handles = [
    { point: screenA, name: "a", pointIndex: 0 },
    { point: screenB, name: "b", pointIndex: 1 },
    { point: screenC, name: "c", pointIndex: 2 },
  ];
  return finish(builder, entity, selected);
}

function projectAnchoredVwap(entity: CalculatedDrawingRenderEntity, context: CalculatedProjectionContext, selected: boolean): CalculatedProjection {
  const anchors = timedAnchors(entity);
  const anchor = anchors?.[0];
  if (!anchor) return null;
  const vwap = anchoredVwap(barsFor(context.seriesData), anchor.time);
  const first = vwap[0];
  const projected = context.project(first ? vwap : [anchor]);
  if (!projected) return CALCULATED_PROJECTION_FAILED;
  const builder = createBuilder();
  const head = pointAt(projected, 0);
  if (!head) return null;
  if (vwap.length >= 2) {
    const line: ScreenPoint[] = [];
    for (let index = 0; index < vwap.length; index += 1) {
      const point = pointAt(projected, index);
      if (point) line.push(point);
    }
    if (line.length >= 2) {
      addLine(builder, entity, line, { name: "vwap" });
      const last = vwap[vwap.length - 1]!;
      // Right-aligned so the label ends at the latest bar instead of running under the price axis.
      addLabel(builder, line[line.length - 1]!, t("drawing.calculated.vwapLabel", { price: context.formatPrice(last.price) }), entity.style.color, "right");
    }
  }
  builder.handles = [{ point: head, name: "anchor", pointIndex: 0 }];
  return finish(builder, entity, selected);
}

function emptyRange(entity: CalculatedDrawingRenderEntity, context: CalculatedProjectionContext, selected: boolean, anchors: readonly { time: number; price: number }[]): CalculatedProjection {
  const projected = context.project(anchors);
  if (!projected) return CALCULATED_PROJECTION_FAILED;
  const first = pointAt(projected, 0);
  const second = pointAt(projected, 1);
  if (!first || !second) return null;
  const builder = createBuilder();
  addLine(builder, entity, [first, second], { dashed: true, name: "range" });
  addLabel(builder, first, t("drawing.calculated.noBars"), entity.style.color, "left");
  builder.handles = [
    { point: first, name: "start", pointIndex: 0 },
    { point: second, name: "end", pointIndex: 1 },
  ];
  return finish(builder, entity, selected);
}

function projectVolumeProfile(entity: CalculatedDrawingRenderEntity, context: CalculatedProjectionContext, selected: boolean): CalculatedProjection {
  const anchors = timedAnchors(entity);
  if (!anchors || anchors.length !== 2) return null;
  const [a, b] = anchors as [typeof anchors[0], typeof anchors[0]];
  const profile = fixedRangeVolumeProfile(barsFor(context.seriesData), a.time, b.time, entity.style.rows);
  if (!profile) return emptyRange(entity, context, selected, anchors);
  const boundaries = [profile.low, ...profile.rows.map((row) => row.high)];
  const poc = profile.rows[profile.pocIndex]!;
  const pocPrice = (poc.low + poc.high) / 2;
  const projected = context.project([
    { time: profile.startTime, price: profile.high },
    { time: profile.endTime, price: profile.low },
    ...boundaries.map((price) => ({ time: profile.startTime, price })),
    { time: profile.startTime, price: pocPrice },
  ]);
  if (!projected) return CALCULATED_PROJECTION_FAILED;
  const topLeft = pointAt(projected, 0);
  const bottomRight = pointAt(projected, 1);
  if (!topLeft || !bottomRight) return null;
  const left = Math.min(topLeft.x, bottomRight.x);
  const right = Math.max(topLeft.x, bottomRight.x);
  const top = Math.min(topLeft.y, bottomRight.y);
  const bottom = Math.max(topLeft.y, bottomRight.y);
  const builder = createBuilder();
  const color = entity.style.color;
  // The whole range is one faint body so it can be picked between rows.
  const rangeOffset = builder.points.push({ x: left, y: top }, { x: right, y: bottom });
  builder.boxes.push(Object.freeze({ pointOffset: rangeOffset, fillColor: context.paintAlpha(color, 0.05) }));
  builder.hitZones.push(bodyZone("box", "range", rangeOffset, 2, 0));
  const maxVolume = Math.max(...profile.rows.map((row) => row.volume));
  const maxWidth = Math.max(24, (right - left) * 0.7);
  profile.rows.forEach((row, index) => {
    if (!(row.volume > 0) || !(maxVolume > 0)) return;
    const yLow = projected[(2 + index) * 2 + 1];
    const yHigh = projected[(3 + index) * 2 + 1];
    if (!finite(yLow) || !finite(yHigh)) return;
    const width = (row.volume / maxVolume) * maxWidth;
    // Leave a hairline between rows so neighbouring rows stay distinct.
    const gap = Math.abs(yLow - yHigh) > 3 ? 0.5 : 0;
    const offset = builder.points.push(
      { x: left, y: Math.min(yLow, yHigh) + gap },
      { x: left + width, y: Math.max(yLow, yHigh) - gap },
    );
    const alpha = index === profile.pocIndex ? 0.6 : row.inValueArea ? 0.38 : 0.18;
    builder.boxes.push(Object.freeze({ pointOffset: offset, fillColor: context.paintAlpha(color, alpha) }));
  });
  const pocY = projected[(2 + boundaries.length) * 2 + 1];
  if (finite(pocY)) {
    addLine(builder, entity, [{ x: left, y: pocY }, { x: right, y: pocY }], { name: "poc", dashed: true, width: 1, hit: false });
    addLabel(builder, { x: right, y: pocY }, t("drawing.calculated.pocLabel", { price: context.formatPrice(pocPrice) }), color, "left");
  }
  // Built from bars, so the profile is labelled as an estimate.
  addLabel(builder, { x: left, y: top - 4 }, t("drawing.calculated.profileEstimate", { count: profile.barCount }), color, "left");
  const startIndex = a.time <= b.time ? 0 : 1;
  builder.handles = [
    { point: { x: left, y: bottom }, name: "start", pointIndex: startIndex },
    { point: { x: right, y: bottom }, name: "end", pointIndex: 1 - startIndex },
  ];
  return finish(builder, entity, selected);
}

function projectRegressionChannel(entity: CalculatedDrawingRenderEntity, context: CalculatedProjectionContext, selected: boolean): CalculatedProjection {
  const anchors = timedAnchors(entity);
  if (!anchors || anchors.length !== 2) return null;
  const [a, b] = anchors as [typeof anchors[0], typeof anchors[0]];
  const channel = regressionChannel(barsFor(context.seriesData), a.time, b.time, entity.style.deviation);
  if (!channel) return emptyRange(entity, context, selected, anchors);
  const projected = context.project([
    { time: channel.startTime, price: channel.startPrice },
    { time: channel.endTime, price: channel.endPrice },
    { time: channel.startTime, price: channel.startPrice + channel.offset },
    { time: channel.endTime, price: channel.endPrice + channel.offset },
    { time: channel.endTime, price: channel.endPrice - channel.offset },
    { time: channel.startTime, price: channel.startPrice - channel.offset },
  ]);
  if (!projected) return CALCULATED_PROJECTION_FAILED;
  const points = [0, 1, 2, 3, 4, 5].map((index) => pointAt(projected, index));
  if (points.some((point) => point === null)) return null;
  const [midStart, midEnd, upperStart, upperEnd, lowerEnd, lowerStart] = points as ScreenPoint[];
  const builder = createBuilder();
  const polygonOffset = builder.points.push(upperStart!, upperEnd!, lowerEnd!, lowerStart!);
  builder.polygons.push(Object.freeze({ pointOffset: polygonOffset, pointCount: 4, fillColor: context.paintAlpha(entity.style.color, 0.08) }));
  builder.hitZones.push(bodyZone("polygon", "body", polygonOffset, 4, 0));
  addLine(builder, entity, [upperStart!, upperEnd!], { name: "upper" });
  addLine(builder, entity, [lowerStart!, lowerEnd!], { name: "lower" });
  addLine(builder, entity, [midStart!, midEnd!], { name: "middle", dashed: true });
  const startIndex = a.time <= b.time ? 0 : 1;
  builder.handles = [
    { point: midStart!, name: "start", pointIndex: startIndex },
    { point: midEnd!, name: "end", pointIndex: 1 - startIndex },
  ];
  return finish(builder, entity, selected);
}

export function projectCalculatedDrawing(
  entity: CalculatedDrawingRenderEntity,
  context: CalculatedProjectionContext,
  selected: boolean,
): CalculatedProjection {
  switch (entity.geometry.calcType) {
    case "fib-extension": return projectFibExtension(entity, context, selected);
    case "anchored-vwap": return projectAnchoredVwap(entity, context, selected);
    case "volume-profile": return projectVolumeProfile(entity, context, selected);
    case "regression-channel": return projectRegressionChannel(entity, context, selected);
  }
}
