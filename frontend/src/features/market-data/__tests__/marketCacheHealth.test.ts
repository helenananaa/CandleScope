import assert from "node:assert/strict";
import test from "node:test";
import { SharedMarketCache } from "../manager/sharedMarketCache.js";
import { parseMarketVersion } from "../manager/marketHealth.js";
import { MarketDataManager } from "../manager/marketDataManager.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import { ForegroundPreloadGate } from "../foregroundPreloadGate.js";
import type { KlineApi, KlineFetchResult, KlineStreamController, KlineStreamOptions } from "../klineContracts.js";
import type { KlineBar, MarketSeries, EpochSeconds } from "../marketDataTypes.js";

const series: MarketSeries = { exchange: "binance", marketType: "spot", symbol: "ETHUSDT", interval: "1m" };
const now = 1_800_000_000_000;
const row = (time: number, closed = true, close = 10): KlineBar => ({ time: time as EpochSeconds, open: 10, high: 30, low: 0, close, volume: 1, is_closed: closed });
const wire = (sequence: number, barrier = 1, extra: Record<string, unknown> = {}) => ({
  protocol: 1, epoch: "server-a", generation: 1, sequence, barrier, observed_at_ms: now, stable: true,
  series: { exchange: "binance", market_type: "spot", symbol: "ETHUSDT", interval: "1m", provider_id: "binance", venue: "binance",
    asset_class: "crypto", series_variant: "native", price_adjustment: "raw", session_variant: "continuous", volume_semantics: "base_asset" }, ...extra,
});
const proof = (version: unknown, rows = [row(60), row(120)]): KlineFetchResult => ({ data: rows, stream_version: version,
  all_rows_final: true, complete: true, retryable: false, history_state: "ready", verified_contiguous: true,
  missing_ranges: [], has_tail_gap: false, truncated: false });
function read(cache: SharedMarketCache, version: unknown, rows?: KlineBar[]) {
  const token = cache.beginRead(series);
  try { return cache.admitResponse(token, proof(version, rows)); } finally { token.release(); }
}
function healthy(cache = new SharedMarketCache({ now: () => now })) {
  cache.connect(series);
  read(cache, wire(0, 0));
  cache.admitRealtime(series, row(180, false), "bar.created", wire(1), 120_000);
  assert.equal(cache.planHistory(series, 2).action, "reuse");
  return cache;
}

test("a subscription/ACK and a legacy or unstable snapshot never prove health", () => {
  for (const version of [undefined, wire(1), wire(1, 1, { stable: false })]) {
    const cache = new SharedMarketCache({ now: () => now }); cache.connect(series); read(cache, version);
    assert.notEqual(cache.planHistory(series, 2).action, "reuse");
  }
});

test("snapshot-before-stream and stream-before-snapshot converge on the same scoped cutover", () => {
  healthy();
  const cache = new SharedMarketCache({ now: () => now }); cache.connect(series);
  cache.admitRealtime(series, row(180, false), "bar.created", wire(1), 120_000);
  read(cache, wire(1));
  assert.equal(cache.planHistory(series, 2).action, "reuse");
  assert.equal(parseMarketVersion(wire(1), { ...series, priceAdjustment: "adjusted" }), null);
  assert.equal(parseMarketVersion(wire(1, 2), series), null);
});

test("coalesced forming revisions preserve continuity; a missing critical barrier revokes it", () => {
  const cache = healthy();
  cache.admitRealtime(series, row(180, false, 11), "bar.updated", wire(8), 120_000);
  assert.equal(cache.planHistory(series, 2).action, "reuse");
  cache.admitRealtime(series, row(240, false), "bar.updated", wire(11, 3), 180_000);
  assert.notEqual(cache.planHistory(series, 2).action, "reuse");
  assert.equal(cache.verificationDemand(series), 2);
});

test("a server predecessor extends coverage on close, but a jumped tail cannot invent missing bars", () => {
  const cache = healthy();
  cache.admitRealtime(series, row(180), "bar.closed", wire(2, 2), 120_000);
  cache.admitRealtime(series, row(240, false), "bar.created", wire(3, 3), 180_000);
  assert.equal(cache.planHistory(series, 3).action, "reuse");
  cache.admitRealtime(series, row(360, false), "bar.created", wire(4, 4), 300_000);
  assert.equal(cache.planHistory(series, 3).action, "verify");
  assert.ok(cache.verificationDemand(series));
});

