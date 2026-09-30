import assert from "node:assert/strict";
import test from "node:test";
import { projectStrokeForDrag, translateStroke, type CaptureStroke, type SavedStroke } from "../freehandDrag.js";
import { applyDrawingEntityDrag, drawingEntityGeometryCommandForDrag } from "../drawingEntityDrag.js";
import { drawingCommandsForSavedDrawing } from "../../core/drawingDocumentRuntime.js";
import { createDrawingDocumentStore } from "../../core/drawingDocumentStore.js";
import type { DrawingChartAdapter, DrawingDataPoint, SourceLineageSpan } from "../../drawingTypes.js";

const identity = {};
const points = [{ x: 100, y: 10 }, { x: 110, y: 11 }, { x: 120, y: 12 }];
const original: SavedStroke = { id: "pen", type: "freehand", color: "#123456", lineWidth: 3,
  dataPoints: points.map(p => ({ time: p.x, price: p.y })) };
const capture: CaptureStroke = samples => ({ captureIdentity: identity, sourceProjection: "time",
  sourceProjectionConfig: "{}", captures: samples.map(p => ({ time: p.x, price: p.y, screen: p })) });
const project = (p: DrawingDataPoint) => ({ x: Number(p.time), y: p.price });
const adapter = { priceToCoordinate: (price: number) => price, captureDrawingFrame: () => ({}) } as unknown as DrawingChartAdapter;

test("whole-stroke translation retains every collinear sample and original style; zero movement is a no-op", () => {
  assert.equal(translateStroke(original, points, { x: 0, y: 0 }, identity, capture), original);
  const moved = translateStroke(original, points, { x: 20, y: -3 }, identity, capture);
  assert.ok(moved?.dataPoints);
  assert.deepEqual(moved.dataPoints, [{ time: 120, price: 7 }, { time: 130, price: 8 }, { time: 140, price: 9 }]);
  assert.equal(moved.color, original.color);
  assert.equal(moved.lineWidth, 3);
  assert.equal("stroke" in moved, false);
  assert.deepEqual(projectStrokeForDrag(moved, project, adapter), [{ x: 120, y: 7 }, { x: 130, y: 8 }, { x: 140, y: 9 }]);
  assert.deepEqual(projectStrokeForDrag(original, project, adapter), points);
});

test("unresolved samples, partial capture, changed identity and locked strokes fail closed", () => {
  assert.equal(projectStrokeForDrag(original, p => p.price === 11 ? null : project(p), adapter), null);
  for (const bad of [() => null, () => ({ ...capture(points), captureIdentity: {} }),
    () => ({ ...capture(points), captures: [{ time: 100, price: 1 }] }),
    () => ({ ...capture(points), captures: [{}, {}, {}] })] as CaptureStroke[]) {
    assert.equal(translateStroke(original, points, { x: 1, y: 2 }, identity, bad), null);
  }
  assert.equal(translateStroke({ ...original, locked: true }, points, { x: 1, y: 2 }, identity, capture), null);
});

test("successive pointer moves always translate original samples and document history restores the exact legacy payload", () => {
  const descriptor = { type: "freehand" as const, id: original.id!, startMouse: { x: 100, y: 10 },
    original, origScreenPoints: points, captureIdentity: identity };
  const options = { descriptor, drawing: original, pos: { x: 110, y: 20 }, snap: false,
    screenToData: (x: number, y: number) => ({ time: x, price: y }),
    screenToDrawingData: (x: number, y: number) => ({ time: x, price: y }), dataToScreen: project, captureStroke: capture };
  const first = applyDrawingEntityDrag(options);
  assert.ok(first);
  const moved = applyDrawingEntityDrag({ ...options, drawing: first, pos: { x: 120, y: 30 } });
  assert.ok(moved && moved.type === "freehand");
  assert.deepEqual(moved.dataPoints?.[0], { time: 120, price: 30 });
  assert.equal(drawingEntityGeometryCommandForDrag(descriptor), "move");
  const store = createDrawingDocumentStore("stroke-test");
  store.dispatchMany(drawingCommandsForSavedDrawing(original, { type: "create" })!);
  const before = store.getSnapshot().entities.get(original.id!)?.geometry;
  const result = store.dispatchMany(drawingCommandsForSavedDrawing(moved, { type: "update", geometryCommand: "move" })!);
  assert.equal(result.changed, true);
  const after = store.getSnapshot().entities.get(original.id!)?.geometry;
  assert.equal(store.replayHistory("undo", commands => store.dispatchMany(commands).ok), true);
  assert.deepEqual(store.getSnapshot().entities.get(original.id!)?.geometry, before);
  assert.equal(store.replayHistory("redo", commands => store.dispatchMany(commands).ok), true);
  assert.deepEqual(store.getSnapshot().entities.get(original.id!)?.geometry, after);
});

