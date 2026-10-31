import assert from "node:assert/strict";
import test from "node:test";

import type { IndicatorStreamSocket } from "../indicatorStreamConnection.js";
import type { IndicatorStreamSubscription } from "../indicatorStreamConnection.js";
import {
  SharedIndicatorStreamCoordinator,
  indicatorWireClientId,
} from "../sharedIndicatorStreamCoordinator.js";
import type { IndicatorSubscribeMessage, IndicatorWsMessage } from "../indicatorTypes.js";
import type { SharedIndicatorLogicalOptions } from "../sharedIndicatorStreamCoordinator.js";

class FakeSocket implements IndicatorStreamSocket {
  readonly OPEN = 1;
  readyState = 0;
  onopen: ((event: Event) => unknown) | null = null;
  onmessage: ((event: MessageEvent<unknown>) => unknown) | null = null;
  onerror: ((event: Event) => unknown) | null = null;
  onclose: ((event: CloseEvent) => unknown) | null = null;
  closed = false;
  sent: string[] = [];

  close(): void { this.closed = true; this.readyState = 3; }
  send(payload: string): void { this.sent.push(payload); }
  open(): void { this.readyState = this.OPEN; this.onopen?.(new Event("open")); }
  message(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<unknown>);
  }
  serverClose(code = 1006): void { this.readyState = 3; this.onclose?.({ code } as CloseEvent); }
}

function subscription(clientId: string, signature = `${clientId}:v1`) {
  return {
    clientId,
    signature,
    message: {
      action: "subscribe" as const,
      clientId,
      kind: "builtin" as const,
      exchange: "binance",
      marketType: "futures",
      symbol: "BTCUSDT",
      interval: "1m",
      displayName: clientId,
      name: clientId,
      params: {},
      historyLimit: 100,
    },
  };
}

function sent(socket: FakeSocket): Array<Record<string, unknown>> {
  return socket.sent.map((payload) => JSON.parse(payload) as Record<string, unknown>);
}

function equivalent(clientId: string): IndicatorStreamSubscription {
  const sub = subscription(clientId);
  return { ...sub, message: { ...sub.message, name: "EMA", displayName: "EMA", params: { period: 20 } } };
}

test("equal hosted demands use one subscription and retain each consumer signature", () => {
  const sockets: FakeSocket[] = [];
  const received: Array<{ id: string | undefined; signature: string | undefined }> = [];
  const coordinator = new SharedIndicatorStreamCoordinator({ url: "ws://example", maxSubscriptions: 2,
    socketFactory: () => { const socket = new FakeSocket(); sockets.push(socket); return socket; } });
  try {
    for (const id of ["left", "right"]) {
      const logical = coordinator.createLogicalConnection({ workspaceId: "w", windowId: "window", cellId: id }, {
        onMessage: (message, context) => received.push({ id: message.clientId, signature: context.subscriptionSignature }),
      });
      logical.setSubscriptions([equivalent(id)]); logical.start();
    }
    assert.equal(coordinator.diagnostics().subscriptions, 1);
    sockets[0]!.open();
    const [wire] = sent(sockets[0]!);
    sockets[0]!.message({ type: "indicator.preview", clientId: wire!.clientId, values: { ema: 12 }, barTime: 1_700_000_000 });
    assert.deepEqual(received, [{ id: "left", signature: "left:v1" }, { id: "right", signature: "right:v1" }]);
  } finally { coordinator.closeAll(); }
});

test("closing one equal consumer does not unsubscribe or reset the survivor", () => {
  const sockets: FakeSocket[] = [];
  const coordinator = new SharedIndicatorStreamCoordinator({ url: "ws://example", maxSubscriptions: 2,
    socketFactory: () => { const socket = new FakeSocket(); sockets.push(socket); return socket; } });
  const clients = ["left", "right"].map(id => {
    const client = coordinator.createLogicalConnection({ workspaceId: "w", windowId: "window", cellId: id });
    client.setSubscriptions([equivalent(id)]); client.start(); return client;
  });
  try {
    sockets[0]!.open(); const before = sent(sockets[0]!).length;
    clients[0]!.close();
    assert.equal(sent(sockets[0]!).length, before, "surviving equal demand must retain its wire lease");
    assert.equal(coordinator.diagnostics().subscriptions, 1);
  } finally { coordinator.closeAll(); }
});

