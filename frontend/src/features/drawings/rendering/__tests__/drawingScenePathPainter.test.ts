import assert from "node:assert/strict";
import test from "node:test";
import { structuralMock } from "../../../../test/testHelpers.js";
import type { DrawingDisplayEntity, DrawingScreenDisplayList } from "../drawingDisplayList.js";
import { drawPathSceneEntity } from "../drawingScenePathPainter.js";

function filledPolygons(points: number[], arrowEnd = true) {
  const polygons: number[][] = [];
  let current: number[] = [];
  const lineTo = (x: number, y: number) => current.push(x, y);
  const ctx = structuralMock<CanvasRenderingContext2D>({
    save() {}, restore() {}, scale() {}, stroke() {}, closePath() {},
    beginPath() { current = []; }, moveTo: lineTo, lineTo,
    fill() { polygons.push([...current]); },
  });
  const entity = structuralMock<DrawingDisplayEntity>({
    pointOffset: 1, pointCount: points.length / 2,
    renderSpec: { op: "path", arrowEnd, selected: false, lineWidthCssPx: 2, strokeColor: "#ccc" },
  });
  const list = structuralMock<DrawingScreenDisplayList>({ points: new Float32Array([99, 99, ...points]) });
  drawPathSceneEntity(ctx, entity, list, 2, 2);
  return polygons;
}

test("one terminal arrow follows the last nonzero projected segment even after a reverse turn", () => {
  const [head, ...additional] = filledPolygons([10, 10, 35, 15, 5, 15, 5, 15]);
  assert.ok(head);
  assert.deepEqual(additional, []);
  assert.deepEqual(head.slice(0, 2), [5, 15]);
  assert.ok(head[2]! > 5 && head[4]! > 5);
  assert.equal((head[3]! + head[5]!) / 2, 15);
});

test("coincident projections and the plain path variant paint no head", () => {
  assert.deepEqual(filledPolygons([12, 12, 12, 12, 12, 12]), []);
  assert.deepEqual(filledPolygons([12, 12, 20, 42], false), []);
});
