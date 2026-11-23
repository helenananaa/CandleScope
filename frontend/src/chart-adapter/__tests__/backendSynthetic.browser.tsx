import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { useLayoutEffect } from "react";
import MarketChartSurface from "../../features/market-chart-platform/MarketChartSurface.js";
import { createFrozenSnapshotSource, createLiveReferenceSource } from "../../features/market-chart-platform/marketChartSourceRuntime.js";
import { MarketDataWorkspaceProvider } from "../../features/market-data/MarketDataWorkspaceProvider.js";
import { BACKEND_SYNTHETIC_SERIES_ENABLED } from "../../features/market-data/synthetic/backendSyntheticFeature.js";
import type { SyntheticTransform } from "../../features/market-data/synthetic/syntheticSeries.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import { buildSeriesWindowKey } from "../../features/market-data/window/seriesWindowKey.js";
import { API_BASE } from "../../services/apiConfig.js";
import { useChartSurfaceRuntime } from "../useChartSurfaceRuntime.js";
import { RenkoProjector } from "../../features/chart-representation/projectors/renkoProjector.js";
import { HeikinAshiProjector } from "../../features/chart-representation/projectors/heikinAshiProjector.js";
import { PointFigureProjector } from "../../features/chart-representation/projectors/pointFigureProjector.js";
import { KagiProjector } from "../../features/chart-representation/projectors/kagiProjector.js";
import { LineBreakProjector } from "../../features/chart-representation/projectors/lineBreakProjector.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
const isSnapshot = (message: Record<string, unknown>) => message["type"] === "snapshot"
  || (message["type"] === "snapshot_chunk" && message["complete"] === true);
async function until(predicate: () => boolean, message: string, timeout = 10_000) {
  const deadline = performance.now() + timeout;
  while (!predicate()) { assert(performance.now() < deadline, message); await delay(30); }
}

