import assert from "node:assert/strict";
import test from "node:test";

import type { KlineStreamSocket } from "../klineContracts.js";
import { BatchKlineStreamCoordinator } from "../feed/batchKlineStreamCoordinator.js";
import { resolveKlineBatchStreamEnabled } from "../klineBatchFeature.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import { KlineConsumerRecovery } from "../feed/klineConsumerRecovery.js";
import type { KlineFetchResult } from "../klineContracts.js";
import { epochSeconds } from "../../../test/testHelpers.js";

class FakeSocket implements KlineStreamSocket {
  readonly OPEN = 1;
  readyState = 0;
  onopen: ((event: Event) => unknown) | null = null;
  onmessage: ((event: MessageEvent<string>) => unknown) | null = null;
  onerror: ((event: Event) => unknown) | null = null;
  onclose: ((event: CloseEvent) => unknown) | null = null;
  readonly sent: string[] = [];
  closed = false;

  send(payload: string): void { this.sent.push(payload); }
  close(): void { this.closed = true; this.readyState = 3; }
  open(): void { this.readyState = 1; this.onopen?.({} as Event); }
  message(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
  }
}

for (const retire of ["last-subscriber", "close-all"] as const) {
  test(`retired socket events cannot invalidate a new interval's history (${retire})`, async () => {
    const sockets: FakeSocket[] = [];
    const coordinator = new BatchKlineStreamCoordinator({
      url: "ws://test/stream/klines_batch",
      socketFactory: () => { const socket = new FakeSocket(); sockets.push(socket); return socket; },
    });
    const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "4h" };
    let finish!: (result: KlineFetchResult) => void;
    const response = new Promise<KlineFetchResult>((resolve) => { finish = resolve; });
    const committed: number[] = [];
    const feed = new SeriesDataFeed({
      api: {
        fetchKlinesHistory: () => response,
        fetchKlinesBefore: () => response,
        fetchKlinesRange: () => response,
        fetchLatestKlines: () => response,
        getMultiStreamUrl: () => "ws://test",
      },
      getActiveSeries: () => series,
      commitMergedChartData: (_symbol, _interval, rows) => { committed.push(rows.length); },
    });
    const recovery = new KlineConsumerRecovery();
    let closes = 0;
    let opens = 0;
    let errors = 0;
    let controls = 0;
    try {
      const previous = coordinator.subscribe(series, { intervals: ["1m"] });
      const oldSocket = sockets[0]!;
      oldSocket.open();
      if (retire === "close-all") coordinator.closeAll();
      else previous.close();
      coordinator.subscribe(series, {
        intervals: ["4h"],
        onClose: () => { closes += 1; recovery.capture(feed, series, []); },
        onOpen: () => { opens += 1; },
        onError: () => { errors += 1; },
        onControlMessage: () => { controls += 1; },
      });
      const currentSocket = sockets[1]!;
      currentSocket.open();
      feed.beginEpoch(series);
      const history = feed.getBars(series, { countBack: 500, source: "initial-history" });
      await new Promise<void>((resolve) => setImmediate(resolve));
      // Browser close events arrive asynchronously, after the new subscription
      // and its HTTP bootstrap have already started.
      oldSocket.onclose?.({} as CloseEvent);
      oldSocket.onerror?.({} as Event);
      oldSocket.onopen?.({} as Event);
      oldSocket.message({ type: "connected" });
      finish({ data: [{ time: epochSeconds(14400), close: 1 }], complete: true, retryable: false });
      const result = await history;
      assert.equal(result.stale, false, "retired socket must not fence the new bootstrap");
      assert.deepEqual(committed, [1]);
      assert.equal(closes, 0);
      assert.equal(errors, 0);
      assert.equal(opens, 1);
      assert.equal(controls, 0);
      assert.equal(currentSocket.sent.length, 1, "retired open must not duplicate subscribe");
      // A genuine close of the current transport still triggers recovery.
      currentSocket.onclose?.({} as CloseEvent);
      assert.equal(closes, 1);
    } finally {
      coordinator.closeAll();
    }
  });
}

