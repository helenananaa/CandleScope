import { AxisLineDrawingPrimitive } from "./primitives/AxisLineDrawingPrimitive.js";
import { AngleMeasurementPrimitive } from "./primitives/AngleMeasurementPrimitive.js";
import { FibonacciDrawingPrimitive } from "./primitives/FibonacciDrawingPrimitive.js";
import { FreehandDrawingPrimitive } from "./primitives/FreehandDrawingPrimitive.js";
import { LineDrawingPrimitive } from "./primitives/LineDrawingPrimitive.js";
import { PositionDrawingPrimitive } from "./primitives/PositionDrawingPrimitive.js";
import { ShapeDrawingPrimitive } from "./primitives/ShapeDrawingPrimitive.js";
import { TextDrawingPrimitive } from "./primitives/TextDrawingPrimitive.js";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import type {
  DrawingHit,
  DrawingHitType,
  DrawingPrimitive,
  SavedDrawing,
  ScreenBox,
  FibonacciLevel,
  ShapeLineStyle,
  TextAlign,
} from "./drawingTypes.js";
import { drawingPerfCounters } from "./performance/drawingPerfCounters.js";
import { drawingCoordinates, type DrawingCoordinate } from "./drawingProperties.js";
import {
  DEFAULT_DRAWING_RENDER_COLOR,
  DEFAULT_DRAWING_RENDER_LINE_WIDTH,
  DEFAULT_FIBONACCI_RENDER_LEVELS,
  DEFAULT_HIGHLIGHTER_RENDER_OPACITY,
  DEFAULT_SHAPE_RENDER_FILL_OPACITY,
  DEFAULT_TEXT_RENDER_COLOR,
  DEFAULT_TEXT_RENDER_FONT_FAMILY,
  DEFAULT_TEXT_RENDER_FONT_SIZE,
} from "./rendering/drawingRenderDefaults.js";

export interface SelectedTextSnapshot {
  visibleIntervals?: readonly string[] | null;
  locked?: boolean;
  text: string;
  color: string;
  fontSize: number;
  fontFamily: string;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  align: TextAlign;
  bgColor: string | null;
  borderColor: string | null;
  borderWidth: number;
  widthPx: number | null;
  padding: number;
}

export interface SelectedTextUi {
  snapshot: SelectedTextSnapshot | null;
  box: ScreenBox | null;
}

export interface SelectedDrawingMeta {
  visibleIntervals?: readonly string[] | null;
  locked?: boolean;
  coordinates?: readonly DrawingCoordinate[];
  id: string;
  type: string;
  color?: string;
  lineWidth?: number;
  opacity?: number;
  fillColor?: string;
  fillOpacity?: number;
  lineStyle?: ShapeLineStyle;
  levels?: FibonacciLevel[];
  positionSize?: number;
}

export type DrawingPrimitiveHit = DrawingHit & (
  | { prim: PositionDrawingPrimitive; type: "position" }
  | { prim: LineDrawingPrimitive; type: "line" }
  | { prim: AxisLineDrawingPrimitive; type: "axis-line" }
  | { prim: AngleMeasurementPrimitive; type: "angle" }
  | { prim: FibonacciDrawingPrimitive; type: "fibonacci" }
  | { prim: ShapeDrawingPrimitive; type: "shape" }
  | { prim: FreehandDrawingPrimitive; type: Extract<DrawingHitType, "freehand" | "highlighter"> }
  | { prim: TextDrawingPrimitive; type: "text" }
);

type SelectablePrimitive = Exclude<DrawingPrimitive, FreehandDrawingPrimitive>;

export const EMPTY_SELECTED_TEXT_UI: SelectedTextUi = { snapshot: null, box: null };

export function isSelectablePrimitive(prim: DrawingPrimitive): prim is SelectablePrimitive {
  return prim instanceof LineDrawingPrimitive
    || prim instanceof AxisLineDrawingPrimitive
    || prim instanceof AngleMeasurementPrimitive
    || prim instanceof TextDrawingPrimitive
    || prim instanceof FibonacciDrawingPrimitive
    || prim instanceof PositionDrawingPrimitive
    || prim instanceof ShapeDrawingPrimitive;
}

