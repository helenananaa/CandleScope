import assert from "node:assert/strict";
import test from "node:test";
import { MarketDataManager } from "../manager/marketDataManager.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import { ForegroundPreloadGate } from "../foregroundPreloadGate.js";
import type { KlineApi, KlineFetchResult, KlineStreamController, KlineStreamOptions } from "../klineContracts.js";
import type { EpochSeconds, KlineBar, MarketSeries } from "../marketDataTypes.js";

const series: MarketSeries = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const row = (time: number, close = 10, final = true): KlineBar => ({
  time: time as EpochSeconds, open: 10, high: 30, low: 0, close, volume: 2, is_closed: final,
});
const proof = (rows: KlineBar[]): KlineFetchResult => ({ data: rows, all_rows_final: true,
  complete: true, retryable: false, history_state: "ready", verified_contiguous: true,
  missing_ranges: [], has_tail_gap: false, truncated: false });
const turn = () => new Promise<void>(resolve => setImmediate(resolve));
function setup(api: Partial<KlineApi> = {}, gate?: ForegroundPreloadGate, reconnects = false) {
  const streams: Array<{ options: KlineStreamOptions; closed: boolean; intervals: readonly string[]; controller: KlineStreamController }> = [];
  const transport = {
    reconnects,
    subscribe: (_series: unknown, options: KlineStreamOptions = {}) => {
      const state = { options, closed: false, intervals: options.intervals ?? [], controller: null as unknown as KlineStreamController };
      state.controller = {
        readyState: () => 1, isOpen: () => !state.closed, send: () => true, sendPing: () => true,
        updateIntervals: values => { state.intervals = values; }, close: () => { state.closed = true; },
      };
      streams.push(state);
      queueMicrotask(() => options.onOpen?.(state.controller));
      return state.controller;
    }, diagnostics: () => ({ physicalStreams: streams.filter(stream => !stream.closed).length }),
    closeAll: () => { streams.forEach(stream => stream.controller.close()); },
  };
  const manager = new MarketDataManager({ api: { getMultiStreamUrl: () => "ws://fixture", ...api } as KlineApi,
    streams: transport, ...(gate ? { foregroundPreloadGate: gate } : {}) });
  const tick = (bar: KlineBar, eventType = "bar.closed") => {
    const stream = streams.at(-1)!;
    stream.options.onKline?.({ interval: "1m", tick: bar,
      message: { type: "kline", symbol: "BTCUSDT", interval: "1m", data: bar, event_type: eventType },
    }, stream.controller);
  };
  return { manager, streams, tick };
}

test("a reconnecting transport retains live leases and resumes admission without duplicating streams", async t => {
  const { manager, streams, tick } = setup({}, undefined, true);
  t.after(() => manager.closeAll());
  let opens = 0;
  const received: number[] = [];
  const a = manager.subscribe(series, { intervals: ["1m"], onOpen: () => { opens += 1; },
    onKline: event => received.push(event.tick.close!) });
  await turn();
  tick(row(60));
  const physical = streams[0]!;
  physical.options.onClose?.({} as CloseEvent, physical.controller);
  tick(row(120, 20));
  assert.deepEqual(received, [10], "no admission from the disconnected connection");
  physical.options.onOpen?.(physical.controller);
  assert.equal(opens, 2, "the retained lease receives its new transport connection");
  tick(row(120, 20));
  assert.deepEqual(received, [10, 20]);
  assert.equal(manager.read(series).rows.at(-1)!.close, 20);
  const b = manager.subscribe(series, { intervals: ["1m"] });
  await turn();
  assert.equal(streams.length, 1, "a new consumer joins the recovered shared entry");
  a.close(); b.close();
  physical.options.onOpen?.(physical.controller);
  tick(row(180, 30));
  assert.deepEqual(received, [10, 20], "released leases cannot be resurrected");
  assert.equal(manager.read(series).rows.at(-1)!.time, 120);
});

