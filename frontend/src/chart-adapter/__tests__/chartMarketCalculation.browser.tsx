import { useLayoutEffect, useMemo, useRef } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { API_BASE } from "../../services/apiConfig.js";
import { getIndicatorStreamUrl } from "../../services/indicatorApi.js";
import { useIndicatorHistoryPreparation } from "../../features/market-data/useIndicatorHistoryPreparation.js";
import { useMarketDataRuntime } from "../../features/market-data/useMarketDataRuntime.js";
import type { MarketDataRuntime } from "../../features/market-data/useMarketDataRuntime.js";
import { MarketDataManager } from "../../features/market-data/manager/marketDataManager.js";
import { ChartDataFlowManager } from "../../features/market-data/manager/chartDataFlowManager.js";
import { ChartWorkScheduler } from "../../features/market-data/chartWorkScheduler.js";
import { MarketWindowRegistry } from "../../features/market-data/window/marketWindowSession.js";
import { MarketDataWorkspaceContext, type MarketDataWorkspaceResources } from "../../features/market-data/marketDataWorkspaceContext.js";
import { IndicatorDataManager } from "../../features/indicators/indicatorDataManager.js";
import { SharedIndicatorStreamCoordinator } from "../../features/indicators/sharedIndicatorStreamCoordinator.js";
import { useIndicatorRuntime } from "../../features/indicators/useIndicatorRuntime.js";
import type { IndicatorRuntime } from "../../features/indicators/indicatorRuntimeContract.js";
import { createActiveIndicatorPersistence } from "../../features/indicators/activeIndicatorStore.js";
import type { ChartSessionRuntime } from "../../features/chart-session/chartSessionTypes.js";
import type { KlineApi, KlineFetchResult, KlineStreamOptions, KlineStreamController } from "../../features/market-data/klineContracts.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";
import { structuralMock } from "../../test/testHelpers.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw Error(message); }
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/** Real market/initial-load/window hooks, scheduling and Pine HTTP/WS/core.
 * Only session configuration and upstream BAR/lease ports are deterministic.
 * No ready metadata is injected into the indicator hook.
 */
