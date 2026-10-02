import assert from "node:assert/strict";
import test from "node:test";

import { LiquidationStore } from "../liquidationStore.js";
import { LiquidationHistoryRequestCoordinator } from "../liquidationHistoryRequests.js";
import { loadLiquidationHistoryPages } from "../liquidationHistoryLoader.js";
import type {
  LiquidationEvent,
  LiquidationQualityMetadata,
  LiquidationRollup,
  LiquidationHistoryPayload,
} from "../liquidationTypes.js";

const identity = { exchange: "binance", marketType: "futures", symbol: "BTCUSDT" };
const quality: LiquidationQualityMetadata = {
  sourceQuality: "sampled_best_effort",
  sourceExhaustive: false,
  samplingMode: "latest_per_symbol_1000ms",
  lossySnapshot: true,
  backfillable: false,
  exchangeUpdateIntervalMs: 1000,
};

function event(overrides: Partial<LiquidationEvent> = {}): LiquidationEvent {
  return {
    ...identity,
    orderSide: "SELL",
    positionSide: "long",
    filledQuantity: 1,
    executedNotional: 20_000,
    tradeTimeMs: 1_700_000_000_100,
    eventTimeMs: 1_700_000_000_110,
    receivedAtMs: 1_700_000_000_120,
    source: "websocket",
    fingerprint: "event-1",
    ...overrides,
  };
}

function rollup(overrides: Partial<LiquidationRollup> = {}): LiquidationRollup {
  return {
    ...identity,
    period: "1m",
    positionSide: "long",
    bucketStartMs: 1_699_999_980_000,
    bucketEndMs: 1_700_000_040_000,
    filledQuantity: 1,
    filledNotional: 20_000,
    eventCount: 1,
    maxEventNotional: 20_000,
    firstEventTimeMs: 1_700_000_000_100,
    lastEventTimeMs: 1_700_000_000_100,
    isFinal: false,
    revision: 1,
    updatedAtMs: 1_700_000_000_120,
    ...overrides,
  };
}

test("liquidation store deduplicates replayed events and removes history-covered live data", () => {
  const store = new LiquidationStore();
  store.applyEvents(identity, [event(), event()], quality);
  assert.equal(store.getSnapshot(identity).liveEvents.length, 1);

  store.mergeHistory(identity, [rollup()], quality);
  const snapshot = store.getSnapshot(identity);
  assert.equal(snapshot.liveEvents.length, 0);
  assert.equal(snapshot.rollups[0]?.filledNotional, 20_000);
});

test("final liquidation rollups cannot be overwritten by later provisional rows", () => {
  const store = new LiquidationStore();
  store.mergeHistory(identity, [rollup({
    isFinal: true,
    revision: 2,
    filledNotional: 30_000,
  })], quality);
  store.mergeHistory(identity, [rollup({
    isFinal: false,
    revision: 99,
    updatedAtMs: 1_700_000_100_000,
    filledNotional: 99_000,
  })], quality);
  assert.equal(store.getSnapshot(identity).rollups[0]?.filledNotional, 30_000);
});

test("resync clears only unconfirmed liquidation state", () => {
  const store = new LiquidationStore();
  store.mergeHistory(identity, [
    rollup({ isFinal: true }),
    rollup({
      bucketStartMs: 1_700_000_040_000,
      bucketEndMs: 1_700_000_100_000,
      isFinal: false,
    }),
  ], quality);
  store.applyEvents(identity, [event({
    fingerprint: "event-later",
    tradeTimeMs: 1_700_000_110_000,
    receivedAtMs: 1_700_000_110_010,
  })], quality);

  store.clearUnconfirmed(identity);
  const snapshot = store.getSnapshot(identity);
  assert.equal(snapshot.rollups.length, 1);
  assert.equal(snapshot.rollups[0]?.isFinal, true);
  assert.equal(snapshot.liveEvents.length, 0);
});

