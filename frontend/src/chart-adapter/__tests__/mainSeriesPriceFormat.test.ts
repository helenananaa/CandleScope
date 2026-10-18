import assert from "node:assert/strict";
import test from "node:test";
import { MainSeriesPriceFormatTracker } from "../mainSeriesPriceFormat.js";
import { createMainSeries, replaceMainSeries } from "../seriesLifecycle.js";
import { structuralMock } from "../../test/testHelpers.js";

type AdapterChart = Parameters<typeof createMainSeries>[0];
type AdapterSeries = NonNullable<Parameters<typeof replaceMainSeries>[1]>;

test("all price series start with enough precision for sub-cent markets", () => {
  for (const chartType of ["candlestick", "point-and-figure", "renko", "kagi", "line"] as const) {
    const options: unknown[] = [];
    const add = (_series: unknown, config: unknown) => {
      options.push(config); return structuralMock<AdapterSeries>({});
    };
    createMainSeries(structuralMock<AdapterChart>({ addSeries: add, addCustomSeries: add }), {
      chartType, data: [{ time: 1, open: 0.08532, high: 0.08534, low: 0.08531, close: 0.08533 }],
    });
    assert.deepEqual((options[0] as { priceFormat: unknown }).priceFormat,
      { type: "price", precision: 5, minMove: 0.00001 });
  }
});

test("cold price precision updates on history arrival and tick work stays bounded", () => {
  let reads = 0;
  const rows = Array.from({ length: 100_000 }, (_, index) => ({ time: index + 1,
    get close() { reads += 1; return 0.08532; } }));
  const tracker = new MainSeriesPriceFormatTracker();
  assert.equal(tracker.resolve([]).precision, 2);
  assert.equal(tracker.resolve(rows, { type: "replace" }).precision, 5);
  reads = 0;
  assert.equal(tracker.resolve(rows, { type: "tick" }).precision, 5);
  assert.ok(reads <= 1, `tick re-read ${reads} historical prices`);
  const appended = [...rows, { time: rows.length + 1, close: 1e-8 }];
  assert.equal(tracker.resolve(appended, { type: "append", addedRight: 1 }).precision, 8);
  assert.equal(tracker.resolve([{ time: 1, close: 63.43 }], { type: "replace" }).precision, 2);
});