test("promoted viewport warming is admitted once and reused by two foreground feeds across different window scopes", async t => {
  let calls = 0, finish!: (result: KlineFetchResult) => void, signal!: AbortSignal;
  const gate = new ForegroundPreloadGate({ quietDwellMs: 0 });
  const { manager, tick } = setup({ fetchKlinesHistory: async (...args) => {
    calls += 1; signal = args[5].signal!;
    return new Promise(resolve => { finish = resolve; });
  } }, gate);
  t.after(() => { manager.closeAll(); gate.dispose(); });
  manager.subscribe(series, { intervals: ["1m"] });
  const warm = manager.warm(series, { owner: "hover", reason: "hover", nativeIntervals: ["1m"], limit: 2 });
  await turn(); assert.equal(calls, 1);
  const handoff = manager.prepareForeground(series);
  const a = new SeriesDataFeed({ api: manager, foregroundPreloadGate: gate, getActiveSeries: () => series });
  const b = new SeriesDataFeed({ api: manager, foregroundPreloadGate: gate, getActiveSeries: () => series });
  a.setRequestDemand(series, { scope: "chart-a", generation: 7 });
  b.setRequestDemand(series, { scope: "chart-b", generation: 11 });
  const first = a.getHistory(series, { countBack: 2, intent: "viewport", maxWaitMs: 0, commit: "none" });
  const second = b.getHistory(series, { countBack: 2, intent: "viewport", maxWaitMs: 0, commit: "none" });
  warm.release(); await turn();
  assert.equal(signal.aborted, false);
  tick(row(60, 20), "bar.amended");
  finish(proof([row(60, 10), row(120)]));
  const [left, right] = await Promise.all([first, second]);
  assert.equal(calls, 1);
  assert.equal(left.rows[0]!.close, 20);
  assert.equal(right.rows[0]!.close, 20);
  assert.equal(manager.read(series).rows[0]!.close, 20);
  handoff.release();
});

test("the production getBars planner joins promoted count-back warming despite its derived days fallback", async t => {
  let calls = 0, finish!: (result: KlineFetchResult) => void;
  const gate = new ForegroundPreloadGate({ quietDwellMs: 0 });
  const { manager } = setup({ fetchKlinesHistory: async () => {
    calls += 1;
    return calls === 1 ? new Promise(resolve => { finish = resolve; }) : proof([row(60), row(120)]);
  } }, gate);
  t.after(() => { manager.closeAll(); gate.dispose(); });
  const warm = manager.warm(series, { owner: "chart-hover", reason: "hover", nativeIntervals: ["1m"], limit: 2 });
  await turn();
  const handoff = manager.prepareForeground(series);
  const feed = new SeriesDataFeed({ api: manager, foregroundPreloadGate: gate, getActiveSeries: () => series });
  const foreground = feed.getBars(series, { countBack: 2, intent: "viewport", maxWaitMs: 0, commit: "none" });
  warm.release(); await turn();
  finish(proof([row(60), row(120)]));
  assert.equal((await foreground).rows.length, 2);
  assert.equal(calls, 1, "count_back overrides the planner's day-window fallback in the HTTP contract");
  handoff.release();
});

test("warm promotion cannot satisfy a different count, hydration intent or repair read", async t => {
  let calls = 0;
  const gate = new ForegroundPreloadGate({ quietDwellMs: 0 });
  const releases: Array<() => void> = [];
  const { manager } = setup({ fetchKlinesHistory: async () => {
    calls += 1;
    await new Promise<void>(resolve => releases.push(resolve));
    return proof([row(60)]);
  } }, gate);
  t.after(() => { manager.closeAll(); gate.dispose(); });
  const warm = manager.warm(series, { owner: "hover", reason: "hover", nativeIntervals: ["1m"], limit: 2 });
  await turn(); const handoff = manager.prepareForeground(series);
  const count = manager.fetchKlinesHistory("BTCUSDT", "1m", null, "spot", "binance", { countBack: 3, maxWaitMs: 0, intent: "viewport" });
  const hydrate = manager.fetchKlinesHistory("BTCUSDT", "1m", null, "spot", "binance", { countBack: 2, maxWaitMs: 0, intent: "active_hydration" });
  const recovery = manager.fetchKlinesHistory("BTCUSDT", "1m", null, "spot", "binance", { countBack: 2, maxWaitMs: 1500, intent: "viewport" });
  await turn(); assert.equal(calls, 4);
  releases.forEach(release => release());
  await Promise.all([count, hydrate, recovery, warm.done]); handoff.release();
});

