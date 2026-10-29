import assert from "node:assert/strict";
import test from "node:test";
import { SharedMarketCache } from "../manager/sharedMarketCache.js";
import { bindSharedWindow } from "../manager/sharedWindowBinding.js";
import { MarketWindowRegistry } from "../window/marketWindowSession.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";
import type { EpochSeconds, KlineBar, MarketSeries } from "../marketDataTypes.js";

const series: MarketSeries = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const row = (time: number, close = 10): KlineBar => ({ time: time as EpochSeconds, open: 10, high: 30, low: 0, close, volume: 1, is_closed: true });

test("shared HTTP corrections reach both private windows without sharing their navigation boundaries", () => {
  const cache = new SharedMarketCache();
  const registry = new MarketWindowRegistry({ maxBars: 3 });
  const key = buildSeriesWindowKey(series);
  const a = registry.createWindow("history"), b = registry.createWindow("live");
  const sa = a.prepareSelection(key), sb = b.prepareSelection(key);
  for (const [owner, selection, times] of [[a, sa, [60, 120, 180]], [b, sb, [180, 240, 300]]] as const) {
    owner.activate(selection);
    owner.transact(selection, () => {
      owner.getOrCreate(key);
      owner.apply(key, { type: "replace", rows: times.map(time => row(time)) });
    });
  }
  const releaseA = bindSharedWindow(cache, series, { read: () => a.get(key)!.snapshot(),
    commit: (rows, quality) => a.transact(sa, () => a.apply(key, { type: "range", rows, quality })) });
  const releaseB = bindSharedWindow(cache, series, { read: () => b.get(key)!.snapshot(),
    commit: (rows, quality) => b.transact(sb, () => b.apply(key, { type: "range", rows, quality })) });
  const request = cache.beginRead(series);
  cache.admitResponse(request, { data: [row(0), row(60), row(120), row(180, 25), row(240), row(300), row(360)],
    endpoint: "range", all_rows_final: true, complete: true, retryable: false, history_state: "ready",
    verified_contiguous: true, missing_ranges: [], has_tail_gap: false, truncated: false });
  request.release();
  assert.deepEqual(a.get(key)!.snapshot().map(item => item.time), [60, 120, 180]);
  assert.deepEqual(b.get(key)!.snapshot().map(item => item.time), [180, 240, 300]);
  assert.equal(a.get(key)!.last()!.close, 25);
  assert.equal(b.get(key)!.first()!.close, 25);
  const versionB = b.get(key)!.version;
  a.transact(sa, () => a.apply(key, { type: "replace", rows: [row(420), row(480), row(540)] }));
  assert.equal(b.get(key)!.version, versionB);
  releaseA(); releaseB();
});

test("old window selection cannot adopt a shared correction after switching", () => {
  const cache = new SharedMarketCache();
  const session = new MarketWindowRegistry().createWindow();
  const key = buildSeriesWindowKey(series), old = session.prepareSelection(key);
  session.activate(old);
  session.transact(old, () => { session.getOrCreate(key); session.apply(key, { type: "replace", rows: [row(60)] }); });
  const release = bindSharedWindow(cache, series, { read: () => session.get(key)!.snapshot(),
    commit: (rows, quality) => session.transact(old, () => session.apply(key, { type: "range", rows, quality })) });
  session.activate(session.prepareSelection("other"));
  const token = cache.beginRead(series);
  cache.admitResponse(token, { data: [row(60, 20)] }); token.release();
  assert.equal(session.get(key)!.first()!.close, 10);
  release();
});

test("shared WS admission leaves per-consumer amendment recovery its pre-update row", () => {
  const cache = new SharedMarketCache();
  const current = [row(60)];
  let commits = 0;
  const release = bindSharedWindow(cache, series, { read: () => current, commit: () => { commits += 1; } });
  cache.admitRealtime(series, row(60, 20), "bar.amended");
  assert.equal(commits, 0);
  assert.equal(current[0]!.close, 10);
  assert.equal(cache.read(series).rows[0]!.close, 20);
  release();
});