test("eviction removes coverage and reloading an older page retains its data", () => {
  const store = new LiquidationStore({ maxRollupsPerIdentity: 2 });
  const base = 1_699_999_980_000;
  const rows = [0, 1, 2].map((index) => rollup({
    bucketStartMs: base + index * 60_000,
    bucketEndMs: base + (index + 1) * 60_000,
    isFinal: true,
  }));
  const requested = { startMs: base, endMs: base + 3 * 60_000 - 1 };
  store.mergeHistory(identity, rows, quality, { side: "long", range: requested });
  const coordinator = new LiquidationHistoryRequestCoordinator();
  const claims = coordinator.claim("long", requested, store.historyCoverage(identity, "long"));
  assert.deepEqual(claims.map((claim) => claim.range), [{ startMs: base, endMs: base + 59_999 }]);
  const first = rows[0]!;
  store.mergeHistory(identity, [first], quality, { side: "long", range: claims[0]!.range });
  assert.equal(store.getSnapshot(identity).rollups[0], first);
  assert.deepEqual(store.historyCoverage(identity, "long"), [
    { startMs: base, endMs: base + 59_999 },
    { startMs: base + 120_000, endMs: requested.endMs },
  ]);
});

test("coverage preserves confirmed empty ranges and other liquidation sides", () => {
  const store = new LiquidationStore({ maxRollupsPerIdentity: 1 });
  const base = 1_699_999_980_000;
  const range = { startMs: base, endMs: base + 179_999 };
  store.mergeHistory(identity, [], quality, { side: "short", range });
  store.mergeHistory(identity, [rollup()], quality, { side: "long", range });
  store.mergeHistory(identity, [rollup({
    bucketStartMs: base + 120_000, bucketEndMs: base + 180_000,
  })], quality);
  assert.deepEqual(store.historyCoverage(identity, "short"), [range]);
  assert.deepEqual(store.historyCoverage(identity, "long"), [{ startMs: base + 60_000, endMs: range.endMs }]);
  store.invalidateHistoryCoverage(identity, { startMs: base + 120_000, endMs: range.endMs });
  assert.deepEqual(store.historyCoverage(identity, "long"), [{ startMs: base + 60_000, endMs: base + 119_999 }]);
});

test("history and coverage are released only after the last runtime and subscriber leave", () => {
  const store = new LiquidationStore();
  const releaseA = store.retain(identity);
  const releaseB = store.retain(identity);
  const unsubscribe = store.subscribe(identity, () => undefined);
  store.mergeHistory(identity, [rollup()], quality, {
    side: "long", range: { startMs: 0, endMs: 2_000_000_000_000 },
  });
  releaseA(); releaseA();
  releaseB();
  assert.equal(store.getSnapshot(identity).rollups.length, 1);
  unsubscribe();
  assert.equal(store.getSnapshot(identity).rollups.length, 0);
  assert.deepEqual(store.historyCoverage(identity, "long"), []);
  store.setConnectionStatus(identity, "disconnected");
  assert.equal(store.getSnapshot(identity).connectionStatus, "disabled");
});

test("global budgets evict inactive identities while preserving active subscribers", () => {
  const store = new LiquidationStore({ maxEntries: 2, maxTotalRecords: 2 });
  const eth = { ...identity, symbol: "ETHUSDT" };
  const sol = { ...identity, symbol: "SOLUSDT" };
  const release = store.retain(identity);
  store.mergeHistory(identity, [rollup()], quality);
  store.mergeHistory(eth, [rollup(eth)], quality);
  store.mergeHistory(sol, [rollup(sol)], quality);
  assert.equal(store.getSnapshot(identity).rollups.length, 1);
  assert.equal(store.getSnapshot(eth).rollups.length, 0);
  assert.equal(store.getSnapshot(sol).rollups.length, 1);
  release();
});

test("global active-record trimming invalidates coverage and publishes the reduced snapshot", () => {
  const store = new LiquidationStore({ maxTotalRecords: 1 });
  const eth = { ...identity, symbol: "ETHUSDT" };
  const releaseA = store.retain(identity);
  const releaseB = store.retain(eth);
  const range = { startMs: 1_699_999_980_000, endMs: 1_700_000_039_999 };
  store.mergeHistory(identity, [rollup()], quality, { side: "long", range });
  let notifications = 0;
  const unsubscribe = store.subscribe(identity, () => { notifications += 1; });
  store.mergeHistory(eth, [rollup(eth)], quality, { side: "long", range });
  assert.equal(store.getSnapshot(identity).rollups.length, 0);
  assert.deepEqual(store.historyCoverage(identity, "long"), []);
  assert.equal(notifications, 1);
  assert.equal(store.getSnapshot(eth).rollups.length, 1);
  unsubscribe(); releaseA(); releaseB();
});

