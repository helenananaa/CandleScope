import assert from "node:assert/strict";
import test from "node:test";
import { IndicatorDataManager } from "../indicatorDataManager.js";
import { IndicatorResultManager } from "../indicatorResultManager.js";
import { indicatorRuntimeAdapter } from "../indicatorRuntimeAdapter.js";
import { createIndicatorCacheInputSource } from "../indicatorInputBinding.js";
import { buildIndicatorOhlcvSignature } from "../indicatorComputeRuntime.js";
import { buildIndicatorCacheContext, resetIndicatorResultCache } from "../indicatorResultCacheStore.js";
import { SharedMarketCache } from "../../market-data/manager/sharedMarketCache.js";
import { registerSharedMarketCache } from "../../cache-gc/sharedMarketCacheOwner.js";
import { ForegroundPreloadGate } from "../../market-data/foregroundPreloadGate.js";
import { epochSeconds } from "../../../test/testHelpers.js";
import { parseIndicatorPayloadEnvelope } from "../indicatorContracts.js";
import { stringSignature } from "../indicatorPayloadRuntime.js";
import type { IndicatorComputeRequest, IndicatorDefinition, NormalizedIndicatorPayload } from "../indicatorTypes.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const rows = [60, 120, 180].map(time => ({ time: epochSeconds(time), open: 10, high: 20, low: 5, close: 12, volume: 1, is_closed: true }));
const request: IndicatorComputeRequest = { ...series, mode: "script", language: "frontend-js", script: "plot('x', bars.map(b => b.close))", params: {}, ohlcv: rows };
const payload = () => parseIndicatorPayloadEnvelope({ ok: true, lines: [{ name: "x", data: rows.map(row => ({ time: row.time, value: row.close })) }] });
const normalized = (): NormalizedIndicatorPayload => ({ lines: payload().lines, markers: [], fills: [], hlines: [], bgcolors: [], barcolors: [], signals: [] });
function seeded() {
  const cache = new SharedMarketCache();
  for (const symbol of ["BTCUSDT", "ETHUSDT"]) for (const interval of ["1m", "5m"]) {
    const token = cache.beginRead({ ...series, symbol, interval });
    cache.admitResponse(token, { data: rows, endpoint: "history" }); token.release();
  }
  return cache;
}

test("all four runtime adapters commit through one immutable result ingress, then notify readers", t => {
  resetIndicatorResultCache();
  const cache = seeded();
  t.after(registerSharedMarketCache(cache));
  const inputSource = createIndicatorCacheInputSource(cache);
  const results = new IndicatorResultManager(inputSource);
  const context = buildIndicatorCacheContext({ ...series, inputSource, projectionOwner: "chart-a",
    localInputKey: buildIndicatorOhlcvSignature(rows, { limit: rows.length }) });
  const definitions: IndicatorDefinition[] = [
    { id: "ema", engineName: "EMA", params: { period: 5 } },
    { id: "js", language: "frontend-js", script: request.script! },
    { id: "pine", language: "pine", script: "plot(close)" },
    { id: "python", language: "python", script: "plot(close)" },
  ];
  const events: string[] = [];
  const release = results.subscribe(commit => {
    const definition = definitions.find(item => item.id === commit.indicatorId)!;
    const held = results.read(definition, context);
    assert.equal(held.state, "ready");
    assert.equal(held.result?.contentVersion, commit.contentVersion, "notification must follow cache commit");
    events.push(commit.adapter.runtime);
  });
  for (const definition of definitions) {
    const output = normalized();
    assert.ok(results.snapshot(definition, context, output, [], {
      inputVersion: inputSource.captureProvided(series, rows)!, range: { start: 60, end: 180 },
    }));
    output.lines[0]!.data[0]!.value = 999;
    assert.equal(results.read(definition, context).result?.normalized.lines[0]!.data[0]!.value, 12);
    assert.equal(Object.isFrozen(results.read(definition, context).result?.normalized), true);
  }
  assert.deepEqual(events, ["builtin", "frontend-js", "pine", "python"]);
  assert.equal(indicatorRuntimeAdapter(definitions[1]!, context).sharing, "exact-input");
  assert.equal(indicatorRuntimeAdapter(definitions[2]!, context).sharing, "private-session");
  assert.equal(indicatorRuntimeAdapter(definitions[3]!, context).owner, "chart-a");
  assert.equal(results.read(definitions[2]!, { ...context, projectionOwner: "chart-b" }).state, "unavailable");
  release(); results.dispose();
  assert.equal(results.diagnostics().subscribers, 0);
});

