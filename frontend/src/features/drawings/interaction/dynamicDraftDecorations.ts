/**
 * Dynamic-canvas drafts and selected-handle affordances for overlay drawings.
 * Split from drawingInteractionController.ts; the controller re-exports these.
 */
import type { DrawingFrameThemePalette } from "../../../chart-adapter/drawingFrameSnapshot.js";
import { DEFAULT_DRAWING_POSITION_THEME_PALETTE } from "../drawingPositionColors.js";
import { serializeDrawingPrimitive } from "../drawingPersistence.js";
import type {
  DrawingDataPoint,
  DrawingDataToScreen,
  DrawingHit,
  DrawingPrimitive,
  PersistableDrawingPrimitive,
  SavedDrawing,
  ScreenBox,
  ScreenPoint,
} from "../drawingTypes.js";
import { parallelChannelScreenGeometry } from "../geometry/drawingToolGeometry.js";
import { measureDrawingRange, rangeMeasurementLabel } from "../rangeMeasurement.js";
import { DEFAULT_FIBONACCI_RENDER_LEVELS } from "../rendering/drawingRenderDefaults.js";
import { calculatedSelectionHandles } from "./drawingCalculatedInteraction.js";
import { textAnnotationDraftDecorations } from "./drawingTextAnnotations.js";
import {
  buildAngleDynamicOverlayDecoration,
  type DynamicOverlayDecoration,
} from "./dynamicOverlayController.js";
import { buildDynamicPositionOverlayDecoration } from "./dynamicPositionOverlay.js";
import type { SavedStroke } from "./freehandDrag.js";

function dataPointFromSavedHorizontalAnchor(
  anchor: unknown,
  price: unknown,
): DrawingDataPoint | null {
  if (typeof price !== "number" || !Number.isFinite(price)) return null;
  if (typeof anchor === "number" && Number.isFinite(anchor)) return { time: anchor, price };
  if (!anchor || typeof anchor !== "object") return null;
  return { ...(anchor as Record<string, unknown>), price } as DrawingDataPoint;
}

