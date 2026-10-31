import assert from "node:assert/strict";
import test from "node:test";
import { ReplayDataManager, type ReplaySequenceIdentity } from "../../replay/replayDataManager.js";
import { MarketDataManager } from "../manager/marketDataManager.js";
import { createReplayMarketDataManager } from "../../replay/replayDataContext.js";
import { epochSeconds } from "../../../test/testHelpers.js";

const identity: ReplaySequenceIdentity = { runId: "run-a", trackId: "btc-track", sessionId: "adapter-a",
  dataEpoch: "epoch-1", generation: 1, interval: "1m" };
const row = (time: number) => ({ time: epochSeconds(time), open: 10, high: 12, low: 9, close: 11, volume: 1 });

test("inert render candidates do not retain sequences; equal replay identities keep private paged windows", () => {
  const manager = new ReplayDataManager();
  for (let i = 0; i < 20; i++) manager.createSequence();
  assert.equal(manager.diagnostics().activeSequences, 0);
  const a = manager.createSequence(), b = manager.createSequence();
  const releaseA = a.retain(), releaseB = b.retain();
  a.bind(identity); b.bind(identity);
  a.store.replace([row(60), row(120)]); b.store.replace([row(600), row(660)]);
  assert.notEqual(a.store, b.store);
  a.store.applyRange([row(0)]);
  assert.deepEqual(b.store.snapshot().map(bar => bar.time), [600, 660]);
  releaseA(); releaseA(); assert.equal(manager.diagnostics().activeSequences, 1);
  assert.equal(b.store.barCount, 2);
  releaseB(); assert.equal(manager.diagnostics().activeSequences, 0);
});

test("run, track, version and period changes cancel ignored-abort work before it can publish", async () => {
  for (const change of [{ runId: "run-b" }, { trackId: "eth-track" }, { sessionId: "adapter-b" },
    { dataEpoch: "epoch-2" }, { generation: 2 }, { interval: "5m" }]) {
    const manager = new ReplayDataManager(), sequence = manager.createSequence();
    const release = sequence.retain(); sequence.bind(identity); sequence.store.replace([row(60)]);
    let complete!: (value: string) => void, signal!: AbortSignal;
    const pending = sequence.request(input => { signal = input; return new Promise(resolve => { complete = resolve; }); });
    const rejected = assert.rejects(pending, { name: "AbortError" });
    sequence.bind({ ...identity, ...change });
    await rejected; assert.equal(signal.aborted, true); assert.equal(sequence.store.barCount, 0);
    complete("obsolete");
    assert.equal(await sequence.request(async () => "current"), "current");
    release(); manager.dispose();
  }
});

test("one consumer's cancellation preserves siblings, including same-identity ABA and manager shutdown", async () => {
  const manager = new ReplayDataManager(), a = manager.createSequence(), b = manager.createSequence();
  const releaseA = a.retain(), releaseB = b.retain(); a.bind(identity); b.bind(identity);
  let finishA!: (n: number) => void, finishB!: (n: number) => void;
  const first = a.request(() => new Promise<number>(resolve => { finishA = resolve; }));
  const rejected = assert.rejects(first, { name: "AbortError" });
  const second = b.request(() => new Promise<number>(resolve => { finishB = resolve; }));
  releaseA(); await rejected;
  const nextA = a.retain(); a.bind(identity);
  finishA(1); finishB(2); assert.equal(await second, 2);
  assert.equal(await a.request(async () => 3), 3);
  const third = a.request(() => new Promise(() => {})), stopped = assert.rejects(third, { name: "AbortError" });
  manager.dispose(); await stopped;
  assert.equal(manager.diagnostics().activeSequences, 0);
  nextA(); releaseB(); assert.throws(() => a.retain(), /closed/);
});

test("replay namespace never reads or mutates the live cache and its root has no live IO fallback", () => {
  const forbidden = (): never => { throw new Error("Unexpected live IO"); };
  const manager = new MarketDataManager({ api: {
    getMultiStreamUrl: forbidden, fetchKlinesHistory: forbidden, fetchKlinesBefore: forbidden,
    fetchKlinesRange: forbidden, fetchLatestKlines: forbidden,
  }, streams: { subscribe: forbidden, closeAll() {}, diagnostics: () => ({}) } });
  const market = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
  const token = manager.cache.beginRead(market);
  manager.cache.admitResponse(token, { data: [row(600)], endpoint: "history" }); token.release();
  const a = manager.replay.createSequence(), b = manager.replay.createSequence();
  const releaseA = a.retain(), releaseB = b.retain();
  a.bind(identity); b.bind({ ...identity, runId: "run-b" });
  a.store.replace([row(60)]); b.store.replace([row(120)]);
  a.bind({ ...identity, dataEpoch: "rewind" });
  assert.deepEqual(manager.cache.read(market).rows.map(bar => bar.time), [600]);
  assert.deepEqual(b.store.snapshot().map(bar => bar.time), [120]);
  const replayRoot = createReplayMarketDataManager();
  assert.equal("subscribe" in replayRoot, false);
  assert.equal("fetchKlinesHistory" in replayRoot, false);
  replayRoot.closeAll();
  releaseA(); releaseB(); manager.closeAll();
});
