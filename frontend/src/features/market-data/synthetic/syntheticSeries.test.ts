import assert from "node:assert/strict";
import test from "node:test";
import { adoptSynthetic, EMPTY_SYNTHETIC, syntheticRequest } from "./syntheticSeries.js";
import { SyntheticSeriesManager, type SyntheticSocket } from "./syntheticSeriesManager.js";
import { SyntheticChartBinding } from "./syntheticChartBinding.js";
import { BackendProjectionStore } from "../../chart-representation/backendProjectionStore.js";
import { SeriesWindowStore } from "../window/seriesWindowStore.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";
import { resolveBackendSyntheticEnabled } from "./backendSyntheticFeature.js";

const source = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const request = syntheticRequest(source, "renko", { mode: "traditional", boxSize: 2 }, 60, 120);
test("backend candidate rollout requires an explicit acceptance-build switch", () => {
  for (const value of [undefined, false, 0, "0", "true"]) assert.equal(resolveBackendSyntheticEnabled(value), false);
  for (const value of [true, 1, "1"]) assert.equal(resolveBackendSyntheticEnabled(value), true);
});
function row(ordinal: number, generation = "generation", close = 102 + ordinal * 2) {
  return { id: `series:${generation}:${ordinal}`, ordinal,
    time: { order: ordinal, sourceTime: 120, sourceOrdinal: ordinal },
    open: close - 2, high: close, low: close - 2, close,
    customValues: { chartProjection: { projectorId: "renko", sourceFromTime: 60, sourceToTime: 120, sourceOrdinal: ordinal, synthetic: true } } };
}
function snapshot(revision = 1, generation = "generation") {
  return { protocol: "candlescope.synthetic/1", type: "snapshot", series_id: "series",
    definition: { source: request.source, config: { ...request.config, algorithm: "close-source/1" }, anchor: 60, through: 120 },
    generation, revision, status: "ready", reason: null, from_index: 0, total: 3,
    rows: [row(0, generation), row(1, generation), row(2, generation)] };
}
class Socket implements SyntheticSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  closed = false;
  send(value: string) { this.sent.push(value); }
  close() { this.closed = true; this.onclose?.(); }
  receive(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }); }
}

test("same-time bricks survive immutable admission and ordinal tail replacement", () => {
  const first = adoptSynthetic(EMPTY_SYNTHETIC, snapshot(), request);
  assert.equal(first.rows.length, 3);
  assert.equal(new Set(first.rows.map(item => item.time && typeof item.time === "object" ? item.time.sourceTime : item.time)).size, 1);
  const changed = { ...snapshot(2), type: "patch", from_index: 1, delete_count: 2, total: 2, rows: [row(1)] };
  const second = adoptSynthetic(first, changed, request);
  assert.deepEqual(second.rows.map(item => item.ordinal), [0, 1]);
  assert.equal(first.rows.length, 3);
  assert.ok(Object.isFrozen(second.rows[1]?.time));
  assert.throws(() => { (second.rows[0] as { close: number }).close = 0; }, TypeError);
});

test("rejects wrong identity, missing revisions and old-generation patches", () => {
  const first = adoptSynthetic(EMPTY_SYNTHETIC, snapshot(), request);
  const patch = { ...snapshot(2), type: "patch", from_index: 0, delete_count: 3 };
  assert.throws(() => adoptSynthetic(first, { ...patch, generation: "old" }, request), /snapshot/);
  assert.throws(() => adoptSynthetic(first, { ...patch, revision: 3 }, request), /snapshot/);
  assert.throws(() => adoptSynthetic(first, snapshot(2), { ...request, anchor: 0 }), /identity/);
  assert.throws(() => adoptSynthetic(first, { ...snapshot(2), rows: [row(2), row(1), row(0)] }, request), /order/);
  assert.equal(adoptSynthetic(first, snapshot(1), request), first);
});

test("shared transport, independent leases and late-frame fencing", () => {
  const sockets: Socket[] = [];
  const manager = new SyntheticSeriesManager(() => { const socket = new Socket(); sockets.push(socket); return socket; });
  const left = manager.acquire(request), right = manager.acquire(request);
  assert.equal(sockets.length, 1);
  sockets[0]!.onopen?.();
  assert.deepEqual(JSON.parse(sockets[0]!.sent[0]!), request);
  sockets[0]!.receive(snapshot());
  assert.equal(left.getSnapshot(), right.getSnapshot());
  left.release();
  assert.equal(sockets[0]!.closed, false);
  sockets[0]!.receive({ ...snapshot(2), type: "patch", from_index: 2, delete_count: 1, rows: [row(2, "generation", 110)] });
  assert.equal(right.getSnapshot().rows.at(-1)?.close, 110);
  right.release();
  assert.equal(sockets[0]!.closed, true);
  sockets[0]!.receive(snapshot(3));
  assert.equal(manager.diagnostics().sharedSeries, 0);
  manager.closeAll();
});

test("backend renderer adapter consumes supplied prices without a local transform", () => {
  const sockets: Socket[] = [];
  const manager = new SyntheticSeriesManager(() => { const socket = new Socket(); sockets.push(socket); return socket; });
  const sourceRows = [{ time: 60, open: 100, high: 100, low: 100, close: 100 },
    { time: 120, open: 100, high: 106, low: 100, close: 106 }];
  const reader = new SeriesWindowStore({ seriesKey: buildSeriesWindowKey(source) });
  reader.replace(sourceRows);
  const binding = new SyntheticChartBinding(manager, source, reader, "renko", { mode: "traditional", boxSize: 2 });
  binding.start();
  const store = new BackendProjectionStore(binding);
  store.reset(sourceRows);
  assert.equal(store.displaySnapshot().length, 0);
  // Intentionally differs from the local fixed-box result (102/104/106).
  sockets[0]!.receive({ ...snapshot(), rows: [row(0, "generation", 202), row(1, "generation", 204), row(2, "generation", 206)] });
  store.applySourceDelta({ type: "replace" }, sourceRows);
  assert.deepEqual(store.displaySnapshot().map(item => item.close), [202, 204, 206]);
  const other = new SyntheticChartBinding(manager, source, reader, "renko", { mode: "traditional", boxSize: 2 });
  other.start();
  assert.equal(sockets.length, 1);
  assert.notEqual(other.configurationKey, binding.configurationKey,
    "renderer mappings must not reuse a closed binding after a same-series reader replacement");
  other.close();
  reader.applyRange([{ time: 0, open: 100, high: 100, low: 100, close: 100 }]);
  assert.equal(sockets[0]!.closed, true);
  sockets[0]!.receive(snapshot(99));
  assert.equal(binding.rows().length, 0);
  binding.close(); manager.closeAll();
});
