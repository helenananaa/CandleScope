import assert from "node:assert/strict";
import test from "node:test";
import { IndicatorInputRanges } from "../indicatorInputRanges.js";
import { SharedMarketCache } from "../../market-data/manager/sharedMarketCache.js";
import { epochSeconds } from "../../../test/testHelpers.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const row = (time: number, close = 10, is_closed = true) => ({ time: epochSeconds(time), open: 10, high: 30, low: 0, close, volume: 2, is_closed });
function fixture() {
  const cache = new SharedMarketCache();
  const token = cache.beginRead(series);
  cache.admitResponse(token, { data: [row(60), row(120), row(180, 10, false)], endpoint: "history" }); token.release();
  return { cache, inputs: new IndicatorInputRanges(cache) };
}

test("bounded inputs read shared immutable facts and keep calculation origins distinct", () => {
  const { cache, inputs } = fixture();
  const a = inputs.read(series, { from: 60, to: 180 }), b = inputs.read(series, { from: 120, to: 180 });
  assert.deepEqual(a.rows.map(r => r.time), [60, 120, 180]);
  assert.deepEqual(b.rows.map(r => r.time), [120, 180]);
  assert.equal(a.rows[1], b.rows[0]);
  assert.equal(a.rows[1], cache.read(series, { from: 120, to: 120 }).rows[0]);
  assert.throws(() => Object.defineProperty(a.rows[0]!, "close", { value: 999 }), TypeError);
  assert.equal(inputs.read({ ...series, priceAdjustment: "split" }, { from: 60, to: 180 }).rows.length, 0);
  assert.throws(() => inputs.read(series, { from: 180, to: 60 }), /range/);
});

test("two consumers retain and release independent ranges; outside edits do not wake them", () => {
  const { cache, inputs } = fixture(); let a = 0, b = 0;
  const range = { from: 60, to: 120 };
  const releaseA = inputs.subscribe(series, range, () => a++);
  const releaseB = inputs.subscribe(series, { from: 120, to: 180 }, () => b++);
  range.to = 999;
  cache.admitRealtime(series, row(240), "bar.closed");
  assert.deepEqual([a, b], [0, 0]);
  cache.admitRealtime(series, row(120, 20), "bar.amended");
  assert.deepEqual([a, b], [1, 1]);
  releaseA(); releaseA();
  cache.admitRealtime(series, row(120, 25), "bar.amended");
  assert.deepEqual([a, b], [1, 2]);
  assert.equal(cache.diagnostics().retainedRanges, 1);
  releaseB(); assert.equal(cache.diagnostics().retainedRanges, 0);
  assert.equal(inputs.diagnostics().subscriptions, 0);
});

test("held forming samples progress through ticks but corrections, finality and disconnect revoke them", () => {
  for (const cause of ["correction", "close", "disconnect"] as const) {
    const { cache, inputs } = fixture();
    const mutableRange = { from: 60, to: 180 }, mutableSeries = { ...series };
    const held = inputs.read(mutableSeries, mutableRange);
    mutableRange.from = 180; mutableSeries.symbol = "ETHUSDT";
    cache.admitRealtime(series, row(180, 11, false), "bar.updated");
    assert.equal(held.isCurrent(), false);
    assert.equal(held.isCurrent("forming-preview"), true);
    assert.equal(held.rows.at(-1)!.close, 10);
    if (cause === "correction") cache.admitRealtime(series, row(60, 20), "bar.amended");
    if (cause === "close") cache.admitRealtime(series, row(180, 12), "bar.closed");
    if (cause === "disconnect") cache.markDisconnected(series);
    assert.equal(held.isCurrent("forming-preview"), false, cause);
  }
});

test("invalidation wakes bounded consumers and disposal revokes captures and all retained resources", () => {
  const { cache, inputs } = fixture(); let changes = 0;
  inputs.subscribe(series, { from: 60, to: 180 }, () => changes++);
  const captured = inputs.read(series, { from: 60, to: 120 });
  cache.invalidateRange(series, { from: 60, to: 60 });
  assert.equal(changes, 1); assert.equal(captured.isCurrent(), false);
  const next = inputs.read(series, { from: 120, to: 180 });
  inputs.dispose(); inputs.dispose();
  assert.equal(next.isCurrent("forming-preview"), false);
  assert.equal(cache.diagnostics().retainedRanges, 0);
  cache.admitRealtime(series, row(120, 20), "bar.amended");
  assert.equal(changes, 1);
  assert.throws(() => inputs.subscribe(series, { from: 60, to: 120 }, () => {}), /disposed/);
});
