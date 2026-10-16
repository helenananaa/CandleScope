import { act, createRef } from "react";
import { createRoot } from "react-dom/client";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import type { ChartSurfaceHandle } from "../useChartSurfaceRuntime.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";

const assert = (condition: unknown, message: string) => { if (!condition) throw new Error(message); };

/** Exercise the production React surface, not a copy of its range calculation. */
export async function checkReplayInitialPane() {
  const host = document.createElement("div"), style = document.createElement("style");
  host.style.cssText = "width:700px;height:400px;position:relative;display:flex";
  style.textContent = ".qa-initial-pane .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-initial-pane .chart-pane{position:absolute;inset:0}.qa-initial-pane .chart-return-to-realtime{position:absolute;bottom:0;right:0}.qa-initial-pane .pane-overlay-anchor{position:absolute;left:10px}";
  host.className = "qa-initial-pane"; document.head.append(style); document.body.append(host);
  const root = createRoot(host), surface = createRef<ChartSurfaceHandle>();
  const rows: KlineBar[] = Array.from({ length: 628 }, (_, i) => ({ time: (1_800_000_000 + i * 60) as KlineBar["time"],
    open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 10 }));
  const store = new SeriesWindowStore({ seriesKey: "initial-pane" }); store.replace(rows.slice(-128));
  const paneId = "separate-initial-rsi";
  const render = (ready: boolean) => root.render(<SingleChartPanes ref={surface} seriesStore={store}
    symbol="FIXTURE" interval="1m" datasetKey="initial-pane" theme="dark" customBg="" upColor="#00aa00" downColor="#aa0000"
    drawingReadOnly followLatest={false} subPanes={[{ id: paneId, label: "RSI", statusText: ready ? null : "Calculating 25%",
      lines: ready ? [{ id: "rsi", pane: "separate", name: "RSI", data: rows.slice(-128).map(row => ({ time: Number(row.time), value: 50 })) }] : [] }]} />);
  const settle = async () => { await act(async () => { await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); }); };
  try {
    await act(async () => render(false)); await settle();
    const label = host.querySelector(`.indicator-pane-label[data-pane-id="${paneId}"]`);
    assert(label?.textContent?.includes("Calculating 25%"), "configured pending pane is missing on the real chart");
    assert(surface.current?.setLinkedVisibleTimeRange({ from: Number(rows[510]!.time), to: Number(rows[550]!.time) }), "chart viewport was not ready");
    await settle();
    assert(host.querySelector(".chart-return-to-realtime"), "historical view has no return control before prepend");
    const before = surface.current!.getVisibleRange();
    await act(async () => { store.applyRange(rows.slice(0, 500)); }); await settle();
    const after = surface.current!.getVisibleRange();
    assert(host.querySelector(".chart-return-to-realtime"), "history prepend hid the return control although the latest bar is off screen");
    assert(JSON.stringify(before?.time) === JSON.stringify(after?.time), `prepend moved the time viewport: ${JSON.stringify({ before, after })}`);
    await act(async () => render(true)); await settle();
    assert(host.querySelector(`.indicator-pane-label[data-pane-id="${paneId}"]`) === label, "ready indicator remounted its label/pane");
    assert(!label?.textContent?.includes("Calculating"), "ready pane retained its preparation label");
    await act(async () => { (host.querySelector(".chart-return-to-realtime") as HTMLButtonElement).click(); }); await settle();
    const latest = surface.current!.getVisibleRange();
    assert(!host.querySelector(".chart-return-to-realtime") && (latest?.logical?.to ?? 0) >= 627, "return control did not restore the real latest bar");
    return { name: "real chart keeps preparation pane, historical viewport and return control through prepend", status: "PASS", before, after, latest };
  } finally { await act(async () => root.unmount()); host.remove(); style.remove(); }
}
