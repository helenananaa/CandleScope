import assert from "node:assert/strict";
import test from "node:test";

import { createDrawingFrameSnapshotFactory } from "../../../chart-adapter/drawingFrameSnapshot.js";
import type { CoordinateDataPoint } from "../../../chart-adapter/coordinateBridge.js";
import { CHART_DRAWING_ANCHOR_MODES } from "../../chart-representation/chartTypeRegistry.js";
import { exportDrawingDocument, importSavedDrawings, savedDrawingFromEntity } from "../core/drawingCodec.js";
import { createDrawingDocument, createDrawingEntity } from "../core/drawingDocument.js";
import { drawingCommandsForSavedDrawing } from "../core/drawingDocumentRuntime.js";
import { createDrawingDocumentStore } from "../core/drawingDocumentStore.js";
import { drawingToolForSavedObject } from "../drawingAutoSelection.js";
import { supportsDrawingTool } from "../drawingCapabilities.js";
import { normalizeSavedDrawingItemStrict } from "../drawingPersistence.js";
import { formatDrawingPositionPrice } from "../drawingPositionPresentation.js";
import type { DrawingDataPoint, SavedTextDrawing } from "../drawingTypes.js";
import { createDrawingSceneRegistry } from "../engine/drawingSceneRegistry.js";
import { projectDrawingScene, type DrawingSceneProjectionAdapter } from "../engine/drawingSceneProjector.js";
import { applyDrawingEntityDrag } from "../interaction/drawingEntityDrag.js";
import {
  annotationToolForSavedText,
  calloutEditingDecorations,
  createCalloutSavedDrawing,
  createPriceLabelSavedDrawing,
  isEditableTextDrawing,
  textAnnotationDraftDecorations,
  textDragOrigin,
} from "../interaction/drawingTextAnnotations.js";
import { hitTestDrawingScreenDisplayList, type DrawingScreenDisplayList } from "../rendering/drawingDisplayList.js";

const BOX = { time: 100, price: 60 };
const TARGET = { time: 40, price: 140 };
const STYLE = { color: "#f59e0b", fontSize: 12 };

// Identity projection: x = time, y = price.
const toScreen = (point: DrawingDataPoint) => ({ x: point.time ?? 0, y: point.price });
const toData = (x: number, y: number) => ({ time: x, price: y }) as DrawingDataPoint;

function callout(text = "Breakout"): SavedTextDrawing {
  const created = createCalloutSavedDrawing(BOX, TARGET, STYLE, text);
  assert.ok(created);
  return created;
}

function roundTrip(drawing: SavedTextDrawing): unknown {
  const document = importSavedDrawings("callouts", [drawing]);
  assert.ok(document);
  return exportDrawingDocument(document)?.[0];
}

test("a callout keeps its box and target anchors through the document codec", () => {
  const created = callout();
  assert.equal(created.type, "text");
  assert.deepEqual(created.dataPoint, BOX);
  assert.deepEqual(created.target, TARGET);
  assert.equal(created.priceLabel, undefined);
  assert.equal(created.borderColor, STYLE.color, "the box border shows the callout's colour");
  assert.deepEqual(roundTrip(created), created);
  assert.equal(annotationToolForSavedText(created), "callout");
  assert.equal(drawingToolForSavedObject(created), "callout");
  assert.equal(isEditableTextDrawing(created), true);
});

test("a price label stores one anchor and no typed text", () => {
  const created = createPriceLabelSavedDrawing(TARGET, STYLE);
  assert.ok(created);
  assert.equal(created.priceLabel, true);
  assert.equal(created.target, undefined);
  assert.equal(created.text, "");
  assert.equal(created.bgColor, STYLE.color, "the tag is filled with the chosen colour");
  assert.deepEqual(roundTrip(created), created);
  assert.equal(drawingToolForSavedObject(created), "price-label");
  assert.equal(isEditableTextDrawing(created), false, "a price label is never opened for typing");
});

test("persistence rejects malformed callout targets and a price label with a target", () => {
  const base = callout();
  for (const bad of [
    { ...base, target: { time: 1 } },
    { ...base, target: "not a point" },
    { ...base, priceLabel: true },
    { ...base, priceLabel: "yes", target: undefined },
  ]) assert.equal(normalizeSavedDrawingItemStrict(bad), null, JSON.stringify(bad));
  const plain = { ...base, target: undefined };
  assert.ok(normalizeSavedDrawingItemStrict(plain), "plain text stays valid");
});

test("callouts and price labels are offered only on ordinary time-axis charts", () => {
  for (const tool of ["callout", "price-label"] as const) {
    assert.equal(supportsDrawingTool(CHART_DRAWING_ANCHOR_MODES.SOURCE_TIME, tool), true);
    assert.equal(supportsDrawingTool(CHART_DRAWING_ANCHOR_MODES.SOURCE_LINEAGE, tool), false);
  }
});

