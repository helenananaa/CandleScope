import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  DesktopShellStateStore,
  DesktopTopologyRevisionConflictError,
  compareAndSwapShellState,
  emptyShellState,
  normalizeShellState,
} from "./shell-state-store.mjs";

function stateAt(revision, windowIds = ["main-window"]) {
  return {
    schemaVersion: "candlescope.desktop-shell-state/1",
    workspaceId: "workspace-default",
    workspaceRevision: revision,
    activeWindowId: windowIds[0],
    windows: Object.fromEntries(windowIds.map((id) => [id, {
      id,
      boundsDip: { x: 0, y: 0, width: 1280, height: 800 },
    }])),
  };
}

test("topology CAS rejects a stale renderer revision", () => {
  const current = stateAt(7);
  assert.throws(
    () => compareAndSwapShellState(current, 6, stateAt(8)),
    (error) => error instanceof DesktopTopologyRevisionConflictError
      && error.expectedRevision === 6
      && error.actualRevision === 7,
  );
});

test("shell store writes an atomic restorable projection", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-shell-state-"));
  const filePath = path.join(root, "desktop-windows.json");
  const store = new DesktopShellStateStore(filePath);
  assert.deepEqual(await store.load(), emptyShellState());
  await store.compareAndSwap(-1, stateAt(3, ["main-window", "window-2"]));
  const reloaded = new DesktopShellStateStore(filePath);
  assert.deepEqual(await reloaded.load(), { ...stateAt(3, ["main-window", "window-2"]), shellRevision: 0 });
  assert.equal(JSON.parse(await readFile(filePath, "utf8")).workspaceRevision, 3);
});

test("legacy shell state starts with its old CAS token and advances independently", () => {
  const legacy = normalizeShellState(stateAt(50));
  assert.equal(legacy.shellRevision, 50);
  const next = compareAndSwapShellState(legacy, 50, { ...stateAt(0), workspaceId: "other" });
  assert.equal(next.shellRevision, 51);
  assert.equal(next.workspaceRevision, 0);
});

test("concurrent CAS accepts only one writer and keeps disk and memory consistent", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-shell-cas-"));
  const store = new DesktopShellStateStore(path.join(root, "state.json"));
  const results = await Promise.allSettled([
    store.compareAndSwap(-1, stateAt(1)),
    store.compareAndSwap(-1, stateAt(2)),
  ]);
  assert.equal(results[0].status, "fulfilled");
  assert.equal(results[1].status, "rejected");
  assert.equal(results[1].reason.code, "DESKTOP_TOPOLOGY_REVISION_CONFLICT");
  assert.deepEqual(JSON.parse(await readFile(store.filePath, "utf8")), store.snapshot());
  await store.compareAndSwap(0, stateAt(3));
  assert.equal(store.snapshot().shellRevision, 1);
  assert.deepEqual(await readdir(root), ["state.json"]);
});

test("a failed write keeps the version reusable and does not poison the write queue", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-shell-failure-"));
  const store = new DesktopShellStateStore(root);
  await assert.rejects(store.compareAndSwap(-1, stateAt(1)));
  assert.deepEqual(store.snapshot(), emptyShellState());
  store.filePath = path.join(root, "recovered.json");
  assert.equal((await store.compareAndSwap(-1, stateAt(2))).shellRevision, 0);
});

test("normalization caps untrusted persisted topology at four windows", () => {
  const oversized = stateAt(1, ["w1", "w2", "w3", "w4", "w5"]);
  const committed = compareAndSwapShellState(emptyShellState(), -1, oversized);
  assert.deepEqual(Object.keys(committed.windows), ["w1", "w2", "w3", "w4"]);
});
