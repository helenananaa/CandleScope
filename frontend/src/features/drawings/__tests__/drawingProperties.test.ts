import assert from "node:assert/strict";
import test from "node:test";
import { drawingCoordinates, drawingPropertiesCandidate, formatCoordinateTime, parseCoordinateTime } from "../drawingProperties.js";
import { coordinateDraft, parseCoordinateDraft } from "../drawingProperties.js";
import { drawingCommandsForSavedDrawing } from "../core/drawingDocumentRuntime.js";
import { importSavedDrawings, exportDrawingDocument } from "../core/drawingCodec.js";
import { createDrawingDocumentStore } from "../core/drawingDocumentStore.js";
import type { SavedDrawing } from "../drawingTypes.js";

const shape: SavedDrawing = {
  id: "rectangle", type: "shape", shapeType: "rectangle",
  dataPoints: [{ time: 1790688000, price: 10.12345 }, { time: 1790691600, price: -2 }],
  color: "#123456", fillColor: "#abcdef", fillOpacity: 0.25, lineWidth: 2, lineStyle: "solid",
};

test("coordinate dates round-trip in UTC, including leap days, and reject normalized invalid dates", () => {
  const valid = ["2024-02-29T12:34", "2026-09-29T00:00:01", "2026-09-29T00:00:01.123"];
  for (const value of valid) {
    const time = parseCoordinateTime(value);
    assert.notEqual(time, null);
    assert.equal(formatCoordinateTime(time!).slice(0, value.length), value);
  }
  for (const value of ["", "2025-02-29T12:00", "2026-02-30T12:00", "2026-01-01T24:00", "2026-01-01T12:00+08:00", "0000-01-01T00:00"]) {
    assert.equal(parseCoordinateTime(value), null, value);
  }
  assert.equal(formatCoordinateTime(Infinity), "");
});

test("coordinate drafts retain untouched timestamp precision and reject partial numeric input", () => {
  const original = [{ time: 1790688000.12345, price: -0.000001 }];
  assert.deepEqual(parseCoordinateDraft(coordinateDraft(original), original), original);
  assert.equal(parseCoordinateDraft([{ time: "2026-09-29T00:00", price: "" }]), null);
  assert.equal(parseCoordinateDraft([{ time: "2026-09-29T00:00", price: "1e" }]), null);
  assert.equal(parseCoordinateDraft([{ time: "2026-09-29T00:00", price: "Infinity" }]), null);
});

test("coordinate support preserves lineage and logical anchors by refusing reinterpretation", () => {
  assert.deepEqual(drawingCoordinates(shape), shape.dataPoints);
  for (const point of [
    { time: 100, sourceOrdinal: 2, price: 10 },
    { time: 100, sourceProjection: "renko", price: 10 },
    { logical: 3, price: 10 },
  ]) {
    const saved: SavedDrawing = { ...shape, dataPoints: [point, point] };
    assert.equal(drawingCoordinates(saved), null);
    assert.equal(drawingPropertiesCandidate(saved, {}, [{ time: 200, price: 20 }, { time: 300, price: 30 }]), null);
  }
});

test("properties reject stale coordinates, invalid values and wrong point counts without changing input", () => {
  const before = JSON.stringify(shape);
  assert.equal(drawingPropertiesCandidate(shape, {}, [{ time: 100, price: 20 }]), null);
  assert.equal(drawingPropertiesCandidate(shape, {}, [{ time: NaN, price: 20 }, { time: 200, price: 30 }]), null);
  const points = drawingCoordinates(shape)!;
  assert.equal(drawingPropertiesCandidate(shape, {}, points, points.map((point) => ({ ...point, price: 999 }))), null);
  assert.equal(JSON.stringify(shape), before);
});

test("combined coordinate and style save persists future timestamps and is a single undoable batch", () => {
  const document = importSavedDrawings("coordinates", [shape]);
  assert.ok(document);
  const store = createDrawingDocumentStore(document);
  const readFirst = () => {
    const drawings = exportDrawingDocument(store.getSnapshot());
    const first = drawings?.[0];
    assert.ok(first);
    return first;
  };
  const original = drawingCoordinates(shape)!;
  const moved = original.map((point) => ({ time: point.time + 86400 * 100, price: point.price + 10 }));
  const candidate = drawingPropertiesCandidate(shape, { color: "#ff0000", fillOpacity: 0.5 }, moved, original);
  assert.ok(candidate);
  const commands = drawingCommandsForSavedDrawing(candidate, { type: "update", geometryCommand: "resize" });
  assert.ok(commands);
  assert.equal(store.dispatchMany(commands).ok, true);
  assert.equal(store.getSnapshot().documentRevision, document.documentRevision + 1);
  const saved = readFirst();
  assert.deepEqual(drawingCoordinates(saved), moved);
  assert.ok(saved.type === "shape");
  assert.equal(saved.color, "#ff0000");
  assert.equal(store.replayHistory("undo", (batch) => store.dispatchMany(batch).ok), true);
  assert.deepEqual(drawingCoordinates(readFirst()), original);
  assert.equal(store.canUndo, false);
  assert.equal(store.replayHistory("redo", (batch) => store.dispatchMany(batch).ok), true);
  assert.deepEqual(drawingCoordinates(readFirst()), moved);
});

test("axis lines expose a single point and style edits preserve the other geometry fields", () => {
  const axis: SavedDrawing = { id: "axis", type: "axis-line", axisLineType: "horizontal", dataPoint: { time: 100, price: 10 }, color: "#fff", lineWidth: 2 };
  assert.equal(drawingCoordinates(axis)?.length, 1);
  const candidate = drawingPropertiesCandidate(axis, { fillOpacity: 0.9 }, [{ time: 200, price: 30 }]);
  assert.ok(candidate && candidate.type === "axis-line");
  assert.equal(candidate.axisLineType, "horizontal");
  assert.deepEqual(candidate.dataPoint, { time: 200, price: 30 });
  assert.equal("fillOpacity" in candidate, false);
});
