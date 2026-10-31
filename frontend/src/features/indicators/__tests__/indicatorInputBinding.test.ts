import assert from "node:assert/strict";
import test from "node:test";
import { SharedMarketCache } from "../../market-data/manager/sharedMarketCache.js";
import type { KlineBar, MarketSeries } from "../../market-data/marketDataTypes.js";
import { epochSeconds } from "../../../test/testHelpers.js";
import { registerSharedMarketCache } from "../../cache-gc/sharedMarketCacheOwner.js";
import { dependencyAvailable, klineDependencyKey } from "../../cache-gc/cacheRegistry.js";
import { bindSharedIndicatorPrefix, createIndicatorCacheInputSource } from "../indicatorInputBinding.js";
import { buildIndicatorOhlcvSignature } from "../indicatorComputeRuntime.js";
import { normalizeIndicatorPayload } from "../indicatorPayloadRuntime.js";
import {
  buildIndicatorResultCacheKey, buildIndicatorCacheHydrationSignature, cacheIndicatorSnapshot, getCachedIndicatorResult,
  getCachedIndicatorComputedSegments, patchCachedIndicatorResult, resetIndicatorResultCache,
} from "../indicatorResultCacheStore.js";

const series: MarketSeries = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const indicator = { id: "ema", engineName: "EMA", params: { period: 20 } };
const row = (time: number, close = 10): KlineBar => ({
  time: epochSeconds(time), open: 10, high: 30, low: 0, close, volume: 2, is_closed: true,
});
const payload = (time: number) => normalizeIndicatorPayload({ lines: [{ id: "ema", data: [{ time, value: 10 }] }] }, indicator.id);
function admit(cache: SharedMarketCache, rows: KlineBar[], identity = series) {
  const token = cache.beginRead(identity);
  try { cache.admitResponse(token, { data: rows, endpoint: "history" }); } finally { token.release(); }
}

test("recursive hosted output depends on its observed prefix; unrelated appends remain reusable", t => {
  resetIndicatorResultCache();
  const cache = new SharedMarketCache();
  t.after(registerSharedMarketCache(cache));
  admit(cache, [row(60), row(120), row(180)]);
  const context = { ...series, inputSource: createIndicatorCacheInputSource(cache) };
  assert.ok(cacheIndicatorSnapshot(indicator, context, payload(180), [], { range: { start: 180, end: 180 } }));
  const result = getCachedIndicatorResult(indicator, context);
  cache.admitRealtime(series, row(240), "bar.closed");
  assert.equal(getCachedIndicatorResult(indicator, context), result);
  cache.admitRealtime(series, row(60, 20), "bar.amended");
  assert.equal(getCachedIndicatorResult(indicator, context), null, "correction before outputs invalidates recursive state");
  assert.deepEqual(getCachedIndicatorComputedSegments(indicator, context), []);
  patchCachedIndicatorResult(indicator, context, payload(240));
  assert.deepEqual(getCachedIndicatorResult(indicator, context)?.normalized.lines[0]?.data.map(point => point.time), [240],
    "a fresh suffix cannot resurrect an invalid old prefix");
});

test("a provided-input cache binds origin, values, full identity and in-flight version", t => {
  resetIndicatorResultCache();
  const cache = new SharedMarketCache();
  t.after(registerSharedMarketCache(cache));
  const rows = [row(60), row(120), row(180)];
  admit(cache, rows);
  const source = createIndicatorCacheInputSource(cache);
  const local = { ...indicator, executionTarget: "local" as const };
  const context = { ...series, inputSource: source, localInputKey: buildIndicatorOhlcvSignature(rows) };
  const shorter = { ...context, localInputKey: buildIndicatorOhlcvSignature(rows.slice(1)) };
  assert.notEqual(buildIndicatorResultCacheKey(local, context), buildIndicatorResultCacheKey(local, shorter));
  assert.equal(buildIndicatorCacheHydrationSignature([local], context), buildIndicatorCacheHydrationSignature([local], shorter),
    "sampling a new input must not reset the chart's indicator UI context");
  const inputVersion = source.captureProvided(series, rows);
  assert.ok(inputVersion);
  assert.equal(source.captureProvided(series, [row(60, 15), ...rows.slice(1)]), null);
  assert.equal(source.captureProvided({ ...series, priceAdjustment: "split" }, rows), null);
  assert.equal(cacheIndicatorSnapshot(local, context, payload(180)), null, "unspecified provided input is not certified");
  assert.ok(cacheIndicatorSnapshot(local, context, payload(180), [], { inputVersion }));
  assert.equal(getCachedIndicatorResult(local, shorter), null, "equal output timestamp does not imply equal EMA origin");
  admit(cache, [row(120, 20)]);
  assert.equal(cacheIndicatorSnapshot(local, context, payload(180), [], { inputVersion }), null,
    "late completion cannot cache against a newly captured revision");
  assert.equal(getCachedIndicatorResult(local, context), null);
});

