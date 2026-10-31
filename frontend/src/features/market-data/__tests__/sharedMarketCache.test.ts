import assert from "node:assert/strict";
import test from "node:test";
import { SharedMarketCache } from "../manager/sharedMarketCache.js";
import type { KlineFetchResult } from "../klineContracts.js";
import type { EpochSeconds, KlineBar, MarketSeries } from "../marketDataTypes.js";

const series: MarketSeries = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const row = (time: number, close = 10, final = true): KlineBar => ({
  time: time as EpochSeconds, open: 10, high: 30, low: 0, close, volume: 2, is_closed: final,
});
const history = (rows: KlineBar[]): KlineFetchResult => ({
  endpoint: "range", data: rows, all_rows_final: rows.every(item => item.is_closed), complete: true,
  retryable: false, history_state: "ready", verified_contiguous: true, missing_ranges: [],
  has_tail_gap: false, truncated: false,
});
function admit(cache: SharedMarketCache, rows: KlineBar[], target = series, extra: Partial<KlineFetchResult> = {}) {
  const request = cache.beginRead(target);
  try { return cache.admitResponse(request, { ...history(rows), ...extra }); }
  finally { request.release(); }
}

test("shared immutable facts support distinct reads and cannot be mutated by input or consumers", () => {
  const cache = new SharedMarketCache();
  const input = [row(60), row(120), row(180)];
  input[0]!.order_flow = { taker_sell_base: 1, volume_delta_base: -1, taker_buy_ratio_base: 0.3, cvd_contribution_base: -1 };
  admit(cache, input);
  const old = cache.read(series, { from: 60, to: 120 });
  const live = cache.read(series, { from: 120, to: 180 });
  assert.deepEqual(old.rows.map(item => item.time), [60, 120]);
  assert.deepEqual(live.rows.map(item => item.time), [120, 180]);
  assert.equal(old.rows[1], live.rows[0]);
  input[0]!.close = 29;
  assert.equal(old.rows[0]!.close, 10);
  assert.throws(() => { old.rows[0]!.close = 28; }, TypeError);
  assert.throws(() => { old.rows[0]!.order_flow!.volume_delta_base = 5; }, TypeError);
  cache.admitRealtime(series, row(240), "bar.closed");
  assert.deepEqual(old.rows.map(item => item.time), [60, 120]);
  assert.equal(old.isCurrent(), true, "unrelated append must not invalidate an exact bounded input range");
  cache.admitRealtime(series, row(120, 20), "bar.amended");
  assert.equal(old.rows[1]!.close, 10, "captured input stays stable");
  assert.equal(old.isCurrent(), false);
});

test("invalid HTTP batch is atomic and cannot certify a range", () => {
  const cache = new SharedMarketCache();
  admit(cache, [row(60)]);
  const before = cache.read(series);
  assert.throws(() => admit(cache, [row(60, 11), { ...row(120), volume: -1 }]), /volume/);
  assert.equal(cache.read(series).version, before.version);
  assert.equal(cache.read(series).rows[0]!.close, 10);
  assert.equal(cache.read(series, { from: 60, to: 120 }).complete, false);
});

test("a before-page proof covers the requested boundary, not only the last retained row", () => {
  const cache = new SharedMarketCache();
  admit(cache, [row(60), row(120)]);
  assert.equal(cache.read(series, { before: 180, limit: 2 }).complete, false);
  admit(cache, [row(60), row(120), row(180)]);
  assert.equal(cache.read(series, { before: 180, limit: 2 }).complete, true);
  assert.equal(cache.read(series, { before: 240, limit: 2 }).complete, false);
});

test("cache capacity preserves active consumers and rejects surplus realtime without throwing", () => {
  const cache = new SharedMarketCache({ maxSeries: 1 });
  admit(cache, [row(60)]);
  const release = cache.subscribe(series, () => {});
  const other = { ...series, symbol: "ETHUSDT" };
  assert.equal(cache.admitRealtime(other, row(60)).accepted, false);
  assert.equal(cache.diagnostics().capacityRejects, 1);
  assert.equal(cache.read(series).rows.length, 1);
  release();
  assert.equal(cache.admitRealtime(other, row(60)).accepted, true);
  assert.equal(cache.diagnostics().series, 1);
});

test("shared request fence protects concurrent close and amendment, then permits a later repair", () => {
  const cache = new SharedMarketCache();
  admit(cache, [row(60)]);
  const slow = cache.beginRead(series);
  cache.admitRealtime(series, row(60, 20), "bar.amended");
  cache.admitRealtime(series, row(120, 21), "bar.closed");
  const result = cache.admitResponse(slow, history([row(60, 12), row(120, 13)]));
  assert.deepEqual(result.data!.map(item => item.close), [20, 21]);
  slow.release();
  admit(cache, [row(60, 22), row(120, 23)]);
  assert.deepEqual(cache.read(series).rows.map(item => item.close), [22, 23]);
  assert.equal(cache.admitRealtime(series, row(120, 11, false), "bar.updated").accepted, false);
});

test("verified final HTTP can finish a forming tail and fences another earlier response", () => {
  const cache = new SharedMarketCache();
  const first = cache.beginRead(series), second = cache.beginRead(series);
  cache.admitRealtime(series, row(60, 11, false), "bar.updated");
  cache.admitResponse(first, history([row(60, 20)]));
  const old = cache.admitResponse(second, { data: [row(60, 12, false)], endpoint: "latest" });
  assert.equal(old.data![0]!.close, 20);
  first.release(); second.release();
});