export async function checkChartMarketCalculation({ deepHistory = false }: { deepHistory?: boolean } = {}) {
  const originalFetch = window.fetch.bind(window), originalNow = Date.now, NativeSocket = window.WebSocket;
  const frames: Array<Record<string, unknown>> = [];
  class ObservedSocket extends NativeSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols); this.addEventListener("message", event => { frames.push(JSON.parse(String(event.data)) as Record<string, unknown>); });
    }
  }
  window.WebSocket = ObservedSocket;
  const read = async () => await (await originalFetch(`${API_BASE}/fixture/bars`)).json() as { rows: KlineBar[]; script: string };
  let data = await read(), sequence = 1;
  let releaseDeep: () => void = () => {};
  const deepReady = new Promise<void>(resolve => { releaseDeep = resolve; });
  const clockStart = performance.now();
  Date.now = () => Number(data.rows.at(-1)!.time) * 1000 + (data.rows.at(-1)!.is_closed ? 60_000 : 30_000)
    + Math.floor(performance.now() - clockStart);
  const http: Array<{ url: string; method: string }> = [];
  window.fetch = (input, options) => {
    const url = String(input);
    if (url.includes("/indicators/")) http.push({ url, method: options?.method ?? "GET" });
    return originalFetch(input, options);
  };
  const marketCalls: string[] = [];
  const wire = () => ({ protocol: 1, epoch: "market-hook", generation: 1, sequence, barrier: 1,
    observed_at_ms: Date.now(), stable: true, series: { exchange: "binance", market_type: "spot", symbol: "BTCUSDT", interval: "1m",
      provider_id: "binance", venue: "binance", asset_class: "crypto", series_variant: "native", price_adjustment: "raw",
      session_variant: "continuous", volume_semantics: "base_asset" } });
  const result = (kind: string, count = 500): KlineFetchResult => {
    marketCalls.push(`${kind}:${count}`);
    const rows = kind === "latest" ? data.rows.slice(-2) : data.rows.filter(row => row.is_closed).slice(-count);
    return { data: rows, stream_version: wire(), all_rows_final: rows.every(row => row.is_closed === true), complete: true, retryable: false,
      history_state: "ready", verified_contiguous: true, missing_ranges: [], has_tail_gap: false, truncated: false };
  };
  const api: KlineApi = { getMultiStreamUrl: () => "ws://controlled-market-hook",
    fetchKlinesHistory: async (_symbol, _interval, _days, _market, _exchange, options) => {
      const count = options.countBack ?? 500;
      if (deepHistory && count > 500) await deepReady;
      return result("history", count);
    }, fetchKlinesRange: async () => result("range", deepHistory ? 1500 : 500),
    fetchLatestKlines: async () => result("latest"), fetchKlinesBefore: async () => { throw Error("Unexpected historical pagination"); } };
  const physical: Array<{ options: KlineStreamOptions; controller: KlineStreamController; closed: boolean }> = [];
  const market = new MarketDataManager({ api, streams: {
    subscribe: (_series, options = {}) => {
      const state = { options, closed: false, controller: null as unknown as KlineStreamController };
      state.controller = { isOpen: () => !state.closed, readyState: () => state.closed ? 3 : 1,
        send: () => true, sendPing: () => true, updateIntervals() {}, close: () => { state.closed = true; } };
      physical.push(state); queueMicrotask(() => options.onOpen?.(state.controller)); return state.controller;
    }, closeAll() {}, diagnostics: () => ({ physicalStreams: physical.filter(s => !s.closed).length }),
  } });
  const streams = new SharedIndicatorStreamCoordinator({ url: getIndicatorStreamUrl, maxSubscriptions: 50 });
  const indicators = new IndicatorDataManager({ cache: market.cache, gate: market.foregroundPreloadGate, streams });
  const resources: MarketDataWorkspaceResources = { brokerEnabled: true, dataManager: market, indicatorDataManager: indicators,
    dataFlow: new ChartDataFlowManager(market, indicators), klineApi: market, streamCoordinator: market,
    requestCoordinator: market.requestCoordinator, indicatorStreamCoordinator: streams,
    workScheduler: new ChartWorkScheduler(), windowRegistry: new MarketWindowRegistry() };
  const saved = new Map<string, string>();
  const persistence = createActiveIndicatorPersistence("full-market-chart", {
    getItem: key => saved.get(key) ?? null, setItem: (key, value) => { saved.set(key, value); },
  });
  let latest: { market: MarketDataRuntime; indicator: IndicatorRuntime } | null = null;
  const snapshots: Array<Record<string, unknown>> = [];
  const diagnostics = () => ({ meta: latest?.market.view.meta, market: latest?.market.status,
    indicatorMonitor: (window as unknown as { __CANDLESCOPE_INDICATOR_MONITOR__?: { snapshot(): unknown } }).__CANDLESCOPE_INDICATOR_MONITOR__?.snapshot(),
    scheduler: resources.workScheduler?.diagnostics(), http, marketCalls });
  async function until(predicate: () => boolean | Promise<boolean>, message: string) {
    const end = performance.now() + 15_000;
    while (!await predicate()) { assert(performance.now() < end, message + " " + JSON.stringify(diagnostics())); await delay(20); }
  }
  const noop = () => {};
  function Cell() {
    const price = useRef<number | null>(null);
    const session = useMemo(() => structuralMock<ChartSessionRuntime>({
      view: { symbol: "BTCUSDT", exchange: "binance", marketType: "spot", interval: "1m", sessionKey: "market-hook", datasetKey: "market-hook",
        datasetVersion: 0, trackedIntervals: ["1m"], prefetchIntervals: [], nativeIntervals: [{ value: "1m", seconds: 60 }],
        exchangeConfig: { id: "binance", label: "Binance", markets: [{ market_type: "spot", label: "Spot" }],
          nativeIntervals: [{ value: "1m", seconds: 60 }], intervalDays: { "1m": 1 }, intervalDaysSource: "capability",
          protocolFeatures: new Set<string>(), limits: {}, knownLimitations: [], wsConnectionModel: "single", raw: null }, savedVisibleRange: null },
      status: { exchangeCatalogStatus: "ready", historyIntervalAvailable: true, realtimeIntervalAvailable: true, marketDataReady: true, webSocketReady: true },
      actions: { handleVisibleRangeChange: noop, updateVisibleRangeDataMeta: noop },
      refs: { intervalRef: { current: "1m" }, trackedIntervalsRef: { current: ["1m"] } },
      events: { lastTransition: null, transitionToken: 0 },
    }), []);
    const runtime = useMarketDataRuntime({ session, realtimePriceRef: price, backgroundPrefetchEnabled: deepHistory,
      schedulerCellId: "full-market", workspaceId: "fixture", windowId: "browser" });
    const streamIdentity = useMemo(() => ({ cellId: "full-market", workspaceId: "fixture", windowId: "browser" }), []);
    const indicator = useIndicatorRuntime({ session, marketData: runtime, autoAddVolume: false, indicatorPersistence: persistence,
      workSchedulerCellId: "full-market", streamIdentity });
    useIndicatorHistoryPreparation(runtime.status.historyPreparing === true, indicator.status.computing, runtime.actions.holdHistoryHydrationForIndicators);
    useLayoutEffect(() => { latest = { market: runtime, indicator }; });
    return <output>{runtime.status.barCount} / {indicator.view.activeIndicators[0]?.lines?.[0]?.data.at(-1)?.value}</output>;
  }
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  const counter = () => latest?.indicator.view.activeIndicators[0]?.lines?.find(l => l.name === "counter")?.data.at(-1)?.value;
  try {
    flushSync(() => root.render(<MarketDataWorkspaceContext.Provider value={resources}><Cell /></MarketDataWorkspaceContext.Provider>));
    await until(() => Boolean(latest?.market.status.activeChartReady && !latest.market.view.loading), "Market did not become ready");
    snapshots.push({ phase: "before-add", ...diagnostics() });
    flushSync(() => latest!.indicator.actions.addIndicator({ id: "counter", name: "market counter", kind: "script", language: "pine",
      executionTarget: "hosted", script: data.script, visible: true }));
    await until(() => counter() === 500, "Ready real market hook never opened the Pine calculation");
    await until(() => frames.some(frame => frame.type === "indicator.subscribed" && frame.ok === true), "Calculation WS did not attach");
    snapshots.push({ phase: "initial-counter", ...diagnostics() });
    if (deepHistory) {
      await originalFetch(`${API_BASE}/fixture/seed-left`, { method: "POST" });
      data = await read();
      releaseDeep();
      await until(() => latest!.market.status.barCount === 1500 && counter() === 1500, "Historical left expansion did not replace the calculation origin");
      await until(() => frames.filter(frame => frame.type === "indicator.subscribed" && frame.ok === true).length >= 2, "Expanded calculation did not reattach WS");
      snapshots.push({ phase: "historical-left1500", ...diagnostics() });
    }
    await originalFetch(`${API_BASE}/fixture/${deepHistory ? "append" : "tick/501"}`, { method: "POST" });
    data = await read(); sequence++;
    for (const stream of physical.filter(s => !s.closed)) stream.options.onKline?.({ interval: "1m", tick: data.rows.at(-1)!,
      message: { type: "kline", interval: "1m", data: data.rows.at(-1)!, event_type: "bar.updated", stream_version: wire(),
        previous_open_ms: Number(data.rows.at(-2)!.time) * 1000 } }, stream.controller);
    await until(() => counter() === (deepHistory ? 1501 : 501) && latest!.market.status.barCount === (deepHistory ? 1501 : 501), "Live source did not advance chart and calculation");
    snapshots.push({ phase: "forming-counter", ...diagnostics() });
    return { scope: "Full market/indicator React hooks and actual Pine HTTP/WS/SDK/core; controlled market transport, not Native acceptance", snapshots, http, frames: frames.map(frame => ({ type: frame.type, ok: frame.ok, calculation: frame.calculation })) };
  } finally {
    releaseDeep();
    flushSync(() => root.unmount());
    await until(() => http.some(x => x.method === "DELETE") || !http.some(x => x.method === "POST"), "Calculation did not release");
    try {
      await until(async () => {
        const state = await (await originalFetch(`${API_BASE}/fixture/state`)).json() as { registry: { entries: number }; callbacks: number; leases: number };
        return state.registry.entries === 0 && state.callbacks === 0 && state.leases === 0;
      }, "Chart did not physically release the source/domain before server shutdown");
    } finally {
      resources.dataFlow.dispose(); streams.closeAll(); market.closeAll(); resources.workScheduler?.dispose();
      host.remove(); window.fetch = originalFetch; window.WebSocket = NativeSocket; Date.now = originalNow;
    }
  }
}