/** Project one canonical interaction draft into cheap dynamic-canvas commands. */
export function dynamicDecorationsForSavedDrawingDraft(
  saved: SavedDrawing,
  dataToScreen: DrawingDataToScreen,
  themePalette: DrawingFrameThemePalette = DEFAULT_DRAWING_POSITION_THEME_PALETTE,
  currentPrice: number | null = null,
  projectStroke?: (saved: SavedStroke) => readonly ScreenPoint[] | null,
): readonly DynamicOverlayDecoration[] {
  const color = "color" in saved && typeof saved.color === "string"
    ? saved.color
    : "#3b82f6";
  const lineWidth = "lineWidth" in saved && typeof saved.lineWidth === "number"
    ? saved.lineWidth
    : 2;
  if (saved.type === "freehand" || saved.type === "highlighter") {
    const points = projectStroke?.(saved);
    if (!points) return [];
    const highlighter = saved.type === "highlighter";
    return [{ type: "freehand", points, color, lineWidth, quadratic: !saved.stroke,
      opacity: highlighter ? saved.opacity ?? 0.35 : 1,
      compositeOperation: highlighter ? saved.compositeOperation ?? "multiply" : "source-over",
      squareBrush: highlighter && (saved.brushShape ?? "square") === "square",
    }];
  }
  if ("dataPoints" in saved && Array.isArray(saved.dataPoints)) {
    const projected = saved.dataPoints
      .map((point) => dataToScreen(point))
      .filter((point): point is ScreenPoint => point !== null);
    if (projected.length < 2) return [];
    const first = projected[0];
    const last = projected.at(-1);
    if (!first || !last) return [];
    if (saved.type === "path") {
      if (projected.length !== saved.dataPoints.length) return [];
      const tip = projected[projected.length - 1]!;
      let headSegment = projected.length - 2;
      while (headSegment >= 0 && projected[headSegment]!.x === tip.x && projected[headSegment]!.y === tip.y) headSegment--;
      return projected.slice(1).map((to, i) => ({ type: "line" as const, from: projected[i]!, to, color, lineWidth,
        arrowEnd: saved.arrowEnd === true && i === headSegment, handles: i === 0 ? projected : [] }));
    }
    if (saved.type === "channel") {
      const channel = parallelChannelScreenGeometry(projected[0], projected[1], projected[2]);
      if (!channel) return [];
      const [start, end] = channel.baseline;
      const [parallelStart, parallelEnd] = channel.parallel;
      return Object.freeze([
        Object.freeze({ type: "line" as const, from: start, to: end, color, lineWidth, handles: Object.freeze([start, end, channel.offsetHandle]) }),
        Object.freeze({ type: "line" as const, from: parallelStart, to: parallelEnd, color, lineWidth }),
        Object.freeze({ type: "line" as const, from: channel.midline[0], to: channel.midline[1], color, lineWidth: Math.max(1, lineWidth / 2), dashed: true }),
      ]);
    }
    if (saved.type === "shape") {
      return [Object.freeze({
        type: "shape",
        box: Object.freeze({
          x: Math.min(first.x, last.x),
          y: Math.min(first.y, last.y),
          width: Math.abs(last.x - first.x),
          height: Math.abs(last.y - first.y),
        }),
        shapeType: saved.shapeType ?? "rectangle",
        color,
        lineWidth,
        ...(saved.fillColor !== undefined ? { fillColor: saved.fillColor } : {}),
        ...(saved.fillOpacity !== undefined ? { fillOpacity: saved.fillOpacity } : {}),
        dashed: saved.lineStyle !== undefined && saved.lineStyle !== "solid",
        handles: Object.freeze([first, last]),
      })];
    }
    if (saved.type === "fibonacci") {
      const minX = Math.min(first.x, last.x);
      const maxX = Math.max(first.x, last.x);
      const startY = saved.inverted ? last.y : first.y;
      const endY = saved.inverted ? first.y : last.y;
      const firstPrice = saved.dataPoints[0]?.price;
      const lastPrice = saved.dataPoints.at(-1)?.price;
      const hasPrices = typeof firstPrice === "number"
        && Number.isFinite(firstPrice)
        && typeof lastPrice === "number"
        && Number.isFinite(lastPrice);
      const startPrice = saved.inverted ? lastPrice : firstPrice;
      const endPrice = saved.inverted ? firstPrice : lastPrice;
      const levels = (saved.levels ?? DEFAULT_FIBONACCI_RENDER_LEVELS)
        .flatMap((level) => {
          if (!level.enabled || !Number.isFinite(level.level)) return [];
          const y = startY + (endY - startY) * level.level;
          const logicalPrice = hasPrices
            ? (startPrice as number) + ((endPrice as number) - (startPrice as number)) * level.level
            : null;
          return [Object.freeze({
            color: level.color,
            line: Object.freeze([
              Object.freeze({ x: minX, y }),
              Object.freeze({ x: maxX, y }),
            ] as const),
            ...(logicalPrice === null
              ? {}
              : {
                  label: Object.freeze({
                    anchor: Object.freeze({ x: minX + 4, y: y - 2 }),
                    text: `${level.level} (${logicalPrice.toFixed(2)})`,
                  }),
                }),
          })];
        })
        .sort((left, right) => left.line[0].y - right.line[0].y);
      return Object.freeze([
        Object.freeze({
          type: "fibonacci" as const,
          trend: Object.freeze([first, last] as const),
          color,
          lineWidth,
          levels: Object.freeze(levels),
          handles: Object.freeze([first, last]),
        }),
      ]);
    }
    if (saved.type === "range-measure") {
      const measurement = measureDrawingRange(saved.dataPoints);
      if (!measurement) return [];
      const corner = Object.freeze({ x: last.x, y: first.y });
      const label = Object.freeze({
        anchor: Object.freeze({ x: (first.x + last.x) / 2, y: Math.min(first.y, last.y) - 12 }),
        text: rangeMeasurementLabel(measurement, saved.measureType),
      });
      return [
        Object.freeze({ type: "box", box: { x: Math.min(first.x, last.x), y: Math.min(first.y, last.y), width: Math.abs(last.x - first.x), height: Math.abs(last.y - first.y) }, color, dashed: true }),
        Object.freeze({ type: "line", from: first, to: corner, color, lineWidth, dashed: saved.measureType === "price", label, handles: Object.freeze([first, last]) }),
        Object.freeze({ type: "line", from: corner, to: last, color, lineWidth, dashed: saved.measureType === "time" }),
      ];
    }
    if (saved.type === "angle-measure") {
      const decoration = buildAngleDynamicOverlayDecoration(
        first,
        last,
        color,
        lineWidth,
        true,
      );
      return decoration ? Object.freeze([decoration]) : [];
    }
    return [Object.freeze({
      type: "line",
      from: first,
      to: last,
      color,
      lineWidth,
      ...(saved.type === "line" ? { extension: saved.lineType ?? "line-segment" } : {}),
      ...(saved.type === "line" && saved.arrowEnd && (saved.lineType ?? "line-segment") === "line-segment"
        ? { arrowEnd: true }
        : {}),
      handles: Object.freeze([first, last]),
    })];
  }
  if (saved.type === "axis-line" && saved.dataPoint) {
    const point = dataToScreen(saved.dataPoint);
    return point ? [Object.freeze({
      type: "axis-line",
      point,
      axisLineType: saved.axisLineType ?? "horizontal",
      color,
      lineWidth,
      handles: Object.freeze([point]),
    })] : [];
  }
  if (saved.type === "text" && (saved.target || saved.priceLabel)) {
    return textAnnotationDraftDecorations(saved, dataToScreen, color);
  }
  if (saved.type === "text" && saved.dataPoint) {
    const point = dataToScreen(saved.dataPoint);
    if (!point) return [];
    return [Object.freeze({
      type: "box",
      box: Object.freeze({
        x: point.x,
        y: point.y - (saved.fontSize ?? 14),
        width: saved.widthPx ?? 96,
        height: (saved.fontSize ?? 14) + (saved.padding ?? 6) * 2,
      }),
      color,
      dashed: false,
    })];
  }
  if (saved.type === "position" && saved.timeRange) {
    const decoration = buildDynamicPositionOverlayDecoration(
      saved,
      dataToScreen,
      themePalette,
      currentPrice,
    );
    return decoration ? Object.freeze([decoration]) : [];
  }
  return [];
}