test("input revisions and workspace replacement revoke every runtime's result; stale JS cannot republish", t => {
  resetIndicatorResultCache();
  const cache = seeded(), inputSource = createIndicatorCacheInputSource(cache);
  t.after(registerSharedMarketCache(cache));
  const results = new IndicatorResultManager(inputSource);
  const js = { id: "js", language: "frontend-js", script: request.script! };
  const context = buildIndicatorCacheContext({ ...series, inputSource, localInputKey: "exact-window" });
  const version = inputSource.captureProvided(series, rows)!;
  assert.ok(results.snapshot(js, context, normalized(), [], { inputVersion: version }));
  cache.admitRealtime(series, { ...rows[0]!, close: 18 }, "bar.amended");
  assert.equal(results.read(js, context).state, "unavailable");
  assert.equal(results.snapshot(js, context, normalized(), [], { inputVersion: version }), null);
  assert.equal(results.snapshot(js, { ...context, inputSource: createIndicatorCacheInputSource(seeded()) }, normalized()), null);
  assert.throws(() => results.snapshot({ id: "old", language: "pyne", script: "legacy" }, context, normalized()), /retired/);
  results.dispose();
  assert.equal(results.snapshot(js, context, normalized()), null);
});

test("JS output is reused across chart IDs and warm switches, while definition, origin and market stay isolated", async t => {
  const cache = seeded(), gate = new ForegroundPreloadGate(0);
  let executions = 0;
  const manager = new IndicatorDataManager({ cache, gate, coalesceMs: 0, compute: async ({ jobs }) => {
    executions += jobs.length;
    return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload: payload() })) };
  } });
  t.after(() => { manager.dispose(); gate.dispose(); });
  const run = (clientId: string, input = request, force = false) => manager.compute({ force, jobs: [{ clientId, jobKey: clientId, request: input }] });
  const first = await run("chart-a");
  const second = await run("chart-b");
  assert.equal(second.results[0]!.clientId, "chart-b");
  assert.equal(executions, 1);
  assert.throws(() => { first.results[0]!.payload.lines[0]!.data[0]!.value = 999; }, TypeError);
  assert.equal(second.results[0]!.payload.lines[0]!.data[0]!.value, 12);
  for (const symbol of ["BTCUSDT", "ETHUSDT"]) for (const interval of ["1m", "5m"]) {
    const input = { ...request, symbol, interval };
    await run("cold", input); const count: number = executions;
    await run("hot", structuredClone(input)); assert.equal(executions, count);
  }
  const before = executions;
  for (const input of [{ ...request, params: { period: 10 } }, { ...request, script: request.script + ";" },
    { ...request, ohlcv: rows.slice(1) }]) await run("different", input);
  assert.equal(executions, before + 3);
  await run("forced", request, true); assert.equal(executions, before + 4);
  cache.admitRealtime(series, { ...rows[0]!, close: 18 }, "bar.amended");
  const amended = [{ ...rows[0]!, close: 18 }, ...rows.slice(1)];
  await run("corrected", { ...request, ohlcv: amended }); assert.equal(executions, before + 5);
  assert.equal(manager.diagnostics().compute.consumers, 0);
  const hot = run("disposed-hot", { ...request, ohlcv: amended });
  manager.dispose();
  await assert.rejects(hot, { name: "AbortError" }, "a completed-cache hit cannot publish after workspace disposal");
});

test("bounded JS results never retain previews, errors, obsolete input or hosted session output", () => {
  const cache = seeded(), source = createIndicatorCacheInputSource(cache);
  const results = new IndicatorResultManager(source, { entries: 1, bytes: 100_000 });
  const first = results.captureCompute(request)!;
  results.publishCompute(first, payload()); assert.ok(results.reuseCompute(first));
  const other = results.captureCompute({ ...request, params: { period: 2 } })!;
  results.publishCompute(other, payload()); assert.equal(results.reuseCompute(first), null);
  assert.equal(results.diagnostics().completed, 1);
  assert.equal(results.captureCompute({ ...request, language: "pine" }), null);
  assert.equal(results.captureCompute({ ...request, ohlcv: rows.map(row => ({ ...row, is_closed: false })) }), null);
  results.publishCompute(first, { ...payload(), ok: false }); assert.equal(results.reuseCompute(first), null);
  cache.markDisconnected(series);
  results.publishCompute(first, payload()); assert.equal(results.reuseCompute(other), null);
  results.dispose(); assert.equal(results.diagnostics().bytes, 0);
});

