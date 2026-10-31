import assert from "node:assert/strict";
import test from "node:test";
import { SharedMarketCache } from "../manager/sharedMarketCache.js";
import { resolveSharedInitialRows } from "../manager/initialMarketRows.js";
import type { EpochSeconds } from "../marketDataTypes.js";
const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const row = (time: number) => ({ time: time as EpochSeconds, open: 1, high: 2, low: 0, close: 1, volume: 1, is_closed: true });

test("a private history window keeps its boundary when shared cache has a newer tail", () => {
  const cache = new SharedMarketCache();
  cache.admitRealtime(series, row(180)); cache.admitRealtime(series, row(240));
  const window = [row(60), row(120)];
  const resolved = resolveSharedInitialRows(series, window, cache, 1);
  assert.equal(resolved!.rows, window);
  assert.equal(resolved!.tier, "market-data-memory");
});

test("a missing window gets a bounded provisional preview with full series isolation", () => {
  const cache = new SharedMarketCache();
  for (const time of [60, 120, 180, 240]) cache.admitRealtime(series, row(time));
  const preview = resolveSharedInitialRows(series, [], cache, 2)!;
  assert.deepEqual(preview.rows.map(item => item.time), [180, 240]);
  assert.equal(preview.needsRepair, true);
  preview.rows.pop();
  assert.equal(cache.read(series).rows.length, 4);
  assert.equal(resolveSharedInitialRows({ ...series, priceAdjustment: "adjusted" }, [], cache, 2), null);
  assert.equal(resolveSharedInitialRows({ ...series, exchange: "okx" }, [], cache, 2), null);
});
