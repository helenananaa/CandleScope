import assert from "node:assert/strict";
import test from "node:test";
import { adoptSynthetic, EMPTY_SYNTHETIC, syntheticRequest, type SyntheticRequest } from "./syntheticSeries.js";
import { SyntheticSeriesManager, type SyntheticSocket } from "./syntheticSeriesManager.js";
import { SyntheticChartBinding } from "./syntheticChartBinding.js";
import { BackendProjectionStore } from "../../chart-representation/backendProjectionStore.js";
import { SeriesWindowStore } from "../window/seriesWindowStore.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";
import { resolveBackendSyntheticEnabled } from "./backendSyntheticFeature.js";
import { backendSyntheticSourceFor } from "../../market-chart-platform/marketChartSurfaceModel.js";
import { createFrozenSnapshotSource, createRunResultSource } from "../../market-chart-platform/marketChartSourceRuntime.js";
import { replaySyntheticSource } from "../../replay/replaySyntheticSource.js";
import { capturedSyntheticSource } from "./capturedSyntheticSource.js";

const source = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const request = syntheticRequest(source, "renko", { mode: "traditional", boxSize: 2 }, 60, 120);
test("backend computation defaults on and supports an explicit rollout rollback", () => {
  for (const value of [false, 0, "0", "true"]) assert.equal(resolveBackendSyntheticEnabled(value), false);
  for (const value of [undefined, true, 1, "1"]) assert.equal(resolveBackendSyntheticEnabled(value), true);
});
function row(ordinal: number, generation = "generation", close = 102 + ordinal * 2) {
  return { id: `series:${generation}:${ordinal}`, ordinal,
    time: { order: ordinal, sourceTime: 120, sourceOrdinal: ordinal },
    open: close - 2, high: close, low: close - 2, close,
    customValues: { renko: { direction: "up", boxSize: 2, source: "close", wickPolicy: "none" },
      chartProjection: { projectorId: "renko", sourceFromTime: 60, sourceToTime: 120, sourceOrdinal: ordinal, synthetic: true } } };
}
function snapshot(revision = 1, generation = "generation") {
  return { protocol: "candlescope.synthetic/1", type: "snapshot", series_id: "series",
    definition: { source: request.source, config: { ...request.config, algorithm: "close-source/2" }, anchor: 60, through: 120 },
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

test("complete-window chunks publish atomically and keep more than 5000 bricks", () => {
  const socket = new Socket(), manager = new SyntheticSeriesManager(() => socket);
  const view = manager.acquire(request);
  const rows = Array.from({ length: 6000 }, (_, index) => row(index));
  socket.receive({ ...snapshot(), type: "snapshot_chunk", rows: rows.slice(0, 3000), total: 6000, complete: false });
  assert.equal(view.getSnapshot().rows.length, 0);
  assert.equal(view.getSnapshot().status, "preparing");
  socket.receive({ ...snapshot(), type: "snapshot_chunk", from_index: 3000, rows: rows.slice(3000), total: 6000, complete: true });
  assert.equal(view.getSnapshot().rows.length, 6000);
  assert.equal(view.getSnapshot().from, 0);
  socket.receive({ ...snapshot(2), type: "patch", from_index: 6000, delete_count: 0, total: 6001, rows: [row(6000)] });
  assert.equal(view.getSnapshot().rows.length, 6001);
  assert.equal(view.getSnapshot().rows[0]?.ordinal, 0);
  view.release(); manager.closeAll();
});

test("mixed-generation chunks fail closed without publishing a partial series", () => {
  const socket = new Socket(), manager = new SyntheticSeriesManager(() => socket);
  const view = manager.acquire(request);
  socket.receive({ ...snapshot(), type: "snapshot_chunk", rows: [row(0)], complete: false });
  socket.receive({ ...snapshot(2, "changed"), type: "snapshot_chunk", from_index: 1,
    rows: [row(1, "changed"), row(2, "changed")], complete: true });
  assert.equal(view.getSnapshot().rows.length, 0);
  assert.equal(view.getSnapshot().status, "stale");
  assert.equal(socket.closed, true);
  view.release(); manager.closeAll();
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

test("frozen and saved-result charts select backend references without sending browser prices", () => {
  const bars = [{ time: 60, open: 100, high: 100, low: 100, close: 100 },
    { time: 120, open: 106, high: 106, low: 106, close: 106 }];
  const frozen = createFrozenSnapshotSource({ session: source, datasetId: "dataset", dataEpoch: "epoch",
    snapshotHash: "snapshot", runId: "run", chartHash: "chart", bars });
  const result = createRunResultSource({ session: source, runId: "run", configHash: "config",
    reportHash: "report", chartHash: "chart", bars });
  const sockets: Socket[] = [], manager = new SyntheticSeriesManager(() => {
    const socket = new Socket(); sockets.push(socket); return socket;
  });
  const bindings = [frozen, result].map(chart => {
    const backend = backendSyntheticSourceFor(chart);
    assert.ok(backend);
    const binding = new SyntheticChartBinding(manager, backend, chart.marketData.view.seriesStore!, "renko", { boxSize: 2 });
    binding.start(); return binding;
  });
  assert.equal(sockets.length, 2, "different frozen/result contracts cannot share a live-series identity");
  for (const socket of sockets) socket.onopen?.();
  const requests = sockets.map(socket => JSON.parse(socket.sent[0]!) as SyntheticRequest & { bars?: unknown; rows?: unknown; ohlcv?: unknown });
  assert.deepEqual(requests.map(request => request.origin?.kind), ["FROZEN_SNAPSHOT", "RUN_RESULT"]);
  assert.deepEqual(requests[0]!.origin, frozen.syntheticOrigin);
  assert.deepEqual(requests[1]!.origin, result.syntheticOrigin);
  assert.ok(requests.every(request => !request.bars && !request.rows && !request.ohlcv));
  assert.throws(() => adoptSynthetic(EMPTY_SYNTHETIC, snapshot(), requests[0]!), /origin/);
  const message = { ...snapshot(), definition: { ...snapshot().definition, origin: requests[0]!.origin } };
  assert.equal(adoptSynthetic(EMPTY_SYNTHETIC, message, requests[0]!).rows.length, 3);
  assert.throws(() => adoptSynthetic(EMPTY_SYNTHETIC, message, requests[1]!), /origin/);
  bindings.forEach(binding => binding.close()); frozen.dispose(); result.dispose(); manager.closeAll();
});

test("replay cursor changes invalidate same-window series and unavailable prefixes never select local math", () => {
  const input = { market: source, seriesKey: "replay-window", sessionId: "session", trackId: "track",
    dataEpoch: "revision", revealedBoundaryMs: 120_000, sourceSequence: 1 };
  const first = replaySyntheticSource(input)!;
  const later = replaySyntheticSource({ ...input, sourceSequence: 2 })!;
  const earlier = replaySyntheticSource({ ...input, revealedBoundaryMs: 119_999, sourceSequence: 0 })!;
  const definitions = [first, later, earlier].map(source => syntheticRequest(source, "renko", {}, 60, 120));
  assert.equal(new Set(definitions.map(request => JSON.stringify(request))).size, 3);
  assert.deepEqual(definitions.map(request => request.origin?.kind), ["REPLAY", "REPLAY", "REPLAY"]);
  const unavailable = replaySyntheticSource({ ...input, revealedBoundaryMs: null })!;
  assert.ok(unavailable, "loading replay must still choose the backend renderer path");
  const reader = new SeriesWindowStore({ seriesKey: input.seriesKey });
  reader.replace([{ time: 60, open: 100, high: 100, low: 100, close: 100 }]);
  let opened = 0;
  const manager = new SyntheticSeriesManager(() => { opened++; return new Socket(); });
  const binding = new SyntheticChartBinding(manager, unavailable, reader, "renko", {});
  binding.start();
  assert.equal(opened, 0); assert.equal(binding.status(), "preparing");
  binding.close(); manager.closeAll();
});

test("browser-owned historical prefixes register once, re-register on reconnect and fence rewinds", async () => {
  const requests: Array<{ rows: unknown[]; cutoff_ms: number }> = [];
  const sockets: Socket[] = [];
  const fetcher: typeof fetch = async (_url, options) => {
    const body = JSON.parse(String(options?.body)) as { rows: unknown[]; cutoff_ms: number };
    requests.push(body);
    return new Response(JSON.stringify({ kind: "CAPTURED_WINDOW", capture_id: String(body.rows.length).repeat(64), cutoff_ms: body.cutoff_ms }));
  };
  const manager = new SyntheticSeriesManager(() => { const socket = new Socket(); sockets.push(socket); return socket; }, fetcher);
  const reader = new SeriesWindowStore({ seriesKey: "study" });
  const rows = [{ time: 60, open: 100, high: 100, low: 100, close: 100 }, { time: 120, open: 106, high: 106, low: 106, close: 106 }];
  reader.replace(rows);
  const binding = new SyntheticChartBinding(manager, capturedSyntheticSource(source, "study", "study:input", 120_000)!, reader, "renko", {});
  const settle = () => new Promise(resolve => setTimeout(resolve, 10));
  binding.start(); await settle();
  assert.equal(requests.length, 1); assert.equal(requests[0]?.rows.length, 2);
  sockets[0]!.onopen?.();
  const wire = JSON.parse(sockets[0]!.sent[0]!) as SyntheticRequest;
  assert.equal(wire.origin?.kind, "CAPTURED_WINDOW"); assert.equal(Object.hasOwn(wire, "rows"), false);
  sockets[0]!.close(); await new Promise(resolve => setTimeout(resolve, 550));
  assert.equal(requests.length, 2, "reconnect restores an evicted or restarted backend capture");
  assert.equal(sockets.length, 2);
  reader.replace(rows.slice(0, 1)); await settle();
  assert.equal(requests.at(-1)?.rows.length, 1, "rewind cannot register hidden future rows");
  assert.equal(sockets[1]!.closed, true);
  sockets[1]!.receive(snapshot()); assert.equal(binding.rows().length, 0);
  binding.close(); manager.closeAll(); assert.equal(manager.diagnostics().sharedSeries, 0);
});

test("disposal during captured-prefix registration cannot acquire a late transport", async () => {
  let resolve!: (response: Response) => void;
  const fetcher: typeof fetch = () => new Promise<Response>(done => { resolve = done; });
  let sockets = 0;
  const manager = new SyntheticSeriesManager(() => { sockets++; return new Socket(); }, fetcher);
  const reader = new SeriesWindowStore({ seriesKey: "study" });
  reader.replace([{ time: 60, open: 100, high: 100, low: 100, close: 100 }]);
  const binding = new SyntheticChartBinding(manager, capturedSyntheticSource(source, "study", "study:input", 60_000)!, reader, "renko", {});
  binding.start(); binding.close(); manager.closeAll();
  resolve(new Response(JSON.stringify({ kind: "CAPTURED_WINDOW", capture_id: "a".repeat(64), cutoff_ms: 60_000 })));
  await new Promise(done => setTimeout(done, 10));
  assert.equal(sockets, 0); assert.equal(manager.diagnostics().sharedSeries, 0);
});