export function selectedDrawingMetaFromPrimitive(
  prim: DrawingPrimitive | null | undefined,
): SelectedDrawingMeta | null {
  if (!prim) return null;
  if (prim instanceof TextDrawingPrimitive) return null;
  if (prim instanceof PositionDrawingPrimitive) return {
    id: prim.id,
    type: prim.direction === "short" ? "position-short" : "position-long",
    positionSize: prim.positionSize,
  };
  if (typeof prim.setColor !== "function" && typeof prim.setLineWidth !== "function") {
    return null;
  }
  let type = "drawing";
  if (prim instanceof LineDrawingPrimitive) type = prim.lineType;
  else if (prim instanceof AxisLineDrawingPrimitive) type = prim.axisLineType === "cross" ? "cross-line" : `${prim.axisLineType}-line`;
  else if (prim instanceof AngleMeasurementPrimitive) type = "angle-measure";
  else if (prim instanceof FreehandDrawingPrimitive) type = prim.type === "highlighter" ? "highlighter" : "freehand";
  else if (prim instanceof FibonacciDrawingPrimitive) type = "fibonacci";
  else if (prim instanceof ShapeDrawingPrimitive) type = prim.shapeType || "shape";
  return {
    id: prim.id,
    type,
    color: prim.color,
    lineWidth: prim.lineWidth,
    ...(typeof (prim as { opacity?: unknown }).opacity === "number"
      ? { opacity: (prim as { opacity: number }).opacity }
      : {}),
    ...(prim instanceof ShapeDrawingPrimitive ? {
      fillColor: prim.fillColor,
      fillOpacity: prim.fillOpacity,
      lineStyle: prim.lineStyle,
    } : {}),
    ...(prim instanceof FibonacciDrawingPrimitive
      ? { levels: prim.levels.map((level) => ({ ...level })) } : {}),
  };
}

export function selectedTextUiFromPrimitive(
  prim: DrawingPrimitive | null | undefined,
): SelectedTextUi {
  if (!(prim instanceof TextDrawingPrimitive)) return EMPTY_SELECTED_TEXT_UI;
  let box = null;
  try {
    box = prim.getBoundingBoxScreen();
  } catch {
    box = null;
  }
  return {
    snapshot: {
      text: prim.text,
      color: prim.color,
      fontSize: prim.fontSize,
      fontFamily: prim.fontFamily,
      bold: prim.bold,
      italic: prim.italic,
      underline: prim.underline,
      align: prim.align,
      bgColor: prim.bgColor,
      borderColor: prim.borderColor,
      borderWidth: prim.borderWidth,
      widthPx: prim.widthPx,
      padding: prim.padding,
    },
    box,
  };
}

export function hitTestDrawingPrimitives(
  primitives: DrawingPrimitive[],
  x: number,
  y: number,
  hitRadius = 8,
  shouldTest: (primitive: DrawingPrimitive, index: number) => boolean = () => true,
): DrawingPrimitiveHit | null {
  const startedAt = typeof performance !== "undefined" && typeof performance.now === "function"
    ? performance.now()
    : Date.now();
  try {
    for (let index = primitives.length - 1; index >= 0; index -= 1) {
      const prim = primitives[index];
      if (!prim || !shouldTest(prim, index)) continue;

      if (prim instanceof PositionDrawingPrimitive) {
        const hit = prim.hitTestGeometry(x, y);
        if (hit) return { prim, type: "position", ...hit };
      } else if (prim instanceof LineDrawingPrimitive) {
        const hit = prim.hitTestGeometry(x, y);
        if (hit) return { prim, type: "line", ...hit };
      } else if (prim instanceof AxisLineDrawingPrimitive) {
        const hit = prim.hitTestGeometry(x, y);
        if (hit) return { prim, type: "axis-line", ...hit };
      } else if (prim instanceof AngleMeasurementPrimitive) {
        const hit = prim.hitTestGeometry(x, y);
        if (hit) return { prim, type: "angle", ...hit };
      } else if (prim instanceof FibonacciDrawingPrimitive) {
        const hit = prim.hitTestGeometry(x, y);
        if (hit) return { prim, type: "fibonacci", ...hit };
      } else if (prim instanceof ShapeDrawingPrimitive) {
        const hit = prim.hitTestGeometry(x, y);
        if (hit) return { prim, type: "shape", ...hit };
      } else if (prim instanceof FreehandDrawingPrimitive) {
        if (prim.hitTestGeometry(x, y, hitRadius)) return { prim, type: prim.type === "highlighter" ? "highlighter" : "freehand" };
      } else if (prim instanceof TextDrawingPrimitive) {
        const hit = prim.hitTestGeometry(x, y);
        if (hit) return { prim, type: "text", ...hit };
      }
    }
    return null;
  } finally {
    const endedAt = typeof performance !== "undefined" && typeof performance.now === "function"
      ? performance.now()
      : Date.now();
    drawingPerfCounters.recordHitQueryDuration(Math.max(0, endedAt - startedAt));
  }
}