test("a result task cannot commit after consumer generation or definition ownership changes", t => {
  resetIndicatorResultCache();
  const cache = seeded(); t.after(registerSharedMarketCache(cache));
  const source = createIndicatorCacheInputSource(cache), results = new IndicatorResultManager(source);
  const context = buildIndicatorCacheContext({ ...series, inputSource: source, localInputKey: "exact-input" });
  const definition = { id: "js", language: "frontend-js", script: request.script! };
  let generation = 1;
  const task = results.begin(definition, context, "generation:1", () => generation === 1);
  const metadata = { inputVersion: source.captureProvided(series, rows)! };
  generation = 2;
  assert.equal(results.snapshot(definition, context, normalized(), [], metadata, task), null);
  assert.equal(results.read(definition, context).state, "unavailable");
  generation = 1;
  assert.equal(results.snapshot({ ...definition, script: "changed" }, context, normalized(), [], metadata, task), null);
  assert.equal(task.isCurrent(), false, "a retired task must not revive when a textual generation is reused");
  const fresh = results.begin(definition, context, "generation:2", () => generation === 1);
  const commits: string[] = [];
  results.subscribe(event => commits.push(event.taskKey!));
  assert.ok(results.snapshot(definition, context, normalized(), [], metadata, fresh));
  assert.deepEqual(commits, ["generation:2"]);
  results.dispose(); assert.equal(task.isCurrent(), false);
});

test("same-length script hash collisions never reuse a projection or its result task", t => {
  resetIndicatorResultCache();
  const cache = seeded(); t.after(registerSharedMarketCache(cache));
  const source = createIndicatorCacheInputSource(cache), results = new IndicatorResultManager(source);
  const context = buildIndicatorCacheContext({ ...series, inputSource: source, localInputKey: "exact-input" });
  const a = { id: "js", language: "frontend-js", script: request.script! + " // Aa" };
  const b = { ...a, script: request.script! + " // BB" };
  assert.equal(stringSignature(a.script), stringSignature(b.script), "fixture must reproduce the old lossy equality");
  const task = results.begin(a, context, "a", () => true);
  const metadata = { inputVersion: source.captureProvided(series, rows)! };
  assert.ok(results.snapshot(a, context, normalized(), [], metadata, task));
  assert.equal(results.read(b, context).state, "unavailable");
  assert.equal(results.snapshot(b, context, normalized(), [], metadata, task), null);
});

test("one JS consumer can leave while the other commits; all consumers leaving cannot warm a late result", async t => {
  const gate = new ForegroundPreloadGate(0);
  let finish!: () => void;
  let signal!: AbortSignal | undefined;
  const manager = new IndicatorDataManager({ cache: seeded(), gate, coalesceMs: 0, compute: async options => {
    signal = options.signal;
    await new Promise<void>(resolve => { finish = resolve; });
    return { ok: true, results: options.jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload: payload() })) };
  } });
  t.after(() => { manager.dispose(); gate.dispose(); });
  const a = new AbortController(), b = new AbortController();
  const run = (clientId: string, signal: AbortSignal, input = request) => manager.compute({ signal, jobs: [{ clientId, jobKey: clientId, request: input }] });
  const first = run("a", a.signal), second = run("b", b.signal);
  const rejected = assert.rejects(first, { name: "AbortError" });
  await new Promise(resolve => setTimeout(resolve, 20));
  a.abort(); await rejected; assert.equal(signal?.aborted, false);
  finish(); await second; assert.equal(manager.results.diagnostics().completed, 1);
  const c = new AbortController();
  const late = run("c", c.signal, { ...request, params: { changed: true } });
  const cancelled = assert.rejects(late, { name: "AbortError" });
  await new Promise(resolve => setTimeout(resolve, 20));
  c.abort(); await cancelled; assert.equal(signal?.aborted, true);
  finish(); await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(manager.results.diagnostics().completed, 1);
});
