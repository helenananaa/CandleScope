import assert from "node:assert/strict";
import test from "node:test";
import { ReplayChartProjection } from "../replayChartProjection.js";
import { buildReplayViewerSeriesKey } from "../replayViewerProjection.js";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import type { ReplayRuntimeLifecycle } from "../useReplayRuntime.js";
import type { ReplayDisplayProjectionResponse } from "../replayDisplayProjection.js";
import { createReplayMarketDataManager } from "../replayDataContext.js";

const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 10));

test("same-market cells keep independent history windows while following one source", async () => {
  const manager = createReplayMarketDataManager();
  const listeners = new Set<() => void>();
  const bar = (time: number) => ({ time, open: 10, high: 12, low: 9, close: 11, volume: 1 });
  const source = new SeriesWindowStore({ intervalSeconds: 60, seriesKey: "replay-test" });
  source.replace([bar(600), bar(660)]);
  let store = { sessionConfig: { source_kind: "bar", base_interval: "1m", symbol: "BTCUSDT", exchange: "binance", market_type: "spot" },
    virtualTimeMs: 720_000, dataEpoch: "epoch", sessionId: "session", generation: 1 };
  const lifecycle = { store: { seriesStore: source }, getSnapshot: () => ({ store }),
    subscribe: (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); },
  } as unknown as ReplayRuntimeLifecycle;
  const past = new ReplayChartProjection(lifecycle, "track-1", "1m", undefined, undefined, manager.replay, "run-a");
  const latest = new ReplayChartProjection(lifecycle, "track-1", "1m", undefined, undefined, manager.replay, "run-b");
  assert.equal(past.seriesStore.seriesKey, buildReplayViewerSeriesKey(source, "1m"),
    "target identity exists before first render/retain so viewport hand-off is not superseded");
  const coarse = new ReplayChartProjection(lifecycle, "track-1", "5m");
  assert.equal(coarse.seriesStore.seriesKey, buildReplayViewerSeriesKey(source, "5m"));
  assert.notEqual(coarse.seriesStore.seriesKey, past.seriesStore.seriesKey);
  const releasePast = past.retain();
  const releaseLatest = latest.retain();
  assert.equal(manager.diagnostics().replay.activeSequences, 2);
  assert.deepEqual(manager.diagnostics().replay.sequences.map(item => item.identity?.runId), ["run-a", "run-b"]);
  past.seriesStore.maxBars = 2;
  past.seriesStore.applyRange([bar(300), bar(360)]);
  assert.equal(past.seriesStore.rightTruncated, true);
  const historical = past.seriesStore.snapshot();
  source.applyRange([bar(720)]);
  store = { ...store, virtualTimeMs: 780_000 };
  listeners.forEach((notify) => notify()); await settle();
  assert.deepEqual(past.seriesStore.snapshot(), historical);
  assert.equal(latest.seriesStore.snapshot().at(-1)?.time, 720);
  const frozen = latest.seriesStore.snapshot();
  manager.closeAll();
  source.applyRange([bar(780)]);
  listeners.forEach(notify => notify()); await settle();
  assert.deepEqual(latest.seriesStore.snapshot(), frozen, "manager shutdown also fences local projection updates");
  releasePast(); releaseLatest();
  assert.equal(manager.diagnostics().replay.activeSequences, 0);
  assert.equal(store.virtualTimeMs, 780_000, "display reads must not advance the replay clock");
  manager.closeAll();
});

