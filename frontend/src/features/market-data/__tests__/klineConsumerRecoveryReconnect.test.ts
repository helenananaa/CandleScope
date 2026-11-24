import assert from "node:assert/strict";
import test from "node:test";

import { parseKlineResponse } from "../../../services/apiPayloadParsers.js";
import { decodeKlineResult } from "../feed/klineEndpointDecoder.js";
import { KlineConsumerRecovery } from "../feed/klineConsumerRecovery.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import type { KlineApi, KlineFetchResult, KlineStreamController, KlineStreamOptions } from "../klineContracts.js";
import { MarketDataManager } from "../manager/marketDataManager.js";
import type { EpochSeconds, KlineBar, MarketSeries } from "../marketDataTypes.js";
import { resolveKlineTransportStatus } from "../useKlineStreamRuntime.js";

// Recorded 2026-11-24 from a RC-runtime backend (BTCUSDT spot 1h) after its
// exchange stream reconnected and closed the chart's K-line socket. The strict
// range is a complete closed proof through 05:00; /klines/latest has no
// forming 06:00 row (excluded as forming_bar) for minutes, while the socket
// keeps delivering it. Bulky diagnostics (`cache`) are omitted.
const HOUR = 3_600;
const FORMING = 1_795_500_000; // 06:00 UTC
const LAST_CLOSED = FORMING - HOUR;
const FIRST = LAST_CLOSED - 499 * HOUR;
const identity = {
  provider_id: "binance", venue: "binance", asset_class: "crypto", series_variant: "native",
  price_adjustment: "raw", session_variant: "continuous", volume_semantics: "base_asset",
};
const scope = { symbol: "BTCUSDT", interval: "1h", exchange: "binance", market_type: "spot", ...identity };
const EPOCH = "c58b98c45f054231a2088e78ce68d0ea";
const version = (sequence: number, barrier: number, observed: number, extra: Record<string, unknown> = {}) => ({
  protocol: 1, epoch: EPOCH, generation: 1, sequence, barrier, series: scope, observed_at_ms: observed, ...extra,
});
const SNAPSHOT_OBSERVED = 1_795_501_938_488;
const closedRow = (time: number) => ({
  time, open: 60_379.65, high: 60_768.56, low: 60_322.49, close: 60_628.99, volume: 499.58025, is_closed: true,
  quote_volume: 30_288_045.03, trades: 198_948, taker_buy_base: 293.32364, taker_buy_quote: 17_783_129.42,
});
const closedRows = Array.from({ length: 500 }, (_, index) => closedRow(FIRST + index * HOUR));
const recordedRange = {
  exchange: "binance", market_type: "spot", ...identity, symbol: "BTCUSDT", interval: "1h",
  start_ms: FIRST * 1000, end_ms: FORMING * 1000, effective_end_ms: LAST_CLOSED * 1000,
  reached_latest_closed_bar: true, query_start_ms: FIRST * 1000, query_end_ms: LAST_CLOSED * 1000,
  truncated: false, next_end_ms: null, count: 500, source: "storage", fetched: 500, has_tail_gap: false,
  backfill_triggered: false, verified_contiguous: true, all_rows_final: true, renderable: true,
  missing_ranges: [], expected_bars: 500, actual_bars: 500, history_state: "ready", complete: true,
  retryable: false, terminal_reason: null, earliest_available_ms: null, next_before_ms: FIRST * 1000,
  availability_revision: "b7462370d955eac7f75efae3", excluded_ranges: [], retry_at_ms: null,
  stream_version: version(7, 6, SNAPSHOT_OBSERVED, { stable: true }), storage_revision: 502,
  base_interval: null, data: closedRows,
};
const recordedLatest = {
  exchange: "binance", market_type: "spot", ...identity, symbol: "BTCUSDT", interval: "1h",
  count: 2, source: "cache", fetched: 2, backfill_triggered: false, has_tail_gap: false, missing_ranges: [],
  history_state: "ready", complete: true, retryable: false, terminal_reason: null, earliest_available_ms: null,
  next_before_ms: (LAST_CLOSED - HOUR) * 1000, availability_revision: "b7462370d955eac7f75efae3",
  excluded_ranges: [{ start_ms: FORMING * 1000, end_ms: FORMING * 1000, disposition: "not_expected", reason: "forming_bar" }],
  retry_at_ms: null, all_rows_final: true, stream_version: version(7, 6, SNAPSHOT_OBSERVED, { stable: true }),
  storage_revision: 502, base_interval: null, data: closedRows.slice(-2),
};
const decoded = (payload: unknown, endpoint: "range" | "latest"): KlineFetchResult =>
  decodeKlineResult(parseKlineResponse(structuredClone(payload)), endpoint);