test("browser URL resolution waits for an active indicator subscription", () => {
  const browser = { url: undefined as string | undefined };
  let resolutions = 0;
  const urls: string[] = [];
  const coordinator = new SharedIndicatorStreamCoordinator({
    url: () => {
      resolutions += 1;
      assert.ok(browser.url, "browser context must be ready before connecting");
      return browser.url;
    },
    socketFactory: (url) => {
      urls.push(url);
      return new FakeSocket();
    },
  });
  const connection = coordinator.createLogicalConnection({
    workspaceId: "workspace-a", windowId: "main-window", cellId: "cell-1",
  });
  connection.setSubscriptions([subscription("ma")]);
  assert.equal(resolutions, 0);
  browser.url = "wss://example/api/v1/indicators/stream";
  connection.start();
  assert.equal(resolutions, 1);
  assert.deepEqual(urls, [browser.url]);
  coordinator.closeAll();
});

test("logical identity validates workspace, window, Cell, and indicator names", () => {
  assert.equal(
    indicatorWireClientId(
      { workspaceId: "workspace-a", windowId: "main-window", cellId: "cell-1" },
      "rsi/fast",
    ),
    "workspace-a/main-window/cell-1/rsi%2Ffast",
  );
  assert.equal(
    indicatorWireClientId(
      { workspaceId: "workspace-a", windowId: "main-window", cellId: "cell-1" },
      "x".repeat(256),
    ),
    null,
  );
});

test("logical Cell subscriptions share backend-sized physical shards and localize callbacks", () => {
  const sockets: FakeSocket[] = [];
  const messages: Array<{ cell: string; message: IndicatorWsMessage }> = [];
  const coordinator = new SharedIndicatorStreamCoordinator({
    url: "ws://example/indicators",
    maxSubscriptions: 2,
    socketFactory: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  });
  const first = coordinator.createLogicalConnection(
    { workspaceId: "workspace-a", windowId: "main-window", cellId: "cell-1" },
    { onMessage: (message) => messages.push({ cell: "cell-1", message }) },
  );
  const second = coordinator.createLogicalConnection(
    { workspaceId: "workspace-a", windowId: "main-window", cellId: "cell-2" },
    { onMessage: (message) => messages.push({ cell: "cell-2", message }) },
  );
  first.setSubscriptions([subscription("ma"), subscription("rsi")]);
  second.setSubscriptions([subscription("ma")]);
  first.start();
  second.start();
  assert.equal(sockets.length, 1);
  sockets.forEach((socket) => socket.open());

  const wireIds = sockets.flatMap((socket) => sent(socket))
    .filter((message) => message.action === "subscribe")
    .map((message) => String(message.clientId));
  assert.equal(new Set(wireIds).size, 2);
  assert.ok(wireIds.every(id => id.startsWith("indicator-stream:")));
  assert.deepEqual(coordinator.diagnostics(), {
    logicalClients: 2,
    logicalSubscriptions: 3,
    sharedSubscriptions: 1,
    deduplicatedSubscriptions: 1,
    privateScriptSubscriptions: 0,
    maxSubscriptions: 2,
    physicalShards: 1,
    shards: [
      { index: 0, subscriptions: 2 },
    ],
    subscriptions: 2,
  });

  const socket = sockets[0]!;
  const ma = sent(socket).find(message => message.name === "ma")!;
  socket.message({
    type: "indicator.preview",
    clientId: ma.clientId,
    values: { value: 12 },
    barTime: 1_700_000_000,
  });
  assert.deepEqual(messages.map(item => [item.cell, item.message.clientId]), [["cell-1", "ma"], ["cell-2", "ma"]]);
  coordinator.closeAll();
});

