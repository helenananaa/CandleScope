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
    publishLink(windowId: string, payload: unknown): unknown;
    diagnostics(): { hasSnapshot: boolean };
  };
};

test("ordinary native windows attach link messages without bootstrapping layout authority", async () => {
  const originalWindow = globalThis.window;
  const hub = new WorkspaceBusHub(), listeners = new Set<(event: unknown) => void>(), received: unknown[] = [];
  let registrations = 0;
  hub.register("other-window", () => {});
  Object.defineProperty(globalThis, "window", { configurable: true, value: { candlescopeDesktop: {
    onWorkspaceBusEvent: (listener: (event: unknown) => void) => { listeners.add(listener); return () => listeners.delete(listener); },
    workspaceBusRegisterLinks: async () => {
      registrations++; hub.register("main-window", event => listeners.forEach(listener => listener(event)));
      return { ok: true, windowId: "main-window" };
    },
    workspaceBusConnect: async () => { throw new Error("Link-only registration must not own the layout snapshot"); },
  } } });
  const bus = new WorkspaceBusClient("main-window");
  try {
    const first = bus.attachLinks(), second = bus.attachLinks(); await Promise.all([first.ready, second.ready]);
    bus.subscribeLink(event => received.push(event));
    hub.publishLink("other-window", { workspaceId: "workspace-default", sourceWindowId: "other-window", sourceCellId: "cell-2",
      kind: "dateSeek", payload: { requestedTimeMs: 600_000 } });
    assert.equal(received.length, 1); assert.equal(registrations, 1);
    assert.equal(bus.current.ready, false); assert.equal(hub.diagnostics().hasSnapshot, false);
    first.release(); assert.equal(listeners.size, 1);
    second.release(); assert.equal(listeners.size, 0);
    const stale = bus.attachLinks(); await stale.ready; bus.dispose();
    const replacement = bus.attachLinks(); await replacement.ready; stale.release();
    assert.equal(listeners.size, 1); replacement.release(); assert.equal(listeners.size, 0);
  } finally {
    bus.dispose();
    if (originalWindow === undefined) Reflect.deleteProperty(globalThis, "window");
    else Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
  }
});

test("native ordered clock returns the desktop hub stamp rather than a renderer-local sequence", async () => {
  const originalWindow = globalThis.window;
  const hub = new WorkspaceBusHub(), remote: unknown[] = [];
  hub.register("main-window", () => {}); hub.register("other-window", event => remote.push(event));
  Object.defineProperty(globalThis, "window", { configurable: true, value: { candlescopeDesktop: {
    workspaceBusPublishLink: async (event: unknown) => hub.publishLink("main-window", event),
  } } });
  try {
    const bus = new WorkspaceBusClient("main-window");
    const result = await bus.publishOrderedLink({ workspaceId: "workspace-default", sourceCellId: "cell-1", kind: "studyCursor",
      payload: { requestId: "cursor-1", studyId: "hs_saved", revision: 3, cursorMs: 600_000 } });
    assert.equal(result.eventId, "link-1");
    assert.deepEqual(remote, [{ type: "link", event: result }]);
    const mode = await bus.publishOrderedLink({ workspaceId: "workspace-default", sourceCellId: "cell-1", kind: "studyMode",
      payload: { requestId: "mode-1", studyId: "hs_saved", revision: 4, cursorMs: 600_000, operation: "mode", active: false } });
    assert.equal(mode.eventId, "link-2");
    assert.deepEqual(remote.at(-1), { type: "link", event: mode });
  } finally {
    if (originalWindow === undefined) Reflect.deleteProperty(globalThis, "window");
    else Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
  }
});

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

test("configuration barriers observe an own commit without a snapshot echo and reject when the client closes", async () => {
  const originalWindow = globalThis.window, hub = new WorkspaceBusHub();
  hub.register("main-window", () => {});
  Object.defineProperty(globalThis, "window", { configurable: true, value: { candlescopeDesktop: {
    onWorkspaceBusEvent: () => () => {},
    workspaceBusConnect: async ({ snapshot }: { snapshot: unknown }) => hub.connect("main-window", snapshot),
    workspaceBusCommit: async (value: unknown) => hub.commit("main-window", value),
  } } });
  const bus = new WorkspaceBusClient("main-window");
  try {
    const record = createDefaultChartWorkspaceRecord(1), snapshot = { activeWorkspaceId: record.id, workspaces: [record] };
    await bus.connect(snapshot);
    let confirmed = false;
    const wait = bus.waitForWorkspaceRevision(record.id, record.document.revision + 1).then(() => { confirmed = true; });
    let policyConfirmed = false;
    const policy = bus.waitForWorkspaceRevision(record.id, record.document.revision, 5_000,
      document => document.linkGroups["group-primary"]?.peerPolicy.studyMode === true).then(() => { policyConfirmed = true; });
    await Promise.resolve(); assert.equal(confirmed, false);
    assert.equal(policyConfirmed, false);
    const edited = structuredClone(snapshot); edited.workspaces[0]!.document.revision++;
    edited.workspaces[0]!.document.linkGroups["group-primary"]!.peerPolicy.studyMode = true;
    await bus.commit(edited); await Promise.all([wait, policy]); assert.equal(confirmed, true); assert.equal(policyConfirmed, true);
    const closed = bus.waitForWorkspaceRevision(record.id, edited.workspaces[0]!.document.revision + 1);
    bus.dispose(); await assert.rejects(closed, /closed/);
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
    const existingSnapshot = bus.current.snapshot;
    for (const listener of events) listener({ type: "health", sequence: 0, writerWindowId: "window-2" });
    assert.equal(bus.current.snapshot, existingSnapshot);
    assert.equal(bus.current.writerWindowId, "window-2");
    assert.equal(bus.current.sequence, 0);
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