test("batch stream resolves the browser origin at subscription time, not during rendering", () => {
  const previousLocation = Object.getOwnPropertyDescriptor(globalThis, "location");
  const urls: string[] = [];
  let coordinator: BatchKlineStreamCoordinator | undefined;
  try {
    Reflect.deleteProperty(globalThis, "location");
    coordinator = new BatchKlineStreamCoordinator({
      socketFactory: (url) => { urls.push(url); return new FakeSocket(); },
    });
    assert.equal(urls.length, 0);
    Object.defineProperty(globalThis, "location", {
      configurable: true, value: { protocol: "https:", host: "charts.example" },
    });
    coordinator.subscribe(
      { exchange: "binance", marketType: "spot", symbol: "BTCUSDT" },
      { intervals: ["1m"], onKline() {} },
    );
    assert.equal(urls.length, 1);
    assert.ok(urls[0]?.startsWith("wss://charts.example/api/v1/"));
  } finally {
    coordinator?.closeAll();
    if (previousLocation) Object.defineProperty(globalThis, "location", previousLocation);
    else Reflect.deleteProperty(globalThis, "location");
  }
});

test("batch K-line flag defaults on and preserves strict explicit rollback", () => {
  assert.equal(resolveKlineBatchStreamEnabled(), true);
  for (const value of ["0", false, 0, "", null, "invalid"]) {
    assert.equal(resolveKlineBatchStreamEnabled({ KLINE_BATCH_STREAM_ENABLED: value }), false);
  }
  assert.equal(resolveKlineBatchStreamEnabled({ KLINE_BATCH_STREAM_ENABLED: "1" }), true);
  assert.equal(resolveKlineBatchStreamEnabled({ KLINE_BATCH_STREAM_ENABLED: "true" }), false);
});

test("different instruments share one batch socket with isolated stable client IDs", () => {
  const sockets: FakeSocket[] = [];
  const controls: Array<{ owner: string; type: string; active: readonly string[] }> = [];
  const ticks: Array<{ owner: string; interval: string }> = [];
  const coordinator = new BatchKlineStreamCoordinator({
    url: "ws://test/stream/klines_batch",
    socketFactory: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  });

  const btc = coordinator.subscribe(
    { exchange: "binance", marketType: "spot", symbol: "BTCUSDT" },
    {
      intervals: ["1m"],
      onControlMessage: (message) => controls.push({
        owner: "btc",
        type: message.type,
        active: message.active_intervals || [],
      }),
      onKline: (event) => ticks.push({ owner: "btc", interval: event.interval }),
    },
  );
  const eth = coordinator.subscribe(
    { exchange: "okx", marketType: "spot", symbol: "ETH-USDT" },
    {
      intervals: ["5m"],
      onControlMessage: (message) => controls.push({
        owner: "eth",
        type: message.type,
        active: message.active_intervals || [],
      }),
      onKline: (event) => ticks.push({ owner: "eth", interval: event.interval }),
    },
  );

  assert.equal(sockets.length, 1);
  const socket = sockets[0]!;
  socket.open();
  const subscribe = JSON.parse(socket.sent[0]!) as {
    action: string;
    items: Array<{ clientId: string; symbol: string }>;
  };
  assert.equal(subscribe.action, "subscribe");
  assert.deepEqual(subscribe.items.map((item) => item.symbol), ["BTCUSDT", "ETH-USDT"]);
  assert.equal(new Set(subscribe.items.map((item) => item.clientId)).size, 2);

  const btcId = subscribe.items[0]!.clientId;
  const ethId = subscribe.items[1]!.clientId;
  socket.message({
    type: "subscription_ack",
    action: "subscribe",
    ok: true,
    client_id: btcId,
    active_intervals: ["1m"],
  });
  socket.message({
    type: "kline",
    protocol: "candlescope.kline-batch/1",
    client_id: ethId,
    exchange: "okx",
    market_type: "spot",
    symbol: "ETH-USDT",
    interval: "5m",
    data: { time: 1, open: 1, high: 2, low: 1, close: 2, volume: 3 },
  });
  assert.deepEqual(controls, [{ owner: "btc", type: "subscribed", active: ["1m"] }]);
  assert.deepEqual(ticks, [{ owner: "eth", interval: "5m" }]);

  btc.updateIntervals(["15m"]);
  const update = JSON.parse(socket.sent.at(-1)!) as {
    action: string;
    items: Array<{ clientId: string; intervals: string[] }>;
  };
  assert.equal(update.action, "update");
  assert.equal(update.items[0]!.clientId, btcId);
  assert.deepEqual(update.items[0]!.intervals, ["15m"]);
  assert.deepEqual(coordinator.diagnostics(), {
    mode: "batch",
    physicalStreams: 1,
    open: true,
    logicalSubscribers: 2,
    logicalSubscriptions: 2,
    clientIds: [btcId, ethId].sort(),
    serverStates: { subscribed: 1, subscribing: 1 },
    activeLogicalSubscriptions: 1,
    counts: {
      messages: 2,
      klines: 1,
      closed: 0,
      amended: 0,
      parseErrors: 0,
      socketOpens: 1,
      socketCloses: 0,
      retriesScheduled: 0,
      retriesSent: 0,
    },
  });

  btc.close();
  assert.equal(socket.closed, false);
  eth.close();
  assert.equal(socket.closed, true);
  assert.equal(coordinator.activePhysicalStreamCount(), 0);
});