test("local cancellation removes only that Cell and compacts shards", () => {
  const sockets: FakeSocket[] = [];
  const coordinator = new SharedIndicatorStreamCoordinator({
    url: "ws://example/indicators",
    maxSubscriptions: 1,
    socketFactory: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  });
  const first = coordinator.createLogicalConnection(
    { workspaceId: "w", windowId: "window", cellId: "cell-1" },
  );
  const second = coordinator.createLogicalConnection(
    { workspaceId: "w", windowId: "window", cellId: "cell-2" },
  );
  first.setSubscriptions([subscription("ma")]);
  second.setSubscriptions([subscription("rsi")]);
  first.start();
  second.start();
  assert.equal(coordinator.diagnostics().physicalShards, 2);

  first.close();
  assert.equal(coordinator.diagnostics().logicalClients, 1);
  assert.equal(coordinator.diagnostics().physicalShards, 1);
  assert.equal(coordinator.diagnostics().subscriptions, 1);
  assert.equal(sockets.filter((socket) => socket.closed).length, 1);
  second.close();
  assert.equal(coordinator.diagnostics().physicalShards, 0);
});

test("a capability update reshards without exceeding the advertised limit", () => {
  const sockets: FakeSocket[] = [];
  const coordinator = new SharedIndicatorStreamCoordinator({
    url: "ws://example/indicators",
    maxSubscriptions: 1,
    socketFactory: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  });
  const logical = coordinator.createLogicalConnection(
    { workspaceId: "w", windowId: "window", cellId: "cell-1" },
  );
  logical.setSubscriptions([subscription("a"), subscription("b"), subscription("c")]);
  logical.start();
  assert.equal(coordinator.diagnostics().physicalShards, 3);
  coordinator.setMaxSubscriptions(2);
  assert.equal(coordinator.diagnostics().physicalShards, 2);
  assert.ok(coordinator.diagnostics().shards.every((shard) => shard.subscriptions <= 2));
  coordinator.closeAll();
});

function rig(maxSubscriptions = 2) {
  const sockets: FakeSocket[] = [];
  const coordinator = new SharedIndicatorStreamCoordinator({ url: "ws://example", maxSubscriptions,
    socketFactory: () => { const socket = new FakeSocket(); sockets.push(socket); return socket; } });
  const add = (id: string, subscriptions = [equivalent(id)], options: SharedIndicatorLogicalOptions = {}, scope = ["w", "window"]) => {
    const client = coordinator.createLogicalConnection({ workspaceId: scope[0]!, windowId: scope[1]!, cellId: id }, options);
    client.setSubscriptions(subscriptions); client.start(); return client;
  };
  return { coordinator, sockets, add };
}
const subscribes = (socket: FakeSocket) => sent(socket).filter(item => item.action === "subscribe");
const acknowledge = (socket: FakeSocket, clientId: unknown, revision = { serverEpoch: "epoch", correctionRevision: "1", closedThrough: 100 }) =>
  socket.message({ type: "indicator.subscribed", clientId, ok: true, resumeStatus: "history_required", dataRevision: revision });

const variants: Array<[string, Partial<IndicatorSubscribeMessage>]> = [
  ["parameters", { params: { period: 21 } }],
  ["exchange", { exchange: "okx" }],
  ["market", { marketType: "spot" }],
  ["symbol", { symbol: "ETHUSDT" }],
  ["interval", { interval: "5m" }],
  ["full price identity", { seriesIdentity: { priceAdjustment: "adjusted" } }],
  ["provider identity", { seriesIdentity: { providerId: "other-provider" } }],
];
for (const [label, patch] of variants) test(`hosted sharing separates ${label}`, () => {
  const r = rig();
  try {
    r.add("left"); const right = equivalent("right"); right.message = { ...right.message, ...patch }; r.add("right", [right]);
    assert.equal(r.coordinator.diagnostics().subscriptions, 2);
  } finally { r.coordinator.closeAll(); }
});

