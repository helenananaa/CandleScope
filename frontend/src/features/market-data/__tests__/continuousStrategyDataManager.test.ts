import assert from "node:assert/strict";
import test from "node:test";
import { StrategyDataManager } from "../manager/strategyDataManager.js";
import { StrategyRunStreamError } from "../../backtest/backtestRunStream.js";
import { resultKinds, type ContinuousApi, type ContinuousCreation, type ContinuousPacket, type ContinuousPage } from "../../backtest/continuous/continuousTypes.js";
import { ContinuousStrategyDataManager, type ContinuousObservation } from "../manager/continuousStrategyDataManager.js";

const creation: ContinuousCreation = { request_key: "chart/one", run_id: "one", revision: 1, phase: "COMMITTED", cutoff_ms: 60000, mode: "HISTORY_LIVE" };
function page(revision = 1, values = ["first"]): ContinuousPage {
  const identity = { id: "one", generation: 1, revision, checkpoint_revision: revision, sequence: revision, event_time_ms: revision * 60000, data_revision: "source" };
  return { identity, run: { ...identity, phase: "LIVE" }, summary: {}, stale: false,
    counts: { ...Object.fromEntries(resultKinds.map((kind) => [kind, 0])) as ContinuousPage["counts"], fills: values.length },
    items: values.map((value, index) => ({ kind: "fills", index, value })), more: false, next_cursor: null };
}
function pending(signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true }));
}
async function until(predicate: () => boolean) {
  const deadline = Date.now() + 3000;
  while (!predicate()) { if (Date.now() > deadline) assert.fail("Timed out waiting for view"); await new Promise((resolve) => setTimeout(resolve, 5)); }
}
function fixture(overrides: Partial<ContinuousApi> = {}): ContinuousApi {
  return { async status() { return { creation, run: page().run, identity: page().identity }; },
    async initial() { return { creation, initial_result_ready: true, result: page() }; },
    async stream(_id, _after, signal) { await pending(signal); },
    ...overrides } as ContinuousApi;
}

test("sibling consumers share one HTTP initial load and one resumable socket; release does not stop execution", async () => {
  let reads = 0, streams = 0, controls = 0, wireSignal: AbortSignal | undefined;
  const manager: StrategyDataManager = new StrategyDataManager(undefined, fixture({
    async initial() { reads += 1; return { creation, initial_result_ready: true, result: page() }; },
    async control() { controls += 1; throw new Error("No implicit controls"); },
    async stream(_id, after, signal) { streams += 1; wireSignal = signal; assert.deepEqual(after, page().identity); await pending(signal); },
  }));
  let first: ContinuousObservation | undefined, second: ContinuousObservation | undefined;
  const release = manager.continuous.observe("one", (value) => { first = value; });
  const sibling = manager.continuous.observe("one", (value) => { second = value; });
  await until(() => streams === 1); assert.equal(reads, 1);
  assert.equal(first!.result, second!.result); assert.equal(first!.initialReady, true);
  release(); assert.equal(wireSignal!.aborted, false);
  assert.deepEqual(manager.continuous.rows("one", "fills", first!.result!.identity), ["first"]);
  sibling(); sibling(); assert.equal(wireSignal!.aborted, true);
  await until(() => manager.diagnostics().operations === 0);
  assert.equal(controls, 0); assert.equal(manager.continuous.diagnostics().views.length, 0); manager.dispose();
});

test("disconnect during a partial delta resumes from last complete HTTP identity without exposing partial rows", async () => {
  let streams = 0; let observed: ContinuousObservation | undefined;
  const manager: StrategyDataManager = new StrategyDataManager(undefined, fixture({
    async stream(_id, after, signal, accept) {
      streams += 1; assert.deepEqual(after, page().identity);
      const update = page(2, ["changed", "second"]);
      const packet = { ...update, protocol: "continuous.v1", type: "update", begin: true, complete: false, more: true,
        after_checkpoint: 1, initial_result_ready: true, items: update.items.slice(0, 1) } as ContinuousPacket;
      accept(packet);
      assert.deepEqual(manager.continuous.rows("one", "fills", page().identity), ["first"]);
      if (streams === 1) throw new StrategyRunStreamError("CONTINUOUS_DISCONNECTED", "dropped");
      accept({ ...packet, items: update.items.slice(1), begin: false, complete: true, more: false });
      await pending(signal);
    },
  }));
  const release = manager.continuous.observe("one", (value) => { observed = value; });
  await until(() => observed?.result?.identity.revision === 2);
  assert.equal(streams, 2); assert.deepEqual(manager.continuous.rows("one", "fills", page(2).identity), ["changed", "second"]);
  release(); manager.dispose();
});

