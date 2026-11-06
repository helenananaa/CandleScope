import { useLayoutEffect, useMemo, useRef } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { API_BASE } from "../../services/apiConfig.js";
import { getIndicatorStreamUrl } from "../../services/indicatorApi.js";
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
export async function checkChartMarketCalculation() {
  const originalFetch = window.fetch.bind(window), originalNow = Date.now;
  const read = async () => await (await originalFetch(`${API_BASE}/fixture/bars`)).json() as { rows: KlineBar[]; script: string };
  let data = await read(), sequence = 1;
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
  const result = (kind: string): KlineFetchResult => {
    marketCalls.push(kind);
    return { data: data.rows, stream_version: wire(), all_rows_final: true, complete: true, retryable: false,
      history_state: "ready", verified_contiguous: true, missing_ranges: [], has_tail_gap: false, truncated: false };
  };
  const api: KlineApi = { getMultiStreamUrl: () => "ws://controlled-market-hook",
    fetchKlinesHistory: async () => result("history"), fetchKlinesRange: async () => result("range"),
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
  async function until(predicate: () => boolean, message: string) {
    const end = performance.now() + 15_000;
    while (!predicate()) { assert(performance.now() < end, message + " " + JSON.stringify(diagnostics())); await delay(20); }
  }
  const noop = () => {};
  function Cell() {
    const price = useRef<number | null>(null);
    const session = useMemo(() => structuralMock<ChartSessionRuntime>({
      view: { symbol: "BTCUSDT", exchange: "binance", marketType: "spot", interval: "1m", sessionKey: "market-hook", datasetKey: "market-hook",
        datasetVersion: 0, trackedIntervals: ["1m"], prefetchIntervals: [], nativeIntervals: [{ value: "1m", seconds: 60 }],
        exchangeConfig: { nativeIntervals: [{ value: "1m", seconds: 60 }], intervalDays: { "1m": 1 } }, savedVisibleRange: null },
      status: { exchangeCatalogStatus: "ready", historyIntervalAvailable: true, realtimeIntervalAvailable: true, marketDataReady: true, webSocketReady: true },
      actions: { handleVisibleRangeChange: noop, updateVisibleRangeDataMeta: noop },
      refs: { intervalRef: { current: "1m" }, trackedIntervalsRef: { current: ["1m"] } },
      events: { lastTransition: null, transitionToken: 0 },
    }), []);
    const runtime = useMarketDataRuntime({ session, realtimePriceRef: price, backgroundPrefetchEnabled: false,
      schedulerCellId: "full-market", workspaceId: "fixture", windowId: "browser" });
    const indicator = useIndicatorRuntime({ session, marketData: runtime, autoAddVolume: false, indicatorPersistence: persistence,
      workSchedulerCellId: "full-market", streamIdentity: { cellId: "full-market", workspaceId: "fixture", windowId: "browser" } });
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
    snapshots.push({ phase: "initial-counter", ...diagnostics() });
    await originalFetch(`${API_BASE}/fixture/tick/501`, { method: "POST" });
    data = await read(); sequence++;
    for (const stream of physical.filter(s => !s.closed)) stream.options.onKline?.({ interval: "1m", tick: data.rows.at(-1)!,
      message: { type: "kline", interval: "1m", data: data.rows.at(-1)!, event_type: "bar.updated", stream_version: wire(),
        previous_open_ms: Number(data.rows.at(-2)!.time) * 1000 } }, stream.controller);
    await until(() => counter() === 501 && latest!.market.status.barCount === 501, "Live source did not advance chart and calculation");
    snapshots.push({ phase: "forming-counter", ...diagnostics() });
    return { scope: "Full market/indicator React hooks and actual Pine HTTP/WS/SDK/core; controlled market transport, not Native acceptance", snapshots, http };
  } finally {
    flushSync(() => root.unmount());
    await until(() => http.some(x => x.method === "DELETE") || !http.some(x => x.method === "POST"), "Calculation did not release");
    resources.dataFlow.dispose(); indicators.dispose(); streams.closeAll(); market.closeAll(); resources.workScheduler?.dispose();
    host.remove(); window.fetch = originalFetch; Date.now = originalNow;
  }
}