test("a transient subscribe rejection retries the affected logical client", async () => {
  const socket = new FakeSocket();
  const coordinator = new BatchKlineStreamCoordinator({
    url: "ws://test/stream/klines_batch",
    socketFactory: () => socket,
  });
  coordinator.subscribe(
    { exchange: "binance", marketType: "spot", symbol: "BTCUSDT" },
    { intervals: ["1m"] },
  );
  socket.open();
  const initial = JSON.parse(socket.sent[0]!) as { items: Array<{ clientId: string }> };
  socket.message({
    type: "subscription_ack",
    action: "subscribe",
    ok: false,
    status: "failed",
    code: "kline_app_capacity",
    client_id: initial.items[0]!.clientId,
    active_intervals: [],
  });

  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.equal(socket.sent.length, 2);
  const retry = JSON.parse(socket.sent[1]!) as unknown as { action?: unknown };
  assert.equal(retry.action, "subscribe");
  const diagnostics = coordinator.diagnostics();
  assert.deepEqual(diagnostics.serverStates, { subscribing: 1 });
  assert.equal((diagnostics.counts as Record<string, number>).retriesScheduled, 1);
  assert.equal((diagnostics.counts as Record<string, number>).retriesSent, 1);
  coordinator.closeAll();
});

test("authoritative close and amendment counters remain distinct and parse failures stay visible", () => {
  const socket = new FakeSocket();
  const coordinator = new BatchKlineStreamCoordinator({
    url: "ws://test/stream/klines_batch",
    socketFactory: () => socket,
  });
  coordinator.subscribe(
    { exchange: "binance", marketType: "spot", symbol: "BTCUSDT" },
    { intervals: ["1m"] },
  );
  socket.open();
  const clientId = (JSON.parse(socket.sent[0]!) as { items: Array<{ clientId: string }> }).items[0]!.clientId;
  const message = (eventType: string) => ({
    type: "kline",
    event_type: eventType,
    protocol: "candlescope.kline-batch/1",
    client_id: clientId,
    exchange: "binance",
    market_type: "spot",
    symbol: "BTCUSDT",
    interval: "1m",
    data: { time: 1, open: 1, high: 2, low: 1, close: 2, volume: 3, is_closed: true },
  });
  socket.message(message("bar.closed"));
  socket.message(message("bar.amended"));
  socket.onmessage?.({ data: "not-json" } as MessageEvent<string>);
  const counts = coordinator.diagnostics().counts as Record<string, number>;
  assert.equal(counts.closed, 1);
  assert.equal(counts.amended, 1);
  assert.equal(counts.parseErrors, 1);
});

test("a Cell mounted after socket open subscribes only after its intervals are known", () => {
  const socket = new FakeSocket();
  const coordinator = new BatchKlineStreamCoordinator({
    url: "ws://test/stream/klines_batch",
    socketFactory: () => socket,
  });
  const controller = coordinator.subscribe(
    { exchange: "binance", marketType: "spot", symbol: "BTCUSDT" },
    { intervals: [] },
  );

  socket.open();
  assert.equal(socket.sent.length, 0);
  controller.updateIntervals(["1m"]);
  assert.equal(socket.sent.length, 1);
  const subscribe = JSON.parse(socket.sent[0]!) as {
    action: string;
    items: Array<{ clientId: string; intervals: string[] }>;
  };
  assert.equal(subscribe.action, "subscribe");
  assert.deepEqual(subscribe.items[0]!.intervals, ["1m"]);

  controller.updateIntervals(["5m"]);
  assert.equal(socket.sent.length, 1, "updates coalesce while the subscribe ACK is pending");
  socket.message({
    type: "subscription_ack",
    action: "subscribe",
    ok: true,
    client_id: subscribe.items[0]!.clientId,
    active_intervals: ["1m"],
  });
  const update = JSON.parse(socket.sent[1]!) as {
    action: string;
    items: Array<{ intervals: string[] }>;
  };
  assert.equal(update.action, "update");
  assert.deepEqual(update.items[0]!.intervals, ["5m"]);
});
