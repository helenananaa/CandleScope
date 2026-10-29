import assert from "node:assert/strict";
import test from "node:test";
import { createWatchlistMarketDataConsumer } from "../watchlistMarketDataConsumer.js";
import { MarketDataManager } from "../../market-data/manager/marketDataManager.js";
import { ForegroundPreloadGate } from "../../market-data/foregroundPreloadGate.js";
import type { KlineApi, KlineFetchResult, KlineStreamController, KlineStreamOptions } from "../../market-data/klineContracts.js";
import type { EpochSeconds, KlineBar } from "../../market-data/marketDataTypes.js";

const target = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", symbolKey: "binance:spot:BTCUSDT", intervals: ["1m"] };
const job = { ...target, preloadIntervals: ["1m"], nativeIntervals: ["1m"], interval: "1m" };
const row = (time: number, close = 10, final = true): KlineBar => ({ time: time as EpochSeconds,
  open: 10, high: 30, low: 0, close, volume: 1, is_closed: final });
const result = (rows: KlineBar[]): KlineFetchResult => ({ data: rows, all_rows_final: true, complete: true,
  retryable: false, history_state: "ready", verified_contiguous: true, missing_ranges: [], has_tail_gap: false, truncated: false });
const turn = () => new Promise<void>(resolve => setImmediate(resolve));

function harness(api: Partial<KlineApi> = {}, gate?: ForegroundPreloadGate) {
  const streams: Array<{ options: KlineStreamOptions; controller: KlineStreamController; closed: boolean; intervals: readonly string[] }> = [];
  const timers = new Map<ReturnType<typeof setTimeout>, { callback: () => void; delay: number }>();
  let sequence = 0;
  const data = new MarketDataManager({ api: { getMultiStreamUrl: () => "ws://fixture", ...api } as KlineApi, ...(gate ? { foregroundPreloadGate: gate } : {}), streams: {
    subscribe: (_series, options = {}) => {
      const state = { options, closed: false, intervals: options.intervals ?? [], controller: null as unknown as KlineStreamController };
      state.controller = { readyState: () => 1, isOpen: () => !state.closed, send: () => true, sendPing: () => true,
        updateIntervals: intervals => { state.intervals = intervals; }, close: () => { state.closed = true; } };
      streams.push(state);
      return state.controller;
    }, closeAll: () => streams.forEach(stream => stream.controller.close()), diagnostics: () => ({}),
  } });
  const consumer = createWatchlistMarketDataConsumer({ data,
    schedule: (callback, delay) => { const key = ++sequence as unknown as ReturnType<typeof setTimeout>; timers.set(key, { callback, delay }); return key; },
    cancel: handle => { timers.delete(handle); },
  });
  const tick = (index: number, bar: KlineBar, eventType = "bar.updated") => {
    const stream = streams[index]!;
    stream.options.onKline?.({ interval: "1m", tick: bar,
      message: { type: "kline", interval: "1m", data: bar, event_type: eventType } }, stream.controller);
  };
  const fire = (delay: number) => {
    const entry = [...timers].find(([, value]) => value.delay === delay);
    assert.ok(entry, `missing timer ${delay}`);
    timers.delete(entry[0]); entry[1].callback();
  };
  return { data, consumer, streams, timers, tick, fire, dispose: () => { consumer.dispose(); data.closeAll(); } };
}

test("watchlist and chart share one accepted stream; releasing the watchlist cannot stop the chart", () => {
  const h = harness();
  let chartTicks = 0;
  const chart = h.data.subscribe(target, { intervals: ["1m"], onKline: () => { chartTicks += 1; } });
  h.consumer.syncTargets([target]);
  assert.equal(h.streams.length, 1);
  const stream = h.streams[0]!;
  stream.options.onOpen?.(stream.controller);
  assert.equal(h.consumer.diagnostics().streams[0]!.status, "waiting");
  h.tick(0, row(60), "bar.amended");
  assert.equal(h.consumer.diagnostics().streams[0]!.status, "waiting", "historical amendment is not live freshness");
  h.tick(0, row(120));
  assert.equal(h.consumer.diagnostics().streams[0]!.status, "live");
  assert.equal(h.data.read(job).rows.length, 2);
  h.consumer.syncTargets([], false);
  assert.equal(stream.closed, false);
  h.tick(0, row(180));
  assert.equal(chartTicks, 3);
  assert.equal(h.data.read(job).rows.length, 3);
  chart.close(); h.dispose();
});

test("reconnect is bounded, uses a new generation, and old messages cannot overwrite shared data", () => {
  const h = harness();
  h.consumer.syncTargets([target]);
  const old = h.streams[0]!;
  old.options.onOpen?.(old.controller);
  h.tick(0, row(60));
  old.options.onClose?.({} as CloseEvent, old.controller);
  assert.equal(h.consumer.diagnostics().streams[0]!.status, "stale");
  h.fire(1_000);
  assert.equal(h.streams.length, 2);
  const next = h.streams[1]!;
  next.options.onOpen?.(next.controller);
  h.tick(1, row(120, 20));
  h.tick(0, row(120, 5));
  old.options.onClose?.({} as CloseEvent, old.controller);
  assert.equal(h.data.read(job).rows.at(-1)!.close, 20);
  assert.equal(h.consumer.diagnostics().streams[0]!.status, "live");
  h.dispose();
  assert.equal(h.timers.size, 0);
});

