import assert from "node:assert/strict";
import test from "node:test";
import { ReplayDataManager } from "../replayDataManager.js";
import { managedReplayAdapterStreams, managedReplayRunApi } from "../managedReplayTransport.js";
import { ReplayV2ApiClient } from "../replayV2Api.js";
import type { ReplayStreamControllerOptions } from "../replayStreamController.js";
import { ReplayRuntimeLifecycle } from "../useReplayRuntime.js";
import { parseReplayCapabilities, parseReplaySessionResponse } from "../replayParser.js";
import { enabledCapabilities, replaySessionResponse } from "./fixtures.js";
import { ReplayHistoryProvider } from "../replayHistoryProvider.js";
import { TrainingHubLifecycle } from "../useTrainingHub.js";

test("operation release fences parsed HTTP completion after headers, without canceling another run", async () => {
  const manager = new ReplayDataManager();
  const a = manager.createOperations({ runId: "run-a", purpose: "run-entry" });
  const b = manager.createOperations({ runId: "run-b", purpose: "run-entry" });
  assert.equal(manager.diagnostics().activeOperations, 0);
  const releaseA = a.retain(), releaseB = b.retain();
  let finishBody!: (text: string) => void;
  let requestSignal: AbortSignal | null | undefined;
  const api = new ReplayV2ApiClient({ fetcher: async (_input, init) => {
    requestSignal = init?.signal;
    const response = new Response();
    response.text = () => new Promise(resolve => { finishBody = resolve; });
    return response;
  } });
  const pending = managedReplayRunApi(a, api).prepareIndex("run-a");
  await Promise.resolve();
  assert.equal(typeof finishBody, "function");
  assert.equal(manager.diagnostics().requests, 1, "body decoding stays inside manager ownership");
  const rejected = assert.rejects(pending, { name: "AbortError" });
  releaseA(); await rejected;
  assert.equal(requestSignal?.aborted, true);
  const reacquired = a.retain();
  finishBody(JSON.stringify({ protocol: "replay.v3", run_id: "run-a", status: "READY" }));
  assert.equal(await b.request(async () => "independent"), "independent");
  assert.equal(manager.diagnostics().requests, 0);
  reacquired(); releaseB(); manager.dispose();
});

test("adapter stream stop/reopen fences all old callbacks and heartbeat, including synchronous stop events", () => {
  const manager = new ReplayDataManager();
  const lease = manager.createOperations({ runId: "run-a", sessionId: "adapter", purpose: "adapter" });
  const release = lease.retain();
  const frames: ReplayStreamControllerOptions[] = [];
  let generations = 0, stops = 0, resyncs = 0;
  const factory = managedReplayAdapterStreams(lease, options => {
    frames.push(options);
    return { start() { options.onGeneration?.({ generation: 1, reason: "initial", resetAuthoritativeState: true }); },
      stop() { stops++; options.onGeneration?.({ generation: 9, reason: "initial", resetAuthoritativeState: true }); },
      requestResync() { resyncs++; } };
  });
  const stream = factory({ sessionId: "adapter", shouldHeartbeat: () => true, onGeneration: () => { generations++; } });
  stream.start(); stream.start();
  assert.equal(frames.length, 1); assert.equal(generations, 1);
  stream.requestResync(); assert.equal(resyncs, 1);
  stream.stop(); stream.start();
  frames[0]!.onGeneration?.({ generation: 12, reason: "initial", resetAuthoritativeState: true });
  assert.equal(generations, 2); assert.equal(frames[0]!.shouldHeartbeat?.(), false);
  assert.equal(frames[1]!.shouldHeartbeat?.(), true);
  assert.equal(manager.diagnostics().streams, 1);
  manager.dispose();
  frames[1]!.onGeneration?.({ generation: 13, reason: "initial", resetAuthoritativeState: true });
  stream.requestResync(); stream.stop(); release();
  assert.equal(generations, 2); assert.equal(stops, 2); assert.equal(resyncs, 1);
  assert.equal(manager.diagnostics().activeOperations, 0);
});

test("resource failure and external request abort preserve sibling ownership", async () => {
  const manager = new ReplayDataManager();
  const lease = manager.createOperations({ runId: "run", purpose: "viewer" });
  const release = lease.retain();
  const abort = new AbortController();
  const pending = lease.request(() => new Promise(() => {}), abort.signal);
  const rejected = assert.rejects(pending, { name: "AbortError" });
  abort.abort(); await rejected;
  const resource = lease.openResource(current => current, () => { throw new Error("stop failed"); });
  const survivor = lease.openResource(current => current, () => {});
  resource.release(); assert.equal(resource.value(), false); assert.equal(survivor.value(), true);
  assert.equal(await lease.request(async () => 4), 4);
  assert.equal(lease.diagnostics().cleanupErrors, 1);
  release(); assert.equal(survivor.value(), false);
});