/**
 * Publish the complete interaction frame before a canonical create command can
 * invalidate the static scene. The returned commit result is intentionally
 * opaque so the ordering boundary stays directly testable without React.
 */
export function commitSavedDrawingAfterDynamicFrame<T>(
  saved: SavedDrawing,
  dataToScreen: DrawingDataToScreen,
  renderDynamicFrame: (decorations: readonly DynamicOverlayDecoration[]) => void,
  commit: () => T,
  themePalette: DrawingFrameThemePalette = DEFAULT_DRAWING_POSITION_THEME_PALETTE,
  currentPrice: number | null = null,
): T {
  const decorations = dynamicDecorationsForSavedDrawingDraft(
    saved,
    dataToScreen,
    themePalette,
    currentPrice,
  );
  if (decorations.length > 0) renderDynamicFrame(decorations);
  return commit();
}

/** Transitional primitive wrapper retained for the legacy interaction surface. */
export function dynamicDecorationsForDrawingDraft(
  primitive: DrawingPrimitive,
  dataToScreen: DrawingDataToScreen,
  themePalette: DrawingFrameThemePalette = DEFAULT_DRAWING_POSITION_THEME_PALETTE,
  currentPrice: number | null = null,
): readonly DynamicOverlayDecoration[] {
  const saved = serializeDrawingPrimitive(
    primitive as unknown as PersistableDrawingPrimitive,
  );
  return saved
    ? dynamicDecorationsForSavedDrawingDraft(saved, dataToScreen, themePalette, currentPrice)
    : [];
}

const DYNAMIC_BOX_HANDLE_NAMES = ["tl", "t", "tr", "r", "br", "b", "bl", "l"] as const;

export interface DynamicSelectionHandleSpec {
  readonly point: ScreenPoint;
  readonly hit: DrawingHit;
  readonly radius: number;
}

