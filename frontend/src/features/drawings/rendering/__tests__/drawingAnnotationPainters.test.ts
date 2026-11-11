import assert from "node:assert/strict";
import test from "node:test";

import type { PrimitiveCanvasTarget } from "../../drawingTypes.js";
import type { DrawingRenderRevisionStamp } from "../../engine/drawingRenderScheduler.js";
import { createDrawingScreenDisplayList } from "../drawingDisplayList.js";
import type { ProjectedDrawingEntity } from "../drawingDisplayList.js";
import { DrawingSceneRenderer } from "../drawingSceneRenderer.js";

const stamp: DrawingRenderRevisionStamp = Object.freeze({
  scopeKey: "annotations",
  documentRevision: 1,
  surfaceGeneration: 1,
  dataRevision: 1,
  projectionRevision: 1,
  lineageIndexRevision: 1,
  viewportRevision: 1,
  themeRevision: 1,
  widthCssPx: 200,
  heightCssPx: 100,
  dpr: 1,
});

interface Call { readonly name: string; readonly args: readonly unknown[] }

function paint(entities: readonly ProjectedDrawingEntity[]): Call[] {
  const calls: Call[] = [];
  const record = (name: string) => (...args: unknown[]) => { calls.push({ name, args }); };
  const context = new Proxy({} as Record<string, unknown>, {
    get(target, property: string) {
      if (property in target) return target[property];
      return record(property);
    },
    set(target, property: string, value) {
      target[property] = value;
      calls.push({ name: `set:${property}`, args: [value] });
      return true;
    },
  }) as unknown as CanvasRenderingContext2D;
  const target = {
    useBitmapCoordinateSpace(callback: (scope: unknown) => void) {
      callback({ context, horizontalPixelRatio: 1, verticalPixelRatio: 1, bitmapSize: { width: 200, height: 100 } });
    },
  } as unknown as PrimitiveCanvasTarget;
  const renderer = new DrawingSceneRenderer();
  renderer.setPlan(createDrawingScreenDisplayList(stamp, entities));
  renderer.draw(target);
  return calls;
}

test("an arrow stops its shaft short of the tip and fills a head there", () => {
  const calls = paint([{
    id: "arrow", kind: "line", geometryRevision: 1, styleRevision: 1,
    style: { kind: "line", color: "#f00", lineWidth: 2, arrowEnd: true },
    points: new Float64Array([10, 50, 110, 50, 10, 50, 110, 50]),
    bbox: [10, 50, 110, 50],
    renderSpec: {
      op: "line", lineType: "line-segment", strokeColor: "#f00", selectionHighlightColor: "rgba(255,0,0,0.15)",
      lineWidthCssPx: 2, selected: false, mainPointOffset: 0, anchorPointOffset: 2, drawEndpointDots: true, arrowEnd: true,
    },
  }]);
  const shaftEnd = calls.find((call) => call.name === "lineTo");
  assert.ok(shaftEnd && Number(shaftEnd.args[0]) < 110, "shaft ends before the tip");
  const tipMove = calls.findIndex((call) => call.name === "moveTo" && call.args[0] === 110 && call.args[1] === 50);
  assert.ok(tipMove >= 0, "head path starts at the tip");
  assert.ok(calls.slice(tipMove).some((call) => call.name === "fill"), "head is filled");
  const endDots = calls.filter((call) => call.name === "arc" && call.args[0] === 110);
  assert.equal(endDots.length, 0, "the tip does not also get an endpoint dot");
});

test("a channel fills its band, strokes both rails and dashes the midline", () => {
  const calls = paint([{
    id: "channel", kind: "channel", geometryRevision: 1, styleRevision: 1,
    style: { kind: "channel", color: "#0a0", lineWidth: 2 },
    points: new Float64Array([20, 80, 120, 40, 120, 10, 20, 50, 20, 65, 120, 25, 70, 30]),
    bbox: [20, 10, 120, 80],
    hitZones: [{ kind: "polygon", pointOffset: 0, pointCount: 4, tolerance: 0, result: { pointIndex: -1, zone: "body" } }],
    renderSpec: {
      op: "channel", strokeColor: "#0a0", fillPaintColor: "rgba(0,170,0,0.08)", lineWidthCssPx: 2, selected: true,
      polygonPointOffset: 0, midlinePointOffset: 4, offsetHandlePointOffset: 6,
    },
  }]);
  assert.ok(calls.some((call) => call.name === "closePath"), "band is a closed polygon");
  assert.ok(calls.some((call) => call.name === "setLineDash" && Array.isArray(call.args[0]) && (call.args[0] as number[]).length === 2));
  assert.deepEqual(calls.filter((call) => call.name === "arc").map((call) => [call.args[0], call.args[1]]),
    [[20, 80], [120, 40], [70, 30]], "selected channels show start, end and width handles");
});

test("polygon hit zones must name at least three vertices", () => {
  assert.throws(() => createDrawingScreenDisplayList(stamp, [{
    id: "bad", kind: "channel", geometryRevision: 1, styleRevision: 1,
    style: { kind: "channel" },
    points: new Float64Array([0, 0, 1, 1]),
    bbox: [0, 0, 1, 1],
    hitZones: [{ kind: "polygon", pointOffset: 0, pointCount: 2, tolerance: 0 }],
  }]), /hit zone is invalid/);
});

test("an extended zone paints an open box to the pane edge with its midline, name and prices", () => {
  const calls = paint([{
    id: "zone", kind: "shape", geometryRevision: 1, styleRevision: 1,
    style: { kind: "shape", color: "#f59e0b", lineWidth: 1 },
    points: new Float64Array([20, 30, 80, 70, 80, 30, 200, 70]),
    bbox: [20, 30, 200, 70],
    renderSpec: {
      op: "shape", shapeType: "rectangle", strokeColor: "#f59e0b", fillPaintColor: "rgba(245,158,11,0.12)",
      lineWidthCssPx: 1, lineStyle: "solid", selected: false, boxPointOffset: 0,
      extensionPointOffset: 2, midline: true, label: "Demand", topPriceText: "101.0000", bottomPriceText: "99.0000",
    },
  }]);
  const fillRect = calls.find((call) => call.name === "rect");
  assert.deepEqual(fillRect?.args, [20, 30, 180, 40], "fill reaches the pane edge");
  assert.ok(calls.some((call) => call.name === "moveTo" && call.args[0] === 200 && call.args[1] === 30), "outline is open on the right");
  assert.ok(calls.some((call) => call.name === "moveTo" && call.args[0] === 20 && call.args[1] === 50), "midline at the mid price");
  const texts = calls.filter((call) => call.name === "fillText").map((call) => call.args[0]);
  assert.deepEqual(texts, ["Demand", "101.0000", "99.0000"]);
});