test("stale and duplicate versions cannot overwrite a newer final fact", () => {
  const cache = healthy();
  cache.admitRealtime(series, row(120, true, 20), "bar.amended", wire(2, 2), 60_000);
  cache.admitRealtime(series, row(120, true, 12), "bar.amended", wire(1), 60_000);
  cache.admitRealtime(series, row(120, true, 13), "bar.amended", wire(2, 2), 60_000);
  assert.equal(cache.read(series, { to: 120 }).rows.at(-1)!.close, 20);
  assert.throws(() => read(cache, wire(1)), /Obsolete/);
  read(cache, wire(3, 2), [row(60), row(120, true, 25)]);
  assert.equal(cache.read(series, { to: 120 }).rows.at(-1)!.close, 25);
});

test("freshness expires independently of coverage; a historical amendment does not refresh it", () => {
  let clock = now;
  const cache = healthy(new SharedMarketCache({ now: () => clock }));
  clock += 16_000;
  cache.admitRealtime(series, row(60, true, 20), "bar.amended", wire(2, 2, { observed_at_ms: clock }), 0);
  const health = cache.planHistory(series, 2).health;
  assert.equal(health.historyCovered, true); assert.equal(health.continuous, true);
  assert.equal(health.fresh, false); assert.equal(health.reason, "stale-tail");
});

test("disconnect and epoch change fence in-flight reads and require a fresh stream/snapshot link", () => {
  const cache = healthy(), token = cache.beginRead(series);
  cache.markDisconnected(series); cache.connect(series);
  cache.admitRealtime(series, row(180, false), "bar.created", wire(1, 1, { epoch: "server-b" }), 120_000);
  assert.throws(() => cache.admitResponse(token, proof(wire(1))), /Obsolete/); token.release();
  assert.notEqual(cache.planHistory(series, 2).action, "reuse");
  read(cache, wire(1, 1, { epoch: "server-b" }));
  assert.equal(cache.planHistory(series, 2).action, "reuse");
});

test("a new HTTP epoch cannot be rolled back by queued events from the old socket", () => {
  const cache = healthy(); read(cache, wire(0, 0, { epoch: "server-b" }));
  const result = cache.admitRealtime(series, row(180, false, 29), "bar.updated", wire(10), 120_000);
  assert.equal(result.accepted, false);
  assert.equal(cache.read(series).rows.at(-1)!.close, 10);
});

test("a legacy server after reconnect remains renderable but cannot regain healthy reuse", () => {
  const cache = healthy();
  const old = cache.beginRead(series);
  cache.markDisconnected(series); cache.connect(series);
  assert.throws(() => cache.admitResponse(old, proof(wire(1))), /Obsolete/); old.release();
  read(cache, undefined);
  assert.equal(cache.admitRealtime(series, row(180, false, 24), "bar.updated").accepted, true);
  assert.equal(cache.read(series).rows.at(-1)!.close, 24);
  assert.notEqual(cache.planHistory(series, 2).action, "reuse");
});

test("retired incarnations stay rejected after the new stream has delivered", () => {
  const cache = healthy();
  cache.admitRealtime(series, row(180, false, 22), "bar.updated", wire(1, 0, { epoch: "server-b" }), 120_000);
  cache.admitRealtime(series, row(180, false, 23), "bar.updated", wire(2, 0, { epoch: "server-b" }), 120_000);
  const stale = cache.admitRealtime(series, row(180, false, 10), "bar.updated", wire(50), 120_000);
  assert.equal(stale.accepted, false);
  assert.throws(() => read(cache, wire(51)), /Obsolete/);
  assert.equal(cache.read(series).rows.at(-1)!.close, 23);
});

test("range invalidation revokes dependent prefix stamps without invalidating an unrelated range", () => {
  const cache = healthy();
  const prefix = cache.captureVersion(series, { to: 120 }), unrelated = cache.captureVersion(series, { from: 180, to: 180 });
  cache.invalidateRange(series, { from: 60, to: 120 }, wire(2, 2));
  assert.equal(prefix.isCurrent(), false); assert.equal(unrelated.isCurrent(), true);
  assert.equal(cache.read(series, { to: 120 }).rows.length, 2);
  assert.equal(cache.planHistory(series, 2).health.continuous, false);
});