export async function checkBackendSynthetic() {
  assert(BACKEND_SYNTHETIC_SERIES_ENABLED, "normal live charts must default to backend computation");
  await fetch(`${API_BASE}/fixture/reset`, { method: "POST" });
  const data = await (await fetch(`${API_BASE}/fixture/bars`)).json() as { rows: KlineBar[] };
  const source = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
  const store = new SeriesWindowStore({ seriesKey: buildSeriesWindowKey(source) });
  store.replace(data.rows);
  const secondStore = new SeriesWindowStore({ seriesKey: buildSeriesWindowKey(source) });
  const frozen = createFrozenSnapshotSource({ session: source, datasetId: "controlled", dataEpoch: "1",
    snapshotHash: "controlled", bars: data.rows });
  const live = createLiveReferenceSource({ sourceId: "synthetic-live", session: source, datasetKey: String(store.seriesKey),
    marketData: { ...frozen.marketData, view: { ...frozen.marketData.view, seriesStore: store } } });
  const secondLive = createLiveReferenceSource({ sourceId: "synthetic-live-second", session: source, datasetKey: String(store.seriesKey),
    marketData: { ...frozen.marketData, view: { ...frozen.marketData.view, seriesStore: secondStore } } });
  const host = document.createElement("div");
  host.style.cssText = "width:900px;height:500px;position:relative;display:flex";
  const style = document.createElement("style");
  style.textContent = ".chart-area{position:relative;flex:1;height:100%;min-width:0}.chart-pane{position:absolute;inset:0}";
  document.body.append(host); document.head.append(style);
  const root = createRoot(host);
  let surface: ReturnType<typeof useChartSurfaceRuntime> | null = null;
  const NativeSocket = window.WebSocket;
  const messages: Array<Record<string, unknown>> = [];
  const sockets: WebSocket[] = [];
  window.WebSocket = class extends NativeSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      sockets.push(this);
      this.addEventListener("message", event => { messages.push(JSON.parse(String(event.data)) as Record<string, unknown>); });
    }
  };
  const originalProject = RenkoProjector.prototype.projectWithState;
  const originalHaProject = HeikinAshiProjector.prototype.project;
  const originalPointFigure = PointFigureProjector.prototype.projectWithState;
  const originalKagi = KagiProjector.prototype.projectWithState;
  const originalLineBreak = LineBreakProjector.prototype.projectWithState;
  RenkoProjector.prototype.projectWithState = () => { throw new Error("browser Renko computation was invoked"); };
  HeikinAshiProjector.prototype.project = () => { throw new Error("browser HA computation was invoked"); };
  PointFigureProjector.prototype.projectWithState = () => { throw new Error("browser P&F computation was invoked"); };
  KagiProjector.prototype.projectWithState = () => { throw new Error("browser Kagi computation was invoked"); };
  LineBreakProjector.prototype.projectWithState = () => { throw new Error("browser Line Break computation was invoked"); };
  let chartType: SyntheticTransform = "renko";
  let showLeft = true, showSecond = false;
  function Probe({ second = false }: { second?: boolean }) {
    const runtime = useChartSurfaceRuntime();
    useLayoutEffect(() => { surface = runtime; });
    return <MarketChartSurface source={second ? secondLive : live} chartProps={{
      ref: runtime.ref, symbol: "BTCUSDT", interval: "1m", datasetKey: String(store.seriesKey),
      chartType, renkoBoxSizeMode: "traditional", renkoBoxSize: 2,
      pointFigureBoxSizeMode: "traditional", pointFigureBoxSize: 2, pointFigureReversalAmount: 2,
      kagiReversalMode: "traditional", kagiReversalAmount: 2, lineBreakNumberOfLines: 2,
      theme: "dark", customBg: "", upColor: "#00aa00", downColor: "#aa0000", drawingReadOnly: true,
    }} />;
  }
  const render = () => flushSync(() => root.render(<MarketDataWorkspaceProvider>
    {showLeft && <Probe key="left" />}{showSecond && <Probe key="right" second />}
  </MarketDataWorkspaceProvider>));
  const tick = async (close: number) => {
    const result = await (await fetch(`${API_BASE}/fixture/tick/${close}`, { method: "POST" })).json() as { row: KlineBar };
    store.applyTick(result.row);
    if (showSecond) secondStore.applyTick(result.row);
  };
  try {
    render();
    await until(() => messages.some(message => isSnapshot(message) && message["status"] === "ready"),
      "real backend synthetic snapshot did not arrive", 60_000);
    await until(() => Boolean((surface as ReturnType<typeof useChartSurfaceRuntime> | null)?.actions.captureViewportTransfer()),
      "backend bricks did not render on ordinal chart");
    const first = messages.find(isSnapshot)!;
    assert(first["total"] === 9, `independent fixed-box reference expected 9 bricks: ${JSON.stringify(first)}`);
    const update = await (await fetch(`${API_BASE}/fixture/tick/118`, { method: "POST" })).json() as { row: KlineBar };
    store.applyTick(update.row);
    await until(() => messages.some(message => message["type"] === "patch" && message["total"] === 11),
      "real backend preview did not update to 11 bricks");
    chartType = "heikin-ashi";
    render();
    const isHa = (message: Record<string, unknown>) =>
      (message["definition"] as { config?: { transform?: string } } | undefined)?.config?.transform === "heikin-ashi";
    await until(() => messages.some(message => isHa(message) && isSnapshot(message) && message["status"] === "ready"),
      "backend HA did not render after switching axis modes");
    const ha = messages.find(message => isHa(message) && isSnapshot(message))!;
    assert(ha["total"] === 5 && (ha["rows"] as Array<{ close: number }>).at(-1)?.close === 116,
      "independent HA snapshot reference differed");
    const haUpdate = await (await fetch(`${API_BASE}/fixture/tick/122`, { method: "POST" })).json() as { row: KlineBar };
    store.applyTick(haUpdate.row);
    await until(() => messages.some(message => isHa(message) && message["type"] === "patch"
      && (message["rows"] as Array<{ close: number }>).at(-1)?.close === 118),
      "backend HA preview did not update");
    const extra: unknown[] = [];
    for (const transform of ["point-and-figure", "kagi", "line-break"] as const) {
      await tick(114);
      const start = messages.length;
      chartType = transform; render();
      const matching = () => messages.slice(start).filter(message =>
        (message["definition"] as { config?: { transform?: string } } | undefined)?.config?.transform === transform);
      await until(() => matching().some(message => isSnapshot(message) && message["status"] === "ready"),
        `${transform} default backend snapshot missing`);
      const first = matching().find(isSnapshot)!;
      assert(first["total"] === 3, `${transform} independent initial reference differed`);
      await tick(118);
      await until(() => matching().some(message => message["type"] === "patch"
        && (message["rows"] as Array<{ close: number }>).at(-1)?.close === 118), `${transform} extension missing`);
      await tick(110);
      const retained = transform === "line-break" ? 2 : 3;
      await until(() => matching().some(message => message["type"] === "patch" && message["total"] === retained
        && (transform === "line-break" || (message["rows"] as Array<{ close: number }>).at(-1)?.close === 110)),
        `${transform} preview retraction missing`);
      extra.push({ transform, initial: 3, extendedClose: 118, retracted: retained });
    }
    const priorSockets = sockets.length, reconnectStart = messages.length;
    sockets.at(-1)!.close();
    await until(() => sockets.length > priorSockets && messages.slice(reconnectStart).some(message =>
      isSnapshot(message) && message["status"] === "ready"), "default backend reconnect failed");
    secondStore.replace(store.snapshot());
    const sharedSockets = sockets.length;
    showSecond = true; render();
    await delay(200);
    const shared = await (await fetch(`${API_BASE}/fixture/state`)).json() as { instances: number; leases: number };
    assert(sockets.length === sharedSockets && shared.instances === 1 && shared.leases === 1,
      "two independent chart windows did not share frontend transport/backend owner");
    showLeft = false; render();
    const survivorStart = messages.length;
    await tick(118);
    await until(() => messages.slice(survivorStart).some(message => message["type"] === "patch"
      && (message["rows"] as Array<{ close: number }>).at(-1)?.close === 118), "closing one chart stopped the survivor");
    assert(!host.textContent?.includes("temporarily unavailable"), "renderer reported unavailable after update");
    flushSync(() => root.unmount());
    await until(() => messages.length > 0, "missing wire observations");
    const deadline = performance.now() + 5000;
    let state: { instances: number; leases: number };
    do {
      state = await (await fetch(`${API_BASE}/fixture/state`)).json() as typeof state;
      if (!state.instances && !state.leases) break;
      await delay(30);
    } while (performance.now() < deadline);
    assert(!state.instances && !state.leases, "last chart leaked backend instance/lease");
    return { status: "PASS", scope: "default MarketChartSurface + workspace data center + real DataManager HTTP/WS; all five transforms",
      initialBricks: first["total"], updatedBricks: 11, haPreviewClose: 118, extra,
      reconnect: true, shared, browserComputation: 0, state };
  } finally {
    RenkoProjector.prototype.projectWithState = originalProject;
    HeikinAshiProjector.prototype.project = originalHaProject;
    PointFigureProjector.prototype.projectWithState = originalPointFigure;
    KagiProjector.prototype.projectWithState = originalKagi;
    LineBreakProjector.prototype.projectWithState = originalLineBreak;
    window.WebSocket = NativeSocket;
    flushSync(() => root.unmount());
    host.remove(); style.remove();
    live.dispose(); secondLive.dispose(); frozen.dispose();
  }
}
