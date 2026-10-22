import { act, useLayoutEffect, useMemo, useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { createChart, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { useProvidedBarsIndicatorRuntime } from "../../features/indicators/useProvidedBarsIndicatorRuntime.js";
import type { IndicatorDefinition } from "../../features/indicators/indicatorTypes.js";
import type { IndicatorRuntime } from "../../features/indicators/indicatorRuntimeContract.js";
import type { ActiveIndicatorPersistence } from "../../features/indicators/activeIndicatorStore.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";
import { useReplayCanonicalIndicatorCompute } from "../../features/replay/useReplayCanonicalIndicatorCompute.js";
import { useReplayReviewIndicators } from "../../features/replay/useReplayReviewIndicators.js";
import { useReplaySharedIndicatorRuntime, type ReplaySharedIndicatorRuntime } from "../../features/replay/useReplaySharedIndicatorRuntime.js";
import type { ReplayRuntime, ReplayRuntimeLifecycle } from "../../features/replay/useReplayRuntime.js";
import type { ReplayViewerRuntime } from "../../features/replay/useReplayViewerRuntime.js";
import type { ReplayTapeViewerObservation } from "../../features/replay/replayTapeViewer.js";
import { useReplayChartProjection } from "../../features/replay/replayChartProjection.js";
import { ReplayCanonicalIndicators, type ReplayCanonicalBinding } from "../../features/replay/replayCanonicalIndicators.js";
import { replayDisplayBarToKline } from "../../features/replay/replaySeriesProjection.js";
import { createReplayHistoryProvider } from "../../features/replay/replayTapeHistoryProvider.js";
import { ReplayReviewHistory } from "../../features/replay/replayReviewHistory.js";
import type { ReplayReviewHistoryState } from "../../features/replay/replayReviewHistory.js";
import type { ReplayDisplayBar } from "../../features/replay/replayTypes.js";
import { ViewportController } from "../viewportController.js";
import { renderSeriesDelta } from "../seriesDeltaRenderer.js";
import { structuralMock } from "../../test/testHelpers.js";
import fixture from "../../features/replay/__tests__/fixtures/builtin-parity.json";

const epoch = `sha256:${"a".repeat(64)}` as const, historyEpoch = `sha256:${"b".repeat(64)}` as const;
const identity = { exchange: "fixture", market_type: "spot", symbol: "FIXTURE", source_kind: "BAR", base_interval: "1m", display_interval: "1m" } as const;
const reference = fixture.cases.find(item => item.name === "RSI" && Object.keys(item.params).length === 0)!;
const rows: ReplayDisplayBar[] = fixture.bars.map(row => ({ open_time_ms: row.time * 1000, close_time_ms: row.time * 1000 + 59999,
  open: String(row.open), high: String(row.high), low: String(row.low), close: String(row.close), volume: String(row.volume),
  quote_volume: null, trades: null, taker_buy_base: null, taker_buy_quote: null,
  first_base_open_ms: row.time * 1000, last_base_open_ms: row.time * 1000, component_count: 1, expected_components: 1,
  is_closed: true, synthetic: false }));
const definitions = [{ id: "rsi", engineName: "RSI", visible: true, params: { period: 14 } }];
const persistence: ActiveIndicatorPersistence = { controlled: true, load: () => definitions, save: () => undefined };
const assert = (condition: unknown, message: string) => { if (!condition) throw new Error(message); };

/** Exercise the real browser fetch receiver and HTTP, without replacing fetch. */
export async function checkNativeCanonicalTransport() {
  const store = new SeriesWindowStore(); store.replace(rows.slice(47, 50).map(replayDisplayBarToKline));
  const binding: ReplayCanonicalBinding = { sessionId: "native-fetch", trackId: "track-1", dataEpoch: epoch,
    historyEpoch, revealedBoundaryMs: rows.at(-1)!.close_time_ms, identity };
  const source = new ReplayCanonicalIndicators(store, () => binding, () => {});
  const result = await source.compute({ jobs: [{ clientId: "rsi", jobKey: "native", request: {
    mode: "builtin", name: "RSI", params: {}, exchange: "fixture", marketType: "spot", symbol: "FIXTURE", interval: "1m",
    ohlcv: fixture.bars.slice(47, 50),
  } }] });
  const expected = reference.canonical.find(item => item.prefix_count === 47)!.result.payload.lines[0]!.data;
  assert(result.ok && JSON.stringify(result.results[0]?.payload.lines[0]?.data) === JSON.stringify(expected),
    `native canonical transport failed: ${JSON.stringify(result)}`);
  return { name: "canonical indicator uses native browser fetch over HTTP", status: "PASS" };
}

/** Real React lifecycle + transport/parser + Python kernel outputs. No replay server/account writes. */
export async function checkCanonicalReplayIndicators() {
  const oldFetch = globalThis.fetch;
  const store = new SeriesWindowStore({ seriesKey: "canonical" });
  store.replace(rows.slice(47, 50).map(replayDisplayBarToKline));
  let posts = 0, gets = 0, cancellations = 0, block = false;
  let latest: IndicatorRuntime | null = null;
  let source: ReplayCanonicalBinding = { sessionId: "adapter", trackId: "track-1", dataEpoch: epoch,
    revealedBoundaryMs: rows.at(-1)!.close_time_ms, identity };
  globalThis.fetch = async (input, options) => {
    const url = new URL(String(input), location.href);
    if (url.pathname.endsWith("/history")) {
      gets++;
      return Response.json({ protocol: "replay.v3", schema_version: "replay.history.v3", run_id: "fixture",
        session_id: "adapter", track_id: "track-1", identity, data_epoch: epoch, history_epoch: historyEpoch,
        history_boundary_ms: rows[0]!.open_time_ms, revealed_boundary_ms: Number(url.searchParams.get("revealed_boundary_ms")),
        history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 2,
          visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null }, visible_history_rows: 128,
          effective_warmup_bars: 2, forward_cache_ms: 86400000, interval_ms: 60000, policy_hash: epoch },
        bars: store.snapshot().map(bar => rows.find(row => row.open_time_ms === Number(bar.time) * 1000)),
        excluded_ranges: [], next_before_ms: Number(store.first()!.time) * 1000, has_more: false });
    }
    assert(url.pathname.endsWith("/indicator-compute"), `unexpected live endpoint: ${url}`);
    posts++;
    if (block) return await new Promise<Response>((_resolve, reject) => {
      const cancel = () => { cancellations++; reject(new DOMException("observer left", "AbortError")); };
      options!.signal!.addEventListener("abort", cancel, { once: true });
      if (options!.signal!.aborted) cancel();
    });
    const request = JSON.parse(String(options?.body)) as { bars: ReplayDisplayBar[]; history_epoch: string | null };
    if (!request.history_epoch) return Response.json({ error: { code: "HISTORY_EPOCH_MISMATCH", message: "reload" } }, { status: 409 });
    const start = fixture.bars.findIndex(bar => bar.time * 1000 === request.bars[0]!.open_time_ms);
    const example = reference.canonical.find(item => item.prefix_count === start)!;
    assert(!!example, `fixture has no prefix ${start}`);
    const data = reference.outputs.rsi!.filter(point => point.time * 1000 >= request.bars[0]!.open_time_ms
      && point.time * 1000 <= request.bars.at(-1)!.open_time_ms);
    const payload = { ...example.result.payload,
      lines: example.result.payload.lines.map(line => ({ ...line, data })),
      series: example.result.payload.series.map(series => ({ ...series, data })) };
    return Response.json({ ...example.result, payload, protocol: "replay.v3", status: "ready",
      seed: { session_id: "adapter", track_id: "track-1", data_epoch: epoch, history_epoch: historyEpoch, identity } });
  };
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  function Training({ scope }: { scope: string }) {
    const version = useSyncExternalStore(listener => store.subscribe(listener), () => store.version);
    const bars = useMemo(() => { void version; return store.snapshot().map(row => ({ ...row })); }, [version]);
    const canonical = useReplayCanonicalIndicatorCompute(scope, store, source);
    const key = `${scope}|${canonical.sourceKey}`;
    const meta = useMemo(() => ({ version, status: "ready", committedAt: null, source: "replay-indicator-revealed-prefix" }), [version]);
    const runtime = useProvidedBarsIndicatorRuntime({ bars, computeBatch: canonical.compute, persistence, chartDataMeta: meta,
      datasetKey: key, sourceScopeKey: key, sourceOrdinal: source.revealedBoundaryMs, seriesReady: version,
      visibleThroughSeconds: source.revealedBoundaryMs / 1000, exchange: "fixture", marketType: "spot", symbol: "FIXTURE", interval: "1m" });
    useLayoutEffect(() => { latest = runtime; });
    return <output>{runtime.status.computing ? "computing" : "idle"}</output>;
  }
  function Review({ scope }: { scope: string }) {
    const runtime = useReplayReviewIndicators({ seriesStore: store, requestedKey: scope, loadedKey: scope,
      cursorMs: source.revealedBoundaryMs, sourceBinding: { ...source, forceInitialRefresh: true }, definitions,
      exchange: "fixture", marketType: "spot", symbol: "FIXTURE", interval: "1m" });
    useLayoutEffect(() => { latest = runtime; });
    return <output>{runtime.status.computing ? "computing" : "idle"}</output>;
  }
  const samples: unknown[] = [];
  const settle = async (label: string) => {
    for (let i = 0; i < 60; i++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
      const current = latest as IndicatorRuntime | null;
      const points = current?.view.activeIndicators[0]?.lines?.[0]?.data;
      const expected = reference.outputs.rsi!.filter(point => store.hasTime(point.time));
      if (!current?.status.computing && JSON.stringify(points) === JSON.stringify(expected)) {
        samples.push({ label, posts, gets, points: points?.length, last: points?.at(-1) }); return;
      }
    }
    throw new Error(`${label} did not settle: ${JSON.stringify({ posts, gets, latest })}`);
  };
  try {
    await act(async () => root.render(<Training scope="training" />));
    await settle("old epoch reload");
    assert(gets === 1 && posts <= 3, "cold epoch caused repeated history reloads");
    const initialized = posts;
    await act(async () => { store.replace(rows.slice(47).map(replayDisplayBarToKline)); });
    await settle("forward append uses shared display anchors");
    assert(posts > initialized && gets === 1, "display append must consult shared anchors without reloading history");
    await act(async () => { store.replace(rows.slice(110).map(replayDisplayBarToKline)); });
    await settle("short independent window");
    await act(async () => root.render(<Review scope="review-1" />));
    await settle("review canonical reload");
    source = { ...source, revealedBoundaryMs: rows[31]!.close_time_ms };
    await act(async () => { store.replace(rows.slice(1, 32).map(replayDisplayBarToKline)); root.render(<Review scope="review-earlier" />); });
    await settle("earlier review event");
    block = true;
    await act(async () => root.render(<Review scope="review-preparing" />));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)); });
    const pendingPane = (latest as IndicatorRuntime | null)?.view.subPanes[0];
    assert(pendingPane?.id === "separate-rsi" && pendingPane.lines.length === 0 && pendingPane.statusText,
      "review dropped its configured pane while canonical calculation was pending");
    samples.push({ label: "review preparation visible", id: pendingPane!.id, status: pendingPane!.statusText });
    block = false;
    await act(async () => root.render(<Review scope="review-retry" />));
    await settle("review retry preserves pane identity");
    const readyPane = (latest as IndicatorRuntime | null)?.view.subPanes[0];
    assert(readyPane?.id === pendingPane!.id && !readyPane.statusText, "review preparation did not settle into its existing pane");
    block = true;
    await act(async () => root.render(<Training scope="pending-unmount" />));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)); });
    await act(async () => root.unmount());
    assert(cancellations === 2, `review switch or unmount left a pending computation: ${cancellations}`);
    return { name: "canonical indicator transport with real React training/review lifecycles", status: "PASS", samples, cancellations };
  } finally { await act(async () => root.unmount()); host.remove(); globalThis.fetch = oldFetch; }
}

