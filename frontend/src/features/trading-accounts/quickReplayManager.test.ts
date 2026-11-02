import assert from "node:assert/strict";
import test from "node:test";
import { epochSeconds } from "../../test/testHelpers.js";
import { MarketDataManager } from "../market-data/manager/marketDataManager.js";
import type { KlineApi, KlineFetchResult, KlineStreamController, KlineStreamOptions } from "../market-data/klineContracts.js";
import { createManagedReplayHistoryReader, loadReplayBars } from "./quickReplayData.js";

const input = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const row = (time: number, close = 10) => ({ time: epochSeconds(time), open: 10, high: 30, low: 0, close, volume: 1, is_closed: true });
const proof = (close = 10): KlineFetchResult => ({ data: [row(60, close), row(120)], all_rows_final: true,
  complete: true, retryable: false, history_state: "ready", verified_contiguous: true,
  missing_ranges: [], has_tail_gap: false, truncated: false });
function setup(fetchKlinesRange: KlineApi["fetchKlinesRange"]) {
  let closed = false;
  let streamOptions: KlineStreamOptions | undefined;
  const controller: KlineStreamController = {
    readyState: () => closed ? 3 : 1, isOpen: () => !closed, send: () => true, sendPing: () => true,
    updateIntervals: () => {}, close: () => { closed = true; },
  };
  const manager = new MarketDataManager({ api: { fetchKlinesRange, getMultiStreamUrl: () => "ws://fixture",
    fetchKlinesHistory: async () => assert.fail("unexpected history read"),
    fetchKlinesBefore: async () => assert.fail("unexpected before read"),
    fetchLatestKlines: async () => assert.fail("unexpected latest read"),
  },
    streams: {
      subscribe: (_series, options) => { streamOptions = options; queueMicrotask(() => options?.onOpen?.(controller)); return controller; },
      diagnostics: () => ({}), closeAll: () => controller.close(),
    },
  });
  return { manager, isClosed: () => closed, tick: (close: number) => {
    const bar = row(60, close);
    streamOptions?.onKline?.({ interval: "1m", tick: bar,
      message: { type: "kline", symbol: "BTCUSDT", interval: "1m", data: bar, event_type: "bar.amended" },
    }, controller);
  } };
}
const turn = () => new Promise<void>(resolve => setImmediate(resolve));

test("trade replay reuses only proven compatible manager history and detaches its candle values", async t => {
  let calls = 0;
  const { manager, tick } = setup(async () => { calls += 1; return proof(); });
  t.after(() => manager.closeAll());
  // A provider/variant-specific cache entry cannot satisfy the canonical trade series.
  await manager.fetchKlinesRange(input.symbol, input.interval, epochSeconds(60), epochSeconds(120), input.marketType, input.exchange,
    { seriesIdentity: { providerId: "external-provider", seriesVariant: "adjusted" } });
  const reader = createManagedReplayHistoryReader(manager);
  const first = await loadReplayBars(input, 60, 120, undefined, reader);
  assert.equal(calls, 2);
  const second = await loadReplayBars(input, 60, 120, undefined, reader);
  assert.equal(calls, 2, "compatible complete history causes no additional transport read");
  manager.subscribe(input, { intervals: ["1m"] });
  await turn(); tick(22);
  assert.equal(manager.read(input).rows[0]!.close, 22);
  assert.equal(first.bars[0]!.close, 10, "a later live amendment cannot rewrite a captured replay");
  assert.equal(second.bars[0]!.close, 10);
  first.bars[0]!.close = 5;
  assert.equal(second.bars[0]!.close, 10, "two replays do not share writable row objects");
  assert.equal(manager.read(input).rows[0]!.close, 22);
});

test("cancelling one replay observer preserves a shared read and live subscription", async t => {
  let calls = 0;
  let finish!: (result: KlineFetchResult) => void;
  let physicalSignal!: AbortSignal;
  const { manager, tick, isClosed } = setup(async (...args) => {
    calls += 1; physicalSignal = args[6].signal!;
    return new Promise(resolve => { finish = resolve; });
  });
  t.after(() => manager.closeAll());
  const live: number[] = [];
  manager.subscribe(input, { intervals: ["1m"], onKline: event => live.push(event.tick.close!) });
  const controller = new AbortController();
  const reader = createManagedReplayHistoryReader(manager);
  const first = loadReplayBars(input, 60, 120, controller.signal, reader);
  const cancelled = assert.rejects(first, { name: "AbortError" });
  const second = loadReplayBars(input, 60, 120, undefined, reader);
  await turn(); assert.equal(calls, 1);
  controller.abort(); await cancelled;
  assert.equal(physicalSignal.aborted, false);
  assert.equal(isClosed(), false);
  tick(22); assert.deepEqual(live, [22]);
  finish(proof());
  assert.equal((await second).bars[0]!.close, 22, "the manager admits a concurrent authoritative amendment");
  tick(24); assert.deepEqual(live, [22, 24]);
  assert.equal(isClosed(), false);
  assert.equal(manager.cache.diagnostics().requests, 0);
});

test("missing workspace manager fails without a direct transport fallback", async () => {
  await assert.rejects(loadReplayBars(input, 60, 120, undefined, createManagedReplayHistoryReader(null)), /manager is unavailable/);
});

test("unproven cached coverage cannot suppress repair of the replay range", async t => {
  let calls = 0;
  const repairs: unknown[] = [];
  const { manager } = setup(async (...args) => {
    calls += 1; repairs.push(args[6].repair);
    return calls === 1 ? { ...proof(), missing_ranges: [{ start_ms: 60_000, end_ms: 120_000 }] } : proof();
  });
  t.after(() => manager.closeAll());
  await manager.fetchKlinesRange(input.symbol, input.interval, epochSeconds(60), epochSeconds(120), input.marketType, input.exchange, {});
  const replay = await loadReplayBars(input, 60, 120, undefined, createManagedReplayHistoryReader(manager));
  assert.equal(calls, 2);
  assert.equal(repairs[1], "wait");
  assert.equal(replay.bars.length, 2);
});
