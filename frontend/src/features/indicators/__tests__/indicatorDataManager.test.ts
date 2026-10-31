import assert from "node:assert/strict";
import test from "node:test";
import { IndicatorDataManager } from "../indicatorDataManager.js";
import { IndicatorRequestBroker } from "../indicatorRequestBroker.js";
import { routeIndicatorComputeBatch } from "../frontendScriptBatch.js";
import { SharedMarketCache } from "../../market-data/manager/sharedMarketCache.js";
import { ForegroundPreloadGate } from "../../market-data/foregroundPreloadGate.js";
import { epochSeconds } from "../../../test/testHelpers.js";
import { parseIndicatorPayloadEnvelope } from "../indicatorContracts.js";
import type { IndicatorComputeBatchExecutor } from "../indicatorComputeController.js";
import type { IndicatorRangeRequest } from "../indicatorTypes.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const rows = [60, 120, 180].map(time => ({ time: epochSeconds(time), open: 10, high: 20, low: 5, close: 12, volume: 1, is_closed: true }));
const payload = parseIndicatorPayloadEnvelope({ ok: true, lines: [{ id: "ema", data: [{ time: 180, value: 12 }] }] });
const tick = () => new Promise<void>(resolve => setTimeout(resolve, 10));
function seeded() {
  const cache = new SharedMarketCache();
  for (const identity of [series, { ...series, priceAdjustment: "split" }]) {
    const token = cache.beginRead(identity); cache.admitResponse(token, { data: rows, endpoint: "history" }); token.release();
  }
  return cache;
}
const range = (clientId: string): IndicatorRangeRequest => ({ ...series, clientId, kind: "builtin", name: "EMA", params: { length: 20 }, start: 120, end: 180 });

test("a failed backend batch cannot poison a pending browser result, including a different input window", async t => {
  for (const sameWindow of [true, false]) {
    const gate = new ForegroundPreloadGate(0);
    const manager = new IndicatorDataManager({ cache: seeded(), gate, coalesceMs: 0,
      compute: options => routeIndicatorComputeBatch(options, async () => { throw new Error("backend offline"); },
        async () => { await tick(); return payload; }),
    });
    t.after(() => { manager.dispose(); gate.dispose(); });
    const published: string[] = [];
    await assert.rejects(manager.compute({ onResults: results => published.push(...results.map(item => item.clientId)), jobs: [
      { clientId: "js", jobKey: "js", request: { ...series, language: "frontend-js", script: "plot(close)", ohlcv: rows } },
      { clientId: "ema", jobKey: "ema", request: { ...series, mode: "builtin", name: "EMA", ohlcv: sameWindow ? rows : rows.slice(1) } },
    ] }), /backend offline/);
    assert.deepEqual(published, ["js"], "successful browser work must publish before a sibling transport failure is reported");
  }
});

test("two charts share a semantic range; cancelling one scope leaves the other alive", async t => {
  const calls: Array<{ requests: Omit<IndicatorRangeRequest, "signal">[]; signal?: AbortSignal }> = [];
  let finish!: () => void;
  const gate = new ForegroundPreloadGate(0);
  const manager = new IndicatorDataManager({ cache: seeded(), gate, coalesceMs: 0, range: async options => {
    calls.push(options); await new Promise<void>(resolve => { finish = resolve; });
    return { ok: true, results: options.requests.map(request => ({ clientId: request.clientId, payload })) };
  } });
  t.after(() => { manager.dispose(); gate.dispose(); });
  const a = new AbortController(), b = new AbortController();
  const first = manager.range({ ...range("chart-a"), requestScope: "a", requestGeneration: 9, signal: a.signal });
  const firstAborted = assert.rejects(first, { name: "AbortError" });
  const second = manager.range({ ...range("chart-b"), requestScope: "b", requestGeneration: 2, signal: b.signal });
  await tick(); assert.equal(calls.length, 1); assert.equal(calls[0]!.requests.length, 1);
  assert.notEqual(calls[0]!.requests[0]!.requestScope, "a");
  a.abort(); await firstAborted; assert.equal(calls[0]!.signal?.aborted, false);
  finish(); assert.equal(await second, payload); assert.equal(manager.diagnostics().range.joined, 1);
});