export function selectedTextUiFromSavedDrawing(
  saved: SavedDrawing | null | undefined,
  box: ScreenBox | null = null,
): SelectedTextUi {
  if (!saved || saved.type !== "text") return EMPTY_SELECTED_TEXT_UI;
  return {
    snapshot: {
      locked: saved.locked === true,
    ...(saved.visibleIntervals === undefined ? {} : { visibleIntervals: saved.visibleIntervals }),
      text: saved.text ?? "Text",
      color: saved.color || DEFAULT_TEXT_RENDER_COLOR,
      fontSize: saved.fontSize || DEFAULT_TEXT_RENDER_FONT_SIZE,
      fontFamily: saved.fontFamily || DEFAULT_TEXT_RENDER_FONT_FAMILY,
      bold: !!saved.bold,
      italic: !!saved.italic,
      underline: !!saved.underline,
      align: saved.align || "left",
      bgColor: saved.bgColor ?? null,
      borderColor: saved.borderColor ?? null,
      borderWidth: saved.borderWidth ?? 1,
      widthPx: saved.widthPx ?? null,
      padding: saved.padding ?? 6,
    },
    box,
  };
}

export function selectedDrawingMetaFromSavedDrawing(
  saved: SavedDrawing | null | undefined,
): SelectedDrawingMeta | null {
  if (!saved?.id || saved.type === "text") return null;
  const coordinates = drawingCoordinates(saved);
  if (saved.type === "position") return {
    id: saved.id,
    locked: saved.locked === true,
    ...(saved.visibleIntervals === undefined ? {} : { visibleIntervals: saved.visibleIntervals }),
    type: saved.direction === "short" ? "position-short" : "position-long",
    positionSize: saved.positionSize ?? 1000,
  };
  const type = saved.type === "line"
    ? saved.lineType ?? "line-segment"
    : saved.type === "axis-line"
    ? saved.axisLineType === "cross" ? "cross-line" : `${saved.axisLineType ?? "horizontal"}-line`
    : saved.type === "angle-measure"
      ? "angle-measure"
      : saved.type === "shape"
        ? saved.shapeType ?? "shape"
        : saved.type;
  return {
    id: saved.id,
    locked: saved.locked === true,
    ...(saved.visibleIntervals === undefined ? {} : { visibleIntervals: saved.visibleIntervals }),
    type,
    ...(coordinates ? { coordinates } : {}),
    color: saved.color || DEFAULT_DRAWING_RENDER_COLOR,
    lineWidth: saved.lineWidth || DEFAULT_DRAWING_RENDER_LINE_WIDTH,
    ...(saved.type === "highlighter"
      ? { opacity: saved.opacity ?? DEFAULT_HIGHLIGHTER_RENDER_OPACITY }
      : {}),
    ...(saved.type === "shape" ? {
      fillColor: saved.fillColor ?? saved.color ?? DEFAULT_DRAWING_RENDER_COLOR,
      fillOpacity: saved.fillOpacity ?? DEFAULT_SHAPE_RENDER_FILL_OPACITY,
      lineStyle: saved.lineStyle ?? "solid",
    } : {}),
    ...(saved.type === "fibonacci" ? {
      levels: (saved.levels ?? DEFAULT_FIBONACCI_RENDER_LEVELS).map((level) => ({ ...level })),
    } : {}),
  };
}

/**
 * useDrawingSelection — selection state + selection lifecycle.
 *
 * Owns which primitive is currently selected and keeps the toolbar-facing
 * derived state (selectedTextUi for the floating text toolbar, selectedDrawingMeta
 * for the style editor) in sync. Extracted from the main interaction controller
 * so selection ownership lives in one place; the host controller asks this hook
 * to select / deselect a primitive after its own hit-testing.
 */
export interface DrawingSelectionRuntime {
  selectedIdRef: MutableRefObject<string | null>;
  selectedPrimId: string | null;
  selectedTextUi: SelectedTextUi;
  selectedDrawingMeta: SelectedDrawingMeta | null;
  setSelectedPrimId: Dispatch<SetStateAction<string | null>>;
  setSelectedTextUi: Dispatch<SetStateAction<SelectedTextUi>>;
  setSelectedDrawingMeta: Dispatch<SetStateAction<SelectedDrawingMeta | null>>;
  selectPrimitive(id: string): void;
  deselectAll(): void;
  getPrimitiveById(id: string): DrawingPrimitive | null;
  refreshSelectedTextUi(id?: string | null): void;
}