test("canonical parameter order shares but workspace/window identities remain separate", () => {
  const r = rig(10);
  try {
    const a = equivalent("a"), b = equivalent("b");
    a.message.params = { period: 20, nested: { a: 1, b: 2 } };
    b.message.params = { nested: { b: 2, a: 1 }, period: 20 };
    r.add("a", [a]); r.add("b", [b]);
    assert.equal(r.coordinator.diagnostics().subscriptions, 1);
    r.add("c", [b], {}, ["other-workspace", "window"]);
    r.add("d", [b], {}, ["w", "other-window"]);
    assert.equal(r.coordinator.diagnostics().subscriptions, 3);
    a.message.params.period = 99; // caller mutation cannot alter owned wire input
    r.sockets[0]!.open(); assert.equal((subscribes(r.sockets[0]!)[0]!.params as { period: number }).period, 20);
  } finally { r.coordinator.closeAll(); }
});

test("identical scripts retain private live state and alert owners", () => {
  const r = rig(10);
  try {
    for (const id of ["left", "right"]) {
      const sub = equivalent(id);
      sub.message = { ...sub.message, kind: "script", customId: "same-saved-script", language: "pine",
        script: "varip int n=0\nn+=1\nplot(n)", securityMode: "safe", params: { __pineAlerts: true, __pineSessionEpoch: "0" } };
      r.add(id, [sub]);
    }
    assert.equal(r.coordinator.diagnostics().subscriptions, 2);
    assert.equal(r.coordinator.diagnostics().privateScriptSubscriptions, 2);
    assert.equal(r.coordinator.diagnostics().deduplicatedSubscriptions, 0);
  } finally { r.coordinator.closeAll(); }
});

test("market identity dimensions cannot collide through delimiters", () => {
  const r = rig();
  try {
    const left = equivalent("left"), right = equivalent("right");
    left.message.seriesIdentity = { providerId: "vendor:regional", venue: "exchange" };
    right.message.seriesIdentity = { providerId: "vendor", venue: "regional:exchange" };
    r.add("left", [left]); r.add("right", [right]);
    assert.equal(r.coordinator.diagnostics().subscriptions, 2);
  } finally { r.coordinator.closeAll(); }
});

test("ordinary history growth preserves the wire and private script session", () => {
  const r = rig(10);
  try {
    const builtin = equivalent("builtin"), script = equivalent("script");
    script.message = { ...script.message, kind: "script", script: "varip int n=0\nn+=1\nplot(n)", language: "pine" };
    const client = r.add("left", [builtin, script]);
    const socket = r.sockets[0]!; socket.open();
    for (const sub of subscribes(socket)) acknowledge(socket, sub.clientId);
    const before = [...socket.sent];
    builtin.message.historyLimit += 1; script.message.historyLimit += 1;
    client.setSubscriptions([builtin, script]);
    assert.deepEqual(socket.sent, before, "new candles must not reset hosted sessions");
  } finally { r.coordinator.closeAll(); }
});

test("shared builtin seed covers the largest consumer budget and refresh uses updated demand", () => {
  const r = rig();
  try {
    const left = equivalent("left"), right = equivalent("right");
    right.message.historyLimit = 500;
    r.add("left", [left]); const client = r.add("right", [right]);
    const socket = r.sockets[0]!; socket.open();
    assert.equal(r.coordinator.diagnostics().subscriptions, 1);
    assert.equal(subscribes(socket)[0]!.historyLimit, 500);
    acknowledge(socket, subscribes(socket)[0]!.clientId);
    right.message.historyLimit = 800; client.setSubscriptions([right]);
    assert.equal(subscribes(socket).length, 1);
    client.forceResubscribe();
    assert.equal(subscribes(socket).at(-1)!.historyLimit, 800);
    assert.equal(r.coordinator.diagnostics().subscriptions, 1);
  } finally { r.coordinator.closeAll(); }
});

