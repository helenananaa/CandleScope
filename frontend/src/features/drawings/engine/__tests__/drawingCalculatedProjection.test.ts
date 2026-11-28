import assert from "node:assert/strict";
import test from "node:test";

import { createDrawingFrameSnapshotFactory } from "../../../../chart-adapter/drawingFrameSnapshot.js";
import type { DrawingFrameSnapshot } from "../../../../chart-adapter/drawingFrameSnapshot.js";
import type { CoordinateDataPoint } from "../../../../chart-adapter/coordinateBridge.js";
import { getLocale, setLocale } from "../../../../i18n/index.js";
import { createDrawingDocument, createDrawingEntity } from "../../core/drawingDocument.js";
import type { DrawingDocument, DrawingEntity } from "../../core/drawingDocument.js";
import type { CalculatedDrawingType } from "../../drawingTypes.js";
import { hitTestDrawingScreenDisplayList } from "../../rendering/drawingDisplayList.js";
import type { CalculatedDisplayRenderSpec, DrawingScreenDisplayList } from "../../rendering/drawingDisplayList.js";
import { createDrawingSceneRegistry } from "../drawingSceneRegistry.js";
import { projectDrawingScene } from "../drawingSceneProjector.js";
import type { DrawingSceneProjectionAdapter } from "../drawingSceneProjector.js";

// The test adapter maps time → x and price → y directly.
const adapter: DrawingSceneProjectionAdapter = {
  measureText: (request) => [...request.text].length * request.fontSize * 0.5,
  projectDrawingFrameDataPoints(_frame, points: readonly CoordinateDataPoint[]) {
    const result = new Float64Array(points.length * 2).fill(Number.NaN);
    points.forEach((point, index) => {
      if (typeof point.time === "number") result[index * 2] = point.time;
      if (typeof point.price === "number" && Number.isFinite(point.price)) result[index * 2 + 1] = point.price;
    });
    return result;
  },
  projectDrawingFrameSourceLineageSpan: () => null,
};

function frameWith(seriesData: DrawingFrameSnapshot["seriesData"]): DrawingFrameSnapshot {
  return createDrawingFrameSnapshotFactory().capture({
    axisKind: "time",
    barSpacing: 10,
    coordinateKey: "test:time",
    dpr: 1,
    drawingViewport: { horizontalDomain: "time", minHorizontal: 0, maxHorizontal: 400, minPrice: 0, maxPrice: 400 },
    heightCssPx: 400,
    projectionKey: "test-projection",
    seriesData,
    surfaceToken: "surface",
    themeKey: "dark",
    viewportKey: "time:0:400",
    widthCssPx: 400,
  });
}

function calculated(
  id: string,
  calcType: CalculatedDrawingType,
  dataPoints: readonly { time: number; price: number }[],
  style: { deviation?: number; rows?: number } = {},
): DrawingEntity {
  return createDrawingEntity({
    id,
    kind: "calculated",
    geometry: { kind: "calculated", calcType, dataPoints: dataPoints.map((point) => ({ ...point })) },
    style: { kind: "calculated", color: "#3b82f6", lineWidth: 2, ...style },
  });
}

function project(entity: DrawingEntity, seriesData: DrawingFrameSnapshot["seriesData"], selectedId: string | null = null): DrawingScreenDisplayList {
  const document: DrawingDocument = createDrawingDocument({ scopeKey: "calculated", entities: [entity] });
  const registry = createDrawingSceneRegistry(document.scopeKey);
  assert.equal(registry.reconcile(document).ok, true);
  const frame = frameWith(seriesData);
  const list = projectDrawingScene({
    adapter,
    document,
    frame,
    nodes: registry.getSnapshot().nodes,
    selectedId,
    stamp: Object.freeze({
      scopeKey: document.scopeKey,
      documentRevision: document.documentRevision,
      surfaceGeneration: frame.surfaceGeneration,
      dataRevision: frame.dataRevision,
      projectionRevision: frame.projectionRevision,
      lineageIndexRevision: frame.lineageIndexRevision,
      viewportRevision: frame.viewportRevision,
      themeRevision: frame.themeRevision,
      widthCssPx: frame.widthCssPx,
      heightCssPx: frame.heightCssPx,
      dpr: frame.dpr,
    }),
    lodToleranceClass: "normalStatic",
  });
  assert.ok(list, "the scene projects");
  return list;
}

function specOf(list: DrawingScreenDisplayList): CalculatedDisplayRenderSpec {
  const spec = list.entities[0]?.renderSpec;
  assert.equal(spec?.op, "calculated");
  return spec as CalculatedDisplayRenderSpec;
}

function inEnglish<T>(run: () => T): T {
  const previous = getLocale();
  setLocale("en");
  try {
    return run();
  } finally {
    setLocale(previous);
  }
}

// Bars at x = 100…200 (step 20); a gap in x between 140 and 180 stands for a closure.
const BARS = [
  { time: 100, open: 100, high: 110, low: 90, close: 100, volume: 10 },
  { time: 120, open: 100, high: 120, low: 100, close: 110, volume: 10 },
  { time: 140, open: 110, high: 130, low: 110, close: 120, volume: 10 },
  { time: 180, open: 120, high: 140, low: 120, close: 130, volume: 10 },
  { time: 200, open: 130, high: 150, low: 130, close: 140, volume: 10 },
];

