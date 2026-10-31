import test from "node:test";
import assert from "node:assert/strict";
import { PineScenePrimitive, pineSceneRange } from "../pineScenePrimitive.js";
import { structuralMock, mustBeDefined } from "../../test/testHelpers.js";
import { normalizeIndicatorPayload, clearIndicatorLineData, pineRuntimeNotice } from "../../features/indicators/indicatorPayloadRuntime.js";

const scene = { schemaVersion: 1, times: [100, 160, 220], objects: [
  { kind: "lines", row: { id: 1, x1: 0, y1: 10, x2: 2, y2: 20, xloc: "xloc.bar_index", color: 0xff0000 } },
  { kind: "tables", row: { id: 2, columns: 1, rows: 1, position: "position.top_right", cells: [{ column: 0, row: 0, text: "OK" }] } },
], plots: {} };

test("native scene survives unified parsing and state clearing removes drawable history", () => {
  const parsed = normalizeIndicatorPayload({ ok: true, series: [{ id: "scene", localId: "scene", type: "line", pane: "main",
    style: { nativeScene: scene }, data: [{ time: 100, value: 15 }] }] }, "pine");
  assert.deepEqual(parsed.lines[0]?.nativeScene, scene);
  assert.deepEqual(clearIndicatorLineData(parsed.lines)[0]?.nativeScene?.times, []);
  assert.equal(pineRuntimeNotice({ sessionRecovered: true }), "pine.host.recovered");
  assert.equal(pineRuntimeNotice({ sessionReset: true, sessionResetReason: "historyChanged" }), "pine.host.resetNotice");
});

test("native scene projects actual time/price coordinates, repaints tables and detaches", () => {
  const primitive = new PineScenePrimitive(scene);
  const calls: Array<[string, ...unknown[]]> = [];
  let updates = 0;
  const context = new Proxy({}, { get: (_target, name) => name === "measureText" ? () => ({ width: 20 }) : (...args: unknown[]) => calls.push([String(name), ...args]), set: () => true });
  primitive.attached(structuralMock({ requestUpdate: () => updates++, chart: { timeScale: () => ({ timeToCoordinate: (time: number) => time / 2, logicalToCoordinate: (index: number) => 50 + index * 30 }) },
    series: { data: () => [{ time: 100, value: 15 }, { time: 160, value: 15 }, { time: 220, value: 15 }], priceToCoordinate: (price: number) => 100 - price } }));
  const paint = () => mustBeDefined(primitive.paneViews()[0]?.renderer()).draw(structuralMock({ useBitmapCoordinateSpace: (draw: (scope: object) => void) => draw({ context,
    bitmapSize: { width: 400, height: 200 }, horizontalPixelRatio: 1, verticalPixelRatio: 1 }) }));
  paint();
  assert(calls.some(([name, x, y]) => name === "moveTo" && x === 50 && y === 90));
  assert(calls.some(([name, x, y]) => name === "lineTo" && x === 110 && y === 80));
  assert(calls.some(([name, text]) => name === "fillText" && text === "OK"));
  assert.deepEqual(pineSceneRange(scene), { priceRange: { minValue: 10, maxValue: 20 } });
  primitive.setScene({ schemaVersion: 1, times: [], objects: [], plots: {} });
  assert.equal(updates, 2);
  const count = calls.length;
  paint();
  assert.equal(calls.length, count);
  primitive.detached();
  paint();
  assert.equal(calls.length, count);
});
