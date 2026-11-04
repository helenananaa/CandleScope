import { act, createRef } from "react";
import { createRoot } from "react-dom/client";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import type { ChartSurfaceHandle } from "../useChartSurfaceRuntime.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";

const assert = (value: unknown, message: string) => { if (!value) throw new Error(message); };

/** A restored replay view must not disappear into future whitespace on split. */
export async function checkReplayResizeViewport() {
  const host = document.createElement("div"), style = document.createElement("style");
  host.style.cssText = "width:900px;height:400px;position:relative;display:flex";
  host.className = "qa-replay-resize";
  style.textContent = ".qa-replay-resize .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-replay-resize .chart-pane{position:absolute;inset:0}";
  document.head.append(style); document.body.append(host);
  const root = createRoot(host), surface = createRef<ChartSurfaceHandle>();
  const rows: KlineBar[] = Array.from({ length: 370 }, (_, i) => ({
    time: (1_800_000_000 + i * 60) as KlineBar["time"], open: 100 + i,
    high: 102 + i, low: 99 + i, close: 101 + i, volume: 10,
  }));
  const store = new SeriesWindowStore({ seriesKey: "replay-resize", intervalSeconds: 60 }); store.replace(rows);
  const settle = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 200)); }); };
  const center = (range: { from: number; to: number }) => (range.from + range.to) / 2;
  try {
    await act(async () => root.render(<SingleChartPanes ref={surface} seriesStore={store}
      symbol="FIXTURE" interval="1m" datasetKey="replay-resize" theme="dark" customBg="" upColor="#00aa00" downColor="#aa0000"
      drawingReadOnly followLatest subPanes={[]} />));
    await settle();
    // Reopen restores public time coordinates and suspends automatic following.
    assert(surface.current?.setLinkedVisibleTimeRange({ from: 1_800_000_000 + 319 * 60, to: 1_800_000_000 + 411 * 60 }), "restore not ready");
    await settle();
    const before = surface.current!.getVisibleRange()!;
    host.style.width = "400px"; await settle();
    const split = surface.current!.getVisibleRange()!;
    assert(Math.abs(center(before.logical!) - center(split.logical!)) < 0.15, `split moved restored center: ${JSON.stringify({ before, split })}`);
    assert(Math.abs(before.barSpacing! - split.barSpacing!) < 0.01, "split changed zoom");
    assert(split.logical!.from < rows.length - 1, "split shows only future whitespace");
    host.style.width = "900px"; await settle();
    const expanded = surface.current!.getVisibleRange()!;
    assert(Math.abs(center(before.logical!) - center(expanded.logical!)) < 0.15, "expand moved restored center");
    // A deliberate historical view remains historical through resize and ticks.
    assert(surface.current?.setLinkedVisibleTimeRange({ from: Number(rows[100]!.time), to: Number(rows[160]!.time) }), "history navigation not ready");
    await settle(); const historical = surface.current!.getVisibleRange()!;
    host.style.width = "400px"; await settle();
    await act(async () => store.applyRange([{ ...rows.at(-1)!, time: (1_800_000_000 + 370 * 60) as KlineBar["time"] }]));
    await settle(); const retained = surface.current!.getVisibleRange()!;
    assert(Math.abs(center(historical.logical!) - center(retained.logical!)) < 0.15, "resize or tick resumed following a historical view");
    return { status: "PASS", before, split, expanded, historical, retained };
  } finally { await act(async () => root.unmount()); host.remove(); style.remove(); }
}