test("the last consumer aborts physical work and cannot resurrect a disposed request", async t => {
  let signal!: AbortSignal;
  let finish!: () => void;
  const broker = new IndicatorRequestBroker<string, string>({ coalesceMs: 0, send: async (_requests, input) => {
    signal = input; await new Promise<void>(resolve => { finish = resolve; }); return ["late"];
  } });
  t.after(() => broker.dispose());
  const controller = new AbortController();
  const pending = broker.request({ key: "same", group: "g", request: "r", current: () => true, signal: controller.signal });
  const rejected = assert.rejects(pending, { name: "AbortError" });
  await tick(); controller.abort(); await rejected; assert.equal(signal.aborted, true);
  finish(); await tick(); assert.equal(broker.diagnostics().consumers, 0);
});

test("definition, full identity, parameters and stored custom scripts do not alias", async t => {
  const sizes: number[] = [], customIds: Array<string | undefined> = [];
  const gate = new ForegroundPreloadGate(0);
  const manager = new IndicatorDataManager({ cache: seeded(), gate, coalesceMs: 0, range: async ({ requests }) => {
    sizes.push(requests.length); customIds.push(...requests.map(request => request.customId));
    return { ok: true, results: requests.map(request => ({ clientId: request.clientId, payload })) };
  } });
  t.after(() => { manager.dispose(); gate.dispose(); });
  await Promise.all([
    manager.range(range("a")), manager.range({ ...range("b"), name: "SMA" }),
    manager.range({ ...range("c"), params: { length: 30 } }),
    manager.range({ ...range("d"), seriesIdentity: { priceAdjustment: "split" } }),
    ...["stored-a", "stored-b"].map(customId => manager.range({ ...range(customId), kind: "script", customId, name: "custom" })),
  ]);
  assert.equal(sizes.reduce((a, b) => a + b, 0), 6); assert.equal(sizes.length, 2);
  assert.ok(customIds.includes("stored-a") && customIds.includes("stored-b"));
});

test("historical amendments and disconnects reject late hosted results", async t => {
  for (const change of ["amend", "disconnect"] as const) {
    const cache = seeded(), gate = new ForegroundPreloadGate(0);
    let finish!: () => void;
    const manager = new IndicatorDataManager({ cache, gate, coalesceMs: 0, range: async ({ requests }) => {
      await new Promise<void>(resolve => { finish = resolve; });
      return { ok: true, results: requests.map(request => ({ clientId: request.clientId, payload })) };
    } });
    t.after(() => { manager.dispose(); gate.dispose(); });
    const pending = manager.range(range("a")), rejected = assert.rejects(pending, { name: "AbortError" });
    await tick();
    if (change === "amend") cache.admitRealtime(series, { ...rows[0]!, close: 18 }, "bar.amended"); else cache.markDisconnected(series);
    finish(); await rejected;
  }
});

