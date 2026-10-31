import { useEffect, useLayoutEffect, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { createChart, CandlestickSeries, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { MarketDataManager } from "../../features/market-data/manager/marketDataManager.js";
import { ChartDataFlowManager } from "../../features/market-data/manager/chartDataFlowManager.js";
import { ChartMarketController } from "../../features/market-data/manager/chartMarketController.js";
import { ForegroundPreloadGate } from "../../features/market-data/foregroundPreloadGate.js";
import { MarketWindowRegistry } from "../../features/market-data/window/marketWindowSession.js";
import { MarketDataWorkspaceContext, type MarketDataWorkspaceResources } from "../../features/market-data/marketDataWorkspaceContext.js";
import { IndicatorDataManager } from "../../features/indicators/indicatorDataManager.js";
import { SharedIndicatorStreamCoordinator } from "../../features/indicators/sharedIndicatorStreamCoordinator.js";
import type { IndicatorStreamSocket } from "../../features/indicators/indicatorStreamConnection.js";
import type { IndicatorSubscribeMessage } from "../../features/indicators/indicatorTypes.js";
import { useIndicatorRuntime } from "../../features/indicators/useIndicatorRuntime.js";
import { createActiveIndicatorPersistence } from "../../features/indicators/activeIndicatorStore.js";
import { computeFrontendScript } from "../../features/indicators/frontendScriptRuntime.js";
import { routeIndicatorComputeBatch } from "../../features/indicators/frontendScriptBatch.js";
import { parseIndicatorPayloadEnvelope } from "../../features/indicators/indicatorContracts.js";
import { registerSharedMarketCache } from "../../features/cache-gc/sharedMarketCacheOwner.js";
import { buildIndicatorOhlcv } from "../../features/indicators/indicatorComputeRuntime.js";
import type { IndicatorRuntime } from "../../features/indicators/indicatorRuntimeContract.js";
import type { EpochSeconds, KlineBar } from "../../features/market-data/marketDataTypes.js";
import type { KlineApi, KlineFetchResult, KlineStreamController } from "../../features/market-data/klineContracts.js";
import type { MarketDataRuntimeContract } from "../../features/market-data/marketDataRuntimeContract.js";
import { structuralMock } from "../../test/testHelpers.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const delay = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));
async function until(predicate: () => boolean, message: string) {
  const deadline = performance.now() + 7000;
  while (!predicate()) { assert(performance.now() < deadline, message); await delay(20); }
}

/** Real React indicator runtime and browser workers, production build. Only
 * exchange/hosted computation transports are controlled; not native acceptance. */
export async function checkIndicatorDataFlow() {
  const checks: string[] = [];
  const identity = (symbol: string) => ({ exchange: "binance", marketType: "spot", symbol, interval: "1m" });
  const start = Math.floor(Date.now() / 60000) * 60 - 500 * 60;
  const corpus = new Map(["BTCUSDT", "ETHUSDT"].map(symbol => [symbol, Array.from({ length: 500 }, (_, i): KlineBar => ({
    time: (start + i * 60) as EpochSeconds, open: 10, high: 100, low: 0, close: symbol === "BTCUSDT" ? 10 : 20, volume: 1, is_closed: true,
  }))]));
  const sequence = new Map<string, number>();
  const wire = (symbol: string) => ({ protocol: 1, epoch: "flow-browser", generation: 1, sequence: sequence.get(symbol) ?? 0,
    barrier: sequence.get(symbol) ?? 0, observed_at_ms: Date.now(), stable: true,
    series: { exchange: "binance", market_type: "spot", symbol, interval: "1m", provider_id: "binance", venue: "binance",
      asset_class: "crypto", series_variant: "native", price_adjustment: "raw", session_variant: "continuous", volume_semantics: "base_asset" } });
  const result = (symbol: string): KlineFetchResult => ({ data: corpus.get(symbol)!, stream_version: wire(symbol), all_rows_final: true,
    complete: true, retryable: false, history_state: "ready", verified_contiguous: true, missing_ranges: [], has_tail_gap: false, truncated: false });
  const api: KlineApi = {
    getMultiStreamUrl: () => "ws://controlled-flow",
    fetchKlinesHistory: async symbol => result(symbol), fetchKlinesBefore: async () => { throw new Error("unexpected pagination"); },
    fetchKlinesRange: async symbol => result(symbol), fetchLatestKlines: async symbol => result(symbol),
  };
  const gate = new ForegroundPreloadGate(0);
  const market = new MarketDataManager({ api, foregroundPreloadGate: gate, streams: {
    subscribe: (_series, options = {}) => {
      const controller: KlineStreamController = { isOpen: () => true, readyState: () => 1, send: () => true, sendPing: () => true, close() {}, updateIntervals() {} };
      queueMicrotask(() => options.onOpen?.(controller)); return controller;
    }, closeAll() {}, diagnostics: () => ({}),
  } });
  const unregister = registerSharedMarketCache(market.cache);
  for (const [symbol, rows] of corpus) {
    market.cache.connect(identity(symbol));
    const token = market.cache.beginRead(identity(symbol)); market.cache.admitResponse(token, result(symbol)); token.release();
    sequence.set(symbol, 1);
    market.cache.admitRealtime(identity(symbol), { ...rows.at(-1)!, time: (start + 500 * 60) as EpochSeconds, is_closed: false },
      "bar.created", wire(symbol), Number(rows.at(-1)!.time) * 1000);
    assert(market.cache.planHistory(identity(symbol), 500).action === "reuse", "fixture health missing");
  }
  let browserExecutions = 0, hostedExecutions = 0;
  let backendAvailable = false, backendFailures = 0;
  let cancelNextBrowser = false;
  const sockets: ControlledSocket[] = [];
  class ControlledSocket implements IndicatorStreamSocket {
    readonly OPEN = 1;
    readyState = 0;
    onopen: ((event: Event) => unknown) | null = null;
    onmessage: ((event: MessageEvent<unknown>) => unknown) | null = null;
    onerror: ((event: Event) => unknown) | null = null;
    onclose: ((event: CloseEvent) => unknown) | null = null;
    subscriptions = new Map<string, IndicatorSubscribeMessage>();
    subscribeCount = 0;
    constructor() { sockets.push(this); queueMicrotask(() => { this.readyState = 1; this.onopen?.(new Event("open")); }); }
    close() { this.readyState = 3; this.subscriptions.clear(); }
    serverClose() { this.readyState = 3; this.subscriptions.clear(); this.onclose?.({ code: 1013 } as CloseEvent); }
    send(raw: string) {
      const message = JSON.parse(raw) as IndicatorSubscribeMessage | { action: "unsubscribe"; clientId: string };
      if (message.action === "unsubscribe") { this.subscriptions.delete(message.clientId); return; }
      this.subscriptions.set(message.clientId, message); this.subscribeCount += 1;
      queueMicrotask(() => {
        if (!this.subscriptions.has(message.clientId)) return;
        this.onmessage?.({ data: JSON.stringify({ type: "indicator.subscribed", clientId: message.clientId, ok: true,
          resumeStatus: "history_required", dataRevision: { serverEpoch: "shared-browser", correctionRevision: "0", closedThrough: start + 499 * 60 } }) } as MessageEvent);
        this.preview(message.clientId, Number(message.params.period));
      });
    }
    preview(clientId: string, value: number) {
      this.onmessage?.({ data: JSON.stringify({ type: "indicator.preview", clientId, values: { ema: value },
        barTime: start + 500 * 60, bar: { ...corpus.get("BTCUSDT")!.at(-1)!, time: start + 500 * 60, is_closed: false } }) } as MessageEvent);
    }
  }
  const streams = new SharedIndicatorStreamCoordinator({ url: "ws://controlled-hosted", maxSubscriptions: 50,
    socketFactory: () => new ControlledSocket() });
  const indicators = new IndicatorDataManager({ cache: market.cache, gate, streams, coalesceMs: 40,
    compute: input => routeIndicatorComputeBatch(input, async ({ jobs }) => {
      if (!backendAvailable) { backendFailures += 1; throw new Error("controlled backend offline"); }
      return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey,
        payload: parseIndicatorPayloadEnvelope({ ok: true, lines: [{ id: "ema", data: job.request.ohlcv.map(row => ({ time: row.time, value: row.close })) }] }) })) };
    }, async (request, signal) => {
      browserExecutions += 1;
      if (cancelNextBrowser) { cancelNextBrowser = false; throw new DOMException("superseded input", "AbortError"); }
      return computeFrontendScript(request, signal);
    }),
    range: async ({ requests }) => {
      hostedExecutions += 1;
      return { ok: true, results: requests.map(request => ({ clientId: request.clientId, payload: parseIndicatorPayloadEnvelope({ ok: true,
        lines: [{ id: "ema", data: corpus.get(request.symbol)!.map(row => ({ time: row.time, value: row.close })) }] }) })) };
    },
  });
  const dataFlow = new ChartDataFlowManager(market, indicators);
  const resources: MarketDataWorkspaceResources = { brokerEnabled: true, dataManager: market, indicatorDataManager: indicators, dataFlow,
    klineApi: market, streamCoordinator: market, requestCoordinator: market.requestCoordinator,
    indicatorStreamCoordinator: streams, workScheduler: null, windowRegistry: new MarketWindowRegistry() };
  const hosts = ["left", "right"].map(id => {
    const element = document.createElement("div"); element.style.cssText = "width:600px;height:240px"; document.body.append(element);
    const chart = createChart(element, { width: 600, height: 240 });
    const candle = chart.addSeries(CandlestickSeries), line = chart.addSeries(LineSeries);
    return { id, element, chart, candle, line };
  });
  const program = 'const until=Date.now()+120; while(Date.now()<until) {} plot("close",bars.map(bar=>bar.close));';
  const definition = { id: "js", language: "frontend-js", script: program, visible: true };
  const persistence = hosts.map(({ id }) => {
    const storage = new Map<string, string>();
    const saved = createActiveIndicatorPersistence(id, { getItem: key => storage.get(key) ?? null, setItem: (key, value) => { storage.set(key, value); } });
    saved.save([definition]); return saved;
  });
  const latest = new Map<string, IndicatorRuntime>();
  const rootHost = document.createElement("div"); document.body.append(rootHost); const root = createRoot(rootHost);
  const controller = new ChartMarketController({ owner: "chart:left", data: dataFlow.forChart("chart:left"), hoverDwellMs: 0 });
  const windows = hosts.map(host => resources.windowRegistry.createWindow(host.id));
  function Cell({ index, symbol, revision }: { index: number; symbol: string; revision: number }) {
    const host = hosts[index]!;
    const streamIdentity = useMemo(() => ({ cellId: host.id, workspaceId: "flow", windowId: "browser" }), [host.id]);
    const rows = useMemo(() => {
      void revision; // Explicit fixture publication boundary after source admission.
      return [...market.cache.read(identity(symbol), { limit: 2000 }).rows];
    }, [symbol, revision]);
    const owned = windows[index]!;
    const selection = useMemo(() => owned.prepareSelection(symbol), [owned, symbol]);
    const reader = useMemo(() => {
      owned.activate(selection);
      return owned.transact(selection, () => owned.getOrCreate(symbol, { intervalSeconds: 60 }))!;
    }, [owned, selection, symbol]);
    useLayoutEffect(() => { owned.transact(selection, () => owned.apply(symbol, { type: "replace", rows })); }, [owned, rows, selection, symbol]);
    const meta = useMemo(() => ({ status: "ready" as const, version: revision, source: "fixture", committedAt: 1 }), [revision]);
    const runtime = useIndicatorRuntime({ chartData: rows, chartDataMeta: meta, ...identity(symbol), datasetKey: symbol, sessionKey: symbol,
      autoAddVolume: false, indicatorPersistence: persistence[index]!, candleUpColor: "#0f0", candleDownColor: "#f00",
      marketData: structuralMock<MarketDataRuntimeContract>({ view: { seriesStore: reader } }),
      streamIdentity });
    useLayoutEffect(() => { latest.set(host.id, runtime); });
    useEffect(() => { host.candle.setData(rows.map(row => ({ time: Number(row.time) as UTCTimestamp, open: row.open!, high: row.high!, low: row.low!, close: row.close! }))); }, [host, rows]);
    useEffect(() => { host.line.setData((runtime.view.activeIndicators[0]?.lines?.[0]?.data || []).map(point => ({ time: Number(point.time) as UTCTimestamp, value: Number(point.value) }))); }, [host, runtime.view.activeIndicators]);
    return <output>{runtime.view.activeIndicators[0]?.lines?.[0]?.data.at(-1)?.value}</output>;
  }
  const render = (symbol = "BTCUSDT", revision = 1, rightRevision = 1) => flushSync(() => root.render(<MarketDataWorkspaceContext.Provider value={resources}>
    <Cell index={0} symbol={symbol} revision={revision} /><Cell index={1} symbol="BTCUSDT" revision={rightRevision} />
  </MarketDataWorkspaceContext.Provider>));
  const value = (id: string) => latest.get(id)?.view.activeIndicators[0]?.lines?.[0]?.data.at(-1)?.value;
  try {
    render(); await until(() => value("left") === 10 && value("right") === 10, "initial two-chart JS did not publish");
    assert(browserExecutions === 1, `same chart input computed ${browserExecutions} times`);
    assert(indicators.inputs.diagnostics().subscriptions === 2, "real runtimes did not retain explicit shared input ranges");
    checks.push("two committed React runtimes share one real browser-worker computation");
    hosts[1]!.chart.timeScale().setVisibleRange({ from: (start + 60 * 30) as UTCTimestamp, to: (start + 60 * 180) as UTCTimestamp });
    // Lightweight Charts applies this command on its render frame. Capture the
    // requested historical range only after it has actually been committed.
    await until(() => Number(hosts[1]!.chart.timeScale().getVisibleRange()?.from) === start + 60 * 30, "historical viewport did not commit");
    const viewport = JSON.stringify(hosts[1]!.chart.timeScale().getVisibleRange());
    controller.preview(identity("ETHUSDT"), ["1m"]);
    await until(() => dataFlow.diagnostics().warmed >= 1, "enabled JS plan did not prewarm healthy target");
    const before = browserExecutions;
    controller.activate(identity("ETHUSDT")); render("ETHUSDT");
    await until(() => value("left") === 20, "warm result did not publish after switch"); await delay(450);
    assert(browserExecutions === before, "warm switch repeated the JS computation");
    assert(value("right") === 10 && JSON.stringify(hosts[1]!.chart.timeScale().getVisibleRange()) === viewport, `switch changed other chart: value=${value("right")}, before=${viewport}, after=${JSON.stringify(hosts[1]!.chart.timeScale().getVisibleRange())}`);
    checks.push("hover warms enabled JS; selection reuses exact cache without another worker and preserves the other chart viewport");
    const hostedPlan = dataFlow.registerPlan("hosted-preview", { indicators: [{ id: "ema", engineName: "EMA", params: { length: 20 } }],
      candleUpColor: "#0f0", candleDownColor: "#f00" });
    const hostedWarm = dataFlow.forChart("hosted-preview").warm(identity("ETHUSDT"), { owner: "hosted-preview", reason: "hover", nativeIntervals: ["1m"] });
    await until(() => dataFlow.diagnostics().warmed === 2, "hosted indicator did not prewarm through range transport");
    assert(hostedExecutions === 1 && browserExecutions === before && sockets.length === 0, "hosted warm used browser execution, live subscriptions or duplicated requests");
    hostedWarm.release(); hostedPlan();
    checks.push("hosted prewarm uses the bounded HTTP range route without starting an indicator WebSocket");
    const a = new AbortController(), b = new AbortController();
    const request = { ...identity("ETHUSDT"), language: "frontend-js", script: program + "\n// independent demand", ohlcv: buildIndicatorOhlcv([...market.cache.read(identity("ETHUSDT")).rows]) };
    const one = indicators.compute({ jobs: [{ clientId: "one", jobKey: "one", request }], signal: a.signal }).then(() => "unexpected", error => (error as Error).name);
    const two = indicators.compute({ jobs: [{ clientId: "two", jobKey: "two", request }], signal: b.signal });
    await delay(65); a.abort(); assert(await one === "AbortError", "cancelled chart received a result");
    assert((await two).results[0]?.payload.ok, "other chart lost shared worker after cancellation");
    checks.push("cancelling one live consumer leaves the other's real worker computation running");
    const corrected = { ...corpus.get("ETHUSDT")![0]!, close: 77 };
    sequence.set("ETHUSDT", 2); market.cache.admitRealtime(identity("ETHUSDT"), corrected, "bar.amended", wire("ETHUSDT"), null);
    await until(() => latest.get("left")?.view.activeIndicators[0]?.lines?.[0]?.data[0]?.value === 77, "correction retained stale prewarmed output");
    assert(windows[0]!.get("ETHUSDT")!.first()?.close === 20, "test accidentally supplied the corrected private chart window");
    render("ETHUSDT", 2);
    assert(value("right") === 10 && JSON.stringify(hosts[1]!.chart.timeScale().getVisibleRange()) === viewport, "correction changed unrelated chart");
    checks.push("shared cache range notification recomputes corrected JS values before private window publication; unrelated chart stays unchanged");
    const beforeFailure = browserExecutions;
    flushSync(() => {
      latest.get("left")!.actions.addIndicator({ id: "offline-ema", engineName: "EMA", executionTarget: "local", params: { period: 20 } });
      latest.get("left")!.actions.updateIndicatorScript("js", program + "\n// mixed transport failure", "frontend-js", "safe");
    });
    await until(() => latest.get("left")?.view.activeIndicators.find(item => item.id === "offline-ema")?.error === "controlled backend offline", "backend failure was not observed");
    const jsAfterFailure = latest.get("left")!.view.activeIndicators.find(item => item.id === "js")!;
    assert(backendFailures > 0 && browserExecutions > beforeFailure && !jsAfterFailure.error && jsAfterFailure.lines?.[0]?.data[0]?.value === 77,
      "backend transport failure poisoned the independent browser computation");
    backendAvailable = true; latest.get("left")!.actions.recompute(true);
    await until(() => { const item = latest.get("left")?.view.activeIndicators.find(item => item.id === "offline-ema"); return Boolean(item?.lines?.length && !item.error); }, "backend result did not recover");
    assert(value("right") === 10 && JSON.stringify(hosts[1]!.chart.timeScale().getVisibleRange()) === viewport, "transport failure changed unrelated chart");
    checks.push("failed backend work cannot poison a pending real JS worker; backend recovery preserves the other chart");
    const beforeCancellation = browserExecutions;
    cancelNextBrowser = true; latest.get("left")!.actions.recompute(true);
    await until(() => browserExecutions > beforeCancellation, "cancelled computation did not run");
    await delay(150);
    assert(!latest.get("left")!.view.activeIndicators.find(item => item.id === "js")!.error,
      "superseded computation became a persistent script error");
    sequence.set("ETHUSDT", 3);
    market.cache.admitRealtime(identity("ETHUSDT"), { ...corrected, close: 88 }, "bar.amended", wire("ETHUSDT"), null);
    render("ETHUSDT", 3);
    await until(() => latest.get("left")?.view.activeIndicators[0]?.lines?.[0]?.data[0]?.value === 88,
      "fresh source did not automatically compute after cancellation");
    checks.push("superseded input cancellation is not a script failure and fresh demand still computes");
    render("BTCUSDT", 4);
    await until(() => value("left") === 10, "left did not return to shared source");
    const hosted = (id: string) => latest.get(id)?.view.activeIndicators.find(item => item.id === "shared-" + id);
    const hostedValue = (id: string) => hosted(id)?.lines?.[0]?.data.at(-1)?.value;
    const addHosted = (id: string) => flushSync(() => latest.get(id)!.actions.addIndicator({ id: "shared-" + id,
      name: "Shared EMA", engineName: "EMA", executionTarget: "hosted", params: { period: 20 }, visible: true }));
    addHosted("left");
    await until(() => hostedValue("left") === 20, "first hosted runtime did not receive real controller preview");
    const firstHistory = hosted("left")!.lines![0]!.data[0]!.time;
    addHosted("right");
    await until(() => streams.diagnostics().logicalSubscriptions === 2 && hostedValue("right") === 20, "late hosted runtime did not join");
    let socket = sockets[0]!;
    assert(Number(sockets.length) === 1 && socket.subscriptions.size === 1 && streams.diagnostics().subscriptions === 1,
      `equal hosted runtimes retained duplicate wire subscriptions: ${JSON.stringify({ diagnostics: streams.diagnostics(), sockets: sockets.map(item => ({ readyState: item.readyState, active: [...item.subscriptions.values()] })) })}`);
    assert(hostedValue("left") === 20 && hosted("left")!.lines![0]!.data[0]!.time === firstHistory,
      "late join discarded the first chart's historical output");
    assert(JSON.stringify(hosts[1]!.chart.timeScale().getVisibleRange()) === viewport, "late join moved the independent viewport");
    checks.push("two real hosted React runtimes share one wire; late join receives a fresh ACK and preserves prior history/viewport");
    socket.serverClose();
    await until(() => sockets.length === 2 && sockets[1]!.subscriptions.size === 1, "shared overload reconnect did not restore one subscription");
    socket = sockets[1]!;
    const recoveredWire = [...socket.subscriptions.keys()][0]!;
    assert(socket.subscriptions.get(recoveredWire)!.resumeFrom === undefined, "overload reconnect reused an unsafe resume cursor");
    socket.preview(recoveredWire, 73);
    await until(() => hostedValue("left") === 73 && hostedValue("right") === 73, "reconnected preview did not fan out to both React runtimes");
    assert(hosted("left")!.lines![0]!.data[0]!.time === firstHistory
      && JSON.stringify(hosts[1]!.chart.timeScale().getVisibleRange()) === viewport, "reconnect discarded history or moved the other viewport");
    checks.push("overload disconnect restores one cold shared subscription and both real runtimes resume without losing private history");
    const beforeGrowth = socket.subscribeCount;
    sequence.set("BTCUSDT", 2);
    market.cache.admitRealtime(identity("BTCUSDT"), { ...corpus.get("BTCUSDT")!.at(-1)!,
      time: (start + 501 * 60) as EpochSeconds, is_closed: false }, "bar.created", wire("BTCUSDT"), null);
    render("BTCUSDT", 5, 2);
    await delay(200);
    assert(socket.subscribeCount === beforeGrowth && socket.subscriptions.size === 1,
      "a normal new candle restarted the shared hosted subscription");
    checks.push("normal chart history growth preserves the live shared subscription without another subscribe");
    const sharedWire = [...socket.subscriptions.keys()][0]!;
    flushSync(() => latest.get("left")!.actions.updateIndicatorParams("shared-left", { period: 35 }));
    await until(() => socket.subscriptions.size === 2 && hostedValue("left") === 35, "parameter change did not split the wire");
    assert(socket.subscriptions.has(sharedWire) && hostedValue("right") === 73, "parameter edit reset the other chart's stream");
    flushSync(() => latest.get("left")!.actions.updateIndicatorParams("shared-left", { period: 20 }));
    await until(() => socket.subscriptions.size === 1 && hostedValue("left") === 20, "equal parameters did not rejoin");
    const beforeRelease = socket.subscribeCount;
    flushSync(() => latest.get("left")!.actions.removeIndicator("shared-left"));
    await until(() => streams.diagnostics().logicalSubscriptions === 1, "removed chart retained a stream consumer");
    assert(socket.subscribeCount === beforeRelease && socket.subscriptions.size === 1, "partial release reset the surviving stream");
    socket.preview([...socket.subscriptions.keys()][0]!, 61);
    await until(() => hostedValue("right") === 61, "surviving chart stopped receiving updates");
    assert(!hosted("left") && JSON.stringify(hosts[1]!.chart.timeScale().getVisibleRange()) === viewport, "release changed another chart");
    flushSync(() => latest.get("right")!.actions.removeIndicator("shared-right"));
    await until(() => streams.diagnostics().subscriptions === 0 && socket.readyState === 3, "final release leaked a transport");
    checks.push("parameter divergence splits only the affected demand; rejoin shares again and final release closes the transport");
    return { checks, browserExecutions, hostedExecutions, diagnostics: dataFlow.diagnostics(), streams: streams.diagnostics() };
  } finally {
    controller.releaseAll(); flushSync(() => root.unmount()); rootHost.remove();
    assert(indicators.inputs.diagnostics().subscriptions === 0, "unmounted runtimes retained input range leases");
    windows.forEach(window => window.close());
    dataFlow.dispose(); streams.closeAll(); market.closeAll(); gate.dispose(); unregister();
    hosts.forEach(host => { host.chart.remove(); host.element.remove(); });
  }
}