test("dragging a callout moves the box, the target or both", () => {
  const drawing = callout();
  const drag = (part: "box" | "target" | "callout") => applyDrawingEntityDrag({
    descriptor: {
      id: drawing.id!, type: "text", startMouse: { x: 0, y: 0 },
      origDataPoint: { ...BOX }, part, ...(part === "box" ? {} : { origTarget: { ...TARGET } }),
    },
    drawing,
    pos: { x: 10, y: -5 },
    screenToData: toData,
    screenToDrawingData: toData,
    dataToScreen: toScreen,
    snap: false,
  }) as SavedTextDrawing | null;
  const box = drag("box");
  assert.deepEqual(box?.dataPoint, { time: 110, price: 55 });
  assert.deepEqual(box?.target, TARGET, "the box moves alone; the leader re-aims");
  const target = drag("target");
  assert.deepEqual(target?.dataPoint, BOX);
  assert.deepEqual(target?.target, { time: 50, price: 135 });
  const both = drag("callout");
  assert.deepEqual(both?.dataPoint, { time: 110, price: 55 });
  assert.deepEqual(both?.target, { time: 50, price: 135 });
});

test("hits choose the dragged part from the zone", () => {
  const drawing = callout();
  assert.deepEqual(textDragOrigin(drawing, { body: true }), { part: "box" });
  assert.deepEqual(textDragOrigin(drawing, { zone: "target", pointIndex: 1 }),
    { part: "target", origTarget: TARGET });
  assert.deepEqual(textDragOrigin(drawing, { zone: "leader", pointIndex: -1 }),
    { part: "callout", origTarget: TARGET });
  const label = createPriceLabelSavedDrawing(TARGET, STYLE);
  assert.ok(label);
  assert.deepEqual(textDragOrigin(label, { zone: "target" }), { part: "box" },
    "a price label always moves as one anchor");
});

test("callout edits share document history: move the target, undo, redo", () => {
  const store = createDrawingDocumentStore("callout-history");
  const drawing = callout();
  const create = drawingCommandsForSavedDrawing(drawing, { type: "create" });
  assert.ok(create);
  assert.equal(store.dispatchMany(create).ok, true);
  const moved = { ...drawing, target: { time: 70, price: 90 } };
  const update = drawingCommandsForSavedDrawing(moved, { type: "update", geometryCommand: "resize" });
  assert.ok(update);
  assert.equal(store.dispatchMany(update).ok, true);
  const current = () => savedDrawingFromEntity(store.getSnapshot().entities.get(drawing.id!)!) as SavedTextDrawing;
  assert.deepEqual(current().target, { time: 70, price: 90 });
  const replay = (direction: "undo" | "redo") => store.replayHistory(direction, (batch) => store.dispatchMany(batch).ok);
  assert.equal(replay("undo"), true);
  assert.deepEqual(current().target, TARGET);
  assert.equal(replay("redo"), true);
  assert.deepEqual(current().target, { time: 70, price: 90 });
  // Locking keeps the pointer where it is.
  assert.equal(store.dispatch({ type: "update-style", id: drawing.id!, patch: { locked: true } }).ok, true);
  assert.equal(store.dispatch({ type: "move", id: drawing.id!,
    geometry: { kind: "text", dataPoint: BOX, target: TARGET } }).ok, false);
});

test("drag previews draw the box and a leader to the target", () => {
  const decorations = textAnnotationDraftDecorations(callout(), toScreen, "#f00");
  assert.equal(decorations.length, 2);
  const leader = decorations[1];
  assert.ok(leader && leader.type === "line");
  assert.deepEqual(leader.to, { x: 40, y: 140 });
  const label = createPriceLabelSavedDrawing(TARGET, STYLE);
  assert.ok(label);
  const tag = textAnnotationDraftDecorations(label, toScreen, "#f00");
  const box = tag[0];
  assert.ok(box && box.type === "box");
  assert.ok(box.box.x > 40 && box.box.y + box.box.height < 140, "the tag sits up and right of its anchor");
});

test("while its text is typed, a callout keeps a leader from the editor box to the target", () => {
  const leader = calloutEditingDecorations(callout(), { x: 100, y: 60 }, 8, toScreen);
  assert.equal(leader.length, 1);
  const line = leader[0];
  assert.ok(line && line.type === "line");
  // 12px text, 6px padding: the box is 69.6 x 27.6 from (100, 60); the target is below-left.
  assert.deepEqual(line.from, { x: 100, y: 87.6 });
  assert.deepEqual(line.to, { x: 40, y: 140 });
  assert.equal(line.color, STYLE.color);
  const label = createPriceLabelSavedDrawing(TARGET, STYLE);
  assert.ok(label);
  assert.deepEqual(calloutEditingDecorations(label, null, 0, toScreen), []);
  assert.deepEqual(calloutEditingDecorations(callout(), { x: 30, y: 130 }, 8, toScreen), [], "no leader when the target is under the box");
});