export async function checkCanonicalCorrectionViewport() {
  const canvas = document.createElement("div"); document.body.append(canvas);
  const chart = createChart(canvas, { width: 600, height: 240 });
  const series = chart.addSeries(LineSeries), store = new SeriesWindowStore();
  const toPoint = (row: KlineBar) => ({ time: Number(row.time) as UTCTimestamp, value: Number(row.close) });
  const original = rows.slice(47, 100).map(replayDisplayBarToKline);
  store.replace(original); series.setData(original.map(toPoint));
  const controller = new ViewportController({ chartProvider: () => structuralMock(chart) });
  try {
    controller.restoreProjectionRange({ from: 20, to: 40 }, { immediate: true, freezeOnNewBars: true });
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const anchor = Number(original[30]!.time) as UTCTimestamp, before = chart.timeScale().timeToCoordinate(anchor);
    const delta = store.correctWindow(original.filter((_row, index) => index !== 1).map(row => ({ ...row, close: Number(row.close) + 1 })));
    renderSeriesDelta({ series, delta, store, previousRows: original,
      viewportController: structuralMock(controller), toPoint });
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const after = chart.timeScale().timeToCoordinate(anchor);
    assert(before !== null && after !== null && Math.abs(before - after) < 0.01, `history correction shifted chart: ${before} -> ${after}`);
    return { name: "canonical price/gap correction preserves real chart viewport", status: "PASS", before, after };
  } finally { chart.remove(); canvas.remove(); }
}

