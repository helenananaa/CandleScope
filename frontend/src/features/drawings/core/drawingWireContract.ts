import type { DrawingKind } from "../drawingTypes.js";
import type { CanonicalDrawingGeometry, DrawingStyle } from "./drawingDocument.js";

/**
 * The drawing wire contract: the geometry and style keys each drawing kind may
 * carry in a canonical drawing document.
 *
 * Replay training saves these documents in the run record, and the backend
 * allowlist in `backend/app/replay/training/review.py` must accept every key
 * listed here. `frontend/contracts/drawing-wire.json` mirrors this module (plus a
 * replay save sample) for the backend test `test_replay_drawing_wire_contract.py`.
 * After changing a list, regenerate the mirror:
 *
 *   UPDATE_DRAWING_WIRE_CONTRACT=1 node scripts/run-frontend-tests.mjs \
 *     src/features/drawings/core/__tests__/drawingWireContract.test.ts
 *
 * The type checks at the end of this file fail to compile when a list drifts
 * from `CanonicalDrawingGeometry` or `DrawingStyle`.
 */
export const DRAWING_COMMON_STYLE_KEYS = ["groupId", "hidden", "locked", "visibleIntervals"] as const;

export const DRAWING_GEOMETRY_KEYS = {
  path: ["dataPoints", "kind"],
  channel: ["dataPoints", "kind"],
  "range-measure": ["dataPoints", "kind", "measureType"],
  "angle-measure": ["dataPoints", "kind"],
  "axis-line": ["axisLineType", "dataPoint", "kind"],
  fibonacci: ["dataPoints", "inverted", "kind"],
  freehand: ["dataPoints", "kind", "stroke"],
  highlighter: ["dataPoints", "kind", "stroke"],
  line: ["dataPoints", "kind", "lineType"],
  position: ["direction", "entryPrice", "kind", "slPrice", "timeRange", "tpPrice"],
  shape: ["dataPoints", "extendRight", "kind", "shapeType"],
  text: ["dataPoint", "kind"],
} as const satisfies Record<DrawingKind, readonly string[]>;

/** Per-kind style keys; every kind also accepts DRAWING_COMMON_STYLE_KEYS. */
export const DRAWING_STYLE_KEYS = {
  path: ["arrowEnd", "color", "kind", "lineWidth"],
  channel: ["color", "fillOpacity", "kind", "lineWidth"],
  "range-measure": ["color", "kind", "lineWidth"],
  "angle-measure": ["color", "kind", "lineWidth"],
  "axis-line": ["color", "kind", "lineWidth"],
  fibonacci: ["color", "kind", "levels", "lineWidth"],
  freehand: ["color", "kind", "lineWidth"],
  highlighter: ["brushShape", "color", "compositeOperation", "kind", "lineWidth", "opacity"],
  line: ["arrowEnd", "color", "kind", "lineWidth"],
  position: ["infoPanelOffset", "kind", "positionSize"],
  shape: [
    "color", "fillColor", "fillOpacity", "kind", "label", "lineStyle", "lineWidth", "midline",
    "priceLabels",
  ],
  text: [
    "align", "bgColor", "bold", "borderColor", "borderWidth", "color", "fontFamily",
    "fontSize", "italic", "kind", "padding", "text", "underline", "widthPx",
  ],
} as const satisfies Record<DrawingKind, readonly string[]>;

type KindMember<Union, Kind extends DrawingKind> = Union extends { readonly kind: infer Member }
  ? Kind extends Member ? Union : never
  : never;
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
type Assert<T extends true> = T;
type CommonStyleKey = (typeof DRAWING_COMMON_STYLE_KEYS)[number];
type GeometryKeysMatch = {
  [Kind in DrawingKind]: Same<
    (typeof DRAWING_GEOMETRY_KEYS)[Kind][number],
    keyof KindMember<CanonicalDrawingGeometry, Kind>
  >;
};
type StyleKeysMatch = {
  [Kind in DrawingKind]: Same<
    (typeof DRAWING_STYLE_KEYS)[Kind][number],
    Exclude<keyof KindMember<DrawingStyle, Kind>, CommonStyleKey>
  >;
};

/** Compile-time proof that the lists above name every canonical key, and no others. */
export type DrawingWireContractChecks = [
  Assert<GeometryKeysMatch[DrawingKind]>,
  Assert<StyleKeysMatch[DrawingKind]>,
  Assert<Same<CommonStyleKey | "kind", keyof DrawingStyle>>,
];