test("HTTP identity conflict discards partial pages and reloads before opening WebSocket", async () => {
  let initials = 0, pages = 0, streams = 0; let observed: ContinuousObservation | undefined;
  const manager = new StrategyDataManager(undefined, fixture({
    async initial() { initials += 1; const result = page(initials, initials === 1 ? ["old", "tail"] : ["new"]);
      if (initials === 1) { result.items = result.items.slice(0, 1); result.more = true; result.next_cursor = [1, "fills", 0]; }
      return { creation, initial_result_ready: true, result }; },
    async page() { pages += 1; throw new StrategyRunStreamError("CONTINUOUS_COMMIT_CONFLICT", "advanced"); },
    async stream(_id, after, signal) { streams += 1; assert.deepEqual(after, page(2).identity); await pending(signal); },
  }));
  const release = manager.continuous.observe("one", (value) => { observed = value; });
  await until(() => streams === 1);
  assert.equal(initials, 2); assert.equal(pages, 1); assert.equal(observed!.initialReady, true);
  assert.deepEqual(manager.continuous.rows("one", "fills", page(2).identity), ["new"]);
  release(); manager.dispose();
});

test("shared observer and view budgets reject excess consumers, and owner disposal aborts views without control", async () => {
  const manager = new StrategyDataManager(undefined, fixture());
  const releases = Array.from({ length: 32 }, () => manager.continuous.observe("one", () => undefined));
  assert.throws(() => manager.continuous.observe("one", () => undefined), { code: "RUN_CAPACITY_EXCEEDED" });
  for (const release of releases) release();
  const views = ["one", "two", "three", "four"].map((id) => manager.continuous.observe(id, () => undefined));
  assert.throws(() => manager.continuous.observe("five", () => undefined), { code: "RUN_CAPACITY_EXCEEDED" });
  manager.dispose(); for (const release of views) release();
  await until(() => manager.diagnostics().operations === 0);
  assert.equal(manager.continuous.diagnostics().observers, 0);
});

test("invalid stream is visible and preserves the last committed result for every observer", async () => {
  let streams = 0, observed: ContinuousObservation | undefined;
  const manager = new StrategyDataManager(undefined, fixture({ async stream() {
    streams += 1; throw new StrategyRunStreamError("CONTINUOUS_VIEW_INVALID", "invalid group");
  } }));
  const release = manager.continuous.observe("one", (value) => { observed = value; });
  await until(() => observed?.connection === "error");
  assert.equal(streams, 1); assert.equal(observed!.result!.identity.revision, 1);
  assert.deepEqual(manager.continuous.rows("one", "fills", observed!.result!.identity), ["first"]);
  let sibling: ContinuousObservation | undefined;
  const stop = manager.continuous.observe("one", (value) => { sibling = value; });
  assert.equal(sibling!.connection, "error"); assert.equal(streams, 1);
  release(); stop(); manager.dispose();
});

test("restored creation metadata is available for pause while the initial HTTP result is still waiting", async () => {
  let observed: ContinuousObservation | undefined, controls = 0;
  const manager = new StrategyDataManager(undefined, fixture({
    async initial(_id, signal) { await pending(signal); throw new Error("initial view cancelled"); },
    async control(key, body) { controls += 1; assert.equal(key, creation.request_key); assert.equal(body.action, "pause");
      return { creation: { ...creation, phase: "PAUSED", revision: 2 }, run: null }; },
  }));
  const release = manager.continuous.observe("one", (value) => { observed = value; });
  await until(() => observed?.creation !== null && observed?.creation !== undefined);
  assert.equal(observed!.result, null); assert.equal(observed!.initialReady, false);
  await manager.continuous.control(creation.request_key, { action: "pause", revision: observed!.creation!.revision, expected: page().identity });
  assert.equal(controls, 1); release(); await until(() => manager.diagnostics().operations === 0); manager.dispose();
});

test("connections that open then drop before a server event cannot reset the retry budget", async () => {
  let streams = 0, observed: ContinuousObservation | undefined;
  const delays: number[] = [];
  const manager = new ContinuousStrategyDataManager(fixture({ async stream(_id, _after, _signal, accept) {
    streams += 1; accept({ protocol: "continuous.v1", type: "connected" });
    throw new StrategyRunStreamError("CONTINUOUS_DISCONNECTED", "dropped before server response");
  } }), (_signal, action) => action(new AbortController().signal), async (delay) => { delays.push(delay); });
  const release = manager.observe("one", (value) => { observed = value; });
  await until(() => observed?.connection === "error");
  assert.equal(streams, 6); assert.deepEqual(delays, [250, 500, 1000, 2000, 4000]);
  assert.equal(observed!.result!.identity.revision, 1); release(); manager.dispose();
});