const forming = (close: number): KlineBar => ({
  time: FORMING as EpochSeconds, open: 60_628.99, high: 60_700, low: 60_600, close, volume: 12.5, is_closed: false,
});

function reconnectHarness() {
  const base = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT" };
  const series: MarketSeries = { ...base, interval: "1h" };
  const reads: string[] = [];
  const api: KlineApi = {
    getMultiStreamUrl: () => "ws://recorded",
    fetchKlinesHistory: async () => ({ data: [], history_state: "pending", complete: false, retryable: true }),
    fetchKlinesBefore: async () => ({ data: [], history_state: "pending", complete: false, retryable: true }),
    fetchKlinesRange: async () => { reads.push("range"); return decoded(recordedRange, "range"); },
    fetchLatestKlines: async () => { reads.push("latest"); return decoded(recordedLatest, "latest"); },
  };
  const physical: Array<{ options: KlineStreamOptions; controller: KlineStreamController }> = [];
  const manager = new MarketDataManager({
    api,
    streams: {
      reconnects: true,
      subscribe: (_series: unknown, options: KlineStreamOptions = {}) => {
        const controller: KlineStreamController = {
          readyState: () => 1, isOpen: () => true, send: () => true, sendPing: () => true,
          updateIntervals: () => undefined, close: () => undefined,
        };
        physical.push({ options, controller });
        return controller;
      },
      diagnostics: () => ({ physicalStreams: physical.length }),
      closeAll: () => undefined,
    },
  });
  const committed: number[][] = [];
  const feed = new SeriesDataFeed({
    api: manager, streamFactory: manager.subscribe, getActiveSeries: () => series,
    commitMergedChartData: (_symbol, _interval, rows) => { committed.push(rows.map((row) => Number(row.time))); },
  });
  // The held window ends in the forming bucket the socket was drawing.
  const held: KlineBar[] = [...closedRows.map((row) => ({ ...row, time: row.time as EpochSeconds })), forming(60_640)];
  const recovery = new KlineConsumerRecovery();
  // Mirrors useKlineStreamRuntime: capture on close, read back once the
  // server acknowledges the interval, offer every fresh forming tick.
  feed.subscribeBars(base, {
    intervals: ["1h"],
    onClose: () => recovery.capture(feed, series, held),
    onControlMessage: () => { void recovery.recover(feed, () => true); },
    onKline: ({ interval, tick, message }) => {
      if (message.continuity_replayed === true) return;
      recovery.observeRealtime(feed, { ...base, interval }, tick, message.stream_version);
    },
  });
  const stream = () => physical.at(-1)!;
  const open = () => {
    stream().options.onOpen?.(stream().controller);
    stream().options.onControlMessage?.({ type: "subscribed", intervals: ["1h"], active_intervals: ["1h"] }, stream().controller);
  };
  const tick = (row: KlineBar, eventType: string, wire: Record<string, unknown>) => stream().options.onKline?.({
    interval: "1h", tick: row, message: { type: "kline", interval: "1h", data: row, event_type: eventType, stream_version: wire },
  }, stream().controller);
  const close = () => stream().options.onClose?.(new Event("close") as CloseEvent, stream().controller);
  return { manager, feed, series, recovery, reads, committed, open, tick, close };
}

const settle = () => new Promise<void>((resolve) => setImmediate(resolve));
const label = (recovery: KlineConsumerRecovery) => resolveKlineTransportStatus("live", {
  upstreamOffline: false, windowVisible: true, consumerRecoveryRequired: recovery.requiredFor("1h"),
});

