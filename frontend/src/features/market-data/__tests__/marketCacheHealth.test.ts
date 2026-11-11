import assert from "node:assert/strict";
import test from "node:test";
import { SharedMarketCache } from "../manager/sharedMarketCache.js";
import { parseMarketVersion } from "../manager/marketHealth.js";
import { MarketDataManager } from "../manager/marketDataManager.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import { ForegroundPreloadGate } from "../foregroundPreloadGate.js";
import type { KlineApi, KlineFetchResult, KlineRangeRequestOptions, KlineStreamController, KlineStreamOptions } from "../klineContracts.js";
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

test("a history snapshot across an unseen critical barrier waits for a matching stream event", () => {
  const cache = healthy();
  read(cache, wire(4, 3));
  const pending = cache.planHistory(series, 2);
  assert.equal(pending.health.historyCovered, true);
  assert.equal(pending.health.continuous, false);
  assert.notEqual(pending.action, "reuse");
  cache.admitRealtime(series, row(180, false, 23), "bar.updated", wire(5, 3), 120_000);
  assert.equal(cache.planHistory(series, 2).action, "reuse");
});

test("a latest observation preserves existing history evidence and cannot replace versioned rows with legacy data", () => {
  const cache = healthy();
  const token = cache.beginRead(series);
  try {
    const legacy = cache.admitResponse(token, { endpoint: "latest", data: [row(120, true, 29)] });
    assert.equal(legacy.data?.[0]?.close, 10);
    cache.admitResponse(token, { endpoint: "latest", data: [row(180, false, 20)], stream_version: wire(2) });
    assert.equal(cache.read(series).rows.at(-1)?.close, 20);
    assert.equal(cache.planHistory(series, 2).action, "reuse");
  } finally {
    token.release();
  }
});

test("latest observations cannot establish a history link or hide a critical barrier or a known tail gap", () => {
  const cache = healthy();
  const token = cache.beginRead(series);
  try {
    cache.admitResponse(token, { endpoint: "latest", data: [row(180, false, 23)], stream_version: wire(4, 3) });
    assert.equal(cache.planHistory(series, 2).health.historyCovered, false);
    assert.equal(cache.planHistory(series, 2).health.continuous, false);
    cache.admitRealtime(series, row(180, false, 24), "bar.updated", wire(5, 3), 120_000);
    assert.equal(cache.planHistory(series, 2).health.continuous, false);
    read(cache, wire(5, 3));
    assert.equal(cache.planHistory(series, 2).action, "reuse");
    cache.admitResponse(token, { endpoint: "latest", data: [], has_tail_gap: true, stream_version: wire(5, 3) });
    assert.equal(cache.planHistory(series, 2).health.continuous, false);
  } finally {
    token.release();
  }
});

test("a versioned latest gap revokes affected coverage without touching a disjoint input", () => {
  const cache = healthy();
  read(cache, wire(1), [row(0), row(60), row(120)]);
  const retained = cache.captureVersion(series, { to: 60 });
  const affected = cache.captureVersion(series, { from: 120, to: 120 });
  const token = cache.beginRead(series);
  try {
    cache.admitResponse(token, { endpoint: "latest", data: [], stream_version: wire(2),
      storage_revision: 1, has_tail_gap: true,
      missing_ranges: [{ interval: "1m", start_ms: 120_000, end_ms: 120_000 }] });
    assert.equal(affected.isCurrent(), false);
    assert.equal(retained.isCurrent(), true);
    assert.equal(cache.planHistory(series, 2).action, "load");
  } finally {
    token.release();
  }
});

test("a subscription/ACK and a legacy or unstable snapshot never prove health", () => {
  for (const version of [undefined, wire(1), wire(1, 1, { stable: false })]) {
    const cache = new SharedMarketCache({ now: () => now }); cache.connect(series); read(cache, version);
    assert.notEqual(cache.planHistory(series, 2).action, "reuse");
  }
});

test("an unstable custom-period response cannot restore coverage revoked by backfill", () => {
  const custom = { ...series, interval: "2m" };
  const scope = { ...wire(0, 0).series, interval: custom.interval };
  const version = (sequence: number, stable = true) => wire(sequence, sequence, { series: scope, stable });
  const cache = new SharedMarketCache({ now: () => now });
  const first = cache.beginRead(custom);
  cache.admitResponse(first, proof(version(0), [row(120), row(240)]));
  first.release();
  assert.equal(cache.read(custom).complete, true);

  const racing = cache.beginRead(custom);
  cache.invalidateRange(custom, { from: 120, to: 120 }, version(1));
  assert.equal(cache.read(custom, { from: 120, to: 120 }).complete, false);
  const pending = cache.admitResponse(racing, proof(version(0, false), [row(120, true, 15), row(240)]));
  racing.release();
  assert.equal(pending.history_state, "pending");
  assert.equal(pending.quality?.complete, false);
  assert.deepEqual(pending.data, []);
  assert.equal(cache.read(custom, { from: 120, to: 120 }).complete, false);
  assert.equal(cache.read(custom).rows[0]?.close, 10);

  const fresh = cache.beginRead(custom);
  cache.admitResponse(fresh, proof(version(1), [row(120, true, 20), row(240)]));
  fresh.release();
  assert.equal(cache.read(custom).complete, true);
  assert.equal(cache.read(custom).rows[0]?.close, 20);
});