test("proof belongs to retained ranges; disjoint, partial and latest-only data never prove the gap", () => {
  const cache = new SharedMarketCache();
  admit(cache, [row(60), row(120)]);
  admit(cache, [row(240), row(300)]);
  assert.equal(cache.read(series, { from: 60, to: 120 }).complete, true);
  assert.equal(cache.read(series, { from: 60, to: 300 }).complete, false);
  admit(cache, [row(180)], series, { complete: false, verified_contiguous: false });
  assert.equal(cache.read(series, { from: 60, to: 300 }).complete, false);
  admit(cache, [row(60), row(120), row(180), row(240), row(300)]);
  assert.equal(cache.read(series, { from: 60, to: 300 }).complete, true);
  const other = { ...series, symbol: "ETHUSDT" };
  admit(cache, [row(60), row(120)], other, { endpoint: "latest" });
  assert.equal(cache.read(other, { from: 60, to: 120 }).complete, false);
});

test("contradictory response downgrades affected evidence even when values do not change", () => {
  const cache = new SharedMarketCache();
  admit(cache, [row(60), row(120)]);
  const first = cache.read(series);
  admit(cache, [row(60), row(120)], series, { missing_ranges: [{ start_ms: 60_000, end_ms: 120_000 }] });
  const next = cache.read(series);
  assert.equal(next.complete, false);
  assert.equal(next.version, first.version, "quality-only invalidation must not manufacture a data change");
  assert.ok(next.commitRevision > first.commitRevision);
});

test("retention is bounded and never shares a chart navigation boundary", () => {
  const cache = new SharedMarketCache({ maxBarsPerSeries: 4, maxBars: 6, maxSeries: 2 });
  admit(cache, [row(60), row(120), row(180), row(240)]);
  const snapshot = cache.read(series, { from: 60, to: 120 });
  const lease = cache.retain(series, { from: 60, to: 120 });
  admit(cache, [row(300), row(360)]);
  assert.deepEqual(cache.read(series).rows.map(item => item.time), [60, 120, 300, 360]);
  assert.equal(snapshot.isCurrent(), true);
  assert.equal(cache.read(series, { from: 60, to: 360 }).complete, false);
  lease.release(); lease.release();
  for (const symbol of ["ETHUSDT", "SOLUSDT", "XRPUSDT"]) admit(cache, [row(60), row(120)], { ...series, symbol });
  assert.ok(cache.diagnostics().bars <= 6);
  assert.ok(cache.diagnostics().series <= 2);
  assert.equal(snapshot.isCurrent(), false);
});

test("full semantic identity and released/invalidated requests cannot contaminate a series", () => {
  const cache = new SharedMarketCache();
  const adjusted = { ...series, priceAdjustment: "adjusted" };
  admit(cache, [row(60)], series);
  admit(cache, [row(60, 20)], adjusted);
  assert.equal(cache.read(series).rows[0]!.close, 10);
  assert.equal(cache.read(adjusted).rows[0]!.close, 20);
  const pending = cache.beginRead(series);
  cache.invalidate(series);
  assert.throws(() => cache.admitResponse(pending, history([row(60, 30)])), /expired/);
  pending.release();
  const released = cache.beginRead(series);
  released.release();
  assert.throws(() => cache.admitResponse(released, history([row(60, 30)])), /expired/);
});

test("subscribers see committed immutable data; duplicate live data does not publish a second change", () => {
  const cache = new SharedMarketCache();
  const events: number[] = [];
  const unsubscribe = cache.subscribe(series, event => {
    events.push(event.version);
    assert.equal(cache.read(series).version, event.version);
    assert.equal(cache.read(series).rows.at(-1)!.close, event.rows.at(-1)!.close);
  });
  cache.admitRealtime(series, row(60, 10, false), "bar.updated");
  cache.admitRealtime(series, row(60, 10, false), "bar.updated");
  cache.admitRealtime(series, row(60, 11, false), "bar.updated");
  assert.equal(events.length, 2);
  unsubscribe();
  cache.admitRealtime(series, row(60, 12, false), "bar.updated");
  assert.equal(events.length, 2);
});

test("disconnect and amendment preserve renderable rows but revoke old completeness", () => {
  const cache = new SharedMarketCache();
  admit(cache, [row(60), row(120)]);
  const snapshot = cache.read(series, { from: 60, to: 120 });
  cache.markDisconnected(series);
  assert.equal(snapshot.isCurrent(), false);
  assert.equal(cache.read(series).rows.length, 2);
  assert.equal(cache.read(series).complete, false);
  admit(cache, [row(60), row(120)]);
  cache.admitRealtime(series, row(60, 25), "bar.amended");
  assert.equal(cache.read(series).complete, false);
});

test("a stalled read cannot retain unbounded real-time fencing history", () => {
  const cache = new SharedMarketCache({ maxBarsPerSeries: 3 });
  const pending = cache.beginRead(series);
  for (const time of [60, 120, 180, 240]) cache.admitRealtime(series, row(time), "bar.closed");
  assert.equal(cache.diagnostics().bars, 3);
  assert.equal(cache.diagnostics().requests, 0);
  assert.throws(() => cache.admitResponse(pending, history([row(60)])), /expired/);
  pending.release();
});

test("one failing subscriber cannot prevent another subscriber observing the commit", () => {
  const cache = new SharedMarketCache();
  cache.subscribe(series, () => { throw new Error("broken consumer"); });
  let delivered = 0;
  cache.subscribe(series, () => { delivered += 1; });
  cache.admitRealtime(series, row(60));
  assert.equal(delivered, 1);
  assert.equal(cache.diagnostics().listenerErrors, 1);
});