test("a closed-only latest tail no longer pins the label once a fresh forming tick extends the range proof", async (t) => {
  const h = reconnectHarness();
  t.after(() => h.manager.closeAll());
  h.open();
  h.tick(forming(60_640), "bar.created", version(6, 6, SNAPSHOT_OBSERVED - 16_632));
  h.tick(forming(60_645), "bar.updated", version(7, 6, SNAPSHOT_OBSERVED));
  h.close();
  h.open();
  await settle(); await settle();
  // Each 10 s attempt reads the same valid range and the same closed-only tail.
  await h.recovery.recover(h.feed, () => true);
  assert.deepEqual(h.reads, ["range", "latest", "range", "latest"]);
  assert.equal(h.recovery.requiredFor("1h"), true, "the reproduced checkpoint is still pending");
  assert.equal(label(h.recovery), "reconnecting");
  assert.deepEqual(h.committed, [], "an unproven forming bucket publishes nothing");

  h.tick(forming(60_650), "bar.updated", version(8, 6, SNAPSHOT_OBSERVED + 1_200));
  assert.equal(h.recovery.requiredFor("1h"), false);
  assert.equal(label(h.recovery), "live");
  assert.deepEqual(h.committed.at(-1), closedRows.map((row) => row.time), "the verified closed snapshot is published once");
});

const unlinkedTicks: Array<[string, KlineBar, Record<string, unknown>]> = [
  ["a critical fact after the snapshot", forming(60_650), version(8, 7, SNAPSHOT_OBSERVED + 1_200)],
  ["a pre-snapshot", forming(60_650), version(6, 6, SNAPSHOT_OBSERVED - 1)],
  ["another bucket", { ...forming(60_650), time: (FORMING + HOUR) as EpochSeconds }, version(8, 6, SNAPSHOT_OBSERVED + 1_200)],
  ["another stream incarnation", forming(60_650), version(1, 0, SNAPSHOT_OBSERVED + 1_200, { generation: 2 })],
];
for (const [name, row, wire] of unlinkedTicks) {
  test(`${name} tick cannot complete the closed range proof`, async (t) => {
    const h = reconnectHarness();
    t.after(() => h.manager.closeAll());
    h.open();
    h.close();
    h.open();
    await settle(); await settle();
    assert.deepEqual(h.reads, ["range", "latest"], "the closed proof was read and its tail rejected");
    // Offered directly: the manager may already drop some of these rows.
    assert.equal(h.recovery.observeRealtime(h.feed, h.series, row, wire), false);
    assert.equal(h.recovery.requiredFor("1h"), true);
    assert.deepEqual(h.committed, []);
    // The same proof still accepts a linked row afterwards.
    assert.equal(h.recovery.observeRealtime(h.feed, h.series, forming(60_650), version(8, 6, SNAPSHOT_OBSERVED + 1_200)), true);
  });
}

test("a final row for the forming bucket is not forming proof", async (t) => {
  const h = reconnectHarness();
  t.after(() => h.manager.closeAll());
  h.open();
  h.close();
  h.open();
  await settle(); await settle();
  const closed = { ...forming(60_650), is_closed: true };
  assert.equal(h.recovery.observeRealtime(h.feed, h.series, closed, version(8, 6, SNAPSHOT_OBSERVED + 1_200)), false);
  assert.equal(h.recovery.requiredFor("1h"), true, "a closed bucket needs the strict range to include it");
});

test("a second disconnect discards the retained proof", async (t) => {
  const h = reconnectHarness();
  t.after(() => h.manager.closeAll());
  h.open();
  h.close();
  h.open();
  await settle(); await settle();
  h.close();
  h.open();
  h.tick(forming(60_650), "bar.updated", version(8, 6, SNAPSHOT_OBSERVED + 1_200));
  assert.equal(h.recovery.requiredFor("1h"), true, "the new gap owns a fresh readback");
  assert.deepEqual(h.committed, []);
});

test("navigation fences a retained proof", async (t) => {
  const h = reconnectHarness();
  t.after(() => h.manager.closeAll());
  h.open();
  h.close();
  h.open();
  await settle(); await settle();
  h.feed.beginEpoch(h.series);
  h.tick(forming(60_650), "bar.updated", version(8, 6, SNAPSHOT_OBSERVED + 1_200));
  assert.deepEqual(h.committed, []);
});