const span: SourceLineageSpan = { exact: { left: { time: 100, sourceOrdinal: 0 }, right: { time: 200, sourceOrdinal: 1 } },
  fallback: { fromTime: 100, toTime: 200, leftRatio: 0, rightRatio: 1 } };

test("span and exact-ordinal strokes project all anchors and preserve highlighter metadata through recapture", () => {
  const saved: SavedStroke = { id: "highlight", type: "highlighter", opacity: 0.22, compositeOperation: "multiply", brushShape: "square",
    stroke: { version: 3, sourceProjection: "renko", sourceProjectionConfig: "{}", spans: [span],
      points: [{ span: 0, ratio: 0.5, price: 10 }, { anchor: { time: 200, sourceOrdinal: 1 }, price: 20 }] } };
  const derivedAdapter = { ...adapter, projectDrawingFrameSourceLineageSpan: () => ({ left: 100, right: 200 }) } as unknown as DrawingChartAdapter;
  const projected = projectStrokeForDrag(saved, project, derivedAdapter);
  assert.deepEqual(projected, [{ x: 150, y: 10 }, { x: 200, y: 20 }]);
  assert.equal(projectStrokeForDrag(saved, project, adapter), null);
  const moved = translateStroke(saved, projected!, { x: 10, y: 5 }, identity, ps => ({ captureIdentity: identity,
    sourceProjection: "renko", sourceProjectionConfig: "{}", captures: ps.map((p, i) => ({ anchor: { time: p.x, sourceOrdinal: i }, price: p.y, screen: p })) }));
  assert.ok(moved?.type === "highlighter");
  assert.equal(moved.opacity, 0.22);
  assert.equal(moved.brushShape, "square");
  assert.deepEqual(moved.stroke?.points[0], { anchor: { time: 160, sourceOrdinal: 0 }, price: 15 });
});


test("canonical collinear stroke translation preserves all samples without a second simplification", () => {
  const saved: SavedStroke = { id: "canonical", type: "freehand", stroke: { version: 3,
    sourceProjection: "time", sourceProjectionConfig: "{}", spans: [],
    points: points.map(p => ({ time: p.x, price: p.y })) } };
  const moved = translateStroke(saved, points, { x: 10, y: 20 }, identity, capture);
  assert.equal(moved?.stroke?.points.length, 3);
  assert.deepEqual(moved?.stroke?.points[1], { time: 120, price: 31 });
});


test("full-capacity zigzag movement retains all samples without simplification", () => {
  const samples = Array.from({ length: 4096 }, (_, i) => ({ x: 100 + i / 4, y: 100 + (i % 2) * 50 }));
  const saved: SavedStroke = { id: "dense", type: "freehand", stroke: { version: 3,
    sourceProjection: "time", sourceProjectionConfig: "{}", spans: [],
    points: samples.map(p => ({ time: p.x, price: p.y })) } };
  const moved = translateStroke(saved, samples, { x: 10, y: 20 }, identity, capture);
  assert.deepEqual(moved?.stroke?.points, samples.map(p => ({ time: p.x + 10, price: p.y + 20 })));
});