test("a delayed stable response cannot undo a newer durable correction at the same stream cursor", () => {
  const cache = healthy();
  const older = cache.beginRead(series);
  const newer = cache.beginRead(series);
  try {
    cache.admitResponse(newer, { ...proof(wire(1), [row(60), row(120, true, 25)]), storage_revision: 41 });
    const pending = cache.admitResponse(older, { ...proof(wire(1)), storage_revision: 40 });
    assert.equal(pending.retryable, true);
    assert.equal(pending.quality?.complete, false);
    assert.deepEqual(pending.data, []);
    assert.equal(cache.read(series, { to: 120 }).rows.at(-1)?.close, 25);
    assert.equal(cache.read(series, { to: 120 }).complete, true);
  } finally {
    older.release();
    newer.release();
  }

  const restarted = cache.beginRead(series);
  try {
    const restored = cache.admitResponse(restarted, {
      ...proof(wire(0, 0, { epoch: "server-restored" }), [row(60), row(120, true, 28)]), storage_revision: 3,
    });
    assert.equal(restored.quality?.complete, true);
    assert.equal(cache.read(series, { to: 120 }).rows.at(-1)?.close, 28);
  } finally {
    restarted.release();
  }
});

test("shared stream observations expire and revoke independently of historical coverage", () => {
  let clock = now;
  const cache = healthy(new SharedMarketCache({ now: () => clock }));
  assert.equal(cache.hasCurrentStream(series), true);
  assert.equal(cache.hasCurrentStream({ ...series, priceAdjustment: "adjusted" }), false);
  // A larger history demand is unproven even while the stream is current.
  assert.equal(cache.planHistory(series, 500).health.historyCovered, false);
  clock += 15_001;
  assert.equal(cache.hasCurrentStream(series), false);
  cache.admitRealtime(series, row(180, false), "bar.updated", wire(2, 1, { observed_at_ms: clock }), 120_000);
  assert.equal(cache.hasCurrentStream(series), true);
  cache.markDisconnected(series);
  assert.equal(cache.hasCurrentStream(series), false);
  cache.connect(series);
  assert.equal(cache.hasCurrentStream(series), false);
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

test("a historical amendment in a new generation cannot reuse the retired stream's freshness", () => {
  const cache = healthy();
  const generation = (sequence: number, barrier = 1) => wire(sequence, barrier, { generation: 2 });
  read(cache, generation(0, 0));
  cache.admitRealtime(series, row(60, true, 20), "bar.amended", generation(1), 0);
  read(cache, generation(1), [row(60, true, 20), row(120)]);
  const health = cache.planHistory(series, 2).health;
  assert.equal(health.continuous, true);
  assert.equal(health.fresh, false);
  cache.admitRealtime(series, row(180, false, 22), "bar.updated", generation(2), 120_000);
  assert.equal(cache.planHistory(series, 2).action, "reuse");
});

test("a new generation announced by a history correction replaces retired row and tail versions", () => {
  const cache = healthy();
  read(cache, wire(5), [row(60), row(120, true, 15)]);
  const version = wire(1, 1, { generation: 2 });
  cache.invalidateRange(series, { from: 120, to: 120 }, version);
  read(cache, version, [row(60), row(120, true, 25)]);
  assert.equal(cache.read(series, { to: 120 }).rows.at(-1)?.close, 25);
  const health = cache.planHistory(series, 2).health;
  assert.equal(health.historyCovered, false);
  assert.equal(health.fresh, false);
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

test("a source gap holds stream health until canonical readback and a fresh non-replayed event", () => {
  const cache = healthy();
  const oldRead = cache.beginRead(series);
  const affected = cache.captureVersion(series, { from: 60, to: 60 });
  const disjoint = cache.captureVersion(series, { from: 120, to: 120 });
  const range = { from: 60, to: 60 };
  assert.ok(cache.invalidateRange(series, range, wire(2, 2), undefined, { id: "gap", resolved: false }));
  try {
    assert.throws(() => cache.admitResponse(oldRead, proof(wire(1))), /Obsolete market snapshot/);
  } finally { oldRead.release(); }
  assert.equal(affected.isCurrent(), false);
  assert.equal(disjoint.isCurrent(), true);
  read(cache, wire(2, 2), [row(120)]);
  assert.equal(cache.planHistory(series, 1).health.historyCovered, true);
  assert.equal(cache.planHistory(series, 1).health.continuous, false);
  assert.equal(cache.read(series, range).complete, false);
  read(cache, wire(5, 4), [row(120)]);
  assert.ok(cache.invalidateRange(series, range, wire(3, 3), undefined, { id: "gap", resolved: true }));
  read(cache, wire(5, 4), [row(60, true, 18), row(120)]);
  cache.admitRealtime(series, row(180, false, 20), "bar.updated", wire(6, 4), 120_000, true);
  assert.equal(cache.planHistory(series, 2).health.fresh, false);
  cache.admitRealtime(series, row(180, false, 21), "bar.updated", wire(7, 4), 120_000);
  assert.equal(cache.planHistory(series, 2).action, "reuse");
  assert.equal(cache.read(series, range).rows[0]?.close, 18);
});

test("a stable empty read revokes the named gap without revoking unaffected historical proof", () => {
  const cache = new SharedMarketCache({ now: () => now });
  const first = cache.beginRead(series);
  cache.admitResponse(first, { ...proof(wire(0, 0), [row(60), row(120), row(180)]), storage_revision: 40 });
  first.release();
  const missing = cache.captureVersion(series, { from: 120, to: 120 });
  const unaffected = cache.captureVersion(series, { from: 60, to: 60 });
  assert.equal(cache.read(series, { from: 120, to: 120 }).complete, true);

  const second = cache.beginRead(series);
  const gap = { ...proof(wire(0, 0), []), storage_revision: 41, endpoint: "range" as const,
    complete: false, retryable: true, history_state: "pending" as const, verified_contiguous: false,
    missing_ranges: [{ interval: series.interval, start_ms: 120_000, end_ms: 120_000 }] };
  cache.admitResponse(second, gap);
  second.release();
  assert.equal(cache.read(series, { from: 120, to: 120 }).complete, false);
  assert.equal(missing.isCurrent(), false);
  assert.equal(cache.read(series, { from: 60, to: 60 }).complete, true);
  assert.equal(cache.read(series, { from: 180, to: 180 }).complete, true);
  assert.equal(unaffected.isCurrent(), true);
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

test("a narrower current snapshot preserves the already-proven wider history", () => {
  const cache = new SharedMarketCache({ now: () => now });
  cache.connect(series);
  read(cache, wire(0, 0), [row(60), row(120), row(180), row(240)]);
  cache.admitRealtime(series, row(300, false), "bar.created", wire(1), 240_000);
  assert.equal(cache.planHistory(series, 4).action, "reuse");
  read(cache, wire(1), [row(180), row(240)]);
  assert.equal(cache.planHistory(series, 4).action, "reuse");
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

test("a storage correction rejects older range snapshots before they reach cache or chart", async t => {
  const requests: KlineRangeRequestOptions[] = [];
  const replies = [
    { ...proof(wire(2, 2), [row(60), row(120, true, 11)]), storage_revision: 40 },
    { ...proof(wire(2, 2, { epoch: "retired" }), [row(60), row(120, true, 12)]), storage_revision: 42 },
    { ...proof(wire(2, 2), [row(60), row(120, true, 21)]), storage_revision: 41 },
    { ...proof(wire(3, 3), [row(60), row(120, true, 23)]), storage_revision: 42 },
    { ...proof(wire(4, 4), [row(60), row(120, true, 24)]), storage_revision: 43 },
  ];
  const manager = new MarketDataManager({
    api: {
      getMultiStreamUrl: () => "ws://test",
      fetchKlinesHistory: async () => { throw new Error("unexpected history"); },
      fetchKlinesRange: async (_symbol, _interval, _start, _end, _market, _exchange, options) => {
        requests.push(options);
        const reply = replies.shift();
        if (!reply) throw new Error("unexpected range");
        return reply;
      },
      fetchKlinesBefore: async () => { throw new Error("unexpected before"); },
      fetchLatestKlines: async () => { throw new Error("unexpected latest"); },
    },
    streams: { subscribe: () => { throw new Error("unexpected stream"); }, closeAll() {}, diagnostics: () => ({}) },
  });
  t.after(() => manager.closeAll());
  const committed: number[] = [];
  const feed = new SeriesDataFeed({ api: manager, getActiveSeries: () => series,
    commitMergedChartData: (_symbol, _interval, data) => {
      const close = data.at(-1)?.close;
      assert.equal(typeof close, "number");
      committed.push(close!);
    } });
  read(manager.cache, wire(1), [row(60), row(120)]);

  const correct = (sequence: number, revision: number, ranged: boolean) => {
    const version = wire(sequence, sequence);
    manager.cache.invalidateRange(series, ranged ? { from: 120, to: 120 } : undefined, version, revision);
    assert.equal(feed.handleBackfillCompleted({
      type: "backfill_completed", interval: series.interval, stream_version: version,
      detail: { reason: "storage_history_changed", storage_revision: revision,
        ...(ranged ? { range_start_ms: 120_000, range_end_ms: 120_000 } : {}) },
    }, { getCacheRows: () => [...manager.read(series).rows] }), true);
  };
  const idle = async () => {
    for (let i = 0; i < 100 && feed.backfillReloadInFlight.size; i += 1) {
      await new Promise<void>((resolve) => setTimeout(resolve, 10));
    }
    assert.equal(feed.backfillReloadInFlight.size, 0);
  };

  correct(2, 41, true);
  await idle();
  assert.deepEqual(requests.map(({ storageRevisionFloor }) => storageRevisionFloor),
    Array.from({ length: 3 }, () => ({ epoch: "server-a", revision: 41 })));
  assert.deepEqual(committed, [21]);
  assert.equal(manager.read(series).rows.at(-1)?.close, 21);

  correct(3, 42, true);
  await idle();
  assert.deepEqual(requests.at(-1)?.storageRevisionFloor, { epoch: "server-a", revision: 42 });
  assert.deepEqual(committed, [21, 23]);

  correct(4, 43, false);
  await idle();
  assert.deepEqual(requests.at(-1)?.storageRevisionFloor, { epoch: "server-a", revision: 43 });
  assert.deepEqual(committed, [21, 23, 24]);
});

test("stream recovery admits repair instead of repeatedly issuing read-only viewport probes", async t => {
  let options!: KlineStreamOptions, controller!: KlineStreamController, reads = 0;
  const manager = new MarketDataManager({ cache: { now: () => now }, batchHistory: false,
    api: { getMultiStreamUrl: () => "ws://test",
      fetchKlinesHistory: async (_symbol, _interval, _days, _type, _exchange, request) => {
        reads += 1;
        // The production history route makes zero-wait viewport probes read-only.
        if (request?.intent === "viewport" && request.maxWaitMs === 0) return {
          ...proof(wire(2, 2), [row(60), row(180)]), complete: false,
          history_state: "pending", verified_contiguous: false, retryable: true,
          missing_ranges: [{ interval: "1m", start_ms: 120_000, end_ms: 120_000 }],
        };
        return proof(wire(2, 2), [row(60), row(120), row(180)]);
      },
      fetchKlinesRange: async () => { throw new Error("unexpected range"); },
      fetchKlinesBefore: async () => { throw new Error("unexpected before"); },
      fetchLatestKlines: async () => { throw new Error("unexpected latest"); },
    } satisfies KlineApi,
    streams: { subscribe: (_series, opts = {}) => {
      options = opts;
      controller = { readyState: () => 1, isOpen: () => true, send: () => true,
        sendPing: () => true, updateIntervals() {}, close() {} };
      queueMicrotask(() => opts.onOpen?.(controller)); return controller;
    }, closeAll() {}, diagnostics: () => ({ physical: 1 }) },
  });
  t.after(() => manager.closeAll());
  manager.subscribe(series, { intervals: ["1m"] });
  await new Promise<void>(resolve => setImmediate(resolve));
  const token = manager.cache.beginRead(series);
  manager.cache.admitResponse(token, proof(wire(0, 0), [row(60), row(120), row(180)])); token.release();
  manager.cache.invalidateRange(series, { from: 120, to: 120 }, wire(2, 2));
  options.onKline?.({ interval: "1m", tick: row(240, false), message: {
    type: "kline", interval: "1m", data: row(240, false), event_type: "bar.created",
    stream_version: wire(2, 2), previous_open_ms: 180_000,
  } }, controller);
  await new Promise<void>(resolve => setImmediate(resolve));
  assert.equal(reads, 1, "one bounded verification request owns admission");
  assert.equal(manager.cache.read(series, { from: 60, to: 180 }).complete, true,
    "the missing durable range must be repaired and proven");
  options.onKline?.({ interval: "1m", tick: row(240, false), message: {
    type: "kline", interval: "1m", data: row(240, false), event_type: "bar.updated",
    stream_version: wire(3, 2), previous_open_ms: 180_000,
  } }, controller);
  assert.equal(manager.cache.planHistory(series, 3).action, "reuse");
});