test("shared coarse charts serialize requests, invalidate old epochs and release independently", async () => {
  let notify = () => {};
  let store = { sessionConfig: { source_kind: "bar", base_interval: "1m", symbol: "BTCUSDT", exchange: "binance", market_type: "spot" },
    virtualTimeMs: 100_000, dataEpoch: "epoch-1", sessionId: "session", generation: 1 };
  const source = new SeriesWindowStore();
  const lifecycle = { store: { seriesStore: source }, getSnapshot: () => ({ store }),
    subscribe: (listener: () => void) => { notify = listener; return () => { notify = () => {}; }; },
  } as unknown as ReplayRuntimeLifecycle;
  const requests: { signal?: AbortSignal; resolve: (value: ReplayDisplayProjectionResponse) => void; reject: (error: Error) => void }[] = [];
  const projection = new ReplayChartProjection(lifecycle, "track-1", "15m", {
    displayProjectionBySession: (_session, _binding, signal) => new Promise((resolve, reject) => {
      requests.push({ ...(signal ? { signal } : {}), resolve, reject });
    }),
  });
  const releaseA = projection.retain();
  const releaseB = projection.retain();
  assert.equal(requests.length, 1);
  store = { ...store, virtualTimeMs: 101_000 };
  notify(); await settle();
  assert.equal(requests.length, 1, "fast clock does not abort/starve the in-flight request");
  releaseA(); releaseA();
  assert.equal(requests[0]!.signal?.aborted, false);
  store = { ...store, generation: 2, dataEpoch: "epoch-2" };
  notify(); await settle();
  assert.equal(requests[0]!.signal?.aborted, true);
  assert.equal(requests.length, 2);
  requests[0]!.resolve({} as ReplayDisplayProjectionResponse);
  await settle();
  assert.equal(projection.getSnapshot().error, null, "obsolete data is ignored before decoding");
  assert.equal(projection.seriesStore.barCount, 0);
  requests[1]!.reject(new Error("history offline")); await settle();
  assert.equal(projection.getSnapshot().error, "history offline");
  projection.retry();
  assert.equal(requests.length, 3, "paused charts can explicitly recover without a new clock tick");
  releaseB();
  assert.equal(requests[2]!.signal?.aborted, true);
});


test("empty multi-chart projections publish independent bootstrap cursors and invalidate them on epoch changes", async () => {
  const listeners = new Set<() => void>();
  let store = { sessionConfig: { source_kind: "bar", base_interval: "1m", symbol: "BTCUSDT", exchange: "binance", market_type: "spot" },
    virtualTimeMs: 1791545339999, dataEpoch: "epoch-1", sessionId: "session", generation: 1 };
  const lifecycle = { store: { seriesStore: new SeriesWindowStore() }, getSnapshot: () => ({ store }),
    subscribe: (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); },
  } as unknown as ReplayRuntimeLifecycle;
  const cursors = { "4h": 1791532800000, "1d": 1791504000000 };
  let offline = false;
  const api = { displayProjectionBySession: async (_session: string, binding: { displayInterval: string }) => {
    if (offline) throw new Error("offline");
    return { session_id: store.sessionId, track_id: "track-1", data_epoch: store.dataEpoch,
      display_interval: binding.displayInterval, revealed_boundary_ms: store.virtualTimeMs,
      identity: { symbol: "BTCUSDT", exchange: "binance", market_type: "spot" }, bars: [],
      history_before_ms: cursors[binding.displayInterval as keyof typeof cursors],
    } as unknown as ReplayDisplayProjectionResponse;
  } };
  const cells = Object.keys(cursors).map(interval => new ReplayChartProjection(lifecycle, "track-1", interval, api));
  const releases = cells.map(cell => cell.retain());
  await settle();
  assert.deepEqual(cells.map(cell => cell.getSnapshot().historyBootstrapBeforeMs), Object.values(cursors));
  assert.ok(cells.every(cell => cell.seriesStore.isEmpty() && !cell.getSnapshot().loading));
  offline = true;
  store = { ...store, generation: 2, dataEpoch: "epoch-2" };
  listeners.forEach(notify => notify()); await settle();
  assert.ok(cells.every(cell => cell.getSnapshot().historyBootstrapBeforeMs == null));
  releases.forEach(release => release());
});