function dynamicBoxSelectionHandles(box: ScreenBox): readonly DynamicSelectionHandleSpec[] {
  const left = box.x;
  const top = box.y;
  const right = left + box.width;
  const bottom = top + box.height;
  const middleX = left + box.width / 2;
  const middleY = top + box.height / 2;
  const points = [
    { x: left, y: top },
    { x: middleX, y: top },
    { x: right, y: top },
    { x: right, y: middleY },
    { x: right, y: bottom },
    { x: middleX, y: bottom },
    { x: left, y: bottom },
    { x: left, y: middleY },
  ] as const;
  return Object.freeze(points.map((point, index) => {
    const handle = DYNAMIC_BOX_HANDLE_NAMES[index];
    if (!handle) throw new RangeError("Dynamic selection handle index is invalid");
    return Object.freeze({
      point: Object.freeze(point),
      hit: Object.freeze({ handle, zone: handle, pointIndex: -1 }),
      radius: 9,
    });
  }));
}

/** Exact selected-handle affordances owned by the Phase 5 overlay. */
export function dynamicSelectionHandlesForSavedDrawing(
  saved: SavedDrawing,
  dataToScreen: DrawingDataToScreen,
  screenBox: ScreenBox | null = null,
  sceneHandles: readonly ScreenPoint[] | null = null,
  positionBarSpacing: number | null = null,
): readonly DynamicSelectionHandleSpec[] {
  if (saved.locked) return [];
  if ((saved.type === "text" || saved.type === "shape") && screenBox) {
    const handles = dynamicBoxSelectionHandles(screenBox);
    const target = saved.type === "text" && saved.target && !saved.priceLabel
      ? dataToScreen(saved.target)
      : null;
    return target
      ? Object.freeze([...handles, Object.freeze({
          point: Object.freeze({ x: target.x, y: target.y }),
          hit: Object.freeze({ zone: "target", pointIndex: 1 }),
          radius: 9,
        })])
      : handles;
  }
  if (saved.type === "freehand" || saved.type === "highlighter" || saved.type === "text") {
    return [];
  }
  if (saved.type === "position" && saved.timeRange) {
    const positionZones: Array<
      "entry" | "tp" | "sl" | "left" | "right"
      | "top-left" | "top-right" | "bottom-left" | "bottom-right"
    > = ["entry"];
    if (typeof saved.tpPrice === "number" && Number.isFinite(saved.tpPrice)) {
      positionZones.push("tp");
    }
    if (typeof saved.slPrice === "number" && Number.isFinite(saved.slPrice)) {
      positionZones.push("sl");
    }
    positionZones.push("left", "right");
    if (typeof saved.tpPrice === "number" && Number.isFinite(saved.tpPrice)
      && typeof saved.slPrice === "number" && Number.isFinite(saved.slPrice)) {
      positionZones.push("top-left", "top-right", "bottom-left", "bottom-right");
    }
    if (sceneHandles?.length === positionZones.length) {
      return Object.freeze(sceneHandles.map((point, index) => {
        const zone = positionZones[index];
        if (!zone) throw new RangeError("Position scene handle index is invalid");
        return Object.freeze({
          point: Object.freeze({ x: point.x, y: point.y }),
          hit: Object.freeze({ zone, pointIndex: -1 }),
          radius: zone === "left" || zone === "right" ? 10 : 9,
        });
      }));
    }
    const entryStart = dataPointFromSavedHorizontalAnchor(saved.timeRange.start, saved.entryPrice);
    const entryEnd = dataPointFromSavedHorizontalAnchor(saved.timeRange.end, saved.entryPrice);
    const start = entryStart ? dataToScreen(entryStart) : null;
    const end = entryEnd ? dataToScreen(entryEnd) : null;
    if (!start || !end) return [];
    const requestedWidth = Math.max(
      24,
      Math.min(
        40,
        typeof positionBarSpacing === "number"
          && Number.isFinite(positionBarSpacing)
          && positionBarSpacing > 0
          ? positionBarSpacing
          : 24,
      ),
    );
    let left = Math.min(start.x, end.x);
    let right = Math.max(start.x, end.x);
    if (right - left < requestedWidth) {
      const center = (left + right) / 2;
      left = center - requestedWidth / 2;
      right = center + requestedWidth / 2;
    }
    const middleX = (left + right) / 2;
    const levels: Array<Readonly<{ zone: "entry" | "tp" | "sl"; price: number }>> = [
      Object.freeze({ zone: "entry", price: saved.entryPrice ?? Number.NaN }),
    ];
    if (typeof saved.tpPrice === "number" && Number.isFinite(saved.tpPrice)) {
      levels.push(Object.freeze({ zone: "tp", price: saved.tpPrice }));
    }
    if (typeof saved.slPrice === "number" && Number.isFinite(saved.slPrice)) {
      levels.push(Object.freeze({ zone: "sl", price: saved.slPrice }));
    }
    const levelHandles = levels.flatMap((level): readonly DynamicSelectionHandleSpec[] => {
      const anchor = dataPointFromSavedHorizontalAnchor(saved.timeRange?.start, level.price);
      const projected = anchor ? dataToScreen(anchor) : null;
      return projected ? [Object.freeze({
        point: Object.freeze({ x: middleX, y: projected.y }),
        hit: Object.freeze({ zone: level.zone, pointIndex: -1 }),
        radius: 9,
      })] : [];
    });
    if (levelHandles.length === 0) return [];
    const ys = levelHandles.map((handle) => handle.point.y);
    const top = Math.min(...ys);
    const bottom = Math.max(...ys);
    const middleY = (Math.min(...ys) + Math.max(...ys)) / 2;
    const cornerHandles = typeof saved.tpPrice === "number" && Number.isFinite(saved.tpPrice)
      && typeof saved.slPrice === "number" && Number.isFinite(saved.slPrice)
      ? [
        Object.freeze({
          point: Object.freeze({ x: left, y: top }),
          hit: Object.freeze({ zone: "top-left", pointIndex: -1 }),
          radius: 10,
        }),
        Object.freeze({
          point: Object.freeze({ x: right, y: top }),
          hit: Object.freeze({ zone: "top-right", pointIndex: -1 }),
          radius: 10,
        }),
        Object.freeze({
          point: Object.freeze({ x: left, y: bottom }),
          hit: Object.freeze({ zone: "bottom-left", pointIndex: -1 }),
          radius: 10,
        }),
        Object.freeze({
          point: Object.freeze({ x: right, y: bottom }),
          hit: Object.freeze({ zone: "bottom-right", pointIndex: -1 }),
          radius: 10,
        }),
      ] as const
      : [];
    return Object.freeze([
      ...levelHandles,
      Object.freeze({
        point: Object.freeze({ x: left, y: middleY }),
        hit: Object.freeze({ zone: "left", pointIndex: -1 }),
        radius: 10,
      }),
      Object.freeze({
        point: Object.freeze({ x: right, y: middleY }),
        hit: Object.freeze({ zone: "right", pointIndex: -1 }),
        radius: 10,
      }),
      ...cornerHandles,
    ]);
  }
  if (saved.type === "axis-line" && saved.dataPoint) {
    const point = dataToScreen(saved.dataPoint);
    return point ? [Object.freeze({
      point: Object.freeze(point),
      hit: Object.freeze({ zone: "center", pointIndex: 0 }),
      radius: 10,
    })] : [];
  }
  if (saved.type === "calculated") {
    // Handles sit where the projection puts them (fitted line ends, profile
    // corners, first VWAP value), not on the stored anchors.
    return calculatedSelectionHandles(saved, sceneHandles);
  }
  if ("dataPoints" in saved && Array.isArray(saved.dataPoints)) {
    const projected = saved.dataPoints
      .map((point) => dataToScreen(point))
      .filter((point): point is ScreenPoint => point !== null);
    if (projected.length < 2 || (saved.type === "path" && projected.length !== saved.dataPoints.length)) return [];
    if (saved.type === "shape") {
      const first = projected[0];
      const last = projected.at(-1);
      if (!first || !last) return [];
      return dynamicBoxSelectionHandles({
        x: Math.min(first.x, last.x),
        y: Math.min(first.y, last.y),
        width: Math.abs(last.x - first.x),
        height: Math.abs(last.y - first.y),
      });
    }
    return Object.freeze(projected.map((point, pointIndex) => Object.freeze({
      point: Object.freeze(point),
      hit: Object.freeze({ pointIndex }),
      radius: 10,
    })));
  }
  return [];
}
