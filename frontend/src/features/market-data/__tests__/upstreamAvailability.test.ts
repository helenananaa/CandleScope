import assert from "node:assert/strict";
import test from "node:test";

import type {
  KlineApi,
  KlineStreamController,
  KlineStreamOptions,
  KlineStreamStatusMessage,
} from "../klineContracts.js";
import { upstreamAvailabilityOf } from "../klineContracts.js";
import { SharedKlineStreamCoordinator } from "../feed/sharedKlineStreamCoordinator.js";
import { MarketDataManager } from "../manager/marketDataManager.js";
import type { EpochSeconds, KlineBar, MarketSeries } from "../marketDataTypes.js";
import { resolveKlineTransportStatus } from "../useKlineStreamRuntime.js";

const OFFLINE: KlineStreamStatusMessage = {
  type: "stream_status", status: "offline", source: "upstream", reason: "Connection closed by remote server",
};
const ONLINE: KlineStreamStatusMessage = { type: "stream_status", status: "online", source: "upstream" };
const visible = { upstreamOffline: false, windowVisible: true, consumerRecoveryRequired: false };

test("only instrument-wide upstream reports count as exchange availability", () => {
  assert.equal(upstreamAvailabilityOf(OFFLINE), "offline");
  assert.equal(upstreamAvailabilityOf(ONLINE), "online");
  // Interval-scoped statuses keep their existing meanings.
  assert.equal(upstreamAvailabilityOf({ ...OFFLINE, interval: "1m" }), null);
  assert.equal(upstreamAvailabilityOf({ status: "reconnecting", source: "upstream" }), null);
  assert.equal(upstreamAvailabilityOf({ status: "offline" }), null);
  assert.equal(upstreamAvailabilityOf({ status: "source_gap", interval: "1m" }), null);
});

test("an exchange outage outranks every local transport state", () => {
  const offline = { ...visible, upstreamOffline: true };
  for (const next of ["connecting", "loading", "live", "fallback", "reconnecting", "offline"] as const) {
    assert.equal(resolveKlineTransportStatus(next, offline), "offline", next);
  }
  assert.equal(resolveKlineTransportStatus("idle", offline), "idle");
});

test("without an outage a quiet market stays waiting, not offline", () => {
  assert.equal(resolveKlineTransportStatus("loading", visible), "loading");
  assert.equal(resolveKlineTransportStatus("live", visible), "live");
  assert.equal(resolveKlineTransportStatus("offline", visible), "reconnecting");
  assert.equal(resolveKlineTransportStatus("live", { ...visible, windowVisible: false }), "reconnecting");
  assert.equal(resolveKlineTransportStatus("live", { ...visible, consumerRecoveryRequired: true }), "reconnecting");
});

function sharedHarness() {
  const physical: Array<{ options: KlineStreamOptions; controller: KlineStreamController }> = [];
  const coordinator = new SharedKlineStreamCoordinator({} as KlineApi, {
    createPhysicalStream: (_series, options) => {
      const controller: KlineStreamController = {
        readyState: () => 1, isOpen: () => true, send: () => true, sendPing: () => true,
        updateIntervals: () => undefined, close: () => undefined,
      };
      physical.push({ options, controller });
      return controller;
    },
  });
  return { coordinator, physical };
}

const BTC = { exchange: "binance", marketType: "futures", symbol: "BTCUSDT" };
const microtask = () => new Promise<void>((resolve) => queueMicrotask(resolve));

test("a chart that joins an instrument during an outage is told it is offline", async () => {
  const { coordinator, physical } = sharedHarness();
  const first: Array<string | undefined> = [];
  coordinator.subscribe(BTC, { intervals: ["1m"], onStreamStatus: (message) => first.push(message.status) });
  const stream = physical[0]!;
  stream.options.onOpen?.(stream.controller);
  stream.options.onStreamStatus?.(OFFLINE, stream.controller);
  assert.deepEqual(first, ["offline"]);

  const joined: Array<string | undefined> = [];
  coordinator.subscribe(BTC, { intervals: ["5m"], onStreamStatus: (message) => joined.push(message.status) });
  await microtask();
  assert.deepEqual(joined, ["offline"]);

  stream.options.onStreamStatus?.(ONLINE, stream.controller);
  const late: Array<string | undefined> = [];
  coordinator.subscribe(BTC, { intervals: ["15m"], onStreamStatus: (message) => late.push(message.status) });
  await microtask();
  assert.deepEqual(late, []);
  assert.deepEqual(joined, ["offline", "online"]);
});

test("a closed backend socket forgets the outage until the backend reports again", async () => {
  const { coordinator, physical } = sharedHarness();
  coordinator.subscribe(BTC, { intervals: ["1m"] });
  const stream = physical[0]!;
  stream.options.onOpen?.(stream.controller);
  stream.options.onStreamStatus?.(OFFLINE, stream.controller);
  stream.options.onClose?.({} as CloseEvent, stream.controller);

  const statuses: Array<string | undefined> = [];
  coordinator.subscribe(BTC, { intervals: ["5m"], onStreamStatus: (message) => statuses.push(message.status) });
  await microtask();
  assert.deepEqual(statuses, []);
});

test("an exchange outage keeps the chart's live admission so recovery resumes without a resubscribe", async (t) => {
  const series: MarketSeries = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
  const row = (time: number, close: number): KlineBar => ({
    time: time as EpochSeconds, open: 10, high: 30, low: 0, close, volume: 2, is_closed: true,
  });
  const streams: Array<{ options: KlineStreamOptions; controller: KlineStreamController }> = [];
  const manager = new MarketDataManager({
    api: { getMultiStreamUrl: () => "ws://fixture" } as unknown as KlineApi,
    streams: {
      reconnects: true,
      subscribe: (_series: unknown, options: KlineStreamOptions = {}) => {
        const controller: KlineStreamController = {
          readyState: () => 1, isOpen: () => true, send: () => true, sendPing: () => true,
          updateIntervals: () => undefined, close: () => undefined,
        };
        streams.push({ options, controller });
        queueMicrotask(() => options.onOpen?.(controller));
        return controller;
      },
      diagnostics: () => ({ physicalStreams: streams.length }),
      closeAll: () => undefined,
    },
  });
  t.after(() => manager.closeAll());
  const received: number[] = [];
  const statuses: Array<string | undefined> = [];
  manager.subscribe(series, {
    intervals: ["1m"],
    onKline: (event) => received.push(event.tick.close!),
    onStreamStatus: (message) => statuses.push(message.status),
  });
  await new Promise<void>((resolve) => setImmediate(resolve));
  const physical = streams[0]!;
  const tick = (bar: KlineBar) => physical.options.onKline?.({ interval: "1m", tick: bar,
    message: { type: "kline", symbol: "BTCUSDT", interval: "1m", data: bar, event_type: "bar.closed" },
  }, physical.controller);

  tick(row(60, 10));
  physical.options.onStreamStatus?.(OFFLINE, physical.controller);
  physical.options.onStreamStatus?.(ONLINE, physical.controller);
  tick(row(120, 20));

  assert.deepEqual(statuses, ["offline", "online"]);
  assert.deepEqual(received, [10, 20]);
});
