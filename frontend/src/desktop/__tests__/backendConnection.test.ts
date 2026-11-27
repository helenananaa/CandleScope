import assert from "node:assert/strict";
import test from "node:test";

import {
  BACKEND_RUNNING,
  createBackendConnectionStore,
  isBackendLive,
  parseBackendStatus,
  watchBackendRestored,
  type BackendStatusBridge,
} from "../backendConnection.js";

const running = (generation: number) => ({
  phase: "running", generation, attempt: 0, maxAttempts: 3, retryAt: null, error: null, exit: null,
});

function fakeBridge(initial: unknown, read: () => Promise<unknown> = () => new Promise(() => undefined)) {
  let listener: ((status: unknown) => void) | null = null;
  const restarts: number[] = [];
  const bridge: BackendStatusBridge = {
    backendStatus: initial,
    getBackendStatus: read,
    onBackendStatus(next) {
      listener = next;
      return () => { listener = null; };
    },
    async restartBackend() {
      restarts.push(Date.now());
      return running(2);
    },
  };
  return { bridge, emit: (status: unknown) => listener?.(status), attached: () => listener !== null, restarts };
}

test("the web build has no supervised backend and always reads as live", () => {
  const store = createBackendConnectionStore(undefined);
  assert.equal(store.supervised, false);
  assert.equal(store.getSnapshot(), BACKEND_RUNNING);
  assert.equal(isBackendLive(store.getSnapshot()), true);
});

test("only known phases are accepted from the host", () => {
  assert.equal(parseBackendStatus(null), null);
  assert.equal(parseBackendStatus({ phase: "crashed" }), null);
  assert.deepEqual(parseBackendStatus({ phase: "restarting", generation: 1, attempt: -1, maxAttempts: 3, retryAt: 5 }), {
    phase: "restarting", generation: 1, attempt: 0, maxAttempts: 3, retryAt: null, error: null,
  });
});

test("the desktop store starts from the host snapshot and follows its events", () => {
  const { bridge, emit, attached } = fakeBridge(running(1));
  const store = createBackendConnectionStore(bridge);
  assert.equal(store.getSnapshot().generation, 1);
  const phases: string[] = [];
  const unsubscribe = store.subscribe(() => phases.push(store.getSnapshot().phase));
  assert.equal(attached(), true);
  emit({ phase: "restarting", generation: 1, attempt: 1, maxAttempts: 3 });
  assert.equal(isBackendLive(store.getSnapshot()), false);
  emit({ phase: "restarting", generation: 1, attempt: 1, maxAttempts: 3 });
  emit(running(2));
  emit({ phase: "failed", generation: 1 });
  assert.deepEqual(phases, ["restarting", "running"], "repeats and older generations are ignored");
  unsubscribe();
  assert.equal(attached(), false);
});

test("a slow status read never overwrites a newer event", async () => {
  let resolveRead: (value: unknown) => void = () => undefined;
  const { bridge, emit } = fakeBridge(running(1), () => new Promise((resolve) => { resolveRead = resolve; }));
  const store = createBackendConnectionStore(bridge);
  store.subscribe(() => undefined);
  emit({ phase: "restarting", generation: 1, attempt: 1, maxAttempts: 3 });
  resolveRead(running(1));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(store.getSnapshot().phase, "restarting");
});

test("a status read catches a change from before the page subscribed", async () => {
  const { bridge } = fakeBridge(running(1), async () => ({ phase: "failed", generation: 1, error: "port in use" }));
  const store = createBackendConnectionStore(bridge);
  store.subscribe(() => undefined);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(store.getSnapshot().phase, "failed");
  assert.equal(store.getSnapshot().error, "port in use");
});

test("restored callbacks fire once per outage, not on first load", async () => {
  const { bridge, emit, restarts } = fakeBridge(running(1));
  const store = createBackendConnectionStore(bridge);
  let restored = 0;
  const stop = watchBackendRestored(store, () => { restored += 1; });
  emit(running(1));
  assert.equal(restored, 0);
  emit({ phase: "restarting", generation: 1, attempt: 1, maxAttempts: 3 });
  emit({ phase: "restarting", generation: 1, attempt: 2, maxAttempts: 3 });
  emit({ phase: "failed", generation: 1, attempt: 3, maxAttempts: 3 });
  assert.equal(restored, 0);
  await store.restart();
  assert.equal(restarts.length, 1);
  assert.equal(store.getSnapshot().generation, 2);
  assert.equal(restored, 1);
  emit(running(2));
  assert.equal(restored, 1);
  stop();
});