test("fib extension draws the A-B-C trend, seven labelled levels from C and three handles", () => {
  const list = inEnglish(() => project(calculated("fib", "fib-extension", [
    { time: 100, price: 100 }, { time: 150, price: 200 }, { time: 200, price: 150 },
  ]), [], "fib"));
  const spec = specOf(list);
  assert.equal(spec.calcType, "fib-extension");
  assert.equal(spec.lines.length, 8, "trend + seven levels");
  assert.equal(spec.labels.length, 7);
  assert.ok(spec.labels.some((label) => label.text.startsWith("1 (") && label.text.includes("250")));
  assert.equal(spec.handleCount, 3);
  assert.equal(spec.selected, true);
  assert.equal(hitTestDrawingScreenDisplayList(list, 150, 200)?.pointIndex, 1, "B handle");
  assert.equal(hitTestDrawingScreenDisplayList(list, 200, 150)?.pointIndex, 2, "C handle");
  assert.equal(hitTestDrawingScreenDisplayList(list, 220, 250)?.pointIndex, -1, "the 100% level is selectable");
});

test("anchored VWAP follows the bars from the anchor and labels the last value", () => {
  const list = inEnglish(() => project(calculated("vwap", "anchored-vwap", [{ time: 120, price: 0 }]), BARS));
  const spec = specOf(list);
  const vwapLine = spec.lines[0]!;
  assert.equal(vwapLine.pointCount, 4, "one point per bar from the anchor, none inside the gap");
  const base = list.entities[0]!.pointOffset + vwapLine.pointOffset;
  const xs = Array.from({ length: vwapLine.pointCount }, (_, index) => list.points[(base + index) * 2]);
  assert.deepEqual(xs, [120, 140, 180, 200]);
  assert.match(spec.labels[0]!.text, /^VWAP /);
  assert.equal(spec.handleCount, 1);
});

test("anchored VWAP on a revealed replay prefix stops at the last revealed bar", () => {
  const list = project(calculated("vwap", "anchored-vwap", [{ time: 100, price: 0 }]), BARS.slice(0, 3));
  const spec = specOf(list);
  const line = spec.lines[0]!;
  const lastIndex = list.entities[0]!.pointOffset + line.pointOffset + line.pointCount - 1;
  assert.equal(list.points[lastIndex * 2], 140);
});

test("volume profile is labelled as an estimate with its bar count and a POC line", () => {
  const list = inEnglish(() => project(calculated("profile", "volume-profile", [
    { time: 200, price: 0 }, { time: 110, price: 0 },
  ], { rows: 8 }), BARS));
  const spec = specOf(list);
  assert.ok(spec.labels.some((label) => label.text === "Estimated from 4 bars"), "bars 120…200 lie in the range");
  assert.ok(spec.labels.some((label) => label.text.startsWith("POC ")));
  assert.ok(spec.boxes.length >= 2, "range body + at least one volume row");
  assert.equal(spec.lines.some((line) => line.dashed), true, "dashed POC line");
  // Handles sit at the range's bottom corners and map back to the anchors by time.
  assert.equal(hitTestDrawingScreenDisplayList(list, 120, 150)?.pointIndex, 1, "left corner is the earlier anchor");
  assert.equal(hitTestDrawingScreenDisplayList(list, 200, 150)?.pointIndex, 0, "right corner is the later anchor");
  assert.equal(hitTestDrawingScreenDisplayList(list, 190, 105)?.zone, "body", "the range is selectable between rows");
});

test("regression channel fits across the gap and fills between its rails", () => {
  const list = project(calculated("reg", "regression-channel", [{ time: 100, price: 0 }, { time: 200, price: 0 }], { deviation: 1 }), BARS);
  const spec = specOf(list);
  assert.equal(spec.polygons.length, 1);
  assert.equal(spec.lines.length, 3);
  const middle = spec.lines.find((line) => line.dashed)!;
  const base = list.entities[0]!.pointOffset + middle.pointOffset;
  // Closes rise 10 per bar by position, so the fit runs 100 → 140 even though x jumps over the gap.
  assert.ok(Math.abs(list.points[base * 2 + 1]! - 100) < 1e-9);
  assert.ok(Math.abs(list.points[(base + 1) * 2 + 1]! - 140) < 1e-9);
  assert.equal(hitTestDrawingScreenDisplayList(list, 100, 100)?.pointIndex, 0);
  assert.equal(hitTestDrawingScreenDisplayList(list, 200, 140)?.pointIndex, 1);
});

test("range drawings with no bars in range say so instead of inventing values", () => {
  for (const calcType of ["volume-profile", "regression-channel"] as const) {
    const list = inEnglish(() => project(calculated(calcType, calcType, [{ time: 150, price: 50 }, { time: 170, price: 60 }]), BARS));
    const spec = specOf(list);
    assert.deepEqual(spec.labels.map((label) => label.text), ["No bars in this range"], calcType);
    assert.equal(spec.handleCount, 2);
  }
});