test("canonical lifecycle startup, restart and disposal register one adapter operation and stream", async () => {
  const manager = new ReplayDataManager();
  let starts = 0, stops = 0;
  const lifecycle = new ReplayRuntimeLifecycle({
    entry: { kind: "adapter", sessionId: "session-0001" }, runId: "run-a", dataManager: manager,
    controllerMode: "observe",
    api: { capabilities: async () => parseReplayCapabilities(enabledCapabilities()),
      getSession: async () => parseReplaySessionResponse(replaySessionResponse()) },
    streamFactory: () => ({ start() { starts++; }, stop() { stops++; }, requestResync() {} }),
  });
  assert.equal(manager.diagnostics().activeOperations, 0);
  lifecycle.start(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(manager.diagnostics().activeOperations, 1);
  assert.equal(manager.diagnostics().operations[0]!.identity?.runId, "run-a");
  assert.equal(manager.diagnostics().operations[0]!.totalRequests, 2);
  assert.equal(manager.diagnostics().streams, 1);
  lifecycle.restart(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(starts, 2); assert.equal(stops, 1);
  assert.equal(manager.diagnostics().streams, 1);
  lifecycle.dispose(); lifecycle.dispose();
  assert.equal(stops, 2); assert.equal(manager.diagnostics().activeOperations, 0);
});

test("Hub is inert until list/preparation demand and shutdown fences ignored-abort capability completion", async () => {
  const manager = new ReplayDataManager();
  let finish!: (value: ReturnType<typeof parseReplayCapabilities>) => void;
  let signal: AbortSignal | undefined;
  const hub = new TrainingHubLifecycle({ dataManager: manager, draftStorage: null, api: {
    capabilities: s => { signal = s; return new Promise(resolve => { finish = resolve; }); },
    catalog: async () => { throw new Error("canceled preparation must not load catalog"); },
    listRuns: async () => { throw new Error("list was not requested"); },
    createRun: async () => { throw new Error("create was not requested"); },
  } });
  assert.equal(manager.diagnostics().activeOperations, 0);
  const pending = hub.openCreate();
  assert.equal(manager.diagnostics().activeOperations, 1);
  assert.equal(manager.diagnostics().requests, 1);
  hub.dispose(); await pending;
  finish(parseReplayCapabilities(enabledCapabilities()));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(signal?.aborted, true);
  assert.equal(hub.getSnapshot().phase, "STOPPED");
  assert.equal(hub.getSnapshot().catalog, null);
  assert.equal(manager.diagnostics().activeOperations, 0);
});

test("managed history keeps physical read sharing while releases cancel only their own consumer", async () => {
  const manager = new ReplayDataManager();
  const a = manager.createOperations({ runId: "run", purpose: "history", scope: "a" });
  const b = manager.createOperations({ runId: "run", purpose: "history", scope: "b" });
  const releaseA = a.retain(), releaseB = b.retain();
  let reads = 0, physicalSignal: AbortSignal | null | undefined;
  const fetcher: typeof fetch = (_input, init) => {
    reads++; physicalSignal = init?.signal;
    return new Promise(() => {});
  };
  const options = { sessionId: "adapter", trackId: "track", fetcher,
    identity: { exchange: "binance", market_type: "spot", symbol: "BTCUSDT", source_kind: "BAR" as const,
      base_interval: "1m", display_interval: "1m" } };
  const first = new ReplayHistoryProvider({ ...options, request: a.request.bind(a) });
  const second = new ReplayHistoryProvider({ ...options, request: b.request.bind(b) });
  const request = { dataEpoch: `sha256:${"a".repeat(64)}` as const, beforeMs: 120_000, revealedBoundaryMs: 119_999 };
  const pendingA = first.loadBefore(request), pendingB = second.loadBefore(request);
  const canceledA = assert.rejects(pendingA, { name: "AbortError" });
  const canceledB = assert.rejects(pendingB, { name: "AbortError" });
  assert.equal(reads, 1);
  releaseA(); await canceledA;
  assert.equal(physicalSignal?.aborted, false);
  assert.equal(manager.diagnostics().requests, 1);
  releaseB(); await canceledB;
  assert.equal(physicalSignal?.aborted, true);
  first.cancel(); second.cancel();
  assert.equal(manager.diagnostics().activeOperations, 0);
});

test("export navigation remains browser-owned after the transient chart lease is released", () => {
  const manager = new ReplayDataManager();
  const lease = manager.createOperations({ runId: "run", purpose: "rail" });
  const release = lease.retain();
  const client = new ReplayV2ApiClient({ fetcher: async () => {
    throw new Error("An export must stream through the browser download, never a renderer Blob");
  } });
  const api = managedReplayRunApi(lease, client);
  const url = api.portfolioExportUrl("run");
  assert.match(url, /\/runs\/run\/portfolio-equity\/export$/);
  release();
  assert.equal(api.portfolioExportUrl("run"), url);
  assert.equal(manager.diagnostics().activeOperations, 0);
  assert.equal(manager.diagnostics().requests, 0);
});

test("releasing history during retry delay drains the complete operation without another read", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const manager = new ReplayDataManager();
  const lease = manager.createOperations({ runId: "run", purpose: "history" });
  const release = lease.retain();
  let reads = 0;
  const provider = new ReplayHistoryProvider({ sessionId: "adapter", trackId: "track",
    identity: { exchange: "binance", market_type: "spot", symbol: "BTCUSDT", source_kind: "BAR",
      base_interval: "1m", display_interval: "1m" },
    request: lease.request.bind(lease), pendingRetryDelaysMs: [1000],
    fetcher: async () => { reads++; return Response.json({ error: { code: "HISTORY_DOWNLOAD_PENDING" } }, { status: 503 }); },
  });
  const pending = provider.loadBefore({ dataEpoch: `sha256:${"a".repeat(64)}`, beforeMs: 120_000, revealedBoundaryMs: 119_999 });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(reads, 1);
  assert.equal(manager.diagnostics().requests, 1, "retry backoff retains the operation");
  const canceled = assert.rejects(pending, { name: "AbortError" });
  release(); await canceled;
  t.mock.timers.tick(2000);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(reads, 1);
  assert.equal(manager.diagnostics().requests, 0);
  provider.cancel();
});