test("production tape cells use server prefixes, publish sampled boundaries and restore their own history window", async () => {
  const epoch = `sha256:${"a".repeat(64)}`;
  const historyEpoch = `sha256:${"b".repeat(64)}`;
  const start = 1_800_000_000_000;
  const boundary = start + 239999;
  const source = new SeriesWindowStore({ seriesKey: "execution-source" });
  source.replace([{ time: start / 1000, open: 999, high: 999, low: 999, close: 999, volume: 999 }]);
  const untouched = JSON.stringify(source.snapshot());
  const listeners = new Set<() => void>();
  let sequence = 7, generation = 1, authoritative = true, held = true;
  const pending: (() => void)[] = [];
  const requests: { sequence: number; signal: AbortSignal | null | undefined }[] = [];
  const lifecycle = { store: { seriesStore: source, getAuthoritySnapshot: () => ({ sessionId: "adapter",
    sourceSequence: sequence, generation, virtualTimeMs: boundary, hasAuthoritativeSnapshot: authoritative }) },
    getSnapshot: () => ({ store: { sessionConfig: { source_kind: "agg_trade", base_interval: "1m",
      symbol: "LTCUSDT", exchange: "binance", market_type: "futures" },
    virtualTimeMs: boundary, sourceSequence: sequence, dataEpoch: epoch, sessionId: "adapter", generation } }),
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
  } as unknown as ReplayRuntimeLifecycle;
  const fetcher: typeof fetch = async (input, options) => {
    const url = new URL(String(input), "http://fixture");
    assert.ok(url.pathname.endsWith("/tape-projection"));
    const selected = Number(url.searchParams.get("source_sequence"));
    requests.push({ sequence: selected, signal: options?.signal });
    if (held) await new Promise<void>(resolve => pending.push(resolve));
    return Response.json({ protocol: "replay.v3", schema_version: "replay.tape-projection.v1", run_id: "run",
      session_id: "adapter", track_id: "track-1", data_epoch: epoch, display_interval: "1m",
      identity: { exchange: "binance", market_type: "futures", symbol: "LTCUSDT",
        source_kind: "AGG_TRADE", base_interval: "1m", display_interval: "1m" },
      history_scope: "FROZEN_WARMUP_AND_TAPE", history_epoch: historyEpoch,
      history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 2,
        visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null }, visible_history_rows: 4,
        effective_warmup_bars: 2, forward_cache_ms: 60000, interval_ms: 60000, policy_hash: epoch },
      context_prepared_before_ms: 0, context_target_before_ms: 0, incomplete_context_buckets: [],
      revealed_boundary_ms: boundary, source_sequence: selected, target_sequence: selected, prepared_sequence: selected,
      before_ms: null, history_boundary_ms: start, next_before_ms: start, has_more: false, status: "ready",
      bars: Array.from({ length: 4 }, (_, index) => ({ open_time_ms: start + index * 60000,
        close_time_ms: start + index * 60000 + 59999, open: "10", high: "12", low: "9", close: "11", volume: String(selected),
        quote_volume: null, trades: null, taker_buy_base: null, taker_buy_quote: null,
        first_base_open_ms: start + index * 60000, last_base_open_ms: start + index * 60000,
        component_count: 1, expected_components: 1, is_closed: index < 3, synthetic: false })) });
  };
  const past = new ReplayChartProjection(lifecycle, "track-1", "1m", undefined, fetcher);
  const latest = new ReplayChartProjection(lifecycle, "track-1", "1m", undefined, fetcher);
  const releases = [past.retain(), latest.retain()];
  const notify = () => listeners.forEach(listener => listener());
  const until = async (predicate: () => boolean) => {
    const deadline = performance.now() + 2500;
    while (!predicate()) { assert.ok(performance.now() < deadline, "cell did not settle"); await settle(); }
  };
  try {
    assert.equal(requests.length, 2);
    assert.equal(past.seriesStore.barCount, 0, "local execution rows cannot bypass the server projection");
    sequence = 8; notify(); await settle();
    assert.equal(requests.length, 2);
    assert.ok(requests.every(request => !request.signal?.aborted));
    held = false; pending.splice(0).forEach(resolve => resolve());
    await until(() => [past, latest].every(cell => cell.getSnapshot().tapeObservation?.sourceSequence === 8));
    assert.equal(latest.seriesStore.last()?.close, 11);
    assert.equal(latest.getSnapshot().tapeObservation?.historyEpoch, historyEpoch);
    past.seriesStore.maxBars = 4;
    past.seriesStore.applyRange([{ time: start / 1000 - 60, open: 5, high: 5, low: 5, close: 5, volume: 1 }]);
    assert.equal(past.seriesStore.rightTruncated, true);
    const historical = JSON.stringify(past.seriesStore.snapshot());
    sequence = 9; notify();
    await until(() => latest.getSnapshot().tapeObservation?.sourceSequence === 9);
    assert.equal(JSON.stringify(past.seriesStore.snapshot()), historical);
    assert.equal(past.getSnapshot().tapeObservation?.sourceSequence, 8);
    assert.equal(await past.restoreLatest(), true);
    assert.equal(past.getSnapshot().tapeObservation?.sourceSequence, 9);
    assert.equal(past.seriesStore.rightTruncated, false);
    authoritative = false; notify();
    await until(() => past.seriesStore.isEmpty() && latest.seriesStore.isEmpty());
    assert.equal(past.getSnapshot().tapeObservation, null);
    authoritative = true; generation++; sequence = 2; notify();
    await until(() => past.getSnapshot().tapeObservation?.sourceSequence === 2);
    assert.equal(JSON.stringify(source.snapshot()), untouched);
  } finally { releases.forEach(release => release()); }
  assert.equal(listeners.size, 0);
});
