import assert from "node:assert/strict";
import test from "node:test";
import { measureDrawingRange, rangeMeasurementLabel } from "../rangeMeasurement.js";
import { createTwoPointSavedDrawing } from "../interaction/drawingEntityCreation.js";
import { exportDrawingDocument, importSavedDrawings } from "../core/drawingCodec.js";
import { drawingCommandsForSavedDrawing } from "../core/drawingDocumentRuntime.js";
import { createDrawingDocumentStore } from "../core/drawingDocumentStore.js";
import { applyDrawingEntityDrag } from "../interaction/drawingEntityDrag.js";
import { normalizeSavedDrawingItemStrict } from "../drawingPersistence.js";
import type { SavedRangeMeasureDrawing } from "../drawingTypes.js";

const sample: SavedRangeMeasureDrawing = {
  id: "measure_1", type: "range-measure", measureType: "price-time", color: "#ffaa33", lineWidth: 2,
  dataPoints: [{ time: 1700000000, price: 100 }, { time: 1700003660, price: 125 }],
};

test("range values use source elapsed time and price, including reversal and zero baseline", () => {
  const value = measureDrawingRange(sample.dataPoints);
  assert.deepEqual(value, { priceDelta: 25, percentDelta: 25, elapsedSeconds: 3660 });
  assert.equal(rangeMeasurementLabel(value!, "price-time"), "Δ +25 (+25%) · Δt +1h 1m");
  assert.equal(rangeMeasurementLabel(measureDrawingRange([...sample.dataPoints].reverse())!, "price-time"), "Δ -25 (-20%) · Δt −1h 1m");
  assert.equal(rangeMeasurementLabel(measureDrawingRange([{ time: 0, price: 0 }, { time: 86400 * 3, price: -4 }])!, "price"), "Δ -4 (—)");
  assert.equal(rangeMeasurementLabel(measureDrawingRange([{ time: 0, price: -100 }, { time: 86400 * 3, price: -75 }])!, "price-time"), "Δ +25 (+25%) · Δt +3d");
  assert.equal(measureDrawingRange([{ logical: 1, price: 100 }, { time: 1, price: 125 }]), null);
  assert.equal(measureDrawingRange([{ time: 0, price: -Number.MAX_VALUE }, { time: 1, price: Number.MAX_VALUE }]), null);
});

test("all ruler variants round-trip without changing anchors; invalid geometry fails closed", () => {
  for (const tool of ["measure-price", "measure-time", "measure-price-time"] as const) {
    const drawing = createTwoPointSavedDrawing({ tool, color: "#f00", lineWidth: 2, dataPoints: sample.dataPoints });
    assert.ok(drawing);
    const document = importSavedDrawings("rulers", [drawing]);
    assert.ok(document);
    assert.deepEqual(exportDrawingDocument(document), [drawing]);
  }
  for (const bad of [
    { ...sample, measureType: "bars" }, { ...sample, dataPoints: sample.dataPoints.slice(1) },
    { ...sample, dataPoints: [...sample.dataPoints, sample.dataPoints[0]] },
    { ...sample, dataPoints: [{ logical: 1, price: 10 }, sample.dataPoints[1]] },
    { ...sample, dataPoints: [{ time: 1, logical: 1, price: 10 }, sample.dataPoints[1]] },
  ]) assert.equal(normalizeSavedDrawingItemStrict(bad), null);
});

test("rulers share document create/style/lock/delete history and restore their exact payload", () => {
  const store = createDrawingDocumentStore("rulers");
  const commands = drawingCommandsForSavedDrawing(sample, { type: "create" });
  assert.ok(commands); assert.equal(store.dispatchMany(commands).ok, true);
  const original = exportDrawingDocument(store.getSnapshot());
  assert.equal(store.dispatch({ type: "update-style", id: sample.id!, patch: { locked: true, color: "#00f" } }).ok, true);
  assert.equal(store.dispatch({ type: "move", id: sample.id!, geometry: { kind: "range-measure", measureType: "price-time", dataPoints: [{ time: 2, price: 3 }, { time: 4, price: 5 }] } }).ok, false);
  assert.equal(store.replayHistory("undo", (batch) => store.dispatchMany(batch).ok), true);
  assert.deepEqual(exportDrawingDocument(store.getSnapshot()), original);
  assert.equal(store.dispatch({ type: "delete", id: sample.id! }).ok, true);
  assert.equal(store.replayHistory("undo", (batch) => store.dispatchMany(batch).ok), true);
  assert.deepEqual(exportDrawingDocument(store.getSnapshot()), original);
  const restored = importSavedDrawings("rulers", JSON.parse(JSON.stringify(original)));
  assert.ok(restored); assert.deepEqual(exportDrawingDocument(restored), original);
});

test("whole ruler movement recaptures both anchors while endpoint movement changes only that anchor", () => {
  const drawing: SavedRangeMeasureDrawing = { ...sample, dataPoints: [{ time: 10, price: 20 }, { time: 30, price: 40 }] };
  const apply = (pointIndex: number) => applyDrawingEntityDrag({
    drawing, descriptor: { id: sample.id!, type: "range-measure", pointIndex, startMouse: { x: 10, y: 20 }, origPoints: drawing.dataPoints },
    pos: { x: 15, y: 25 }, snap: false,
    dataToScreen: (p) => ({ x: Number(p.time), y: p.price }),
    screenToData: (x, y) => ({ time: x, price: y }),
    screenToDrawingData: (x, y) => ({ time: x, price: y }),
  });
  const moved = apply(-1); assert.ok(moved && moved.type === "range-measure");
  assert.deepEqual(moved.dataPoints, [{ time: 15, price: 25 }, { time: 35, price: 45 }]);
  const resized = apply(0); assert.ok(resized && resized.type === "range-measure");
  assert.deepEqual(resized.dataPoints, [{ time: 15, price: 25 }, { time: 30, price: 40 }]);
  assert.deepEqual(drawing.dataPoints, [{ time: 10, price: 20 }, { time: 30, price: 40 }]);
});