export async function checkReviewHistoryViewport(sourceKind: "BAR" | "AGG_TRADE" = "BAR") {
  const all = Array.from({ length: 700 }, (_, index) => ({ ...rows[index % rows.length]!,
    open_time_ms: rows[0]!.open_time_ms + index * 60_000, close_time_ms: rows[0]!.open_time_ms + index * 60_000 + 59_999,
    first_base_open_ms: rows[0]!.open_time_ms + index * 60_000, last_base_open_ms: rows[0]!.open_time_ms + index * 60_000 }));
  if (sourceKind === "AGG_TRADE") all.at(-1)!.is_closed = false;
  const boundary = sourceKind === "AGG_TRADE" ? all.at(-1)!.open_time_ms + 1000 : all.at(-1)!.close_time_ms;
  const requests: (number | null)[] = [];
  const sourceIdentity = { ...identity, source_kind: sourceKind };
  let fail = false, state: ReplayReviewHistoryState | null = null;
  const provider = createReplayHistoryProvider({ sessionId: "adapter", trackId: "track-1", identity: sourceIdentity, sourceSequence: 700,
    fetcher: async input => {
      const url = new URL(String(input), location.href);
      const before = url.searchParams.has("before_ms") ? Number(url.searchParams.get("before_ms")) : null;
      requests.push(before);
      if (fail) { fail = false; return Response.json({ protocol: "replay.v3",
        error: { code: "HISTORY_SOURCE_INCOMPLETE", message: "retry review history", details: {} } }, { status: 503 }); }
      const page = all.filter(row => before === null || row.close_time_ms < before).slice(-Number(url.searchParams.get("limit")));
      const result = { protocol: "replay.v3", schema_version: "replay.history.v3", run_id: "fixture",
        session_id: "adapter", track_id: "track-1", identity: sourceIdentity, data_epoch: epoch, history_epoch: historyEpoch,
        history_boundary_ms: all[0]!.open_time_ms, revealed_boundary_ms: boundary,
        history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 2,
          visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null }, visible_history_rows: 700,
          effective_warmup_bars: 2, forward_cache_ms: 86400000, interval_ms: 60000, policy_hash: epoch },
        bars: page, excluded_ranges: [], next_before_ms: page[0]!.open_time_ms,
        has_more: page[0]!.open_time_ms !== all[0]!.open_time_ms };
      if (sourceKind === "BAR") return Response.json(result);
      assert(url.pathname.endsWith("/tape-projection") && url.searchParams.get("source_sequence") === "700",
        "tape review used a timestamp-only history source");
      const { excluded_ranges: _excluded, ...base } = result;
      return Response.json({ ...base, schema_version: "replay.tape-projection.v1", display_interval: "1m",
        history_scope: "CONTEXT_AND_FROZEN_TAPE", status: "ready", source_sequence: 700, target_sequence: 700, prepared_sequence: 700,
        context_prepared_before_ms: 0, context_target_before_ms: 0, incomplete_context_buckets: [], before_ms: before });
    } });
  const canvas = document.createElement("div"); document.body.append(canvas);
  const chart = createChart(canvas, { width: 600, height: 240 });
  const series = chart.addSeries(LineSeries), store = new SeriesWindowStore();
  const controller = new ViewportController({ chartProvider: () => structuralMock(chart) });
  const history = new ReplayReviewHistory(store, provider, epoch, boundary, value => { state = value; });
  let unsubscribe = () => {};
  try {
    await history.initialize("review-paging");
    assert(store.barCount === 500 && requests.length === 1, "review blocked on eager full history");
    const toPoint = (row: KlineBar) => ({ time: Number(row.time) as UTCTimestamp, value: Number(row.close) });
    let previous = store.snapshot();
    const tail = store.last()!.time;
    series.setData(previous.map(toPoint));
    unsubscribe = store.subscribe(delta => {
      renderSeriesDelta({ series, delta, store, previousRows: previous, viewportController: structuralMock(controller), toPoint });
      previous = store.snapshot();
    });
    controller.restoreProjectionRange({ from: 150, to: 250 }, { immediate: true, freezeOnNewBars: true });
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const anchor = Number(previous[200]!.time) as UTCTimestamp, before = chart.timeScale().timeToCoordinate(anchor);
    fail = true; await history.loadMoreLeft();
    assert(store.barCount === 500 && state !== null && (state as ReplayReviewHistoryState).error !== null,
      "failed history replaced the visible review");
    await history.loadMoreLeft();
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
    const after = chart.timeScale().timeToCoordinate(anchor);
    assert(before !== null && after !== null && Math.abs(before - after) < 0.01, `review paging moved viewport: ${before} -> ${after}`);
    assert(store.barCount === 700 && store.last()!.time === tail, "review paging dropped its selected-event tail");
    assert(sourceKind !== "AGG_TRADE" || store.last()!.replayClosed === false, "review paging lost its forming tail");
    await history.loadMoreLeft();
    assert(requests.length === 3 && requests[1] === requests[2], "review terminal/retry cursor changed");
    return { name: `${sourceKind} review selected-period paging, retry and fixed real chart viewport`, status: "PASS", firstPage: 500,
      finalBars: store.barCount, requests: requests.length, before, after };
  } finally { history.cancel(); unsubscribe(); chart.remove(); canvas.remove(); }
}