test("two chart demands share admission and stream; closing one leaves the other live", async () => {
  const { manager, streams, tick } = setup();
  const receivedA: number[] = [], receivedB: number[] = [];
  const a = manager.subscribe(series, { intervals: ["1m"], onKline: event => {
    assert.equal(manager.cache.read(series).rows.at(-1)!.close, event.tick.close);
    receivedA.push(event.tick.close!);
  } });
  const b = manager.subscribe(series, { intervals: ["1m", "5m"], onKline: event => receivedB.push(event.tick.close!) });
  await Promise.resolve();
  assert.equal(streams.length, 1);
  tick(row(60));
  tick({ ...row(120), volume: -1 });
  assert.deepEqual(receivedA, [10]);
  assert.deepEqual(receivedB, [10]);
  a.close();
  assert.equal(streams[0]!.closed, false);
  tick(row(120, 20));
  assert.deepEqual(receivedA, [10]);
  assert.deepEqual(receivedB, [10, 20]);
  b.close();
  assert.equal(streams[0]!.closed, true);
  manager.closeAll();
});

test("shared HTTP lease admits before delivery and reconciles a concurrent WS amendment", async () => {
  let calls = 0, resolve!: (value: KlineFetchResult) => void, physicalSignal!: AbortSignal;
  const { manager, tick } = setup({ fetchKlinesHistory: async (...args) => {
    calls += 1; physicalSignal = args[5].signal!;
    return new Promise<KlineFetchResult>(done => { resolve = done; });
  } });
  manager.subscribe(series, { intervals: ["1m"] });
  const cancel = new AbortController();
  const a = manager.fetchKlinesHistory("BTCUSDT", "1m", 1, "spot", "binance", { signal: cancel.signal });
  const b = manager.fetchKlinesHistory("BTCUSDT", "1m", 1, "spot", "binance", {});
  await Promise.resolve(); await Promise.resolve();
  assert.equal(calls, 1);
  cancel.abort();
  await assert.rejects(a, { name: "AbortError" });
  assert.equal(physicalSignal.aborted, false);
  tick(row(60, 22), "bar.amended");
  resolve(proof([row(60, 10)]));
  const result = await b;
  assert.equal(result.data![0]!.close, 22);
  assert.equal(manager.cache.read(series).rows[0]!.close, 22);
  assert.equal(manager.cache.diagnostics().requests, 0);
  manager.closeAll();
});

test("bounded historical range hits avoid IO, but repair requests bypass cached proof", async () => {
  let calls = 0;
  const { manager } = setup({ fetchKlinesRange: async () => { calls += 1; return proof([row(60), row(120)]); } });
  const args = ["BTCUSDT", "1m", 60 as EpochSeconds, 120 as EpochSeconds, "spot", "binance"] as const;
  await manager.fetchKlinesRange(...args, {});
  const hit = await manager.fetchKlinesRange(...args, {});
  assert.equal(calls, 1);
  assert.equal(hit.source, "shared-market-cache");
  await manager.fetchKlinesRange(...args, { repair: "wait", strict: true });
  assert.equal(calls, 2);
  manager.closeAll();
});

test("partial or contradictory cache data cannot suppress a missing-range request", async () => {
  let calls = 0;
  const { manager } = setup({ fetchKlinesRange: async () => {
    calls += 1;
    return { ...proof([row(60)]), missing_ranges: [{ start_ms: 120_000, end_ms: 180_000 }] };
  } });
  const args = ["BTCUSDT", "1m", 60 as EpochSeconds, 180 as EpochSeconds, "spot", "binance", {}] as const;
  await manager.fetchKlinesRange(...args);
  await manager.fetchKlinesRange(...args);
  assert.equal(calls, 2);
  manager.closeAll();
});

test("late completion after disposal cannot repopulate the workspace cache", async () => {
  let resolve!: (value: KlineFetchResult) => void;
  const { manager } = setup({ fetchKlinesHistory: () => new Promise(done => { resolve = done; }) });
  const result = manager.fetchKlinesHistory("BTCUSDT", "1m", 1, "spot", "binance", {});
  await Promise.resolve(); await Promise.resolve();
  manager.closeAll();
  await assert.rejects(result, { name: "AbortError" });
  resolve(proof([row(60)]));
  await Promise.resolve(); await Promise.resolve();
  assert.equal(manager.cache.diagnostics().bars, 0);
});

