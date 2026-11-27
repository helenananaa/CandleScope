import { parseDrawingDataPoint } from "../drawingContracts.js";
import type {
  AnnotationToolId,
  DrawingDataPoint,
  DrawingDataToScreen,
  DrawingHit,
  DrawingToolId,
  SavedDrawing,
  SavedTextDrawing,
  ScreenPoint,
  ScreenToDrawingData,
} from "../drawingTypes.js";
import type { DynamicOverlayDecoration } from "./dynamicOverlayController.js";
import { createTextSavedDrawing, type CreatedSavedDrawing } from "./drawingEntityCreation.js";

/**
 * Callouts and price labels are text drawings that point at a priced bar.
 *
 * - A callout keeps two source anchors: the box (`dataPoint`) and the leader's
 *   `target`. Dragging the box moves only the box; the target dot moves only
 *   the target; the leader line moves both.
 * - A price label keeps one anchor (`dataPoint`) and shows that anchor's price.
 *   The box is painted beside the anchor, so the whole label moves as one.
 */
export type TextDragPart = "box" | "target" | "callout";

export const ANNOTATION_TOOL_IDS: ReadonlySet<AnnotationToolId> = new Set(["callout", "price-label"]);

export function isAnnotationToolId(tool: DrawingToolId | null | undefined): tool is AnnotationToolId {
  return tool === "callout" || tool === "price-label";
}

/** The tool that recreates a saved text variant. */
export function annotationToolForSavedText(saved: SavedTextDrawing): AnnotationToolId | null {
  if (saved.priceLabel) return "price-label";
  return saved.target ? "callout" : null;
}

/** A price label's text is its anchor's price, so there is nothing to type. */
export function isEditableTextDrawing(saved: SavedDrawing | null | undefined): boolean {
  return saved?.type === "text" && saved.priceLabel !== true;
}

export function textDragPartForHit(saved: SavedTextDrawing, hit: DrawingHit | null | undefined): TextDragPart {
  if (!saved.target || saved.priceLabel) return "box";
  if (hit?.zone === "target") return "target";
  return hit?.zone === "leader" ? "callout" : "box";
}

export interface TextDragOrigin {
  readonly part: TextDragPart;
  readonly origTarget?: DrawingDataPoint;
}

/** Fields a text drag descriptor needs beyond the box anchor. */
export function textDragOrigin(saved: SavedTextDrawing, hit: DrawingHit | null | undefined): TextDragOrigin {
  const part = textDragPartForHit(saved, hit);
  return part !== "box" && saved.target
    ? { part, origTarget: { ...saved.target } }
    : { part };
}

function frozenPoint(value: unknown): DrawingDataPoint | null {
  const parsed = parseDrawingDataPoint(value);
  return parsed ? Object.freeze({ ...parsed }) as DrawingDataPoint : null;
}

function translated(
  point: DrawingDataPoint,
  dx: number,
  dy: number,
  dataToScreen: DrawingDataToScreen,
  screenToDrawingData: ScreenToDrawingData,
  snap: boolean,
): DrawingDataPoint | null {
  const screen = dataToScreen(point);
  if (!screen || !Number.isFinite(screen.x) || !Number.isFinite(screen.y)) return null;
  return frozenPoint(screenToDrawingData(screen.x + dx, screen.y + dy, { snap }));
}

export interface TextAnnotationDragInput {
  readonly drawing: SavedTextDrawing;
  readonly part: TextDragPart;
  readonly origDataPoint: DrawingDataPoint;
  readonly origTarget?: DrawingDataPoint;
  readonly startMouse: ScreenPoint;
  readonly pos: ScreenPoint;
  readonly dataToScreen: DrawingDataToScreen;
  readonly screenToDrawingData: ScreenToDrawingData;
  readonly snap: boolean;
}

/** Move the dragged part from its gesture-start anchors; null rejects the frame. */
export function applyTextAnnotationDrag(input: TextAnnotationDragInput): SavedTextDrawing | null {
  const { drawing, part, dataToScreen, screenToDrawingData, snap } = input;
  const dx = input.pos.x - input.startMouse.x;
  const dy = input.pos.y - input.startMouse.y;
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) return null;
  const box = frozenPoint(input.origDataPoint);
  if (!box) return null;
  if (part === "box") {
    const dataPoint = translated(box, dx, dy, dataToScreen, screenToDrawingData, snap);
    return dataPoint ? Object.freeze({ ...drawing, dataPoint }) : null;
  }
  const origin = frozenPoint(input.origTarget);
  if (!origin || !drawing.target) return null;
  const target = translated(origin, dx, dy, dataToScreen, screenToDrawingData, snap);
  if (!target) return null;
  if (part === "target") return Object.freeze({ ...drawing, target });
  // Moving the whole callout keeps the box where it sat relative to the pointer.
  const dataPoint = translated(box, dx, dy, dataToScreen, screenToDrawingData, false);
  return dataPoint ? Object.freeze({ ...drawing, dataPoint, target }) : null;
}

export interface AnnotationStyle {
  readonly color: string;
  readonly fontSize?: number;
  readonly bold?: boolean;
  readonly italic?: boolean;
}