export async function checkTapeReviewHistoryViewport() { return checkReviewHistoryViewport("AGG_TRADE"); }

export async function checkTapePlaybackBoundaries() {
  const store = new SeriesWindowStore({ seriesKey: "same-ms-tape" });
  store.replace(rows.slice(47, 50).map(replayDisplayBarToKline));
  const time = rows[49]!.open_time_ms + 123;
  store.applyTick({ ...store.last()!, replayClosed: false, is_closed: false });
  let runtime = structuralMock<ReplayRuntime>({ store: { sessionId: "adapter", dataEpoch: epoch,
    sourceSequence: 7, virtualTimeMs: time, state: "PLAYING", sessionConfig: { exchange: "fixture", market_type: "spot",
      symbol: "FIXTURE", source_kind: "agg_trade", base_interval: "1m" } }, marketData: { view: { meta: {} } } });
  const viewer = structuralMock<ReplayViewerRuntime>({ seriesStore: store,
    viewerState: { selected_track_id: "track-1", display_interval: "1m" } });
  const empty: ActiveIndicatorPersistence = { controlled: true, load: () => [], save: () => {} };
  const requests: { sequence: number; time: number }[] = [];
  let latest: ReplaySharedIndicatorRuntime | null = null, cancelled = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, options) => {
    const url = new URL(String(input), location.href);
    assert(url.pathname.endsWith("/tape-projection"), `unexpected sampled request ${url}`);
    requests.push({ sequence: Number(url.searchParams.get("source_sequence")), time: Number(url.searchParams.get("revealed_boundary_ms")) });
    return new Promise<Response>((_resolve, reject) => {
      const abort = () => { cancelled++; reject(new DOMException("left sample", "AbortError")); };
      options!.signal!.addEventListener("abort", abort, { once: true });
      if (options!.signal!.aborted) abort();
    });
  };
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  function Probe() {
    const value = useReplaySharedIndicatorRuntime(runtime, viewer, "sampled-tape", empty);
    useLayoutEffect(() => { latest = value; });
    return null;
  }
  try {
    await act(async () => root.render(<Probe />));
    await act(async () => {
      runtime = { ...runtime, store: { ...runtime.store, sourceSequence: 8 } };
      store.applyTick({ ...store.last()!, close: Number(store.last()!.close) + 1, high: Number(store.last()!.high) + 1 });
      root.render(<Probe />);
    });
    await act(async () => { (latest as ReplaySharedIndicatorRuntime | null)!.actions.addIndicator(definitions[0]!); });
    assert(requests[0]?.sequence === 7 && requests[0]?.time === time,
      `sampled timestamp was paired with a newer same-ms sequence: ${JSON.stringify(requests)}`);
    for (let attempt = 0; attempt < 60 && requests.length < 2; attempt++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    }
    assert(requests.length === 2 && requests[1]?.sequence === 8 && requests[1]?.time === time,
      `next playback sample did not advance its sequence: ${JSON.stringify(requests)}`);
    await act(async () => root.unmount());
    assert(cancelled === 2, "sample change or unmount left a pending tape observer");
    return { name: "playing indicator time and same-ms tape sequence are sampled together", status: "PASS", requests, cancelled };
  } finally { await act(async () => root.unmount()); host.remove(); globalThis.fetch = originalFetch; }
}

