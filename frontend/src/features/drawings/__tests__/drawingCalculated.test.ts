import assert from "node:assert/strict";
import test from "node:test";

import { exportDrawingDocument, importSavedDrawings } from "../core/drawingCodec.js";
import { isTwoPointCreationTool } from "../interaction/drawingToolPredicates.js";
import {
  calculatedDraftDecorations,
  calculatedSelectionHandles,
  createCalculatedSavedDrawing,
  isThreeClickCreationTool,
} from "../interaction/drawingCalculatedInteraction.js";
import { createTwoPointSavedDrawing } from "../interaction/drawingEntityCreation.js";
import { applyDrawingEntityDrag, drawingEntityGeometryCommandForDrag } from "../interaction/drawingEntityDrag.js";
import { drawingName } from "../drawingObjectLabels.js";
import { loadSavedDrawingsFailClosed, normalizeSavedDrawingItemStrict, saveSavedDrawings } from "../drawingPersistence.js";
import { drawingPropertiesCandidate } from "../drawingProperties.js";
import { selectedDrawingMetaFromSavedDrawing } from "../drawingSelectionController.js";
import { styleFamily } from "../drawingStyleTemplateStore.js";
import { supportsDrawingTool } from "../drawingCapabilities.js";
import { CHART_DRAWING_ANCHOR_MODES } from "../../chart-representation/chartTypeRegistry.js";
import { getLocale, setLocale } from "../../../i18n/index.js";
import type { DrawingDataPoint, SavedCalculatedDrawing, SavedDrawing } from "../drawingTypes.js";

const POINTS = [{ time: 100, price: 10 }, { time: 200, price: 20 }, { time: 300, price: 15 }];

function saved(calcType: SavedCalculatedDrawing["calcType"], count: number, extra: Partial<SavedCalculatedDrawing> = {}): SavedCalculatedDrawing {
  return { id: `calc-${calcType}`, type: "calculated", calcType, dataPoints: POINTS.slice(0, count), color: "#3b82f6", lineWidth: 2, ...extra };
}

test("strict persistence keeps each calculated type with its own anchor count", () => {
  for (const [calcType, count] of [["fib-extension", 3], ["anchored-vwap", 1], ["volume-profile", 2], ["regression-channel", 2]] as const) {
    const item = normalizeSavedDrawingItemStrict(saved(calcType, count));
    assert.equal(item?.type, "calculated", calcType);
    assert.equal((item as SavedCalculatedDrawing).dataPoints.length, count);
    assert.equal(normalizeSavedDrawingItemStrict(saved(calcType, count === 3 ? 2 : count + 1)), null, `${calcType} with the wrong anchor count`);
  }
  assert.equal(normalizeSavedDrawingItemStrict({ ...saved("anchored-vwap", 1), calcType: "pitchfork" }), null);
  assert.equal(normalizeSavedDrawingItemStrict({ ...saved("anchored-vwap", 1), dataPoints: [{ time: 100, price: 1, logical: 4 }] }), null,
    "calculated drawings anchor to bar time, not to a logical index");
  assert.equal(normalizeSavedDrawingItemStrict(saved("volume-profile", 2, { rows: 2 })), null);
  assert.equal(normalizeSavedDrawingItemStrict(saved("regression-channel", 2, { deviation: 50 })), null);
  assert.equal((normalizeSavedDrawingItemStrict(saved("regression-channel", 2, { deviation: 1.5 })) as SavedCalculatedDrawing).deviation, 1.5);
});

test("calculated drawings round-trip through the document codec and local storage", () => {
  const drawings: SavedDrawing[] = [saved("fib-extension", 3), saved("volume-profile", 2, { rows: 40 }), saved("regression-channel", 2, { deviation: 3 })];
  const document = importSavedDrawings("scope", drawings);
  assert.ok(document);
  assert.deepEqual(exportDrawingDocument(document), drawings);

  const values = new Map<string, string>();
  const previous = globalThis.localStorage;
  globalThis.localStorage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
    clear: () => values.clear(),
    key: () => null,
    get length() { return values.size; },
  } as Storage;
  try {
    assert.equal(saveSavedDrawings("BTCUSDT", drawings), true);
    assert.deepEqual(loadSavedDrawingsFailClosed("BTCUSDT"), drawings, "a restart reads the same drawings back");
  } finally {
    if (previous === undefined) Reflect.deleteProperty(globalThis, "localStorage");
    else globalThis.localStorage = previous;
  }
});

test("creation clicks: VWAP takes one, profile and regression two, fib extension three", () => {
  assert.equal(isThreeClickCreationTool("fib-extension"), true);
  assert.equal(isThreeClickCreationTool("channel-parallel"), true);
  assert.equal(isThreeClickCreationTool("regression-channel"), false);
  for (const tool of ["fib-extension", "anchored-vwap", "volume-profile", "regression-channel"] as const) {
    assert.equal(isTwoPointCreationTool(tool), true, tool);
  }
  const preview = createCalculatedSavedDrawing({ tool: "fib-extension", dataPoints: POINTS.slice(0, 2), color: "#fff", lineWidth: 1 });
  assert.equal(preview?.dataPoints.length, 3, "a two-click preview repeats B as C");
  assert.deepEqual(preview?.dataPoints[2], POINTS[1]);
  assert.match(preview?.id ?? "", /^calc/);
  const vwap = createTwoPointSavedDrawing({ tool: "anchored-vwap", dataPoints: [POINTS[0]!, POINTS[1]!], color: "#fff", lineWidth: 1 } as Parameters<typeof createTwoPointSavedDrawing>[0]);
  assert.equal(vwap?.type, "calculated");
  assert.equal((vwap as SavedCalculatedDrawing).dataPoints.length, 1);
});