/** A callout keeps its colour on the text, border and leader; the box stays see-through. */
export function createCalloutSavedDrawing(
  dataPoint: DrawingDataPoint,
  target: DrawingDataPoint,
  style: AnnotationStyle,
  text = "",
): CreatedSavedDrawing<SavedTextDrawing> | null {
  return createTextSavedDrawing({
    dataPoint,
    target,
    text,
    color: style.color,
    fontSize: style.fontSize || 14,
    bold: style.bold || false,
    italic: style.italic || false,
    borderColor: style.color,
    borderWidth: 1,
  });
}

/** A price label is a filled tag in the chosen colour with light text. */
export function createPriceLabelSavedDrawing(
  dataPoint: DrawingDataPoint,
  style: AnnotationStyle,
): CreatedSavedDrawing<SavedTextDrawing> | null {
  return createTextSavedDrawing({
    dataPoint,
    priceLabel: true,
    color: "#ffffff",
    bgColor: style.color,
    borderColor: null,
    fontSize: style.fontSize || 12,
    bold: style.bold ?? true,
    italic: style.italic || false,
    padding: 4,
  });
}

/** Rough box for drag previews; the static scene measures the real text. */
function previewBox(point: ScreenPoint, saved: SavedTextDrawing): Readonly<{ x: number; y: number; width: number; height: number }> {
  const fontSize = saved.fontSize ?? 14;
  const padding = saved.padding ?? 6;
  const height = fontSize * 1.3 + padding * 2;
  const width = saved.widthPx ?? (saved.priceLabel ? 64 : 96);
  return saved.priceLabel
    ? { x: point.x + 10, y: point.y - 12 - height, width, height }
    : { x: point.x, y: point.y - fontSize, width, height };
}

/** Dynamic-canvas preview of a text annotation during creation or a drag. */
export function textAnnotationDraftDecorations(
  saved: SavedTextDrawing,
  dataToScreen: DrawingDataToScreen,
  color: string,
): readonly DynamicOverlayDecoration[] {
  if (!saved.dataPoint) return [];
  const point = dataToScreen(saved.dataPoint);
  if (!point) return [];
  const box = Object.freeze(previewBox(point, saved));
  const decorations: DynamicOverlayDecoration[] = [Object.freeze({ type: "box", box, color, dashed: false })];
  const pointer = saved.priceLabel ? point : saved.target ? dataToScreen(saved.target) : null;
  if (pointer) {
    const from = Object.freeze({
      x: Math.min(Math.max(pointer.x, box.x), box.x + box.width),
      y: Math.min(Math.max(pointer.y, box.y), box.y + box.height),
    });
    decorations.push(Object.freeze({
      type: "line", from, to: Object.freeze({ ...pointer }), color, lineWidth: 1,
      handles: Object.freeze([Object.freeze({ ...pointer })]),
    }));
  }
  return Object.freeze(decorations);
}

/** Creation preview between the callout's first click (target) and the box click. */
export function calloutCreationDecorations(
  target: ScreenPoint,
  pointer: ScreenPoint,
  color: string,
): readonly DynamicOverlayDecoration[] {
  return Object.freeze([Object.freeze({
    type: "line" as const,
    from: Object.freeze({ ...pointer }),
    to: Object.freeze({ ...target }),
    color,
    lineWidth: 1,
    dashed: true,
    handles: Object.freeze([Object.freeze({ ...target })]),
  })]);
}

const clamp = (value: number, min: number, max: number): number => Math.min(Math.max(value, min), max);

/**
 * While the textarea owns a callout's box the scene omits the whole entity, so
 * the leader is drawn here to keep the target visible during typing. The box
 * is estimated from the typed length; the textarea is transparent, so a line
 * ending slightly inside it still reads as attached.
 */
export function calloutEditingDecorations(
  saved: SavedTextDrawing,
  boxOrigin: ScreenPoint | null,
  textLength: number,
  dataToScreen: DrawingDataToScreen,
): readonly DynamicOverlayDecoration[] {
  if (!saved.target || saved.priceLabel) return [];
  const origin = boxOrigin ?? (saved.dataPoint ? dataToScreen(saved.dataPoint) : null);
  const target = dataToScreen(saved.target);
  if (!origin || !target) return [];
  const fontSize = saved.fontSize ?? 14;
  const padding = saved.padding ?? 6;
  const width = saved.widthPx ?? Math.max(60, textLength * fontSize * 0.6 + padding * 2);
  const height = fontSize * 1.3 + padding * 2;
  const from = Object.freeze({
    x: clamp(target.x, origin.x, origin.x + width),
    y: clamp(target.y, origin.y, origin.y + height),
  });
  if (from.x === target.x && from.y === target.y) return [];
  return Object.freeze([Object.freeze({
    type: "line" as const,
    from,
    to: Object.freeze({ ...target }),
    color: saved.borderColor ?? saved.color ?? "#3b82f6",
    lineWidth: 1,
    handles: Object.freeze([Object.freeze({ ...target })]),
  })]);
}