test("input scope and dependency availability cannot cross semantic identities or workspaces", t => {
  resetIndicatorResultCache();
  const first = new SharedMarketCache(), second = new SharedMarketCache();
  t.after(registerSharedMarketCache(first)); t.after(registerSharedMarketCache(second));
  admit(first, [row(60)]); admit(second, [row(60, 20)]);
  const adjusted = { ...series, priceAdjustment: "split" };
  assert.notEqual(klineDependencyKey(series), klineDependencyKey(adjusted));
  assert.equal(dependencyAvailable(klineDependencyKey(adjusted)), false);
  const context = { ...series, inputSource: createIndicatorCacheInputSource(first) };
  const other = { ...series, inputSource: createIndicatorCacheInputSource(second) };
  assert.equal(context.inputSource, createIndicatorCacheInputSource(first));
  assert.notEqual(buildIndicatorResultCacheKey(indicator, context), buildIndicatorResultCacheKey(indicator, other));
  cacheIndicatorSnapshot(indicator, context, payload(60));
  assert.equal(getCachedIndicatorResult(indicator, other), null);
  first.markDisconnected(series);
  assert.equal(getCachedIndicatorResult(indicator, context), null);
});

test("Pine drawing-only results preserve scene ordering and revoke corrected shared inputs", t => {
  resetIndicatorResultCache();
  const cache = new SharedMarketCache();
  t.after(registerSharedMarketCache(cache));
  admit(cache, [row(60), row(120), row(180)]);
  const pine = { id: "pine-scene", language: "pine", script: "line.new(0,1,2,3)" };
  const context = { ...series, inputSource: createIndicatorCacheInputSource(cache) };
  const scene = (asOf: number, value: number) => normalizeIndicatorPayload({ drawings: [{
    id: "scene", pane: "main", asOf, times: [60, 120, 180],
    objects: [{ kind: "lines", row: { x1: 0, x2: 2, y1: 10, y2: value } }],
  }] }, pine.id);
  const inputVersion = cache.captureVersion(series, { to: 180 });
  assert.ok(cacheIndicatorSnapshot(pine, context, scene(180, 20), [], { inputVersion }));
  patchCachedIndicatorResult(pine, context, scene(120, 15));
  assert.equal(getCachedIndicatorResult(pine, context)?.normalized.drawings?.[0]?.asOf, 180);
  cache.admitRealtime(series, row(240), "bar.closed");
  assert.equal(getCachedIndicatorResult(pine, context)?.normalized.drawings?.[0]?.objects[0]?.row.y2, 20);
  cache.admitRealtime(series, row(60, 15), "bar.amended");
  assert.equal(getCachedIndicatorResult(pine, context), null);
  assert.equal(cacheIndicatorSnapshot(pine, context, scene(180, 20), [], { inputVersion }), null,
    "an in-flight drawing completion cannot bind itself to the corrected revision");
});

test("dependency stamps do not retain rows; prefix insertions, eviction and recreation invalidate", () => {
  const cache = new SharedMarketCache({ maxBarsPerSeries: 3 });
  admit(cache, [row(120), row(180)]);
  const range = { to: 180 };
  const stamp = cache.captureVersion(series, range);
  range.to = 0;
  admit(cache, [row(60)]);
  assert.equal(stamp.isCurrent(), false, "an earlier observation enters the captured recursive prefix");
  const fresh = cache.captureVersion(series, { from: 120, to: 180 });
  cache.admitRealtime(series, row(240), "bar.closed");
  assert.equal(fresh.isCurrent(), false, "retention changes conservatively invalidate dependencies");
  const recreated = cache.captureVersion(series);
  cache.invalidate(series); admit(cache, [row(120), row(180)]);
  assert.equal(recreated.isCurrent(), false);
  assert.equal(Object.hasOwn(stamp, "rows"), false);
});

test("another chart's earlier correction enters the existing indicator recovery lane without moving this window", () => {
  const cache = new SharedMarketCache();
  const dirty: Array<{ start: number; end: number }> = [];
  const window = [row(180), row(240)];
  const release = bindSharedIndicatorPrefix(cache, series, () => Number(window[0]!.time), range => dirty.push(range));
  admit(cache, [row(180), row(240)]);
  cache.admitRealtime(series, row(300), "bar.closed");
  cache.admitRealtime(series, row(240, 15), "bar.amended");
  assert.equal(dirty.length, 0, "retained rows stay owned by existing window delta handling");
  admit(cache, [row(60), row(120)]);
  cache.admitRealtime(series, row(60, 15), "bar.amended");
  assert.deepEqual(dirty, [{ start: 60, end: 120 }, { start: 60, end: 60 }]);
  assert.deepEqual(window.map(item => item.time), [180, 240]);
  release();
  admit(cache, [row(120, 20)]);
  assert.equal(dirty.length, 2);
});