test("compute deduplicates exact inputs and preserves logical IDs, input origins and execution route", async t => {
  const calls: Parameters<IndicatorComputeBatchExecutor>[0][] = [];
  const gate = new ForegroundPreloadGate(0);
  const manager = new IndicatorDataManager({ cache: seeded(), gate, coalesceMs: 0, compute: async options => {
    calls.push(options);
    assert.ok(options.jobs.every(job => job.request.ohlcv === options.jobs[0]!.request.ohlcv));
    return { ok: true, results: options.jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload })) };
  } });
  t.after(() => { manager.dispose(); gate.dispose(); });
  const request = { ...series, mode: "script", language: "javascript", script: "plot(close)", ohlcv: rows };
  const [a, b, c] = await Promise.all([
    manager.compute({ jobs: [{ clientId: "a", jobKey: "a-key", request }] }),
    manager.compute({ jobs: [{ clientId: "b", jobKey: "b-key", request: structuredClone(request) }] }),
    manager.compute({ jobs: [{ clientId: "c", jobKey: "c-key", request: { ...request, ohlcv: rows.slice(1) } }] }),
  ]);
  assert.equal(calls.length, 2); assert.equal(calls[0]!.jobs[0]!.request.language, "javascript");
  assert.deepEqual([a, b, c].map(result => result.results[0]!.clientId), ["a", "b", "c"]);
  assert.equal(manager.diagnostics().compute.joined, 1);
});

test("bounded broker prioritizes queued foreground work and rejects overflow", async t => {
  const started: string[][] = [], done: Array<() => void> = [];
  const broker = new IndicatorRequestBroker<string, string>({ coalesceMs: 0, maxConcurrent: 1, maxPending: 3,
    send: async requests => { started.push(requests); await new Promise<void>(resolve => done.push(resolve)); return requests; } });
  t.after(() => broker.dispose());
  const input = (key: string, speculative = false) => ({ key, group: key, request: key, speculative, current: () => true });
  const warm = broker.request(input("warm", true)), front = broker.request(input("front")), third = broker.request(input("third", true));
  await assert.rejects(broker.request(input("overflow")), /budget/);
  await tick(); assert.deepEqual(started, [["front"]]); done.shift()!(); await front;
  await tick(); done.shift()!(); await warm; await tick(); done.shift()!(); await third;
  assert.equal(broker.diagnostics().pending, 0);
});

test("forming samples make progress during ticks, but a close fences the old preview", async t => {
  for (const closes of [false, true]) {
    const cache = seeded(), gate = new ForegroundPreloadGate(0);
    const forming = { ...rows[0]!, time: epochSeconds(240), is_closed: false };
    cache.admitRealtime(series, forming, "bar.created");
    let finish!: () => void;
    const manager = new IndicatorDataManager({ cache, gate, coalesceMs: 0, compute: async ({ jobs }) => {
      await new Promise<void>(resolve => { finish = resolve; });
      return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload })) };
    } });
    t.after(() => { manager.dispose(); gate.dispose(); });
    const result = manager.compute({ jobs: [{ clientId: "js", jobKey: "sample", request: {
      ...series, mode: "script", language: "frontend-js", script: "sample", ohlcv: [...rows, forming],
    } }] });
    const checked = closes ? assert.rejects(result, { name: "AbortError" }) : result;
    await tick(); cache.admitRealtime(series, { ...forming, close: 18, is_closed: closes }, closes ? "bar.closed" : "bar.updated");
    finish(); await checked;
  }
});

test("a cancelled entry cannot abort another entry in its batch, and callers cannot mutate owned input", async t => {
  let finish!: () => void, signal!: AbortSignal;
  const seen: Array<{ value: number }> = [];
  const broker = new IndicatorRequestBroker<{ value: number }, number>({ coalesceMs: 0, send: async (requests, input) => {
    signal = input; seen.push(...requests); await new Promise<void>(resolve => { finish = resolve; }); return requests.map(request => request.value);
  } });
  t.after(() => broker.dispose());
  const controller = new AbortController(), input = { value: 1 };
  const first = broker.request({ key: "a", group: "one-batch", request: input, current: () => true, signal: controller.signal });
  const rejected = assert.rejects(first, { name: "AbortError" });
  const second = broker.request({ key: "b", group: "one-batch", request: { value: 2 }, current: () => true });
  input.value = 999;
  await tick(); assert.deepEqual(seen, [{ value: 1 }, { value: 2 }]);
  controller.abort(); await rejected; assert.equal(signal.aborted, false);
  finish(); assert.equal(await second, 2);
});
