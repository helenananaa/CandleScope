import { createRef } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";
import type { ChartSurfaceHandle } from "../useChartSurfaceRuntime.js";
import type { IndicatorLine } from "../../features/indicators/indicatorTypes.js";

/** Actual chart component, controlled cold-history and async indicator publication. */
export async function checkIndicatorHydration() {
  const host = document.createElement("div"), style = document.createElement("style");
  host.className = "qa-indicator-hydration";
  host.style.cssText = "width:700px;height:400px;position:relative;display:flex";
  style.textContent = ".qa-indicator-hydration .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-indicator-hydration .chart-pane{position:absolute;inset:0}";
  document.head.append(style); document.body.append(host);
  const root = createRoot(host), surface = createRef<ChartSurfaceHandle>();
  const settle = async () => { for (let i = 0; i < 3; i++) await new Promise(requestAnimationFrame); };
  let dataset = "cold-btc", interval = "1m", store = new SeriesWindowStore({ intervalSeconds: 60 });
  let lines: IndicatorLine[] = [];
  const render = () => flushSync(() => root.render(<SingleChartPanes ref={surface} seriesStore={store}
    symbol={dataset} interval={interval} datasetKey={dataset} theme="dark" customBg=""
    upColor="#00aa00" downColor="#aa0000" drawingReadOnly followLatest={false} mainOverlayLines={lines} />));
  const corpus = (step: number): KlineBar[] => Array.from({ length: 1500 }, (_, i) => ({
    time: (1_800_000_000 - (1500 - i) * step) as KlineBar["time"], open: 100, high: 102, low: 98,
    close: 100 + Math.sin(i), volume: 10, is_closed: true,
  }));
  const line = (rows: KlineBar[]): IndicatorLine[] => [{ indicatorId: "close", name: "close", type: "line",
    pane: "main", color: "#f59e0b", data: rows.map(b => ({time:b.time,value:b.close!})) }];
  try {
    const old = corpus(60); store.replace(old); lines = line(old); render(); await settle();
    surface.current!.setLinkedVisibleTimeRange({from:Number(old[100]!.time),to:Number(old[200]!.time)}); await settle();
    for (const seconds of [300,900,60,300]) {
      dataset += "-next"; interval = seconds === 60 ? "1m" : seconds === 300 ? "5m" : "15m";
      store = new SeriesWindowStore({ intervalSeconds: seconds }); lines = []; render(); await settle();
      const rows = corpus(seconds); store.replace(rows.slice(-500)); render(); await settle();
      lines = line(rows.slice(-500)); render(); await settle();
      const canvas = host.querySelector("canvas")!;
      const rect = canvas.getBoundingClientRect();
      canvas.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: rect.left + 250, clientY: rect.top + 120 }));
      // A shared-cache calculation may arrive before or after chart hydration.
      lines = line(rows); render();
      store.replace(rows); render(); await settle();
      lines = line(rows); render(); await settle();
      if (!surface.current?.getVisibleRange()?.time) throw new Error("cold hydration lost the chart surface");
    }
    return "real chart survives staged cold history and indicator publication across markets";
  } finally { flushSync(() => root.unmount()); host.remove(); style.remove(); }
}
