import assert from "node:assert/strict";
import test from "node:test";
import { drawingVisibleAtInterval, validDrawingIntervals } from "../drawingVisibility.js";
import { exportDrawingDocument, importSavedDrawings } from "../core/drawingCodec.js";
import { createDrawingDocumentStore } from "../core/drawingDocumentStore.js";
import { drawingCommandsForSavedDrawing } from "../core/drawingDocumentRuntime.js";
import { drawingPropertiesCandidate } from "../drawingProperties.js";

test("interval filters distinguish minute/month, preserve old drawings and reject empty/invalid lists", () => {
  assert.equal(drawingVisibleAtInterval({}, "15m"), true);
  assert.equal(drawingVisibleAtInterval({ visibleIntervals: null }, "4h"), true);
  assert.equal(drawingVisibleAtInterval({ visibleIntervals: ["1m"] }, "1M"), false);
  assert.equal(drawingVisibleAtInterval({ visibleIntervals: ["1h", "4h"] }, "4h"), true);
  for (const value of [[], ["1h", "1h"], ["bad"], ["0m"], ["1H"], "1h", [null]]) assert.equal(validDrawingIntervals(value), false);
});

test("all drawing families round-trip visibility and resetting to all is undoable without moving locked geometry", () => {
  for (const type of ["line", "axis-line", "angle-measure", "text", "fibonacci", "position", "shape", "freehand", "highlighter"] as const) {
    const doc = importSavedDrawings("scope", [{ id: "x", type, locked: true, visibleIntervals: ["1h", "4h"], ...((type === "freehand" || type === "highlighter") ? { dataPoints: [{ time: 1, price: 10 }, { time: 2, price: 20 }] } : {}) }]);
    assert.ok(doc, type);
    const saved = exportDrawingDocument(doc)?.[0];
    assert.ok(saved);
    assert.deepEqual(saved.visibleIntervals, ["1h", "4h"]);
    const candidate = drawingPropertiesCandidate(saved, { visibleIntervals: null });
    assert.ok(candidate);
    const commands = drawingCommandsForSavedDrawing(candidate, { type: "update-style" });
    assert.ok(commands);
    const store = createDrawingDocumentStore(doc);
    assert.equal(store.dispatchMany(commands).ok, true);
    assert.equal(store.getSnapshot().entities.get("x")?.style.visibleIntervals, null);
    assert.equal(store.getSnapshot().entities.get("x")?.style.locked, true);
    assert.equal(store.replayHistory("undo", batch => store.dispatchMany(batch).ok), true);
    assert.deepEqual(store.getSnapshot().entities.get("x")?.style.visibleIntervals, ["1h", "4h"]);
    assert.deepEqual(store.getSnapshot().entities.get("x")?.geometry, doc.entities.get("x")?.geometry);
  }
  assert.equal(importSavedDrawings("bad", [{ id: "x", type: "text", visibleIntervals: [] }]), null);
});

test("individual hiding round-trips every family, survives deletion undo, and keeps interval filters independent", () => {
  for (const type of ["line", "axis-line", "angle-measure", "text", "fibonacci", "position", "shape", "freehand", "highlighter"] as const) {
    const document = importSavedDrawings("objects", [{ id: "x", type, locked: true, hidden: true, visibleIntervals: ["1h"], ...((type === "freehand" || type === "highlighter") ? { dataPoints: [{ time: 1, price: 10 }, { time: 2, price: 20 }] } : {}) }]);
    assert.ok(document, type);
    const saved = exportDrawingDocument(document)?.[0];
    assert.ok(saved);
    assert.equal(saved.hidden, true);
    assert.equal(drawingVisibleAtInterval(saved, "1h"), false);
    const store = createDrawingDocumentStore(document);
    const candidate = drawingPropertiesCandidate(saved, { hidden: false });
    assert.ok(candidate);
    const commands = drawingCommandsForSavedDrawing(candidate, { type: "update-style" });
    assert.ok(commands);
    assert.equal(store.dispatchMany(commands).ok, true);
    assert.equal(drawingVisibleAtInterval(candidate, "1h"), true);
    assert.equal(drawingVisibleAtInterval(candidate, "15m"), false);
    assert.deepEqual(store.getSnapshot().entities.get("x")?.geometry, document.entities.get("x")?.geometry);
    assert.equal(store.dispatch({ type: "delete", id: "x" }).ok, true);
    assert.equal(store.replayHistory("undo", batch => store.dispatchMany(batch).ok), true);
    assert.equal(exportDrawingDocument(store.getSnapshot())?.[0]?.hidden, false);
    assert.equal(store.replayHistory("undo", batch => store.dispatchMany(batch).ok), true);
    assert.equal(exportDrawingDocument(store.getSnapshot())?.[0]?.hidden, true);
    assert.equal(store.replayHistory("redo", batch => store.dispatchMany(batch).ok), true);
    const restored = importSavedDrawings("objects", exportDrawingDocument(store.getSnapshot()));
    assert.ok(restored);
    assert.equal(restored.entities.get("x")?.style.hidden, false);
    assert.equal(restored.entities.get("x")?.style.locked, true);
  }
  for (const hidden of ["true", 1, null, {}]) assert.equal(importSavedDrawings("bad", [{ id: "x", type: "text", hidden }]), null);
});