export async function checkColdTapePlayback(rewind = false) {
  let store = new SeriesWindowStore({ seriesKey: "cold-playing-tape" });
  const original = rows.slice(47, 50).map(row => ({ ...row })); original[2]!.is_closed = false; original[2]!.volume = "7";
  const boundary = original[2]!.open_time_ms + 123;
  const tapeIdentity = { ...identity, source_kind: "AGG_TRADE" as const };
  const snapshots = new Map<number, ReplayDisplayBar[]>([[7, original]]);
  let sequence = 7, gets = 0, posts = 0, firstResultAt: number | null = null, tick = 0, displayed = 0;
  let observation: ReplayTapeViewerObservation | null = null;
  let generation = 1, cancellations = 0;
  const listeners = new Set<() => void>();
  let latest: ReplaySharedIndicatorRuntime | null = null;
  let runtime = structuralMock<ReplayRuntime>({ store: { sessionId: "adapter", dataEpoch: epoch,
    generation, sourceSequence: sequence, virtualTimeMs: boundary, state: "PLAYING", sessionConfig: { exchange: "fixture", market_type: "spot",
      symbol: "FIXTURE", source_kind: "agg_trade", base_interval: "1m" } }, marketData: { view: { meta: {} } } });
  const lifecycle = structuralMock<ReplayRuntimeLifecycle>({
    store: { seriesStore: new SeriesWindowStore({ seriesKey: "cold-source" }),
      getAuthoritySnapshot: () => ({ sessionId: "adapter", generation, hasAuthoritativeSnapshot: true,
        sourceSequence: sequence, virtualTimeMs: boundary }) },
    getSnapshot: () => ({ store: runtime.store }),
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
  });
  runtime = { ...runtime, lifecycle };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, options) => {
    const url = new URL(String(input), location.href);
    await new Promise<void>((resolve, reject) => {
      const abort = () => { cancellations++; clearTimeout(timer); reject(new DOMException("cold observer left", "AbortError")); };
      const timer = setTimeout(() => { options?.signal?.removeEventListener("abort", abort); resolve(); },
        url.pathname.endsWith("/tape-projection") ? (gets === 0 ? 650 : 80) : 800);
      options?.signal?.addEventListener("abort", abort, { once: true });
      if (options?.signal?.aborted) abort();
    });
    if (url.pathname.endsWith("/tape-projection")) {
      gets++;
      const selected = Number(url.searchParams.get("source_sequence"));
      const bars = snapshots.get(selected)!;
      assert(!!bars, "cold hydration used an unknown tape sequence");
      return Response.json({ protocol: "replay.v3", schema_version: "replay.tape-projection.v1", run_id: "run",
        session_id: "adapter", track_id: "track-1", identity: tapeIdentity, data_epoch: epoch, display_interval: "1m",
        history_scope: "CONTEXT_AND_FROZEN_TAPE", history_epoch: historyEpoch,
        history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 2,
          visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null }, visible_history_rows: 128,
          effective_warmup_bars: 2, forward_cache_ms: 86400000, interval_ms: 60000, policy_hash: epoch },
        context_prepared_before_ms: 0, context_target_before_ms: 0, incomplete_context_buckets: [],
        revealed_boundary_ms: boundary, source_sequence: selected, target_sequence: selected, prepared_sequence: selected,
        before_ms: null, history_boundary_ms: original[0]!.open_time_ms, next_before_ms: original[0]!.open_time_ms,
        has_more: false, status: "ready", bars });
    }
    assert(url.pathname.endsWith("/indicator-compute"), `unexpected cold endpoint ${url}`);
    posts++;
    const body = JSON.parse(String(options?.body)) as { source_sequence: number; bars: ReplayDisplayBar[] };
    assert(body.bars.at(-1)?.volume === snapshots.get(body.source_sequence)?.at(-1)?.volume,
      "indicator prices and source sequence describe different observations");
    const example = reference.canonical.find(item => item.prefix_count === 47)!;
    return Response.json({ ...example.result, protocol: "replay.v3", status: "ready",
      seed: { session_id: "adapter", track_id: "track-1", data_epoch: epoch, history_epoch: historyEpoch, identity: tapeIdentity } });
  };
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  function Probe() {
    const projection = useReplayChartProjection(runtime, "track-1", "1m");
    assert(!projection.error, `production cell projection failed: ${projection.error}`);
    const value = useReplaySharedIndicatorRuntime(runtime, structuralMock<ReplayViewerRuntime>({ seriesStore: projection.seriesStore,
      tapeObservation: projection.tapeObservation ?? null, viewerState: { selected_track_id: "track-1", display_interval: "1m" } }), "cold-tape", persistence);
    useLayoutEffect(() => {
      store = projection.seriesStore;
      observation = projection.tapeObservation ?? null;
      latest = value;
    });
    return null;
  }
  const started = performance.now();
  try {
    await act(async () => { root.render(<Probe />); });
    for (tick = 1; tick <= 150; tick++) {
      if (rewind && tick === 45) { sequence = 2; generation++; displayed = 0; }
      sequence++;
      const selected = original.map((row, i) => i === 2 ? { ...row, volume: String(sequence) } : row);
      snapshots.set(sequence, selected);
      await act(async () => {
        runtime = { ...runtime, store: { ...runtime.store, generation, sourceSequence: sequence } };
        listeners.forEach(notify => notify()); root.render(<Probe />);
        await new Promise(resolve => setTimeout(resolve, 20));
      });
      if (store.last()) {
        const next = Number(store.last()!.volume);
        assert(next >= displayed && next <= sequence, "projection regressed or revealed future trades"); displayed = next;
      }
      const points = (latest as ReplaySharedIndicatorRuntime | null)?.view.activeIndicators[0]?.lines?.[0]?.data;
      if (points?.length && firstResultAt === null) firstResultAt = performance.now() - started;
    }
    const points = (latest as ReplaySharedIndicatorRuntime | null)?.view.activeIndicators[0]?.lines?.[0]?.data;
    assert(firstResultAt !== null && JSON.stringify(points) === JSON.stringify(reference.outputs.rsi!.filter(point => store.hasTime(point.time))),
      `cold indicator did not initialize during continuous playback: ${JSON.stringify({ gets, posts, firstResultAt, ticks: tick - 1,
        error: (latest as ReplaySharedIndicatorRuntime | null)?.view.activeIndicators[0]?.error,
        status: (latest as ReplaySharedIndicatorRuntime | null)?.status, observation, bars: store.snapshot() })}`);
    if (rewind) assert(cancellations > 0, "rewind left the older seed observer running");
    await act(async () => { runtime = { ...runtime, store: { ...runtime.store, state: "PAUSED" } }; root.render(<Probe />); });
    for (let wait = 0; wait < 60 && Number(store.last()?.volume) !== sequence; wait++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    }
    assert(Number(store.last()?.volume) === sequence, "paused chart did not catch up to its final source sequence");
    return { name: `production multi-chart tape hook initializes indicators during continuous trades${rewind ? " after rewind cancels the old seed" : ""}`, status: "PASS", gets, posts, firstResultAt,
      cancellations,
      projectionDelayMs: 650, indicatorDelayMs: 800, ticks: 150, displayedSequence: displayed, sourceSequence: sequence };
  } finally { await act(async () => root.unmount()); host.remove(); globalThis.fetch = originalFetch; }
}

