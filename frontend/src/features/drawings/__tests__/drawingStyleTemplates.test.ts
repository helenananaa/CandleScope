import assert from "node:assert/strict";
import test from "node:test";
import { changeStyleTemplate, readStyleTemplates, STYLE_TEMPLATE_KEY, styleFamily, templateStyle } from "../drawingStyleTemplateStore.js";
import { drawingPropertiesCandidate } from "../drawingProperties.js";
import { importSavedDrawings, exportDrawingDocument } from "../core/drawingCodec.js";
import { drawingCommandsForSavedDrawing } from "../core/drawingDocumentRuntime.js";
import { createDrawingDocumentStore } from "../core/drawingDocumentStore.js";
import type { SavedDrawing } from "../drawingTypes.js";

const style = { color: "#123456", lineWidth: 3, fillColor: "#abcdef", fillOpacity: 0.4, lineStyle: "dotted" };
function memoryStorage() {
  const values = new Map<string, string>();
  return { values, getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); } };
}

test("templates retain only supported style fields and isolate compatible families", () => {
  assert.equal(styleFamily("rectangle"), styleFamily("ellipse"));
  assert.equal(styleFamily("position-long"), null);
  assert.equal(styleFamily("text"), null);
  assert.deepEqual(templateStyle("shape", { ...style, id: "secret", coordinates: [{ time: 100, price: 20 }], positionSize: 10000 }), style);
  assert.deepEqual(templateStyle("stroke", { ...style, opacity: 0.8 }), { color: style.color, lineWidth: 3 });
  assert.equal(templateStyle("shape", { ...style, fillOpacity: 2 }), null);
  assert.equal(templateStyle("stroke", { color: "invalid", lineWidth: 2 }), null);
  assert.equal(templateStyle("stroke", { color: "#abc", lineWidth: 2 })?.color, "#aabbcc");
});

test("templates survive reload, reject duplicate names, and merge writes against latest data", () => {
  const storage = memoryStorage();
  assert.equal(changeStyleTemplate({ kind: "save", family: "shape", name: " Zone ", style }, storage).ok, true);
  assert.equal(changeStyleTemplate({ kind: "save", family: "stroke", name: "Zone", style }, storage).ok, true);
  assert.deepEqual(changeStyleTemplate({ kind: "save", family: "shape", name: "zone", style }, storage), { ok: false, error: "duplicate" });
  const loaded = readStyleTemplates(storage);
  assert.ok(loaded.ok);
  assert.equal(loaded.templates.length, 2);
  assert.equal(loaded.templates[0]?.name, "Zone");
  assert.equal(changeStyleTemplate({ kind: "delete", family: "shape", name: "Zone" }, storage).ok, true);
  const remaining = readStyleTemplates(storage);
  assert.ok(remaining.ok);
  assert.equal(remaining.templates.length, 1);
  assert.equal(remaining.templates[0]?.family, "stroke");
});

test("corrupt or unavailable storage never reports success or overwrites existing data", () => {
  const storage = memoryStorage();
  storage.setItem(STYLE_TEMPLATE_KEY, '{"version":99,"templates":[]}');
  const before = storage.getItem(STYLE_TEMPLATE_KEY);
  assert.equal(changeStyleTemplate({ kind: "save", family: "shape", name: "Zone", style }, storage).ok, false);
  assert.equal(storage.getItem(STYLE_TEMPLATE_KEY), before);
  const blocked = { getItem: () => null, setItem: () => { throw new Error("quota"); } };
  assert.deepEqual(changeStyleTemplate({ kind: "save", family: "shape", name: "Zone", style }, blocked), { ok: false, error: "storage" });
});

test("template counts are bounded and Fibonacci levels are validated and copied", () => {
  const storage = memoryStorage();
  for (let index = 0; index < 20; index++) assert.equal(changeStyleTemplate({ kind: "save", family: "shape", name: String(index), style }, storage).ok, true);
  assert.deepEqual(changeStyleTemplate({ kind: "save", family: "shape", name: "overflow", style }, storage), { ok: false, error: "limit" });
  const levels = [{ level: 0.5, enabled: true, color: "#abc" }];
  const copied = templateStyle("fibonacci", { ...style, levels });
  assert.ok(copied);
  assert.notEqual(copied.levels, levels);
  assert.equal(templateStyle("fibonacci", { ...style, levels: [...levels, ...levels] }), null);
});

test("applying a template changes only style and uses one undo step", () => {
  const target: SavedDrawing = { id: "target", type: "shape", shapeType: "ellipse", dataPoints: [{ time: 100, price: 20 }, { time: 200, price: 30 }], color: "#ff0000", lineWidth: 2, fillColor: "#ff0000", fillOpacity: 0.1, lineStyle: "solid" };
  const document = importSavedDrawings("templates", [target]);
  assert.ok(document);
  const store = createDrawingDocumentStore(document);
  const clean = templateStyle("shape", style);
  assert.ok(clean);
  const candidate = drawingPropertiesCandidate(target, clean);
  assert.ok(candidate);
  const commands = drawingCommandsForSavedDrawing(candidate, { type: "update-style" });
  assert.ok(commands);
  assert.equal(store.dispatchMany(commands).ok, true);
  const entity = store.getSnapshot().entities.get("target");
  assert.deepEqual(entity?.geometry, document.entities.get("target")?.geometry);
  assert.equal(entity?.geometryRevision, document.entities.get("target")?.geometryRevision);
  assert.equal(store.replayHistory("undo", (batch) => store.dispatchMany(batch).ok), true);
  assert.equal(store.canUndo, false);
  assert.deepEqual(exportDrawingDocument(store.getSnapshot()), exportDrawingDocument(document));
});
