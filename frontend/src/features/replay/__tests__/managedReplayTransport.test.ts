import assert from "node:assert/strict";
import test from "node:test";
import { ReplayDataManager } from "../replayDataManager.js";
import { managedReplayAdapterStreams, managedReplayRunApi } from "../managedReplayTransport.js";
import { ReplayV2ApiClient } from "../replayV2Api.js";
import type { ReplayStreamControllerOptions } from "../replayStreamController.js";
import { ReplayRuntimeLifecycle } from "../useReplayRuntime.js";
import { parseReplayCapabilities, parseReplaySessionResponse } from "../replayParser.js";
import { enabledCapabilities, replaySessionResponse } from "./fixtures.js";

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
