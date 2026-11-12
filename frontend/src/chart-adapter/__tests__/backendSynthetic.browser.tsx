import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { useLayoutEffect } from "react";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import { buildSeriesWindowKey } from "../../features/market-data/window/seriesWindowKey.js";
import { API_BASE } from "../../services/apiConfig.js";
import { useChartSurfaceRuntime } from "../useChartSurfaceRuntime.js";
import { RenkoProjector } from "../../features/chart-representation/projectors/renkoProjector.js";
import { HeikinAshiProjector } from "../../features/chart-representation/projectors/heikinAshiProjector.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate: () => boolean, message: string, timeout = 10_000) {
  const deadline = performance.now() + timeout;
  while (!predicate()) { assert(performance.now() < deadline, message); await delay(30); }
}

export async function checkBackendSynthetic() {
  await fetch(`${API_BASE}/fixture/reset`, { method: "POST" });
  const data = await (await fetch(`${API_BASE}/fixture/bars`)).json() as { rows: KlineBar[] };
  const source = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
  const store = new SeriesWindowStore({ seriesKey: buildSeriesWindowKey(source) });
  store.replace(data.rows);
  const host = document.createElement("div");
  host.style.cssText = "width:900px;height:500px;position:relative;display:flex";
  const style = document.createElement("style");
  style.textContent = ".chart-area{position:relative;flex:1;height:100%;min-width:0}.chart-pane{position:absolute;inset:0}";
  document.body.append(host); document.head.append(style);
  const root = createRoot(host);
  let surface: ReturnType<typeof useChartSurfaceRuntime> | null = null;
  const NativeSocket = window.WebSocket;
  const messages: Array<Record<string, unknown>> = [];
  window.WebSocket = class extends NativeSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      this.addEventListener("message", event => { messages.push(JSON.parse(String(event.data)) as Record<string, unknown>); });
    }
  };
  const originalProject = RenkoProjector.prototype.projectWithState;
  const originalHaProject = HeikinAshiProjector.prototype.project;
  RenkoProjector.prototype.projectWithState = () => { throw new Error("browser Renko computation was invoked"); };
  HeikinAshiProjector.prototype.project = () => { throw new Error("browser HA computation was invoked"); };
  let chartType: "renko" | "heikin-ashi" = "renko";
  function Probe() {
    const runtime = useChartSurfaceRuntime();
    useLayoutEffect(() => { surface = runtime; });
    return <SingleChartPanes ref={runtime.ref} seriesStore={store} backendSyntheticSource={source}
      symbol="BTCUSDT" interval="1m" datasetKey={String(store.seriesKey)}
      chartType={chartType} renkoBoxSizeMode="traditional" renkoBoxSize={2}
      theme="dark" customBg="" upColor="#00aa00" downColor="#aa0000" drawingReadOnly />;
  }
  try {
    flushSync(() => root.render(<Probe />));
    await until(() => messages.some(message => message["type"] === "snapshot" && message["status"] === "ready"),
      "real backend synthetic snapshot did not arrive", 60_000);
    await until(() => Boolean((surface as ReturnType<typeof useChartSurfaceRuntime> | null)?.actions.captureViewportTransfer()),
      "backend bricks did not render on ordinal chart");
    const first = messages.find(message => message["type"] === "snapshot")!;
    assert(first["total"] === 9, `independent fixed-box reference expected 9 bricks: ${JSON.stringify(first)}`);
    const update = await (await fetch(`${API_BASE}/fixture/tick/118`, { method: "POST" })).json() as { row: KlineBar };
    store.applyTick(update.row);
    await until(() => messages.some(message => message["type"] === "patch" && message["total"] === 11),
      "real backend preview did not update to 11 bricks");
    chartType = "heikin-ashi";
    flushSync(() => root.render(<Probe />));
    const isHa = (message: Record<string, unknown>) =>
      (message["definition"] as { config?: { transform?: string } } | undefined)?.config?.transform === "heikin-ashi";
    await until(() => messages.some(message => isHa(message) && message["type"] === "snapshot" && message["status"] === "ready"),
      "backend HA did not render after switching axis modes");
    const ha = messages.find(message => isHa(message) && message["type"] === "snapshot")!;
    assert(ha["total"] === 5 && (ha["rows"] as Array<{ close: number }>).at(-1)?.close === 116,
      "independent HA snapshot reference differed");
    const haUpdate = await (await fetch(`${API_BASE}/fixture/tick/122`, { method: "POST" })).json() as { row: KlineBar };
    store.applyTick(haUpdate.row);
    await until(() => messages.some(message => isHa(message) && message["type"] === "patch"
      && (message["rows"] as Array<{ close: number }>).at(-1)?.close === 118),
      "backend HA preview did not update");
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
    return { status: "PASS", scope: "real DataManager cache/query/events, HTTP/WS and mounted Chromium Renko/HA renderer",
      initialBricks: first["total"], updatedBricks: 11, haPreviewClose: 118, browserComputation: 0, state };
  } finally {
    RenkoProjector.prototype.projectWithState = originalProject;
    HeikinAshiProjector.prototype.project = originalHaProject;
    window.WebSocket = NativeSocket;
    flushSync(() => root.unmount());
    host.remove(); style.remove();
  }
}
