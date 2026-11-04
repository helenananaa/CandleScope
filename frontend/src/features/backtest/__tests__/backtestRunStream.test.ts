import assert from "node:assert/strict";
import test from "node:test";
import { readStrategyRunStream, StrategyRunStreamError, type StrategyRunUpdate } from "../backtestRunStream.js";

const run = { run_id: "one", generation: 1, strategy_revision_id: "revision", dataset_id: "dataset",
  data_epoch: "epoch", snapshot_hash: "snapshot", config_hash: "config", engine_version: "引擎",
  fidelity_mode: "BAR_APPROX", source_event_kind: "BAR", state: "RUNNING" };
const status = { schema: "candlescope.strategy-run-events/1", type: "status", terminal: false, run, progress: null };
const complete = { ...status, type: "completed", terminal: true, run: { ...run, state: "COMPLETED" },
  result: { report_hash: "report", summary: { schemaVersion: "backtest.report-summary/1", runId: "one", reportHash: "report" } } };

function body(text: string, bytes = 7): ReadableStream<Uint8Array> {
  const encoded = new TextEncoder().encode(text);
  return new ReadableStream({ start(controller) {
    for (let offset = 0; offset < encoded.length; offset += bytes) controller.enqueue(encoded.slice(offset, offset + bytes));
    controller.close();
  } });
}
const wire = (...frames: unknown[]) => frames.map((frame) => JSON.stringify(frame)).join("\n");

test("finite stream preserves split UTF-8, progress identity and the explicit completed result", async () => {
  const updates: StrategyRunUpdate[] = [];
  const progress = { ...status, type: "progress", progress: { sequence: 13, generation: 1, state_hash: "checkpoint", created_at_ms: 3 } };
  const result = await readStrategyRunStream({ runId: "one", body: body(wire(status,
    { schema: status.schema, type: "heartbeat", terminal: false }, progress, complete), 1), onUpdate: (event) => updates.push(event) });
  assert.equal(result.state, "COMPLETED");
  assert.deepEqual(updates.map((event) => event.type), ["status", "progress", "completed"]);
  assert.equal(updates[1]!.progress!.sequence, 13);
  assert.equal(updates[2]!.result!.report_hash, "report");
});

test("failed and interrupted runs expose the server reason and never produce a completed update", async () => {
  for (const frame of [
    { ...status, type: "failed", terminal: true, run: { ...run, state: "FAILED" }, error: { code: "PROVIDER_TIMEOUT", message: "策略执行超时" } },
    { schema: status.schema, type: "error", terminal: true, run_id: "one", error: { code: "RUN_IDENTITY_CHANGED", message: "reconnect" } },
  ]) {
    const updates: StrategyRunUpdate[] = [];
    await assert.rejects(readStrategyRunStream({ runId: "one", body: body(wire(status, frame)), onUpdate: (event) => updates.push(event) }),
      (error: unknown) => error instanceof StrategyRunStreamError && error.code === frame.error.code && error.message === frame.error.message);
    assert.deepEqual(updates.map((event) => event.type), ["status"]);
  }
  await assert.rejects(readStrategyRunStream({ runId: "one", body: body(wire(status)) }), { code: "STRATEGY_STREAM_INCOMPLETE" });
});

test("mismatched run identity, generation, result, state and future checkpoint are rejected", async () => {
  for (const bad of [
    { ...complete, run: { ...complete.run, run_id: "sibling" } },
    { ...complete, run: { ...complete.run, generation: 2 } },
    { ...complete, run: { ...complete.run, snapshot_hash: "changed" } },
    { ...complete, result: { ...complete.result, summary: { ...complete.result.summary, runId: "sibling" } } },
    { ...complete, result: { ...complete.result, report_hash: "changed" } },
    { ...status, run: { ...run, state: "COMPLETED" } },
    { ...status, run: { ...run, state: "UNKNOWN" } },
    { ...status, type: "progress", progress: { sequence: 9, generation: 2, state_hash: "future", created_at_ms: 3 } },
    { ...complete, terminal: false },
  ]) {
    await assert.rejects(readStrategyRunStream({ runId: "one", body: body(wire(status, bad)) }), { code: "STRATEGY_STREAM_INVALID" });
  }
});

test("malformed and oversized frames fail closed, including newline-terminated whitespace", async () => {
  for (const text of ["{broken}\n", " ".repeat(101) + "\n", "x".repeat(101)]) {
    await assert.rejects(readStrategyRunStream({ runId: "one", body: body(text), maxFrameCharacters: 100 }), { code: "STRATEGY_STREAM_INVALID" });
  }
});

test("abort releases a stalled reader without waiting for a backend event", async () => {
  let cancelled = 0;
  const controller = new AbortController();
  const stream = new ReadableStream<Uint8Array>({ cancel() { cancelled += 1; } });
  const pending = readStrategyRunStream({ runId: "one", body: stream, signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(cancelled, 1);
  assert.equal(stream.locked, false);
});