test("targeted backfill preserves nonintersecting historical coverage", () => {
  const cache = healthy();
  read(cache, wire(1), [row(60), row(120), row(180), row(240)]);
  cache.invalidateRange(series, { from: 60, to: 120 }, wire(2, 2));
  assert.equal(cache.read(series, { from: 180, to: 240 }).complete, true);
  assert.equal(cache.read(series, { from: 60, to: 120 }).complete, false);
});

test("a snapshot crossing unseen critical events revokes proofs and input stamps outside its returned range", () => {
  const cache = healthy();
  const oldInput = cache.captureVersion(series, { from: 60, to: 60 });
  // A correction to time=60 was not delivered. A later HTTP read only covers
  // time=120, so its newer barrier cannot validate the unchanged cached row.
  read(cache, wire(3, 2), [row(120)]);
  assert.equal(cache.read(series, { from: 120, to: 120 }).complete, true);
  assert.equal(cache.read(series, { from: 60, to: 60 }).complete, false);
  assert.equal(oldInput.isCurrent(), false);
  assert.notEqual(cache.planHistory(series, 2).action, "reuse");
});

test("production Feed switching consumes a healthy warm series with no HTTP or physical resubscribe", async t => {
  let calls = 0, currentSequence = 0, physical = 0, closeCount = 0, options!: KlineStreamOptions, controller!: KlineStreamController;
  const gate = new ForegroundPreloadGate({ quietDwellMs: 0 });
  const manager = new MarketDataManager({ cache: { now: () => now }, foregroundPreloadGate: gate,
    api: { getMultiStreamUrl: () => "ws://test", fetchKlinesHistory: async () => { calls += 1; return proof(wire(currentSequence, currentSequence)); },
      fetchKlinesRange: async () => { throw new Error("unexpected range"); },
      fetchKlinesBefore: async () => { throw new Error("unexpected before"); },
      fetchLatestKlines: async () => { throw new Error("unexpected latest"); },
    } satisfies KlineApi,
    streams: { subscribe: (_series, opts = {}) => {
      physical += 1; options = opts;
      controller = { readyState: () => 1, isOpen: () => true, send: () => true, sendPing: () => true,
        updateIntervals() {}, close: () => { closeCount += 1; } };
      queueMicrotask(() => opts.onOpen?.(controller)); return controller;
    }, closeAll() {}, diagnostics: () => ({ physical }) },
  });
  t.after(() => { manager.closeAll(); gate.dispose(); });
  const warm = manager.warm(series, { owner: "eth-hover", reason: "hover", nativeIntervals: ["1m"], limit: 2 });
  assert.equal(await warm.done, "warmed");
  currentSequence = 1;
  options.onKline?.({ interval: "1m", tick: row(180, false), message: { type: "kline", interval: "1m", data: row(180, false),
    event_type: "bar.created", stream_version: wire(1), previous_open_ms: 120_000 } }, controller);
  const chart = manager.subscribe(series, { intervals: ["1m"] });
  const feed = new SeriesDataFeed({ api: manager, getActiveSeries: () => series });
  const result = await feed.getBars(series, { countBack: 2, intent: "viewport", maxWaitMs: 0, cacheMode: "prefer-cache", commit: "none" });
  assert.equal(result.source, "healthy-market-cache"); assert.equal(calls, 1); assert.equal(physical, 1);
  assert.equal(manager.read(series).rows.at(-1)!.is_closed, false, "forming tail remains in the shared projection");
  chart.close(); assert.equal(closeCount, 0, "bounded warm tier retains the existing stream");
  await feed.getHistory(series, { countBack: 2, commit: "none" });
  assert.equal(calls, 2, "explicit network/recovery reads cannot take the shortcut");
  options.onControlMessage?.({ type: "subscribed", intervals: ["1m"], active_intervals: [], failed: [{ interval: "1m" }] }, controller);
  assert.equal(manager.cache.planHistory(series, 2).health.subscribed, false, "negative ACK revokes a previous lease's health");
  options.onControlMessage?.({ type: "subscribed", intervals: ["1m"], active_intervals: ["1m"] }, controller);
  assert.notEqual(manager.cache.planHistory(series, 2).action, "reuse", "a later ACK cannot establish data continuity");
});