export function useDrawingSelection({
  primitivesRef,
  getSavedDrawingById,
  getScreenBoxById,
  onSelectionChange,
  mutatePrimitiveVisualState = true,
}: {
  primitivesRef: MutableRefObject<DrawingPrimitive[]>;
  getSavedDrawingById?: (id: string) => SavedDrawing | null;
  getScreenBoxById?: (id: string) => ScreenBox | null;
  onSelectionChange?: () => void;
  mutatePrimitiveVisualState?: boolean;
}): DrawingSelectionRuntime {
  const selectedIdRef = useRef<string | null>(null);
  const [selectedPrimId, setSelectedPrimId] = useState<string | null>(null);
  const [selectedTextUi, setSelectedTextUi] = useState<SelectedTextUi>(EMPTY_SELECTED_TEXT_UI);
  const [selectedDrawingMeta, setSelectedDrawingMeta] = useState<SelectedDrawingMeta | null>(null);

  // Whenever the selection is cleared from any of the many code paths that
  // touch `selectedPrimId`, also drop the toolbar-facing meta so the style
  // editor goes away. selectPrimitive() sets meta directly, so this only
  // needs to handle the deselect case.
  useEffect(() => {
    if (selectedPrimId == null) {
      setSelectedDrawingMeta(null);
    }
  }, [selectedPrimId]);

  const selectPrimitive = useCallback((id: string) => {
    selectedIdRef.current = id;
    setSelectedPrimId(id);
    let selectedPrim: DrawingPrimitive | null = null;
    for (const prim of primitivesRef.current) {
      if (mutatePrimitiveVisualState && isSelectablePrimitive(prim)) {
        prim.setSelected(prim.id === id);
        if (prim.id === id) selectedPrim = prim;
      } else if (prim.id === id) {
        selectedPrim = prim;
      }
    }
    if (!selectedPrim) {
      // Freehand strokes don't have setSelected; locate by id directly
      selectedPrim = primitivesRef.current.find((p) => p.id === id) || null;
    }
    const saved = selectedPrim ? null : getSavedDrawingById?.(id) ?? null;
    setSelectedTextUi(selectedPrim
      ? selectedTextUiFromPrimitive(selectedPrim)
      : selectedTextUiFromSavedDrawing(saved, getScreenBoxById?.(id) ?? null));
    setSelectedDrawingMeta(selectedPrim
      ? selectedDrawingMetaFromPrimitive(selectedPrim)
      : selectedDrawingMetaFromSavedDrawing(saved));
    if (mutatePrimitiveVisualState) onSelectionChange?.();
  }, [getSavedDrawingById, getScreenBoxById, mutatePrimitiveVisualState, onSelectionChange, primitivesRef]);

  const deselectAll = useCallback(() => {
    selectedIdRef.current = null;
    setSelectedPrimId(null);
    setSelectedTextUi(EMPTY_SELECTED_TEXT_UI);
    setSelectedDrawingMeta(null);
    for (const prim of primitivesRef.current) {
      if (mutatePrimitiveVisualState && isSelectablePrimitive(prim)) {
        prim.setSelected(false);
      }
    }
    if (mutatePrimitiveVisualState) onSelectionChange?.();
  }, [mutatePrimitiveVisualState, onSelectionChange, primitivesRef]);

  const getPrimitiveById = useCallback((id: string) => {
    return primitivesRef.current.find((p) => p.id === id) || null;
  }, [primitivesRef]);

  const refreshSelectedTextUi = useCallback((id: string | null = selectedIdRef.current) => {
    const prim = id ? primitivesRef.current.find((p) => p.id === id) : null;
    const saved = !prim && id ? getSavedDrawingById?.(id) ?? null : null;
    setSelectedTextUi(prim
      ? selectedTextUiFromPrimitive(prim)
      : selectedTextUiFromSavedDrawing(saved, id ? getScreenBoxById?.(id) ?? null : null));
  }, [getSavedDrawingById, getScreenBoxById, primitivesRef]);

  return {
    selectedIdRef,
    selectedPrimId,
    selectedTextUi,
    selectedDrawingMeta,
    setSelectedPrimId,
    setSelectedTextUi,
    setSelectedDrawingMeta,
    selectPrimitive,
    deselectAll,
    getPrimitiveById,
    refreshSelectedTextUi,
  };
}
