import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { createChart, CandlestickSeries, type UTCTimestamp } from "lightweight-charts";
import { MarketDataManager } from "../../features/market-data/manager/marketDataManager.js";
import { resolveSharedInitialRows } from "../../features/market-data/manager/initialMarketRows.js";
import { bindSharedWindow } from "../../features/market-data/manager/sharedWindowBinding.js";
import { ForegroundPreloadGate } from "../../features/market-data/foregroundPreloadGate.js";
import { SeriesDataFeed } from "../../features/market-data/feed/seriesDataFeed.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import { BatchKlineStreamCoordinator } from "../../features/market-data/feed/batchKlineStreamCoordinator.js";
import { useKlineStreamRuntime } from "../../features/market-data/useKlineStreamRuntime.js";
import { useChartInitialLoad } from "../../features/market-data/useChartInitialLoad.js";
import { IndicatorWindowCommitBuffer } from "../../features/market-data/indicatorWindowCommitBuffer.js";
import { partialMock } from "../../test/testHelpers.js";
import StatusBar from "../../app/StatusBar.js";
import type { CommitChartData, KlineApi, KlineFetchResult, KlineStreamController, KlineStreamOptions, KlineStreamSocket, PendingInitialSeries } from "../../features/market-data/klineContracts.js";
import type { EpochSeconds, KlineBar, MarketSeries } from "../../features/market-data/marketDataTypes.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
async function until(predicate: () => boolean, message: string) {
  const deadline = performance.now() + 5000;
  while (!predicate()) { assert(performance.now() < deadline, message); await new Promise(requestAnimationFrame); }
}
const instrument = (symbol: string): MarketSeries => ({ exchange: "binance", marketType: "spot", symbol, interval: "1m" });

class BrowserCell {
  readonly store = new SeriesWindowStore();
  symbol = "BTCUSDT";
  loaded = "";
  rendered = 0;
  select(symbol: string) { this.symbol = symbol; }
  settle(symbol: string) { this.loaded = symbol; }
  published(count: number) { this.rendered = count; }
}

class ControlledBatchSocket implements KlineStreamSocket {
  readyState = 0;
  onopen: KlineStreamSocket["onopen"] = null;
  onmessage: KlineStreamSocket["onmessage"] = null;
  onerror: KlineStreamSocket["onerror"] = null;
  onclose: KlineStreamSocket["onclose"] = null;
  readonly sent: string[] = [];

  send(payload: string) { this.sent.push(payload); }
  close() { this.readyState = 3; }
  open() { this.readyState = 1; this.onopen?.(new Event("open")); }
  disconnect() { this.close(); this.onclose?.(new CloseEvent("close")); }
}

async function checkChartBatchReconnect(host: HTMLElement, api: KlineApi) {
  const sockets: ControlledBatchSocket[] = [];
  const streams = new BatchKlineStreamCoordinator({ url: "ws://controlled-reconnect", socketFactory: () => {
    const socket = new ControlledBatchSocket();
    sockets.push(socket);
    return socket;
  } });
  const manager = new MarketDataManager({ api, streams });
  const series = instrument("BTCUSDT");
  const feed = new SeriesDataFeed({ api: manager, streamFactory: manager.subscribe, getActiveSeries: () => series });
  const root = createRoot(host);
  const noOp = () => undefined;

  function Probe() {
    const interval = useRef(series.interval);
    useKlineStreamRuntime({
      enabled: true, webSocketEnabled: true, symbol: series.symbol, exchange: series.exchange,
      marketType: series.marketType, nativeIntervalValues: [series.interval], trackedIntervals: [series.interval],
      intervalRef: interval, seriesDataFeed: feed, commitPatchedChartData: noOp, patchCacheTick: noOp,
      getCacheRows: () => [], updateLastPrice: noOp, updateRealtimePrice: noOp,
      handleBackfillCompleted: () => false, setWsStatus: noOp,
    });
    return null;
  }

  try {
    flushSync(() => root.render(<Probe />));
    assert(sockets.length === 1, "initial chart socket was not created");
    sockets[0]!.open();
    sockets[0]!.disconnect();
    await until(() => sockets.length >= 2, "the broker did not reconnect the chart");
    sockets[1]!.open();
    await new Promise(resolve => setTimeout(resolve, 2_250));
    assert(Number(sockets.length) === 2, "the chart replaced the broker's recovered socket");
    assert(sockets[1]!.readyState === 1, "the recovered socket closed unexpectedly");
    const subscriptions = sockets[1]!.sent.filter(payload => {
      const message: unknown = JSON.parse(payload);
      return typeof message === "object" && message !== null && "action" in message && message.action === "subscribe";
    });
    assert(subscriptions.length === 1, "recovered physical socket subscribed more than once");
  } finally {
    flushSync(() => root.unmount());
    manager.closeAll();
  }
}