test("late join gets a fresh cold ACK and stale membership frames cannot reach either chart", () => {
  const r = rig(), first: IndicatorWsMessage[] = [], second: IndicatorWsMessage[] = [];
  try {
    r.add("left", [equivalent("left")], { onMessage: message => first.push(message) });
    const socket = r.sockets[0]!; socket.open(); const old = subscribes(socket)[0]!.clientId;
    acknowledge(socket, old); assert.equal(first.length, 1);
    const sub = equivalent("right"); Object.assign(sub.message, { serverEpoch: "epoch", correctionRevision: "1", resumeFrom: 100 });
    r.add("right", [sub], { onMessage: message => second.push(message) });
    const replacement = subscribes(socket).at(-1)!;
    assert.notEqual(replacement.clientId, old); assert.equal(replacement.resumeFrom, undefined);
    assert.equal(second.length, 0, "old ACK must not be replayed to a new consumer");
    acknowledge(socket, old);
    socket.message({ type: "indicator.preview", clientId: old, values: { ema: 999 }, barTime: 100 });
    assert.equal(first.length, 1); assert.equal(second.length, 0);
    acknowledge(socket, replacement.clientId);
    assert.equal(first.length, 2); assert.equal(second.length, 1);
    assert.equal(r.sockets.length, 1, "joining cannot restart the shared socket");
  } finally { r.coordinator.closeAll(); }
});

test("cold group ACK invalidates each stale consumer instead of silently rebasing its cache", () => {
  const r = rig(), received: IndicatorWsMessage[] = [];
  try {
    for (const [id, epoch, revision] of [["old-epoch", "old", "1"], ["old-correction", "epoch", "0"], ["current", "epoch", "1"]]) {
      const sub = equivalent(id!); Object.assign(sub.message, { serverEpoch: epoch, correctionRevision: revision, resumeFrom: 100 });
      r.add(id!, [sub], { onMessage: message => received.push(message) });
    }
    const socket = r.sockets[0]!; socket.open(); const wire = subscribes(socket)[0]!;
    assert.equal(wire.serverEpoch, undefined); assert.equal(wire.resumeFrom, undefined);
    acknowledge(socket, wire.clientId);
    assert.deepEqual(received.map(message => [message.clientId, message.type === "indicator.subscribed" && message.dataRevision?.historyInvalid === true]),
      [["old-epoch", true], ["old-correction", true], ["current", false]]);
  } finally { r.coordinator.closeAll(); }
});

test("configuration A/B/A and last-release/re-add never reuse an old wire identity", () => {
  const r = rig(), received: IndicatorWsMessage[] = [];
  try {
    const a = equivalent("left");
    const client = r.add("left", [a], { onMessage: message => received.push(message) });
    const socket = r.sockets[0]!; socket.open(); const old = subscribes(socket)[0]!.clientId;
    const b = structuredClone(a); b.signature = "left:v2"; b.message.params = { period: 35 };
    client.setSubscriptions([b]); client.setSubscriptions([a]);
    const ids = subscribes(socket).map(item => item.clientId);
    assert.equal(new Set(ids).size, 3);
    acknowledge(socket, old); assert.equal(received.length, 0);
    acknowledge(socket, ids.at(-1)); assert.equal(received.length, 1);
    client.close(); r.add("left-again", [a]); r.sockets.at(-1)!.open();
    assert.ok(!ids.includes(subscribes(r.sockets.at(-1)!)[0]!.clientId));
  } finally { r.coordinator.closeAll(); }
});

