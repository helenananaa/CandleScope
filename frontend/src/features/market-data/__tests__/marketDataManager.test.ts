import assert from "node:assert/strict";
import test from "node:test";
import { MarketDataManager } from "../manager/marketDataManager.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import type { KlineApi, KlineFetchResult, KlineStreamController, KlineStreamOptions } from "../klineContracts.js";
import type { EpochSeconds, KlineBar, MarketSeries } from "../marketDataTypes.js";

const series: MarketSeries = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const row = (time: number, close = 10, final = true): KlineBar => ({
  time: time as EpochSeconds, open: 10, high: 30, low: 0, close, volume: 2, is_closed: final,
});
const proof = (rows: KlineBar[]): KlineFetchResult => ({ data: rows, all_rows_final: true,
  complete: true, retryable: false, history_state: "ready", verified_contiguous: true,
  missing_ranges: [], has_tail_gap: false, truncated: false });
function setup(api: Partial<KlineApi> = {}) {
  const streams: Array<{ options: KlineStreamOptions; closed: boolean; intervals: readonly string[]; controller: KlineStreamController }> = [];
  const transport = {
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
  const manager = new MarketDataManager({ api: { getMultiStreamUrl: () => "ws://fixture", ...api } as KlineApi, streams: transport });
  const tick = (bar: KlineBar, eventType = "bar.closed") => {
    const stream = streams.at(-1)!;
    stream.options.onKline?.({ interval: "1m", tick: bar,
      message: { type: "kline", symbol: "BTCUSDT", interval: "1m", data: bar, event_type: eventType },
    }, stream.controller);
  };
  return { manager, streams, tick };
}

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