test("draft previews compute from the chart's bars while placing", () => {
  const toScreen = (point: DrawingDataPoint) => ({ x: Number(point.time), y: point.price });
  const bars = [100, 150, 200].map((time, index) => ({ time, high: 12 + index, low: 8 + index, close: 10 + index, volume: 5 }));
  const vwap = calculatedDraftDecorations(saved("anchored-vwap", 1), toScreen, bars);
  assert.ok(vwap.some((decoration) => decoration.type === "freehand"));
  const regression = calculatedDraftDecorations(saved("regression-channel", 2), toScreen, bars);
  assert.equal(regression.filter((decoration) => decoration.type === "line").length, 3);
  const noBars = calculatedDraftDecorations(saved("regression-channel", 2), toScreen, []);
  assert.equal(noBars.filter((decoration) => decoration.type === "line").length, 1, "without bars only the anchor line shows");
});

test("dragging moves one anchor or the whole calculated drawing", () => {
  const drawing = saved("regression-channel", 2);
  const toData = (x: number, y: number) => ({ time: x, price: y }) as DrawingDataPoint;
  const toScreen = (point: DrawingDataPoint) => ({ x: Number(point.time), y: point.price });
  const drag = (pointIndex: number, pos: { x: number; y: number }) => {
    const descriptor = { id: drawing.id!, type: "calculated" as const, pointIndex, startMouse: { x: 200, y: 20 }, origPoints: drawing.dataPoints.map((point) => ({ ...point })) };
    return {
      command: drawingEntityGeometryCommandForDrag(descriptor),
      result: applyDrawingEntityDrag({ descriptor, drawing, pos, screenToData: toData as never, screenToDrawingData: toData as never, dataToScreen: toScreen as never, snap: false }) as SavedCalculatedDrawing | null,
    };
  };
  const resized = drag(1, { x: 250, y: 25 });
  assert.equal(resized.command, "resize");
  assert.deepEqual(resized.result?.dataPoints[0], POINTS[0]);
  assert.equal(resized.result?.dataPoints[1]?.time, 250);
  const moved = drag(-1, { x: 230, y: 20 });
  assert.equal(moved.command, "move");
  assert.deepEqual(moved.result?.dataPoints.map((point) => point.time), [130, 230]);
});

test("selection, names, templates and properties treat each calculated type as its own tool", () => {
  const previous = getLocale();
  setLocale("en");
  try {
    const regression = saved("regression-channel", 2);
    const meta = selectedDrawingMetaFromSavedDrawing(regression);
    assert.equal(meta?.type, "regression-channel");
    assert.equal(meta?.deviation, 2);
    assert.equal(selectedDrawingMetaFromSavedDrawing(saved("volume-profile", 2))?.rows, 24);
    assert.equal(drawingName("volume-profile"), "Fixed range volume profile");
    assert.equal(styleFamily("anchored-vwap"), "stroke");
    const patched = drawingPropertiesCandidate(regression, { deviation: 3, color: "#ff0000" }) as SavedCalculatedDrawing;
    assert.equal(patched.deviation, 3);
    assert.equal(patched.color, "#ff0000");
    assert.equal((drawingPropertiesCandidate(saved("volume-profile", 2), { rows: 30.4 }) as SavedCalculatedDrawing).rows, 30);
    assert.equal((drawingPropertiesCandidate(regression, { rows: 30 }) as SavedCalculatedDrawing).rows, undefined,
      "rows belong to the volume profile only");
  } finally {
    setLocale(previous);
  }
});

test("calculated tools are offered on ordinary time charts only", () => {
  for (const tool of ["fib-extension", "anchored-vwap", "volume-profile", "regression-channel"] as const) {
    assert.equal(supportsDrawingTool(CHART_DRAWING_ANCHOR_MODES.SOURCE_TIME, tool), true, tool);
    assert.equal(supportsDrawingTool(CHART_DRAWING_ANCHOR_MODES.SOURCE_LINEAGE, tool), false, tool);
  }
});

test("selection handles follow the scene projection, mapped back to the stored anchors", () => {
  const scene = [{ x: 10, y: 50 }, { x: 90, y: 20 }];
  const forward = calculatedSelectionHandles(saved("regression-channel", 2), scene);
  assert.deepEqual(forward.map((handle) => [handle.point.x, handle.hit.pointIndex]), [[10, 0], [90, 1]]);
  const reversed = calculatedSelectionHandles(saved("regression-channel", 2, { dataPoints: [POINTS[1]!, POINTS[0]!] }), scene);
  assert.deepEqual(reversed.map((handle) => handle.hit.pointIndex), [1, 0], "the earlier bar is the second anchor");
  assert.deepEqual(calculatedSelectionHandles(saved("fib-extension", 3), scene), [], "a stale scene with the wrong handle count shows none");
  assert.deepEqual(calculatedSelectionHandles(saved("anchored-vwap", 1), null), []);
});
