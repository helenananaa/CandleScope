import assert from "node:assert/strict";
import test from "node:test";
import { exportDrawingDocument, importSavedDrawings } from "../core/drawingCodec.js";
import { drawingCommandsForSavedDrawing } from "../core/drawingDocumentRuntime.js";
import { createDrawingDocumentStore } from "../core/drawingDocumentStore.js";
import { drawingToolForSavedObject } from "../drawingAutoSelection.js";
import { supportsDrawingHitType, supportsDrawingTool } from "../drawingCapabilities.js";
import { normalizeSavedDrawingItemStrict } from "../drawingPersistence.js";
import { drawingPatchChangesGeometry, drawingPropertiesCandidate } from "../drawingProperties.js";
import { selectedDrawingMetaFromSavedDrawing } from "../drawingSelectionController.js";
import { createTwoPointSavedDrawing } from "../interaction/drawingEntityCreation.js";
import { applyDrawingEntityDrag } from "../interaction/drawingEntityDrag.js";
import { CHART_DRAWING_ANCHOR_MODES } from "../../chart-representation/chartTypeRegistry.js";
import type { SavedChannelDrawing, SavedLineDrawing, SavedShapeDrawing } from "../drawingTypes.js";

const A = { time: 1_700_000_000, price: 100 };
const B = { time: 1_700_003_600, price: 120 };
const C = { time: 1_700_001_800, price: 130 };

const channel: SavedChannelDrawing = {
  id: "ch_1", type: "channel", color: "#22c55e", lineWidth: 2, dataPoints: [A, B, C],
};
const zone: SavedShapeDrawing = {
  id: "sh_1", type: "shape", shapeType: "rectangle", color: "#f59e0b", lineWidth: 1,
  fillColor: "#f59e0b", fillOpacity: 0.12, dataPoints: [A, B],
  extendRight: true, midline: true, priceLabels: true, label: "Demand",
};

function roundTrip<T>(drawing: T): unknown {
  const document = importSavedDrawings("annotations", [drawing as never]);
  assert.ok(document);
  return exportDrawingDocument(document)?.[0];
}

test("the arrow tool creates an ordinary segment that carries an arrowhead flag", () => {
  const arrow = createTwoPointSavedDrawing({ tool: "line-arrow", color: "#f00", lineWidth: 2, dataPoints: [A, B] });
  assert.ok(arrow && arrow.type === "line");
  assert.equal(arrow.lineType, "line-segment");
  assert.equal(arrow.arrowEnd, true);
  assert.equal(drawingToolForSavedObject(arrow), "line-arrow");
  assert.equal(selectedDrawingMetaFromSavedDrawing(arrow)?.type, "line-arrow");
  assert.deepEqual(roundTrip(arrow), arrow);
  // A ray never reports itself as an arrow, even if a stale flag is present.
  const ray: SavedLineDrawing = { ...arrow, lineType: "line-ray" };
  assert.equal(drawingToolForSavedObject(ray), "line-ray");
  assert.equal(normalizeSavedDrawingItemStrict({ ...arrow, arrowEnd: "yes" }), null);
});

test("arrows stay available on derived charts while channels stay source-time only", () => {
  const lineage = CHART_DRAWING_ANCHOR_MODES.SOURCE_LINEAGE;
  const sourceTime = CHART_DRAWING_ANCHOR_MODES.SOURCE_TIME;
  assert.equal(supportsDrawingTool(lineage, "line-arrow"), true);
  assert.equal(supportsDrawingTool(lineage, "channel-parallel"), false);
  assert.equal(supportsDrawingTool(sourceTime, "channel-parallel"), true);
  assert.equal(supportsDrawingHitType(sourceTime, "channel"), true);
  assert.equal(supportsDrawingHitType(lineage, "channel"), false);
});

test("channels keep three source anchors and reject malformed payloads", () => {
  const twoPoint = createTwoPointSavedDrawing({ tool: "channel-parallel", color: "#0f0", lineWidth: 2, dataPoints: [A, B] });
  assert.ok(twoPoint && twoPoint.type === "channel");
  assert.deepEqual(twoPoint.dataPoints, [A, B, B], "an in-progress channel starts with zero width");
  const created = createTwoPointSavedDrawing({ tool: "channel-parallel", color: "#0f0", lineWidth: 2, dataPoints: [A, B, C] });
  assert.ok(created && created.type === "channel");
  assert.deepEqual(created.dataPoints, [A, B, C]);
  assert.equal(drawingToolForSavedObject(created), "channel-parallel");
  assert.deepEqual(roundTrip(channel), channel);
  assert.deepEqual(roundTrip({ ...channel, fillOpacity: 0.3 }), { ...channel, fillOpacity: 0.3 });
  for (const bad of [
    { ...channel, dataPoints: [A, B] },
    { ...channel, dataPoints: [A, B, C, A] },
    { ...channel, dataPoints: [A, B, { logical: 4, price: 1 }] },
    { ...channel, fillOpacity: 2 },
  ]) assert.equal(normalizeSavedDrawingItemStrict(bad), null);
  assert.equal(createTwoPointSavedDrawing({ tool: "line-segment", color: "#0f0", lineWidth: 2, dataPoints: [A, B, C] }), null);
});

test("channels share document history, locking and exact restore", () => {
  const store = createDrawingDocumentStore("channels");
  const commands = drawingCommandsForSavedDrawing(channel, { type: "create" });
  assert.ok(commands);
  assert.equal(store.dispatchMany(commands).ok, true);
  const original = exportDrawingDocument(store.getSnapshot());
  assert.equal(store.dispatch({ type: "update-style", id: channel.id!, patch: { locked: true, color: "#00f" } }).ok, true);
  assert.equal(store.dispatch({ type: "move", id: channel.id!, geometry: { kind: "channel", dataPoints: [B, C, A] } }).ok, false);
  assert.equal(store.replayHistory("undo", (batch) => store.dispatchMany(batch).ok), true);
  assert.deepEqual(exportDrawingDocument(store.getSnapshot()), original);
  assert.equal(store.dispatch({ type: "delete", id: channel.id! }).ok, true);
  assert.equal(store.replayHistory("undo", (batch) => store.dispatchMany(batch).ok), true);
  assert.deepEqual(exportDrawingDocument(store.getSnapshot()), original);
});