test("Feed backfill readback with repair=none still reaches the backend", async () => {
  let calls = 0;
  const { manager } = setup({ fetchKlinesRange: async () => {
    calls += 1;
    return proof([row(60, calls === 1 ? 10 : 20), row(120)]);
  } });
  await manager.fetchKlinesRange("BTCUSDT", "1m", 60 as EpochSeconds, 120 as EpochSeconds, "spot", "binance", {});
  const feed = new SeriesDataFeed({ api: manager, getActiveSeries: () => series });
  const result = await feed.getRange(series, { start: 60, end: 120, repair: "none", strict: false,
    source: "backfill-completed" });
  assert.equal(calls, 2);
  assert.equal(result.rows[0]!.close, 20);
  manager.closeAll();
});

test("navigation before pages use proven shared coverage; recovery and an unproven right boundary still read network", async t => {
  let beforeCalls = 0, rangeCalls = 0;
  const { manager } = setup({
    fetchKlinesBefore: async () => { beforeCalls += 1; return proof([row(60), row(120)]); },
    fetchKlinesRange: async () => { rangeCalls += 1; return proof([row(60), row(120), row(180), row(240)]); },
  });
  t.after(() => manager.closeAll());
  const token = manager.cache.beginRead(series);
  manager.cache.admitResponse(token, { ...proof([row(60), row(120)]), endpoint: "history" }); token.release();
  const feed = new SeriesDataFeed({ api: manager, getActiveSeries: () => series });
  await feed.getBars(series, { to: 180, countBack: 2, cacheMode: "prefer-cache", commit: "none" });
  assert.equal(beforeCalls, 1, "two old rows do not prove the absence of bars up to the requested boundary");
  await feed.getRange(series, { start: 60, end: 240, commit: "none" });
  const cached = await feed.requestBeforePage(series, { before: 180 as EpochSeconds, bars: 2, commit: "none", cooldownMs: 0 });
  assert.equal(cached.source, "shared-market-cache");
  assert.deepEqual(cached.data?.map(item => item.time), [60, 120]);
  assert.equal(cached.has_more, true, "a retained page never invents global exhaustion");
  assert.equal(beforeCalls, 1);
  await feed.getBefore(series, { before: 180 as EpochSeconds, bars: 2, source: "backfill-completed", commit: "none" });
  assert.equal(beforeCalls, 2, "the default remains fresh readback");
  const rangeHit = await feed.getRange(series, { start: 60, end: 120, repair: "none", cacheMode: "prefer-cache", commit: "none" });
  assert.equal(rangeHit.source, "shared-market-cache");
  assert.equal(rangeCalls, 1);
  await feed.getRange(series, { start: 60, end: 120, repair: "wait", strict: true, cacheMode: "prefer-cache", commit: "none" });
  assert.equal(rangeCalls, 2, "strict repair cannot take the navigation shortcut");
});

test("new backfill completion revokes earlier shared proof before consumers validate it", async t => {
  let calls = 0, observedComplete = true;
  const { manager, streams } = setup({ fetchKlinesRange: async () => { calls += 1; return proof([row(60), row(120)]); } });
  t.after(() => manager.closeAll());
  await manager.fetchKlinesRange("BTCUSDT", "1m", 60 as EpochSeconds, 120 as EpochSeconds, "spot", "binance", {});
  manager.subscribe(series, { intervals: ["1m"], onBackfillCompleted: () => {
    observedComplete = manager.read(series, { from: 60, to: 120 }).complete;
    return true;
  } });
  await turn();
  const stream = streams[0]!;
  stream.options.onBackfillCompleted?.({ type: "backfill_completed", interval: "1m", detail: {
    request_id: "new-correction", request_start_ms: 60_000, request_end_ms: 120_000,
  } }, stream.controller);
  assert.equal(observedComplete, false);
  await manager.fetchKlinesRange("BTCUSDT", "1m", 60 as EpochSeconds, 120 as EpochSeconds, "spot", "binance", { clientContext: { cacheMode: "prefer-cache" } });
  assert.equal(calls, 2);
});
