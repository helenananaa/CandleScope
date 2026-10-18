import assert from "node:assert/strict";
import test from "node:test";
import { clampProvidedBarsIndicatorOutput } from "../providedBarsIndicatorOutput.js";
import type { IndicatorDefinition, IndicatorOutputState } from "../indicatorTypes.js";

const times = [1, 10, 20, 30, 40, 50, 60];
const indicators: IndicatorDefinition[] = [{ id: "recursive", lines: [{
  name: "EMA", data: times.map(time => ({ time, value: time })),
  colorData: times.map(time => ({ time, color: "#00ff00" })),
}] }];
const output: IndicatorOutputState = {
  markers: [{ id: "m", data: times.map(time => ({ time, value: 1 })) }],
  fills: [{ id: "f", data: [{ time: 1, endTime: 60 }, { time: 1, endTime: 10 }, { time: 21, endTime: 39 }] }],
  hlines: [{ id: "constant", price: 10 }, { id: "h", data: [{ time: 1, endTime: 60, value: 10 }] }],
  bgcolors: [{ id: "bg", regions: [{ time: 1, endTime: 60 }], data: [{ time: 30, value: 10 }] }],
  barcolors: [{ id: "bc", data: times.map(time => ({ time, color: "#00ff00" })) }],
  signals: [{ id: "s", data: [{ time: 50 }, { time: 1, endTime: 60 }] }],
  paramSchemas: { recursive: [{ key: "period", type: "int" }] },
};

test("canonical calculation prefix never creates chart times outside the cell's own source window", () => {
  const original = structuredClone({ indicators, output });
  const clipped = clampProvidedBarsIndicatorOutput({ activeIndicators: indicators, outputState: output,
    visibleThroughSeconds: 55, outputBarTimes: [20, 40, 60] });
  assert.deepEqual(clipped.activeIndicators[0]?.lines?.[0]?.data.map(p => p.time), [20, 40]);
  assert.deepEqual(clipped.activeIndicators[0]?.lines?.[0]?.colorData?.map(p => p.time), [20, 40]);
  assert.deepEqual(clipped.outputState.markers[0]?.data.map(p => p.time), [20, 40]);
  assert.deepEqual(clipped.outputState.fills[0]?.data, [{ time: 20, endTime: 40 }]);
  assert.deepEqual(clipped.outputState.hlines[0], output.hlines[0]);
  assert.deepEqual(clipped.outputState.hlines[1]?.data, [{ time: 20, endTime: 40, value: 10 }]);
  assert.deepEqual(clipped.outputState.bgcolors[0]?.regions, [{ time: 20, endTime: 40 }]);
  assert.deepEqual(clipped.outputState.bgcolors[0]?.data, []);
  assert.deepEqual(clipped.outputState.barcolors[0]?.data.map(p => p.time), [20, 40]);
  assert.deepEqual(clipped.outputState.signals[0]?.data, [{ time: 20, endTime: 40 }]);
  assert.deepEqual({ indicators, output }, original, "render cropping must preserve calculation checkpoints");
});

test("prepend, left trim and seek only change the projection, never a shared recursive result", () => {
  const project = (outputBarTimes: number[], boundary = 60) => clampProvidedBarsIndicatorOutput({
    activeIndicators: indicators, outputState: output, visibleThroughSeconds: boundary, outputBarTimes,
  });
  const a = project([40, 50, 60]);
  const b = project([10, 20, 40, 50, 60]);
  assert.deepEqual(a.activeIndicators[0]?.lines?.[0]?.data, b.activeIndicators[0]?.lines?.[0]?.data.slice(-3));
  assert.deepEqual(project([50, 60]).activeIndicators[0]?.lines?.[0]?.data.map(p => p.time), [50, 60]);
  assert.deepEqual(project([10, 20, 40], 20).activeIndicators[0]?.lines?.[0]?.data.map(p => p.time), [10, 20]);
  assert.deepEqual(project([60, 50, 50, Number.NaN, Infinity]).activeIndicators[0]?.lines?.[0]?.data.map(p => p.time), [50, 60]);
});

test("an empty or unrevealed chart clears all outputs but retains parameter schemas", () => {
  for (const outputBarTimes of [[], [60]]) {
    const clipped = clampProvidedBarsIndicatorOutput({ activeIndicators: indicators, outputState: output,
      visibleThroughSeconds: 50, outputBarTimes });
    assert.deepEqual(clipped.activeIndicators[0]?.lines, []);
    for (const [key, value] of Object.entries(clipped.outputState)) {
      assert.deepEqual(value, key === "paramSchemas" ? output.paramSchemas : []);
    }
  }
});