test("batch event eviction preserves receipt-time ties and display order without repeated full scans", () => {
  for (const globalBudget of [false, true]) {
    const store = new LiquidationStore(globalBudget
      ? { maxTotalRecords: 8, maxLiveEventsPerIdentity: 256 }
      : { maxLiveEventsPerIdentity: 8 });
    const release = store.retain(identity);
    let receiptReads = 0;
    const records = Array.from({ length: 128 }, (_, index) => ({
      ...event({ fingerprint: `event-${index}`, tradeTimeMs: 1_700_000_000_000 + (128 - index) * 1000 }),
      get receivedAtMs() { receiptReads += 1; return 1_700_000_200_000; },
    }));
    store.applyEvents(identity, records, quality);
    assert.deepEqual(store.getSnapshot(identity).liveEvents.map((row) => row.fingerprint),
      Array.from({ length: 8 }, (_, index) => `event-${127 - index}`));
    assert.ok(receiptReads < records.length * 32, `batch eviction rescanned receipts ${receiptReads} times`);
    release();
  }
});

function historyPage(data: LiquidationRollup[], hasMore: boolean): LiquidationHistoryPayload {
  return {
    type: "liquidation.history", protocol: "liquidation.v1",
    key: {
      exchange: identity.exchange, market_type: identity.marketType, symbol: identity.symbol,
      channel: "liquidation", params: { period: "1m", position_side: "long" },
    },
    count: data.length, data, hasMore, quality,
    coverage: { earliestMs: data[0]?.bucketStartMs ?? null, latestMs: data.at(-1)?.bucketStartMs ?? null, allRowsFinal: true, observedOnly: true },
  };
}

test("production history loader advances past evicted pages without restarting a large claim", async () => {
  const store = new LiquidationStore({ maxRollupsPerIdentity: 2 });
  const base = 1_699_999_980_000;
  const requested = { startMs: base, endMs: base + 6 * 60_000 - 1 };
  const starts: number[] = [];
  await loadLiquidationHistoryPages({
    identity, side: "long", range: requested, signal: new AbortController().signal,
    isCurrent: () => true,
    fetchPage: async (_identity, query) => {
      starts.push(query.startMs);
      assert.ok(starts.length <= 3, "evicted pages must not re-enter the loading cursor");
      return historyPage([0, 1].map((offset) => rollup({
        bucketStartMs: query.startMs + offset * 60_000,
        bucketEndMs: query.startMs + (offset + 1) * 60_000,
      })), starts.length < 3);
    },
    onPage: (payload, range) => store.mergeHistory(identity, payload.data, payload.quality, { side: "long", range }),
  });
  assert.deepEqual(starts, [base, base + 120_000, base + 240_000]);
  assert.deepEqual(store.historyCoverage(identity, "long"), [{ startMs: base + 240_000, endMs: requested.endMs }]);
  assert.equal(store.getSnapshot(identity).rollups.length, 2);
});

test("a cancelled or superseded history response cannot repopulate a released identity", async () => {
  for (const abort of [false, true]) {
    const store = new LiquidationStore();
    const release = store.retain(identity);
    const controller = new AbortController();
    let current = true;
    let resolvePage: (value: LiquidationHistoryPayload) => void = () => { throw new Error("request not started"); };
    const loading = loadLiquidationHistoryPages({
      identity, side: "long", range: { startMs: 0, endMs: 2_000_000_000_000 }, signal: controller.signal,
      isCurrent: () => current,
      fetchPage: () => new Promise((resolve) => { resolvePage = resolve; }),
      onPage: (payload, range) => store.mergeHistory(identity, payload.data, payload.quality, { side: "long", range }),
    });
    release();
    if (abort) controller.abort();
    else current = false;
    resolvePage(historyPage([rollup()], false));
    await loading;
    assert.equal(store.getSnapshot(identity).rollups.length, 0);
    assert.deepEqual(store.historyCoverage(identity, "long"), []);
  }
});

test("history cursor failures stop before admitting misleading coverage", async () => {
  const store = new LiquidationStore();
  const base = 1_699_999_980_000;
  let calls = 0;
  await assert.rejects(loadLiquidationHistoryPages({
    identity, side: "long", range: { startMs: base, endMs: base + 179_999 }, signal: new AbortController().signal,
    isCurrent: () => true,
    fetchPage: async () => { calls += 1; return historyPage([rollup()], true); },
    onPage: (payload, range) => store.mergeHistory(identity, payload.data, payload.quality, { side: "long", range }),
  }), /did not advance/);
  assert.equal(calls, 2);
  assert.deepEqual(store.historyCoverage(identity, "long"), [{ startMs: base, endMs: base + 59_999 }]);
});
