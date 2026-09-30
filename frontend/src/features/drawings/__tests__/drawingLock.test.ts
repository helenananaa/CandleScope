import assert from "node:assert/strict";
import test from "node:test";
import { importSavedDrawings, exportDrawingDocument } from "../core/drawingCodec.js";
import { createDrawingDocumentStore } from "../core/drawingDocumentStore.js";
import { drawingPropertiesCandidate } from "../drawingProperties.js";
import { dynamicSelectionHandlesForSavedDrawing } from "../drawingInteractionController.js";
import type { SavedDrawing } from "../drawingTypes.js";

const shape: SavedDrawing = { id: "s", type: "shape", shapeType: "rectangle", locked: true,
  dataPoints: [{ time: 100, price: 10 }, { time: 200, price: 20 }], color: "#123456" };

test("lock survives strict document round trips for every drawing family; old drawings remain unlocked", () => {
  for (const type of ["line", "axis-line", "angle-measure", "text", "fibonacci", "position", "shape", "freehand", "highlighter"] as const) {
    const item = { id: type, type, locked: true, ...((type === "freehand" || type === "highlighter") ? { dataPoints: [{ time: 100, price: 10 }, { time: 200, price: 20 }] } : {}) };
    const doc = importSavedDrawings(type, [item]);
    assert.ok(doc, type);
    assert.equal(exportDrawingDocument(doc)?.[0]?.locked, true, type);
  }
  assert.equal(importSavedDrawings("bad", [{ ...shape, locked: "true" }]), null);
  const old = importSavedDrawings("old", [{ ...shape, locked: undefined }]);
  assert.ok(old);
  assert.equal(old.entities.get("s")?.style.locked, undefined);
});

test("locked geometry rejects move and resize atomically; style and unlock remain editable", () => {
  const initial = importSavedDrawings("scope", [shape]);
  assert.ok(initial);
  const store = createDrawingDocumentStore("scope");
  store.loadDocument(initial);
  const entity = initial.entities.get("s")!;
  const geometry = { ...entity.geometry, dataPoints: [{ time: 300, price: 30 }, { time: 400, price: 40 }] };
  for (const type of ["move", "resize"] as const) {
    const before = store.getSnapshot();
    assert.equal(store.dispatchMany([{ type: "update-style", id: "s", patch: { color: "#ffffff" } }, { type, id: "s", geometry }]).ok, false);
    assert.equal(store.getSnapshot(), before);
  }
  assert.equal(store.dispatch({ type: "update-style", id: "s", patch: { color: "#ffffff" } }).ok, true);
  assert.equal(store.dispatch({ type: "update-style", id: "s", patch: { locked: false } }).ok, true);
  assert.equal(store.dispatch({ type: "move", id: "s", geometry }).ok, true);
  const replay = (direction: "undo" | "redo") => store.replayHistory(direction, commands => store.dispatchMany(commands).ok);
  assert.equal(replay("undo"), true);
  assert.equal(replay("undo"), true);
  assert.equal(store.getSnapshot().entities.get("s")?.style.locked, true);
  assert.equal(replay("redo"), true);
  assert.equal(store.getSnapshot().entities.get("s")?.style.locked, false);
});

test("locked properties keep coordinates read-only and suppress resize handles", () => {
  assert.equal(drawingPropertiesCandidate(shape, {}, [{ time: 300, price: 30 }, { time: 400, price: 40 }]), null);
  assert.equal(drawingPropertiesCandidate(shape, { color: "#ffffff" })?.locked, true);
  assert.equal(drawingPropertiesCandidate(shape, { locked: false })?.locked, false);
  assert.deepEqual(dynamicSelectionHandlesForSavedDrawing(shape, p => ({ x: Number(p.time), y: p.price }), { x: 0, y: 0, width: 100, height: 100 }), []);
});