test("refresh targets only the caller's group and unrelated shard assignments survive removal", () => {
  const r = rig();
  try {
    const a = r.add("a"), b = r.add("b", [equivalent("b"), subscription("RSI")]);
    const socket = r.sockets[0]!; socket.open();
    for (const sub of subscribes(socket)) acknowledge(socket, sub.clientId);
    const rsi = subscribes(socket).find(item => item.name === "RSI")!.clientId;
    const before = sent(socket).length; assert.equal(a.forceResubscribe(), true);
    assert.ok(sent(socket).slice(before).every(item => item.clientId !== rsi));
    const after = sent(socket).length; a.close();
    assert.equal(sent(socket).length, after); b.close(); assert.equal(r.coordinator.diagnostics().subscriptions, 0);
  } finally { r.coordinator.closeAll(); }
  const isolated = rig(1);
  try {
    isolated.add("a", [subscription("a")]); const middle = isolated.add("b", [subscription("b")]); isolated.add("c", [subscription("c")]);
    isolated.sockets.forEach(socket => socket.open());
    const survivors = [isolated.sockets[0]!, isolated.sockets[2]!]; const counts = survivors.map(socket => socket.sent.length);
    middle.close();
    assert.deepEqual(survivors.map(socket => [socket.closed, socket.sent.length]), counts.map(count => [false, count]));
  } finally { isolated.coordinator.closeAll(); }
});

test("one callback's mutation or exception cannot corrupt another consumer", () => {
  const r = rig(); let errors = 0; const received: IndicatorWsMessage[] = [];
  try {
    r.add("left", undefined, { onMessage: message => { if (message.type === "indicator.preview") message.values.ema = 999; throw Error("consumer failed"); }, onError: () => { errors++; } });
    r.add("right", undefined, { onMessage: message => received.push(message) });
    const socket = r.sockets[0]!; socket.open(); const wire = subscribes(socket)[0]!.clientId;
    socket.message({ type: "indicator.preview", clientId: wire, values: { ema: 12 }, barTime: 100 });
    assert.equal(errors, 1); assert.equal(received.length, 1);
    assert.equal(received[0]!.type === "indicator.preview" && received[0]!.values.ema, 12);
  } finally { r.coordinator.closeAll(); }
});

test("reentrant cancellation prevents delivery to the removed consumer", () => {
  const r = rig(); const received: IndicatorWsMessage[] = [];
  try {
    let remove = () => {};
    r.add("left", undefined, { onMessage: () => remove() });
    const right = r.add("right", undefined, { onMessage: message => received.push(message) }); remove = () => right.close();
    const socket = r.sockets[0]!; socket.open();
    socket.message({ type: "indicator.preview", clientId: subscribes(socket)[0]!.clientId, values: { ema: 12 }, barTime: 100 });
    assert.deepEqual(received, []); assert.equal(r.coordinator.diagnostics().logicalSubscriptions, 1);
  } finally { r.coordinator.closeAll(); }
});

test("shared ACK retries, compatible checkpoint resume and overload cold recovery retain one demand", context => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const r = rig();
  try {
    for (const [id, resumeFrom] of [["left", 100], ["right", 80]] as const) {
      const sub = equivalent(id); Object.assign(sub.message, { serverEpoch: "epoch", correctionRevision: "1", resumeFrom }); r.add(id, [sub]);
    }
    const first = r.sockets[0]!; first.open(); const wire = subscribes(first)[0]!.clientId;
    context.mock.timers.tick(2001); assert.equal(subscribes(first).length, 2); assert.equal(subscribes(first)[1]!.clientId, wire);
    acknowledge(first, wire); first.serverClose(); context.mock.timers.tick(1001);
    const resumed = r.sockets[1]!; resumed.open(); const resumedWire = subscribes(resumed)[0]!;
    assert.equal(resumedWire.resumeFrom, 80); assert.equal(resumedWire.clientId, wire);
    acknowledge(resumed, wire); resumed.serverClose(1013); context.mock.timers.tick(1001);
    const cold = r.sockets[2]!; cold.open(); assert.equal(subscribes(cold)[0]!.resumeFrom, undefined);
    assert.equal(r.coordinator.diagnostics().subscriptions, 1); assert.equal(r.coordinator.diagnostics().logicalSubscriptions, 2);
  } finally { r.coordinator.closeAll(); context.mock.timers.reset(); }
});