export async function checkColdTapePlaybackRewind() { return checkColdTapePlayback(true); }


/** Controlled workspace restore after early builtin output must recover every result. */
export async function checkControlledCanonicalRestoration() {
    const defs: IndicatorDefinition[] = [{ id: 'ma', engineName: 'MA', visible: true, params: {} }, { id: 'rsi', engineName: 'RSI', visible: true, params: {} }, ...['custom', 'pine', 'cleanup'].map(id => ({ id, script: 'plot(close)', language: 'pyne', visible: true, params: {} }))];
    const old = globalThis.fetch;
    const requests: unknown[] = [];
    const samples: unknown[] = [];
    let releaseScripts: (() => void) | undefined;
    const scriptsPending = new Promise<void>(resolve => { releaseScripts = resolve; });
    globalThis.fetch = async (input, options) => {
        const url = new URL(String(input), location.href), body = JSON.parse(String(options?.body)) as { name: string; requests: { clientId: string; jobKey: string }[] };
        requests.push({ path: url.pathname, name: body.name });
        const example = (name: string) => fixture.cases.find(c => c.name === name && Object.keys(c.params).length === 0)!.canonical.find(c => c.prefix_count === 47)!.result;
        if (url.pathname.endsWith('/indicator-compute')) {
            await new Promise(r => setTimeout(r, body.name === 'MA' ? 5 : 15));
            return Response.json({ ...example(body.name), protocol: 'replay.v3', status: 'ready', seed: { session_id: 'adapter', track_id: 'track-1', data_epoch: epoch, history_epoch: historyEpoch, identity } });
        }
        if (url.pathname.endsWith('/compute/batch')) {
            await scriptsPending;
            return Response.json({ ok: true, results: body.requests.map((j: {
                    clientId: string;
                    jobKey: string;
                }) => ({ ...j, payload: example('MA').payload })) });
        }
        throw new Error(`unexpected ${url}`);
    };
    const store = new SeriesWindowStore({ seriesKey: 'known-epoch' });
    store.replace(rows.slice(47, 50).map(replayDisplayBarToKline));
    const host = document.createElement('div');
    document.body.append(host);
    const root = createRoot(host);
    const latest = new Map<string, IndicatorRuntime>();
    let show: (v: boolean) => void = () => { };
    let change: (v: number) => void = () => { };
    let edit: () => void = () => { };
    const binding = { sessionId: 'adapter', trackId: 'track-1', dataEpoch: epoch, historyEpoch, revealedBoundaryMs: rows.at(-1)!.close_time_ms, identity };
    function Cell({ id, phase, definitions, save }: {
        id: string;
        phase: number;
        definitions: IndicatorDefinition[];
        save: (v: IndicatorDefinition[]) => void;
    }) {
        const persistence = useMemo(() => ({ controlled: true, load: () => definitions, save }), [definitions, save]);
        const canonical = useReplayCanonicalIndicatorCompute(`${id}-${phase}`, store, binding), key = `${id}-${phase}|${canonical.sourceKey}`;
        const bars = useMemo(() => store.snapshot().map(r => ({ ...r })), []);
        const meta = useMemo(() => ({ version: store.version, status: 'ready', committedAt: null, source: 'replay-indicator-revealed-prefix' }), []);
        const runtime = useProvidedBarsIndicatorRuntime({ bars, computeBatch: canonical.compute, persistence, chartDataMeta: meta, datasetKey: key, sourceScopeKey: key, sourceOrdinal: binding.revealedBoundaryMs, seriesReady: store.version, visibleThroughSeconds: binding.revealedBoundaryMs / 1000, exchange: 'fixture', marketType: 'spot', symbol: 'FIXTURE', interval: '1m' });
        useLayoutEffect(() => { latest.set(id, runtime); });
        return <output>{id}:{runtime.view.activeIndicators.map(i => `${i.id}=${i.lines?.length ?? 0}/${i.error ?? ''}`).join(',')}</output>;
    }
    function Workspace() {
        const [documents, setDocuments] = useState(() => Object.fromEntries(['cell-1', 'cell-2', 'cell-3', 'cell-4'].map(id => [id, structuredClone(defs)])));
        const [visible, setVisible] = useState(true);
        const [phase, setPhase] = useState(0);
        useLayoutEffect(() => {
            show = setVisible;
            change = setPhase;
            edit = () => setDocuments(prev => Object.fromEntries(Object.entries(prev).map(([id, list]) => [id, list.map(i => ({ ...i, description: 'restored metadata' }))])));
        }, []);
        return <>{Object.entries(documents).filter(([id]) => visible || id !== 'cell-1').map(([id, definitions]) => <Cell key={id} id={id} phase={phase} definitions={definitions} save={v => setDocuments(prev => ({ ...prev, [id]: v }))}/>)}</>;
    }
    async function settle(label: string) {
        for (let i = 0; i < 100; i++)
            await act(async () => { await new Promise(r => setTimeout(r, 20)); });
        const state = [...latest].map(([id, r]) => ({ id, computing: r.status.computing, lines: r.view.activeIndicators.map(i => [i.id, i.lines?.length ?? 0, i.error]), panes: r.view.subPanes.map(p => p.statusText) }));
        samples.push({ label, state });
        if (state.some(s => s.lines.some(l => !l[1])) || [...latest.values()].some(r => r.view.activeIndicators.slice(0, 2).some(i => { const ref = fixture.cases.find(c => c.name === i.engineName && Object.keys(c.params).length === 0)!; return JSON.stringify(i.lines?.[0]?.data) !== JSON.stringify(ref.canonical.find(c => c.prefix_count === 47)!.result.payload.lines[0]!.data); })))
            throw new Error(JSON.stringify({ label, state, requests }));
    }
    try {
        await act(async () => root.render(<Workspace />));
        for (let i = 0; i < 50; i++) {
            await act(async () => { await new Promise(r => setTimeout(r, 5)); });
            if ([...latest.values()].every(r => r.view.activeIndicators.slice(0, 2).every(i => i.lines?.length)))
                break;
        }
        assert(latest.size === 4 && [...latest.values()].every(r => r.view.activeIndicators.slice(0, 2).every(i => i.lines?.length) && r.view.activeIndicators.slice(2).every(i => !i.lines?.length)), 'restore must occur after builtin publication while script work is still pending');
        await act(async () => edit());
        for (let i = 0; i < 2; i++) await act(async () => { await new Promise(r => setTimeout(r, 20)); });
        releaseScripts?.();
        await settle('metadata restored after builtin partial results');
        await act(async () => show(false));
        await act(async () => show(true));
        await settle('close and restore');
        for (let phase = 1; phase <= 5; phase++) {
            await act(async () => change(phase));
            await settle(`period ${phase}`);
        }
        return { name: 'four controlled replay cells restore early builtin results during an unfinished batch', status: 'PASS', samples, requests };
    }
    catch (error) {
        throw new Error(`${String(error)}; samples=${JSON.stringify(samples)}`);
    }
    finally {
        releaseScripts?.();
        await act(async () => root.unmount());
        host.remove();
        globalThis.fetch = old;
    }
}
