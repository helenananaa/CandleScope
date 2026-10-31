import assert from "node:assert/strict";
import test from "node:test";
import { MarketWarmStreams } from "../manager/marketWarmStreams.js";
import { MarketHealthRecovery } from "../manager/marketHealthRecovery.js";
import type { MarketSeries } from "../marketDataTypes.js";

const series = (symbol: string): MarketSeries => ({ exchange: "binance", marketType: "spot", symbol, interval: "1m" });
const turn = () => new Promise<void>(resolve => setImmediate(resolve));

test("warm streams respect tier, capacity, shared leases and mandatory expiry", async () => {
  const closed: string[] = [], opened: string[] = [];
  const pool = new MarketWarmStreams(input => {
    opened.push(input.symbol);
    return { isOpen: () => true, readyState: () => 1, send: () => true, sendPing: () => true, updateIntervals() {}, close: () => { closed.push(input.symbol); } };
  }, 2, 40);
  const a = pool.acquire(series("ETHUSDT"), "hover"), other = pool.acquire(series("ETHUSDT"), "hover");
  a.release(); assert.equal(closed.length, 0);
  const b = pool.acquire(series("BTCUSDT"), "frequent"); b.retain(); b.release();
  const c = pool.acquire(series("SOLUSDT"), "watchlist"); c.retain(); c.release();
  assert.deepEqual(opened, ["ETHUSDT", "BTCUSDT"], "lower tier cannot evict likely next selection");
  pool.promote(series("ETHUSDT")); other.release();
  const d = pool.acquire(series("ADAUSDT"), "hover"); d.retain(); d.release();
  assert.deepEqual(closed, ["BTCUSDT"]);
  assert.equal(pool.diagnostics().series, 2);
  await new Promise(resolve => setTimeout(resolve, 70));
  assert.equal(pool.diagnostics().series, 0);
  assert.deepEqual(closed.sort(), ["ADAUSDT", "BTCUSDT", "ETHUSDT"]);
  pool.dispose();
});

test("verification coalesces bursts and bounds concurrency, queue and minute budget", async () => {
  const pending: Array<() => void> = [], signals: AbortSignal[] = [];
  let calls = 0;
  const queue = new MarketHealthRecovery(() => 500, async (_series, _limit, signal) => {
    calls += 1; signals.push(signal); await new Promise<void>(resolve => pending.push(resolve));
  });
  for (let i = 0; i < 30; i++) queue.request(series(`COIN${i}`));
  for (let i = 0; i < 30; i++) queue.request(series("COIN0"));
  assert.equal(calls, 2); assert.equal(queue.diagnostics().pending, 8);
  pending.splice(0).forEach(done => done()); await turn();
  assert.equal(calls, 4); assert.equal(queue.diagnostics().active, 2);
  queue.dispose(); assert.equal(signals.at(-1)!.aborted, true);
  pending.splice(0).forEach(done => done()); await turn();
  assert.equal(queue.diagnostics().active, 0); assert.equal(queue.diagnostics().pending, 0);
});