function identityAdapter(): DrawingSceneProjectionAdapter {
  return {
    measureText: (request) => [...request.text].length * request.fontSize * 0.5,
    projectDrawingFrameDataPoints(_frame, points: readonly CoordinateDataPoint[]) {
      const result = new Float64Array(points.length * 2);
      points.forEach((point, index) => {
        result[index * 2] = typeof point.time === "number" ? point.time : Number.NaN;
        result[index * 2 + 1] = Number(point.price);
      });
      return result;
    },
    projectDrawingFrameSourceLineageSpan: () => null,
  };
}

function projectOne(saved: SavedTextDrawing, selected = false): DrawingScreenDisplayList {
  const imported = importSavedDrawings("project", [saved]);
  assert.ok(imported);
  const entity = imported.entities.get(saved.id!);
  assert.ok(entity);
  const document = createDrawingDocument({ scopeKey: "project", entities: [createDrawingEntity(entity)] });
  const registry = createDrawingSceneRegistry("project");
  assert.equal(registry.reconcile(document).ok, true);
  const frame = createDrawingFrameSnapshotFactory().capture({
    axisKind: "time", barSpacing: 10, coordinateKey: "test:time", dpr: 1,
    drawingViewport: { horizontalDomain: "time", minHorizontal: 0, maxHorizontal: 300, minPrice: 0, maxPrice: 300 },
    heightCssPx: 300, projectionKey: "p", seriesData: [], surfaceToken: "s", themeKey: "dark",
    viewportKey: "v", widthCssPx: 300,
  });
  const list = projectDrawingScene({
    adapter: identityAdapter(), document, frame, nodes: registry.getSnapshot().nodes,
    selectedId: selected ? saved.id! : null,
    stamp: Object.freeze({
      scopeKey: document.scopeKey, documentRevision: document.documentRevision,
      surfaceGeneration: frame.surfaceGeneration, dataRevision: frame.dataRevision,
      projectionRevision: frame.projectionRevision, lineageIndexRevision: frame.lineageIndexRevision,
      viewportRevision: frame.viewportRevision, themeRevision: frame.themeRevision,
      widthCssPx: frame.widthCssPx, heightCssPx: frame.heightCssPx, dpr: frame.dpr,
    }),
  });
  assert.ok(list);
  return list;
}

test("the scene paints a callout leader from the box border to its target", () => {
  const list = projectOne(callout());
  const entity = list.entities[0];
  assert.ok(entity && entity.renderSpec?.op === "text");
  assert.equal(entity.renderSpec.leaderPointOffset, 2);
  const point = (index: number) => [list.points[(entity.pointOffset + index) * 2], list.points[(entity.pointOffset + index) * 2 + 1]];
  assert.deepEqual(point(0), [100, 60], "the box still starts at its own anchor");
  assert.deepEqual(point(3), [40, 140], "the leader ends on the target");
  assert.deepEqual(point(2), [100, point(1)[1]], "the leader leaves the box's nearest corner");
  // The target dot grabs the target; the box body grabs the box; the leader grabs both.
  assert.deepEqual(pickZone(list, 40, 140), { zone: "target", pointIndex: 1 });
  assert.deepEqual(pickZone(list, 105, 65), { body: true });
  const midX = (Number(point(2)[0]) + 40) / 2;
  const midY = (Number(point(2)[1]) + 140) / 2;
  assert.deepEqual(pickZone(list, midX, midY), { zone: "leader", pointIndex: -1 });
});

test("a selected callout exposes its target as a handle beside the box handles", () => {
  const list = projectOne(callout(), true);
  const entity = list.entities[0];
  assert.ok(entity);
  assert.equal(entity.handleCount, 9);
  assert.equal(entity.handleNames.at(-1), "target");
});

test("a price label shows its anchor's price and moves as one", () => {
  const label = createPriceLabelSavedDrawing({ time: 50, price: 123.456 }, STYLE);
  assert.ok(label);
  const list = projectOne(label);
  const entity = list.entities[0];
  assert.ok(entity && entity.renderSpec?.op === "text");
  assert.deepEqual(entity.renderSpec.lines.map((line) => line.text), [formatDrawingPositionPrice(123.456)]);
  const top = Number(list.points[entity.pointOffset * 2 + 1]);
  const bottom = Number(list.points[(entity.pointOffset + 1) * 2 + 1]);
  assert.ok(bottom < 123.456, "the tag sits above its anchor");
  assert.ok(top < bottom);
  assert.deepEqual(pickZone(list, 50, 123.456 - 1), { body: true }, "its pointer moves the whole label");
});

function pickZone(list: DrawingScreenDisplayList, x: number, y: number): unknown {
  const hit = hitTestDrawingScreenDisplayList(list, x, y);
  if (!hit) return null;
  const { entityId: _id, kind: _kind, ...rest } = hit;
  return rest;
}
