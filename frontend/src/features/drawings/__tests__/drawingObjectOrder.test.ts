import assert from "node:assert/strict";
import test from "node:test";
import { drawingObjectOrder } from "../drawingObjectApi.js";
import { createDrawingDocumentStore } from "../core/drawingDocumentStore.js";
import { exportDrawingDocument, importSavedDrawings } from "../core/drawingCodec.js";

test("object layering preserves hidden/locked peers, round-trips storage and replays as one history step", () => {
  const store = createDrawingDocumentStore("main");
  for (const id of ["back", "middle", "front"]) store.dispatch({ type: "create", entity: {
    id, kind: "line", geometry: { kind: "line", lineType: "line-segment", dataPoints: [{ time: 100, price: 10 }, { time: 200, price: 20 }] },
    style: { kind: "line", color: "#fff", lineWidth: 2, hidden: id === "front", locked: id === "middle" },
  } });
  const before = store.getSnapshot();
  assert.equal(drawingObjectOrder(before, "unknown", "front"), null);
  assert.equal(drawingObjectOrder(before, "front", "front"), before.zOrder);
  const order = drawingObjectOrder(before, "middle", "front");
  assert.ok(order);
  assert.equal(store.dispatch({ type: "reorder", order }).changed, true);
  const after = store.getSnapshot();
  assert.deepEqual(after.zOrder, ["back", "front", "middle"]);
  for (const id of before.zOrder) assert.equal(after.entities.get(id), before.entities.get(id));
  assert.deepEqual(importSavedDrawings("main", exportDrawingDocument(after))?.zOrder, after.zOrder);
  assert.equal(store.replayHistory("undo", commands => store.dispatchMany(commands).ok), true);
  assert.deepEqual(store.getSnapshot().zOrder, before.zOrder);
  assert.equal(store.replayHistory("redo", commands => store.dispatchMany(commands).ok), true);
  assert.deepEqual(store.getSnapshot().zOrder, after.zOrder);
  assert.deepEqual(drawingObjectOrder(after, "middle", "back"), ["middle", "back", "front"]);
  assert.equal(createDrawingDocumentStore("other-pane").getSnapshot().zOrder.length, 0);
});