test("dragging a channel body moves all three anchors; a handle moves only its anchor", () => {
  const drawing: SavedChannelDrawing = { ...channel, dataPoints: [{ time: 10, price: 20 }, { time: 30, price: 40 }, { time: 20, price: 60 }] };
  const apply = (pointIndex: number) => applyDrawingEntityDrag({
    drawing,
    descriptor: { id: channel.id!, type: "channel", pointIndex, startMouse: { x: 10, y: 20 }, origPoints: drawing.dataPoints },
    pos: { x: 15, y: 25 }, snap: false,
    dataToScreen: (point) => ({ x: Number(point.time), y: point.price }),
    screenToData: (x, y) => ({ time: x, price: y }),
    screenToDrawingData: (x, y) => ({ time: x, price: y }),
  });
  const moved = apply(-1);
  assert.ok(moved && moved.type === "channel");
  assert.deepEqual(moved.dataPoints, [{ time: 15, price: 25 }, { time: 35, price: 45 }, { time: 25, price: 65 }]);
  const widened = apply(2);
  assert.ok(widened && widened.type === "channel");
  assert.deepEqual(widened.dataPoints, [{ time: 10, price: 20 }, { time: 30, price: 40 }, { time: 15, price: 25 }]);
  assert.deepEqual(drawing.dataPoints[2], { time: 20, price: 60 }, "the source drawing is never mutated");
});

test("rectangle zone options round-trip and are rejected when malformed", () => {
  assert.deepEqual(roundTrip(zone), zone);
  assert.equal(normalizeSavedDrawingItemStrict({ ...zone, label: "x".repeat(65) }), null);
  assert.equal(normalizeSavedDrawingItemStrict({ ...zone, midline: 1 }), null);
  assert.equal(normalizeSavedDrawingItemStrict({ ...zone, extendRight: "true" }), null);
  const meta = selectedDrawingMetaFromSavedDrawing(zone);
  assert.equal(meta?.type, "rectangle");
  assert.deepEqual(
    [meta?.extendRight, meta?.midline, meta?.priceLabels, meta?.label],
    [true, true, true, "Demand"],
  );
  const ellipseMeta = selectedDrawingMetaFromSavedDrawing({ ...zone, shapeType: "ellipse" });
  assert.equal(ellipseMeta?.extendRight, undefined, "zone controls are rectangle-only");
});

test("zone property patches are rectangle-only and extension commits as geometry", () => {
  const { extendRight: _extendRight, midline: _midline, priceLabels: _priceLabels, label: _label, ...plain } = zone;
  const patched = drawingPropertiesCandidate(plain, { extendRight: true, midline: true, label: "  Supply  " });
  assert.ok(patched && patched.type === "shape");
  assert.equal(patched.extendRight, true);
  assert.equal(patched.midline, true);
  assert.equal(patched.label, "Supply", "names are trimmed");
  assert.equal(drawingPatchChangesGeometry(plain, patched), true);
  const styleOnly = drawingPropertiesCandidate(plain, { priceLabels: true });
  assert.ok(styleOnly);
  assert.equal(drawingPatchChangesGeometry(plain, styleOnly), false);
  const cleared = drawingPropertiesCandidate(zone, { label: "   " });
  assert.ok(cleared && cleared.type === "shape");
  assert.equal("label" in cleared, false, "an empty name removes the label");
  const ellipse = drawingPropertiesCandidate({ ...plain, shapeType: "ellipse" }, { extendRight: true, midline: true });
  assert.ok(ellipse && ellipse.type === "shape");
  assert.equal(ellipse.extendRight, undefined);
  assert.equal(ellipse.midline, undefined);
  // Both resulting candidates must still pass the strict document boundary.
  assert.ok(drawingCommandsForSavedDrawing(patched, { type: "update", geometryCommand: "resize" }));
});

test("arrowhead and channel fill patches apply only to their own kinds", () => {
  const segment: SavedLineDrawing = { id: "ln_1", type: "line", lineType: "line-segment", dataPoints: [A, B], color: "#fff", lineWidth: 2 };
  const withArrow = drawingPropertiesCandidate(segment, { arrowEnd: true });
  assert.ok(withArrow && withArrow.type === "line");
  assert.equal(withArrow.arrowEnd, true);
  const withoutArrow = drawingPropertiesCandidate(withArrow, { arrowEnd: false });
  assert.ok(withoutArrow && withoutArrow.type === "line");
  assert.equal("arrowEnd" in withoutArrow, false);
  const ray = drawingPropertiesCandidate({ ...segment, lineType: "line-ray" }, { arrowEnd: true });
  assert.ok(ray && ray.type === "line");
  assert.equal(ray.arrowEnd, undefined);
  const filled = drawingPropertiesCandidate(channel, { fillOpacity: 0.25 });
  assert.ok(filled && filled.type === "channel");
  assert.equal(filled.fillOpacity, 0.25);
  const moved = drawingPropertiesCandidate(channel, {}, [
    { time: A.time, price: 101 }, { time: B.time, price: 121 }, { time: C.time, price: 131 },
  ]);
  assert.ok(moved && moved.type === "channel");
  assert.deepEqual(moved.dataPoints.map((point) => point.price), [101, 121, 131], "all three anchors are editable");
});
