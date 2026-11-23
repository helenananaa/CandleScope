import type { ChartSignalDefinition } from "../../../../shared/strategyRunSettings.js";
import assert from "node:assert/strict";
import test from "node:test";
import { chartStrategySignalInput, sameChartSignalInput, withChartSignalInput } from "../chartStrategySignalInput.js";
import { chartStrategyTesterStaleReasons } from "../chartStrategyTesterState.js";
import type { ChartStrategyTesterInputs } from "../chartStrategyTesterState.js";

test("current appearance defaults to chart signals for every transformed type and raw for ordinary styles", () => {
  for (const chartType of ["heikin-ashi", "renko", "point-and-figure", "kagi", "line-break"] as const) {
    const config = chartStrategySignalInput({ chartType });
    assert.equal(config?.transform, chartType);
    assert.equal(config?.contract, "candlescope.chart-signal-input/1");
  }
  for (const chartType of ["candlestick", "line", "bar", "area"] as const) assert.equal(chartStrategySignalInput({ chartType }), undefined);
  assert.deepEqual(chartStrategySignalInput({ chartType: "renko", renkoBoxSizeMode: "traditional", renkoBoxSize: 8 }), {
    contract: "candlescope.chart-signal-input/1", algorithm: "causal-close-source/1", transform: "renko",
    mode: "traditional", box_size: 8, min_tick: null, atr_length: 14, reversal_amount: 3, number_of_lines: 3,
  });
  assert.equal(chartStrategySignalInput({ chartType: "kagi", kagiReversalAmount: 9 })?.reversal_amount, 9);
  assert.equal(chartStrategySignalInput({ chartType: "line-break", lineBreakNumberOfLines: 6 })?.number_of_lines, 6);
});

test("changing chart type or transform parameters invalidates the strategy result", () => {
  const initial = { session: { exchange: "local", marketType: "spot", symbol: "X", interval: "1m" },
    attachment: { parameters: {}, signalChart: chartStrategySignalInput({ chartType: "renko" }) }, draftContentRevision: 1 } as ChartStrategyTesterInputs;
  const changed = { ...initial, attachment: { ...initial.attachment, signalChart: chartStrategySignalInput({ chartType: "renko", renkoAtrLength: 30 }) } };
  assert.deepEqual(chartStrategyTesterStaleReasons(initial, changed), ["CHART_INPUT_CHANGED"]);
  assert.deepEqual(chartStrategyTesterStaleReasons(initial, { ...initial, attachment: { ...initial.attachment, signalChart: undefined } }), ["CHART_INPUT_CHANGED"]);
  assert.equal(sameChartSignalInput(initial.attachment.signalChart, JSON.parse(JSON.stringify(initial.attachment.signalChart)) as ChartSignalDefinition), true);
  assert.equal(sameChartSignalInput(initial.attachment.signalChart, changed.attachment.signalChart), false);
});

test("ordinary charts omit the optional contract from frozen identity rather than storing undefined", () => {
  const previous = { signalChart: chartStrategySignalInput({ chartType: "renko" }), parameters: {} };
  const next = withChartSignalInput(previous, { chartType: "candlestick" });
  assert.equal(Object.hasOwn(next, "signalChart"), false);
  assert.equal(Object.hasOwn(previous, "signalChart"), true);
});