test("interval changes update only the watchlist lease while a chart retains its interval", () => {
  const h = harness();
  const chart = h.data.subscribe(target, { intervals: ["1m"] });
  h.consumer.syncTargets([{ ...target, intervals: ["1m", "5m"] }]);
  h.streams[0]!.options.onOpen?.(h.streams[0]!.controller);
  h.consumer.syncTargets([{ ...target, intervals: ["15m"] }]);
  assert.deepEqual(new Set(h.streams[0]!.intervals), new Set(["1m", "15m"]));
  h.consumer.dispose();
  assert.deepEqual(h.streams[0]!.intervals, ["1m"]);
  chart.close(); h.data.closeAll();
});

test("partial subscription ACK preserves per-interval errors and cannot manufacture live status", () => {
  const h = harness();
  h.consumer.syncTargets([{ ...target, intervals: ["1m", "5m"] }]);
  const stream = h.streams[0]!;
  stream.options.onOpen?.(stream.controller);
  stream.options.onControlMessage?.({ type: "subscribed", intervals: ["1m"],
    failed: [{ interval: "5m", code: "unsupported_interval" }] }, stream.controller);
  assert.equal(h.consumer.diagnostics().streams[0]!.status, "partial");
  assert.deepEqual(h.consumer.diagnostics().streams[0]!.intervalStatus, { "1m": "waiting", "5m": "error" });
  h.tick(0, row(60));
  assert.equal(h.consumer.diagnostics().streams[0]!.status, "partial");
  assert.equal(h.consumer.diagnostics().streams[0]!.intervalStatus["1m"], "live");
  h.dispose();
});

test("disconnect aborts watchlist recovery before a late response can replace shared data", async () => {
  let finish!: (value: KlineFetchResult) => void, signal!: AbortSignal;
  const h = harness({ fetchKlinesRange: (...args) => {
    signal = args[6].signal!;
    return new Promise(resolve => { finish = resolve; });
  } });
  h.data.cache.admitRealtime(job, row(60));
  h.consumer.syncTargets([target]);
  const stream = h.streams[0]!;
  stream.options.onOpen?.(stream.controller);
  stream.options.onBackfillCompleted?.({ type: "backfill_completed", interval: "1m", detail: {
    request_id: "late-repair", request_start_ms: 60_000, request_end_ms: 60_000,
  } }, stream.controller);
  await turn();
  stream.options.onClose?.({} as CloseEvent, stream.controller);
  assert.equal(signal.aborted, true);
  finish(result([row(60, 25)])); await turn();
  assert.equal(h.data.read(job).rows[0]!.close, 10);
  h.dispose();
});

test("warming has independent cancellation and populates the same cache read by charts", async () => {
  let calls = 0, complete!: (response: KlineFetchResult) => void, signal!: AbortSignal;
  const h = harness({ fetchKlinesHistory: async (...args) => {
    calls += 1; signal = args[5].signal!;
    return new Promise(resolve => { complete = resolve; });
  } });
  h.consumer.syncJobs([job]);
  const chartRead = h.data.fetchKlinesHistory("BTCUSDT", "1m", null, "spot", "binance", { countBack: 500, maxWaitMs: 0, intent: "viewport" });
  await turn();
  assert.equal(calls, 1);
  h.consumer.syncJobs([], false);
  assert.equal(signal.aborted, false);
  complete(result([row(60)]));
  await chartRead; await turn();
  assert.equal(h.data.read(job).rows[0]!.close, 10);
  assert.equal(h.consumer.diagnostics().activeWarm, 0);
  h.dispose();
});

test("repeated sync does not spin partial warming and a foreground gate can cancel and resume work", async () => {
  const gate = new ForegroundPreloadGate({ quietDwellMs: 0 });
  const pending: Array<{ resolve: (value: KlineFetchResult) => void; signal: AbortSignal }> = [];
  const h = harness({ fetchKlinesHistory: (...args) => new Promise(resolve => pending.push({ resolve, signal: args[5].signal! })) }, gate);
  h.consumer.syncJobs([job]); await turn();
  const foreground = gate.enterForeground("chart-switch");
  assert.equal(pending[0]!.signal.aborted, true);
  pending[0]!.resolve({ data: [row(60, 10, false)] }); await turn();
  assert.equal(pending.length, 1);
  foreground.release(); await turn();
  assert.equal(pending.length, 2);
  pending[1]!.resolve({ data: [row(60, 11, false)], all_rows_final: false }); await turn();
  h.consumer.syncJobs([job]); await turn();
  assert.equal(pending.length, 2);
  assert.equal(h.data.read(job).complete, false);
  assert.equal(h.data.read(job).rows[0]!.close, 11);
  h.dispose(); gate.dispose();
});

test("backfill completion reads the retained range through the manager and deduplicates repeated events", async () => {
  let calls = 0;
  const h = harness({ fetchKlinesRange: async () => { calls += 1; return result([row(60, 21), row(120)]); } });
  const token = h.data.cache.beginRead(job);
  h.data.cache.admitResponse(token, { ...result([row(60), row(120)]), endpoint: "range" }); token.release();
  h.consumer.syncTargets([target]);
  const stream = h.streams[0]!;
  stream.options.onOpen?.(stream.controller);
  const message = { type: "backfill_completed" as const, interval: "1m", detail: {
    request_id: "repair-a", request_start_ms: 60_000, request_end_ms: 120_000,
  } };
  stream.options.onBackfillCompleted?.(message, stream.controller);
  stream.options.onBackfillCompleted?.(message, stream.controller);
  await turn();
  assert.equal(calls, 1);
  assert.equal(h.data.read(job).rows[0]!.close, 21);
  assert.equal(h.consumer.diagnostics().streams[0]!.status, "waiting");
  h.dispose();
});
