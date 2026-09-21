import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

import { createDefaultChartWorkspaceRecord } from "../chartWorkspaceLibrary.js";
import { WorkspaceBusClient, type WorkspaceBusState } from "../workspaceBus.js";

// Exercise the JavaScript desktop authority with the current TypeScript document factory.
const { WorkspaceBusHub } = createRequire(import.meta.url)("../../../../desktop/workspace-bus-hub.mjs") as {
  WorkspaceBusHub: new () => {
    register(windowId: string, send: (message: unknown) => void): void;
    connect(windowId: string, snapshot: unknown): WorkspaceBusState;
    commit(windowId: string, payload: unknown): WorkspaceBusState;
  };
};

test("current frontend workspace restores and commits through the real desktop hub", async () => {
  const originalWindow = globalThis.window;
  const hub = new WorkspaceBusHub();
  const events = new Set<(value: unknown) => void>();
  hub.register("main-window", (message: unknown) => events.forEach((listener) => listener(message)));
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { candlescopeDesktop: {
      onWorkspaceBusEvent(listener: (value: unknown) => void) {
        events.add(listener);
        return () => { events.delete(listener); };
      },
      workspaceBusConnect: async ({ snapshot }: { snapshot: unknown }) => hub.connect("main-window", snapshot),
      workspaceBusCommit: async (payload: unknown) => hub.commit("main-window", payload),
    } },
  });
  const bus = new WorkspaceBusClient("main-window");
  try {
    const record = createDefaultChartWorkspaceRecord(1);
    const snapshot = { activeWorkspaceId: record.id, workspaces: [record] };
    const connected = await bus.connect(snapshot);
    assert.equal(connected.ready, true);
    assert.deepEqual(connected.snapshot, snapshot);
    const edited = structuredClone(snapshot);
    edited.workspaces[0]!.document.revision += 1;
    edited.workspaces[0]!.name = "Restored workspace";
    const committed = await bus.commit(edited);
    assert.equal(committed.ok, true);
    assert.deepEqual(committed.snapshot, edited);
  } finally {
    bus.dispose();
    if (originalWindow === undefined) Reflect.deleteProperty(globalThis, "window");
    else Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
  }
});

test("rejected native restore surfaces its error instead of resolving an unready state", async () => {
  const originalWindow = globalThis.window;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { candlescopeDesktop: {
      onWorkspaceBusEvent: () => () => undefined,
      workspaceBusConnect: async () => ({
        ok: false, ready: false, sequence: -1, writerWindowId: "main-window",
        revisions: {}, snapshot: null, code: "WORKSPACE_BUS_CONNECT_REJECTED",
        message: "Workspace document revision is invalid",
      }),
    } },
  });
  const bus = new WorkspaceBusClient("main-window");
  try {
    const record = createDefaultChartWorkspaceRecord(1);
    await assert.rejects(bus.connect({ activeWorkspaceId: record.id, workspaces: [record] }),
      /Workspace document revision is invalid/);
    assert.equal(bus.current.ready, false);
  } finally {
    bus.dispose();
    if (originalWindow === undefined) Reflect.deleteProperty(globalThis, "window");
    else Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
  }
});

test("native WorkspaceBus forwards exact CAS authority and adopts conflict snapshots", async () => {
  const originalWindow = globalThis.window;
  const record = createDefaultChartWorkspaceRecord(1);
  const snapshot = { activeWorkspaceId: record.id, workspaces: [record] };
  const events = new Set<(value: unknown) => void>();
  const commits: unknown[] = [];
  let sequence = 0;
  const bridge = {
    onWorkspaceBusEvent(listener: (value: unknown) => void) {
      events.add(listener);
      return () => { events.delete(listener); };
    },
    workspaceBusConnect: async () => ({
      ok: true,
      ready: true,
      sequence,
      writerWindowId: "main-window",
      revisions: { [record.id]: 0 },
      snapshot,
    }),
    workspaceBusCommit: async (payload: unknown) => {
      commits.push(payload);
      sequence += 1;
      return {
        ok: true,
        ready: true,
        sequence,
        writerWindowId: "main-window",
        revisions: { [record.id]: 1 },
        snapshot,
      };
    },
  };
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { candlescopeDesktop: bridge },
  });
  try {
    const bus = new WorkspaceBusClient("main-window");
    const connected = await bus.connect(snapshot);
    assert.equal(connected.sequence, 0);
    await bus.commit(snapshot);
    assert.deepEqual(commits, [{
      expectedSequence: 0,
      expectedRevisions: { [record.id]: 0 },
      baseSnapshot: snapshot,
      snapshot,
    }]);
    bus.dispose();
  } finally {
    if (originalWindow === undefined) Reflect.deleteProperty(globalThis, "window");
    else Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
  }
});

test("native WorkspaceBus bootstraps before an early autosave commit", async () => {
  const originalWindow = globalThis.window;
  const record = createDefaultChartWorkspaceRecord(1);
  const snapshot = { activeWorkspaceId: record.id, workspaces: [record] };
  const calls: string[] = [];
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      candlescopeDesktop: {
        onWorkspaceBusEvent: () => () => undefined,
        workspaceBusConnect: async () => {
          calls.push("connect");
          return {
            ok: true,
            ready: true,
            sequence: 0,
            writerWindowId: "main-window",
            revisions: { [record.id]: 0 },
            snapshot,
          };
        },
        workspaceBusCommit: async () => {
          calls.push("commit");
          return {
            ok: true,
            ready: true,
            sequence: 1,
            writerWindowId: "main-window",
            revisions: { [record.id]: 0 },
            snapshot,
          };
        },
      },
    },
  });
  try {
    const bus = new WorkspaceBusClient("main-window");
    const committed = await bus.commit(snapshot);
    assert.equal(committed.ready, true);
    assert.deepEqual(calls, ["connect", "commit"]);
  } finally {
    if (originalWindow === undefined) Reflect.deleteProperty(globalThis, "window");
    else Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
  }
});

test("WorkspaceBus delivers remote link events without persisting them", async () => {
  const originalWindow = globalThis.window;
  const listeners = new Set<(value: unknown) => void>();
  const record = createDefaultChartWorkspaceRecord(1);
  const snapshot = { activeWorkspaceId: record.id, workspaces: [record] };
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      candlescopeDesktop: {
        onWorkspaceBusEvent(next: (value: unknown) => void) {
          listeners.add(next);
          return () => { listeners.delete(next); };
        },
        workspaceBusConnect: async () => ({
          ok: true,
          ready: true,
          sequence: 7,
          writerWindowId: "main-window",
          revisions: { [record.id]: 0 },
          snapshot,
        }),
      },
    },
  });
  try {
    const bus = new WorkspaceBusClient("window-2");
    await bus.connect(snapshot);
    const links: unknown[] = [];
    bus.subscribeLink((event) => links.push(event));
    for (const listener of listeners) listener({
      type: "link",
      event: {
        eventId: "link-1",
        workspaceId: record.id,
        sourceWindowId: "main-window",
        sourceCellId: "cell-1",
        kind: "crosshair",
        payload: { time: 123 },
      },
    });
    assert.equal(links.length, 1);
    assert.equal(bus.current.sequence, 7);
  } finally {
    if (originalWindow === undefined) Reflect.deleteProperty(globalThis, "window");
    else Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
  }
});