async function checkInitialRetryOwner(host: HTMLElement, rows: KlineBar[], completion = false) {
  const series = instrument("BTCUSDT"), buffer = new IndicatorWindowCommitBuffer();
  const waits: Array<number | undefined> = [];
  let loadFinished = false;
  const completionProgress: string[] = [];
  let rangeReads = 0;
  const pending = { current: null as PendingInitialSeries | null };
  const reply = (pending: boolean): KlineFetchResult => ({ data: rows,
    complete: !pending, retryable: pending, history_state: pending ? "pending" : "ready",
    verified_contiguous: !pending, has_tail_gap: pending, missing_ranges: [],
    all_rows_final: true, truncated: false, backfill_triggered: false });
  const commit: CommitChartData = (_symbol, _interval, _rows, meta) => {
    buffer.record("active", [], { ownerToken: meta?.indicatorWindowOwner,
      epoch: meta?.indicatorWindowEpoch, pending: meta?.deferIndicatorWindow === true });
  };
  const feed = new SeriesDataFeed({ getActiveSeries: () => series,
    commitMergedChartData: commit, commitPatchedChartData: commit,
    api: partialMock<KlineApi>({ fetchKlinesHistory: async (_s, _i, _d, _m, _e, options) => {
      waits.push(options.maxWaitMs); return reply(completion ? waits.length <= 2 : waits.length === 1);
    }, fetchLatestKlines: async () => reply(false), fetchKlinesRange: async () => { rangeReads++; return reply(false); } }) });
  const root = createRoot(host), noop = () => undefined;
  function Probe() {
    const load = useChartInitialLoad({ enabled: true, exchange: "binance", marketType: "spot",
      nativeIntervalValues: ["1m"], getFromCache: () => [], seriesDataFeed: feed,
      activateCachedChartData: () => null, detachActiveChartData: noop, replaceChartData: noop,
      markChartDataTransition: noop, commitMergedChartData: commit, commitPatchedChartData: commit,
      pendingInitialHistoryRef: pending, setInitialHistoryPending: noop, updateLastPrice: noop,
      setConnectionStatus: noop, setLoading: noop, setError: noop, setLoadingMoreLeft: noop,
      setHasMoreLeft: noop, setCrosshairData: noop, setDataSource: noop });
    const latest = useRef(load); latest.current = load;
    useEffect(() => { void latest.current(series.symbol, series.interval).then(() => { loadFinished = true; }); }, []);
    return null;
  }
  try {
    flushSync(() => root.render(<Probe />));
    if (completion) {
      await until(() => waits.length >= 2 && pending.current !== null && loadFinished, "initial repair owner was not established");
      feed.handleBackfillCompleted({ type: "backfill_completed", ...series, market_type: series.marketType,
        detail: { request_id: "browser-initial-owner-completion", reason: "initial_history",
          range_start_ms: rows[0]!.time * 1000, range_end_ms: rows.at(-1)!.time * 1000 } }, {
        activeSeries: series, pendingInitial: pending.current, getPendingInitial: () => pending.current,
        getCacheRows: () => rows, cooldownMs: 0,
        onRecoveryProgress: event => { completionProgress.push(event.type); if (event.type === "initial-resolved") pending.current = null; },
      });
    }
    try { await until(() => waits.length >= 2 && pending.current === null,
      "the initial probe did not settle through its bounded retry"); }
    catch (error) { throw new Error(String(error)+JSON.stringify({completion,waits,pending:pending.current,rangeReads,completionProgress,pendingBuffer:buffer.hasPending("active")})); }
    assert(waits[0] === 0 && waits[1] === 1500, "probe and retry must retain their distinct transport waits");
    assert(!buffer.hasPending("active"), "settled cold retry left the original indicator window owner pending");
  } finally { flushSync(() => root.unmount()); feed.cancelSeriesRequests(series); }
}

/** Actual initial-load hook, Feed, shared manager, private stores and candle
 * renderer. Only the market transport is controlled; no exchange/user profile. */
export async function checkMarketHealth() {
  const start = Math.floor(Date.now() / 60_000) * 60 - 500 * 60;
  const bars = (symbol: string) => Array.from({ length: 500 }, (_, index): KlineBar => ({
    time: (start + index * 60) as EpochSeconds, open: 10, high: 30, low: 0, close: symbol === "BTCUSDT" ? 10 : 20,
    volume: 1, is_closed: true,
  }));
  const corpus = new Map(["BTCUSDT", "ETHUSDT"].map(symbol => [symbol, bars(symbol)]));
  const revisions = new Map<string, { sequence: number; barrier: number }>();
  const generations = new Map<string, number>();
  const wire = (symbol: string) => ({ protocol: 1, epoch: "browser-server", generation: generations.get(symbol) ?? 1,
    sequence: revisions.get(symbol)?.sequence ?? 0, barrier: revisions.get(symbol)?.barrier ?? 0,
    observed_at_ms: Date.now(), stable: true,
    series: { exchange: "binance", market_type: "spot", symbol, interval: "1m", provider_id: "binance", venue: "binance",
      asset_class: "crypto", series_variant: "native", price_adjustment: "raw", session_variant: "continuous", volume_semantics: "base_asset" } });
  const storageRevisions = new Map<string, number>();
  const calls: string[] = [];
  const result = (symbol: string): KlineFetchResult => ({ data: corpus.get(symbol)!.map(row => ({ ...row })), stream_version: wire(symbol),
    storage_revision: storageRevisions.get(symbol) ?? 0,
    all_rows_final: true, complete: true, retryable: false, history_state: "ready", verified_contiguous: true,
    missing_ranges: [], has_tail_gap: false, truncated: false });
  let nextRange: KlineFetchResult | undefined;
  const correctionRevisions: number[] = [];
  const api: KlineApi = {
    getMultiStreamUrl: () => "ws://owned-market-fixture",
    fetchKlinesHistory: async symbol => { calls.push(`history:${symbol}`); await new Promise(resolve => setTimeout(resolve, 10)); return result(symbol); },
    fetchKlinesBefore: async () => { throw new Error("unexpected before"); },
    fetchKlinesRange: async (symbol, _interval, from, to, _market, _exchange, options) => {
      if (options.storageRevisionFloor) {
        assert(options.storageRevisionFloor.epoch === "browser-server", "range lost correction epoch");
        correctionRevisions.push(options.storageRevisionFloor.revision);
      }
      calls.push(`range:${symbol}`);
      const page = result(symbol);
      const response = nextRange ?? { ...page, data: (page.data ?? []).filter(row => from <= row.time && row.time <= to) };
      nextRange = undefined;
      return response;
    },
    fetchLatestKlines: async symbol => { calls.push(`latest:${symbol}`); return result(symbol); },
  };
  const physical: Array<{ symbol: string; options: KlineStreamOptions; controller: KlineStreamController; closed: boolean }> = [];
  const gate = new ForegroundPreloadGate({ quietDwellMs: 0 });
  const manager = new MarketDataManager({ api, foregroundPreloadGate: gate, streams: {
    reconnects: true,
    subscribe: (series, options = {}) => {
      const state = { symbol: series.symbol, options, closed: false, controller: null as unknown as KlineStreamController };
      state.controller = { isOpen: () => !state.closed, readyState: () => state.closed ? 3 : 1,
        send: () => true, sendPing: () => true, updateIntervals() {}, close: () => { state.closed = true; } };
      physical.push(state); queueMicrotask(() => options.onOpen?.(state.controller)); return state.controller;
    }, closeAll() {}, diagnostics: () => ({ physicalStreams: physical.filter(stream => !stream.closed).length }),
  } });
  const emit = (symbol: string, row: KlineBar, type: string, skipBarrier = false) => {
    const previous = revisions.get(symbol) ?? { sequence: 0, barrier: 0 };
    revisions.set(symbol, { sequence: previous.sequence + 1, barrier: previous.barrier + (type === "bar.updated" ? 0 : 1) + (skipBarrier ? 1 : 0) });
    const stream = physical.find(item => item.symbol === symbol && !item.closed)!;
    stream.options.onKline?.({ interval: "1m", tick: row, message: { type: "kline", interval: "1m", data: row,
      event_type: type, stream_version: wire(symbol), previous_open_ms: (row.time - 60) * 1000 } }, stream.controller);
  };
  const cells = new Map<string, BrowserCell>();
  const cellFeeds = new Map<string, SeriesDataFeed>();
  function Cell({ id }: { id: string }) {
    const [symbol, setSymbol] = useState("BTCUSDT"), [status, setStatus] = useState("loading"), [source, setSource] = useState<string | null>(null);
    const canvas = useRef<HTMLDivElement>(null), pending = useRef<PendingInitialSeries | null>(null);
    const model = useMemo(() => new BrowserCell(), []);
    useLayoutEffect(() => { model.select(symbol); cells.set(id, model); }, [id, model, symbol]);
    const bindings = useMemo(() => {
      const merge = (_symbol: string, _interval: string, rows: KlineBar[]) => { model.store.applyRange(rows); };
      const feed = new SeriesDataFeed({ api: manager, streamFactory: manager.subscribe, getActiveSeries: () => instrument(model.symbol),
        commitMergedChartData: merge, commitPatchedChartData: merge });
      const noop = () => undefined;
      return { feed, merge, noop, get: (sym: string) => model.loaded === sym ? model.store.snapshot() : [],
        replace: (_symbol: string, _interval: string, rows: KlineBar[]) => { model.store.replace(rows); },
        resolve: (sym: string) => resolveSharedInitialRows(instrument(sym), model.loaded === sym ? model.store.snapshot() : [], manager.cache, 500) };
    }, [model]);
    useLayoutEffect(() => { cellFeeds.set(id, bindings.feed); }, [id, bindings.feed]);
    const gaps = useSyncExternalStore(bindings.feed.subscribeTerminalHistoryGaps, bindings.feed.getTerminalHistoryGaps);
    const historyGap = gaps.find(gap => gap.seriesKey === bindings.feed.seriesKey(instrument(symbol)));
    const load = useChartInitialLoad({ enabled: true, sharedCacheOwnsHealth: true, exchange: "binance", marketType: "spot",
      nativeIntervalValues: ["1m"], getFromCache: bindings.get, resolveInitialRows: bindings.resolve, seriesDataFeed: bindings.feed,
      activateCachedChartData: () => null, detachActiveChartData: bindings.noop, replaceChartData: bindings.replace,
      markChartDataTransition: bindings.noop, commitMergedChartData: bindings.merge, commitPatchedChartData: bindings.merge,
      pendingInitialHistoryRef: pending, setInitialHistoryPending: bindings.noop, updateLastPrice: bindings.noop,
      setConnectionStatus: setStatus, setLoading: bindings.noop, setError: value => { if (value instanceof Error) throw value; },
      setLoadingMoreLeft: bindings.noop, setHasMoreLeft: bindings.noop, setCrosshairData: bindings.noop, setDataSource: setSource,
    });
    const loadRef = useRef(load); loadRef.current = load;
    useEffect(() => {
      const chart = createChart(canvas.current!, { width: 600, height: 280 });
      const candles = chart.addSeries(CandlestickSeries);
      const paint = () => {
        candles.setData(model.store.snapshot().map(row => ({ time: Number(row.time) as UTCTimestamp,
          open: row.open!, high: row.high!, low: row.low!, close: row.close! })));
        model.published(candles.data().length);
      };
      const unsubscribe = model.store.subscribe(paint); paint();
      return () => { unsubscribe(); chart.remove(); };
    }, [model]);
    useEffect(() => {
      const series = instrument(symbol);
      const stream = manager.subscribe(series, { intervals: ["1m"],
        onKline: event => { model.store.applyTick(event.tick); },
        onBackfillCompleted: event => bindings.feed.handleBackfillCompleted(event, {
          activeSeries: series, getCacheRows: () => model.store.snapshot(), cooldownMs: 0,
        }),
      });
      const release = bindSharedWindow(manager.cache, series, { read: () => model.store.snapshot(),
        commit: rows => { model.store.applyRange(rows); } });
      void loadRef.current(symbol, "1m").then(() => { model.settle(symbol); });
      return () => { stream.close(); release(); };
    }, [symbol, model, bindings.feed]);
    return <section><h2>{id}: {symbol}</h2><button data-switch={id} onClick={() => setSymbol("ETHUSDT")}>ETHUSDT</button>
      <button data-return={id} onClick={() => setSymbol("BTCUSDT")}>BTCUSDT</button>
      <StatusBar status={{ connectionStatus: status, dataSource: source || "", exchangeLabel: "Binance",
        marketLabel: "spot", wsStatus: "live", wsStatusLabel: "Live", barCount: model.rendered,
        hasMoreLeft: true, loadingMoreLeft: false, exchangeCatalogStatus: "ready",
        ...(historyGap ? { historyGap } : {}) }} />
      <p>{status} / {source}</p><div ref={canvas} /></section>;
  }
  const host = document.createElement("main"); document.body.append(host); const root = createRoot(host);
  const checks: string[] = [];
  try {
    flushSync(() => root.render(<><Cell id="A" /><Cell id="B" /></>));
    await until(() => [...cells.values()].length === 2 && [...cells.values()].every(cell => cell.loaded === "BTCUSDT" && cell.rendered === 500), "BTC cells did not load");
    const other = JSON.stringify(cells.get("B")!.store.snapshot());
    const warm = manager.warm(instrument("ETHUSDT"), { owner: "next-symbol", reason: "hover", nativeIntervals: ["1m"] });
    assert(await warm.done === "warmed", "ETH did not warm");
    const forming = { ...corpus.get("ETHUSDT")!.at(-1)!, time: (start + 500 * 60) as EpochSeconds, is_closed: false, close: 21 };
    emit("ETHUSDT", forming, "bar.created");
    assert(manager.cache.planHistory(instrument("ETHUSDT"), 500).action === "reuse", "warm ETH is not healthy");
    const requests = calls.length, sockets = physical.length;
    flushSync(() => host.querySelector<HTMLButtonElement>('[data-switch="A"]')!.click());
    await until(() => cells.get("A")?.loaded === "ETHUSDT" && cells.get("A")!.rendered === 501, "ETH switch lost the forming tail or did not publish");
    assert(calls.length === requests && physical.length === sockets, "healthy switch issued IO or resubscribed");
    assert(JSON.stringify(cells.get("B")!.store.snapshot()) === other, "sibling chart changed");
    checks.push("actual initial-load hook switches BTC → warm ETH with zero HTTP/physical subscribe, 500 final bars plus forming tail, sibling unchanged");
    const corrected = { ...corpus.get("ETHUSDT")![10]!, close: 25 };
    corpus.get("ETHUSDT")![10] = corrected;
    emit("ETHUSDT", { ...forming, close: 22 }, "bar.updated", true);
    await until(() => cells.get("A")!.store.snapshot().find(row => row.time === corrected.time)?.close === 25, "critical gap did not read back historical correction");
    assert(calls.length === requests + 1, "gap recovery was not one coalesced history read");
    checks.push("lost critical barrier triggers one bounded read; shared HTTP correction updates the actual candle window");
    const eth = instrument("ETHUSDT");
    nextRange = { ...result(eth.symbol), stream_version: { ...wire(eth.symbol), stable: false },
      data: [{ ...corrected, close: 28 }] };
    const racing = await manager.fetchKlinesRange(eth.symbol, eth.interval, corrected.time, corrected.time,
      eth.marketType, eth.exchange, { strict: true });
    assert(racing.retryable === true && racing.complete === false && !racing.data?.length,
      "a racing HTTP read did not return retryable without rows");
    assert(cells.get("A")!.store.snapshot().find(row => row.time === corrected.time)?.close === 25,
      "an unstable HTTP read overwrote the rendered correction");
    checks.push("unstable HTTP read is retryable and leaves the corrected candle intact");
    const idleCorrection = { ...corpus.get(eth.symbol)![12]!, close: 27 };
    corpus.get(eth.symbol)![12] = idleCorrection;
    const stream = physical.find(item => item.symbol === eth.symbol && !item.closed)!;
    const previous = revisions.get(eth.symbol)!;
    revisions.set(eth.symbol, { sequence: previous.sequence + 1, barrier: previous.barrier + 1 });
    storageRevisions.set(eth.symbol, 7);
    nextRange = { ...result(eth.symbol), storage_revision: 6, data: [{ ...idleCorrection, close: 28 }] };
    const affected = { range_start_ms: idleCorrection.time * 1000, range_end_ms: idleCorrection.time * 1000 };
    stream.options.onBackfillCompleted?.({ type: "backfill_completed", exchange: eth.exchange, market_type: eth.marketType,
      symbol: eth.symbol, interval: eth.interval, stream_version: wire(eth.symbol),
      detail: { ...affected, reason: "storage_history_changed", storage_revision: 7 } }, stream.controller);
    assert(!manager.cache.read(eth, { from: idleCorrection.time, to: idleCorrection.time }).complete,
      "storage readback notice did not revoke the affected chart coverage");
    await until(() => correctionRevisions.length > 0, "idle chart did not request the affected range");
    assert(cells.get("A")!.store.snapshot().find(row => row.time === idleCorrection.time)?.close !== 28,
      "an old storage revision overwrote the rendered candle");
    await until(() => cells.get("A")!.store.snapshot().find(row => row.time === idleCorrection.time)?.close === 27,
      "idle chart did not apply the durable correction without a tick");
    assert(JSON.stringify(cells.get("B")!.store.snapshot()) === other, "durable readback changed another market");
    assert(correctionRevisions.length === 2 && correctionRevisions.every(revision => revision === 7),
      "correction readback did not retry at the notified revision floor");
    checks.push("durable correction rejects an older storage snapshot and reloads the affected idle chart before another tick");
    stream.options.onClose?.(new CloseEvent("close", { code: 1013, reason: "CONSUMER_RESYNC_REQUIRED" }), stream.controller);
    stream.options.onOpen?.(stream.controller);
    stream.options.onControlMessage?.({ type: "subscribed", active_intervals: ["1m"] }, stream.controller);
    assert(manager.cache.planHistory(eth, 500).action !== "reuse", "reconnect ACK revalidated old chart coverage");
    await manager.fetchKlinesHistory(eth.symbol, eth.interval, null, eth.marketType, eth.exchange,
      { countBack: 500, maxWaitMs: 0, clientContext: { cacheMode: "network-only" } });
    assert(manager.cache.planHistory(eth, 500).action !== "reuse", "snapshot without a linked event proved continuity");
    emit(eth.symbol, { ...forming, close: 23 }, "bar.updated");
    assert(manager.cache.planHistory(eth, 500).action === "reuse", "verified reconnect did not restore healthy reuse");
    checks.push("after reconnect only a stable read linked to a real stream event restores healthy reuse");
    const retainedTail = manager.cache.read(eth).rows.at(-1);
    stream.options.onControlMessage?.({ type: "error", active_intervals: [],
      failed: [{ interval: "1m", code: "interval_unavailable" }] }, stream.controller);
    emit(eth.symbol, { ...forming, close: 29 }, "bar.updated");
    assert(manager.cache.read(eth).rows.at(-1) === retainedTail, "a queued bar entered an inactive interval");
    assert(!manager.cache.planHistory(eth, 500).health.subscribed, "the queued bar reopened the subscription");
    stream.options.onControlMessage?.({ type: "subscribed", active_intervals: ["1m"] }, stream.controller);
    assert(manager.cache.planHistory(eth, 500).action !== "reuse", "re-ACK restored coverage without verification");
    await manager.fetchKlinesHistory(eth.symbol, eth.interval, null, eth.marketType, eth.exchange,
      { countBack: 500, maxWaitMs: 0, clientContext: { cacheMode: "network-only" } });
    emit(eth.symbol, { ...forming, close: 23 }, "bar.updated");
    assert(manager.cache.planHistory(eth, 500).action === "reuse", "acknowledged interval did not regain verified reuse");
    checks.push("a failed interval rejects queued frames until re-acknowledgement and a verified cutover");
    const sourceGapRow = corpus.get(eth.symbol)![18]!;
    const disjoint = corpus.get(eth.symbol)![17]!.time;
    const affectedStamp = manager.cache.captureVersion(eth, { from: sourceGapRow.time, to: sourceGapRow.time });
    const disjointStamp = manager.cache.captureVersion(eth, { from: disjoint, to: disjoint });
    const gapDetail = { gap_id: "browser-source-gap", range_start_ms: sourceGapRow.time * 1000,
      range_end_ms: sourceGapRow.time * 1000 };
    const bumpBarrier = () => {
      const previous = revisions.get(eth.symbol)!;
      revisions.set(eth.symbol, { sequence: previous.sequence + 1, barrier: previous.barrier + 1 });
    };
    bumpBarrier();
    stream.options.onStreamStatus?.({ type: "stream_status", status: "source_gap", interval: eth.interval,
      stream_version: wire(eth.symbol), detail: gapDetail }, stream.controller);
    assert(!affectedStamp.isCurrent() && disjointStamp.isCurrent(), "source gap invalidated the wrong inputs");
    assert(manager.cache.read(eth, { from: disjoint, to: disjoint }).complete,
      "source gap revoked disjoint historical proof");
    assert(!manager.cache.planHistory(eth, 500).health.continuous, "source repair wait retained live continuity");
    assert(cells.get("A")!.store.snapshot().length >= 500, "source repair wait discarded the visible chart");
    corpus.get(eth.symbol)![18] = { ...sourceGapRow, close: 26 };
    bumpBarrier();
    stream.options.onBackfillCompleted?.({ type: "backfill_completed", exchange: eth.exchange,
      market_type: eth.marketType, symbol: eth.symbol, interval: eth.interval, stream_version: wire(eth.symbol),
      detail: { ...gapDetail, reason: "source_gap_resolved" } }, stream.controller);
    await until(() => cells.get("A")!.store.snapshot().find(row => row.time === sourceGapRow.time)?.close === 26,
      "source resolution did not perform exact canonical readback");
    assert(!manager.cache.planHistory(eth, 500).health.fresh, "source resolution supplied fictitious freshness");
    checks.push("pending source repair preserves disjoint evidence and resolution reads the exact corrected candle");
    generations.set(eth.symbol, 2);
    revisions.set(eth.symbol, { sequence: 0, barrier: 0 });
    await manager.fetchKlinesHistory(eth.symbol, eth.interval, null, eth.marketType, eth.exchange,
      { countBack: 500, maxWaitMs: 0, clientContext: { cacheMode: "network-only" } });
    emit(eth.symbol, idleCorrection, "bar.amended");
    const afterAmendment = manager.cache.planHistory(eth, 500);
    assert(afterAmendment.health.continuous && !afterAmendment.health.fresh && afterAmendment.action !== "reuse",
      "a historical amendment borrowed freshness from the retired generation");
    emit(eth.symbol, { ...forming, close: 24 }, "bar.updated");
    assert(manager.cache.planHistory(eth, 500).action === "reuse", "new-generation tail did not restore healthy reuse");
    checks.push("a generation rollover requires a current tail event even after a linked historical amendment");
    await manager.fetchLatestKlines(eth.symbol, eth.interval, 2, eth.marketType, eth.exchange, "browser-tail", {});
    assert(manager.cache.planHistory(eth, 500).action === "reuse", "ordinary tail polling revoked verified health");
    const current = revisions.get(eth.symbol)!;
    revisions.set(eth.symbol, { sequence: current.sequence + 1, barrier: current.barrier + 1 });
    await manager.fetchKlinesHistory(eth.symbol, eth.interval, null, eth.marketType, eth.exchange,
      { countBack: 500, maxWaitMs: 0, clientContext: { cacheMode: "network-only" } });
    const cutover = manager.cache.planHistory(eth, 500);
    assert(cutover.health.historyCovered && !cutover.health.continuous && cutover.action !== "reuse",
      "snapshot crossed an unseen critical barrier using an old stream event");
    emit(eth.symbol, { ...forming, close: 25 }, "bar.updated");
    assert(manager.cache.planHistory(eth, 500).action === "reuse", "fresh matching event did not restore the link");
    checks.push("tail polling preserves health and an unseen HTTP barrier requires a new matching event");
    const active = cells.get("A")!;
    const feed = cellFeeds.get("A")!;
    const missing = corpus.get(eth.symbol)![70]!;
    active.store.replace(active.store.snapshot().filter(row => row.time !== missing.time));
    const gapResult = { ...result(eth.symbol), data: [], history_state: "exhausted" as const,
      terminal_reason: "source_unavailable", availability_revision: "locked-v1",
      start_ms: missing.time * 1000, end_ms: missing.time * 1000,
      complete: false, verified_contiguous: false, all_rows_final: false };
    nextRange = gapResult;
    const beforeGap = calls.length;
    feed.gapPlannerNextAllowedAt.delete(feed.seriesKey(eth));
    const repair = await feed.repairVisibleGaps(eth, active.store.snapshot(), { time: { from: missing.time - 120, to: missing.time + 120 } }, { throttleMs: 0 });
    assert(feed.getTerminalHistoryGaps().length === 1, JSON.stringify({ repair, calls: calls.slice(beforeGap), pending: [...feed.pendingGapRepairs.values()] }));
    const terminal = () => host.querySelector('[data-history-gap="terminal"]');
    await until(() => terminal()?.getAttribute("title")?.includes("source_unavailable") === true,
      "terminal verdict did not reach the chart status bar");
    assert(host.querySelectorAll('[data-history-gap="terminal"]').length === 1, "sibling chart inherited the terminal gap");
    assert(active.rendered === 500, "terminal gap replaced the remaining candles");
    await feed.repairVisibleGaps(eth, active.store.snapshot(), null, { throttleMs: 0 });
    assert(calls.length === beforeGap + 1, "terminal range was requested again");
    stream.options.onControlMessage?.({ type: "subscribed", active_intervals: ["1m"] }, stream.controller);
    assert(terminal(), "reconnect ACK hid an unresolved terminal gap");
    await feed.getRange(eth, { start: missing.time, end: missing.time, strict: true });
    await until(() => !terminal() && active.rendered === 501, "verified readback did not remove the terminal gap");
    flushSync(() => feed.trackTerminalHistoryGaps(eth, gapResult));
    assert(terminal(), "declared terminal history did not project to the chart");
    flushSync(() => host.querySelector<HTMLButtonElement>('[data-return="A"]')!.click());
    await until(() => !terminal() && active.loaded === "BTCUSDT", "market switch retained the previous series' terminal gap");
    checks.push("terminal historical range reaches only the owning status bar; repeat scans and ACK do not change it; verified readback and market switch clear it");
    flushSync(() => root.unmount());
    manager.closeAll(); gate.dispose();
    assert(physical.every(stream => stream.closed), "owned streams leaked");
    await checkChartBatchReconnect(host, api);
    checks.push("the chart keeps the broker-recovered physical socket and sends one subscription");
    await checkInitialRetryOwner(host, corpus.get("BTCUSDT")!);
    checks.push("a completed bounded cold retry releases the original nonblocking probe's indicator window owner");
    await checkInitialRetryOwner(host, corpus.get("BTCUSDT")!, true);
    checks.push("a completed child range verifies the full unknown initial count-back and releases its React load owner");
    return { passed: true, checks, requests: calls, physicalStreamsCreated: sockets,
      scope: "Production-minified Chromium fixture with real React, initial-load hook and candle renderer; controlled market transport, not installed release acceptance" };
  } finally { if (host.hasChildNodes()) flushSync(() => root.unmount()); host.remove(); manager.closeAll(); gate.dispose(); }
}
