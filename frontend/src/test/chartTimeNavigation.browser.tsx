import { useLayoutEffect, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import SingleChartPanes from "../components/SingleChartPanes.js";
import { useChartSurfaceRuntime, type ChartSurfaceActions } from "../chart-adapter/useChartSurfaceRuntime.js";
import { useChartTimeNavigation } from "../features/market-data/useChartTimeNavigation.js";
import { SeriesWindowStore } from "../features/market-data/window/seriesWindowStore.js";
import { ChartWorkScheduler } from "../features/market-data/chartWorkScheduler.js";
import type { MarketDataRuntimeContract } from "../features/market-data/marketDataRuntimeContract.js";
import type { KlineBar } from "../features/market-data/marketDataTypes.js";
import { ChartLinkCoordinator } from "../features/chart-workspace/chartLinkCoordinator.js";
import { createDefaultChartWorkspace } from "../features/chart-workspace/chartWorkspaceStorage.js";
import { partialMock } from "./testHelpers.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(requestAnimationFrame); };
const rows = (start: number): KlineBar[] => Array.from({ length: 501 }, (_, i) => ({
  time: (start + i * 60) as KlineBar["time"], open: 100, close: 101 + Math.sin(i), high: 103, low: 99, volume: 10,
}));

export async function checkChartTimeNavigation() {
  const host = document.createElement("div"), style = document.createElement("style");
  host.className = "qa-date-navigation";
  style.textContent = ".qa-date-navigation section{width:600px;height:360px;position:relative;display:flex}.qa-date-navigation .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-date-navigation .chart-pane{position:absolute;inset:0}";
  document.head.append(style); document.body.append(host);
  const root = createRoot(host), documentState = createDefaultChartWorkspace();
  for (const group of Object.values(documentState.linkGroups)) { group.peerPolicy.dateRange = false; group.peerPolicy.timeAnchor = false; }
  const links = new ChartLinkCoordinator(documentState);
  const ids = ["cell-1", "cell-2"];
  const stores = ids.map((id) => new SeriesWindowStore({ seriesKey: id }));
  stores.forEach((store) => store.replace(rows(1_700_000_040)));
  let frameId = 0;
  const frames = new Map<number, () => void>();
  const scheduler = new ChartWorkScheduler({ now: () => 0,
    requestFrame: (callback) => { frames.set(++frameId, callback); return frameId; },
    cancelFrame: (handle) => { frames.delete(handle); },
  });
  ids.forEach((id) => scheduler.registerCell(id));
  const drivers = ids.map((cellId) => ({ scheduler, cellId }));
  const flushDisplay = async () => {
    for (let i = 0; frames.size && i < 10; i++) {
      const callbacks = [...frames.values()]; frames.clear();
      flushSync(() => callbacks.forEach((callback) => callback())); await settle();
    }
  };
  const surfaces = new Map<string, ChartSurfaceActions>();
  const requests: Array<{ cellId: string; time: number }> = [];
  function Cell({ index }: { index: number }) {
    const cellId = ids[index]!, store = stores[index]!, surface = useChartSurfaceRuntime();
    useSyncExternalStore((listener) => store.subscribe(() => listener()), () => store.version);
    useLayoutEffect(() => { surfaces.set(cellId, surface.actions); });
    useChartTimeNavigation({ active: index === 0, enabled: true, cellId, workspaceId: "default", sessionKey: cellId,
      surface: surface.actions, links, marketData: partialMock<MarketDataRuntimeContract>({ actions: partialMock<MarketDataRuntimeContract["actions"]>({
        seekToTime: async (timeMs) => {
          requests.push({ cellId, time: timeMs });
          await Promise.resolve();
          store.replace(rows(timeMs / 1_000 - 250 * 60), {}, { rightEdgeCurrent: false });
          return { status: "located", requestedTimeMs: timeMs, actualTimeMs: timeMs, exact: true };
        },
      }) }),
    });
    return <section><SingleChartPanes ref={surface.ref} seriesStore={store} datasetKey={cellId} displayScheduler={drivers[index]!}
      dataMeta={{ seriesKey: store.seriesKey, version: store.version, status: "ready", source: "date-seek", committedAt: null }}
      symbol="BTCUSDT" interval="1m" chartType="candlestick" theme="dark" customBg=""
      upColor="#00aa00" downColor="#aa0000" drawingReadOnly followLatest={false} /></section>;
  }
  try {
    flushSync(() => root.render(<>{ids.map((id, index) => <Cell key={id} index={index} />)}</>));
    await settle(); await flushDisplay();
    for (const surface of surfaces.values()) assert(surface.setLinkedVisibleTimeRange({ from: 1_700_006_040, to: 1_700_012_040 }), "initial zoom failed");
    await settle();
    const before = ids.map((id) => surfaces.get(id)!.getVisibleRange());
    const target = 1_600_002_000_000;
    let positionedBeforePaint = false;
    const pending = links.seekToTime("cell-1", target).then((result) => { positionedBeforePaint = true; return result; });
    await settle();
    assert(!positionedBeforePaint, "navigation settled against an unpainted window");
    await flushDisplay();
    const independent = await pending; await settle();
    assert(independent[0]?.result.status === "located", JSON.stringify(independent));
    const after = surfaces.get("cell-1")!.getVisibleRange();
    assert(after?.logical && before[0]?.logical, "missing logical range");
    assert(Math.abs((after.logical.from + after.logical.to) / 2 - 250) < 0.1, `not centered: ${JSON.stringify(after)}`);
    assert(Math.abs((after.logical.to - after.logical.from) - (before[0].logical.to - before[0].logical.from)) < 0.1, "zoom changed");
    assert(JSON.stringify(surfaces.get("cell-2")!.getVisibleRange()) === JSON.stringify(before[1]), "independent sibling moved");
    assert(requests.length === 1, "independent sibling fetched");
    stores[0]!.applyTick({ ...stores[0]!.snapshot()[250]!, close: 102.5 });
    await settle(); await flushDisplay(); await settle();
    const amended = surfaces.get("cell-1")!.getVisibleRange()?.logical;
    assert(amended && Math.abs((amended.from + amended.to) / 2 - 250) < 0.1,
      `late amendment displaced date target: ${JSON.stringify(amended)}`);
    for (const group of Object.values(documentState.linkGroups)) group.peerPolicy.timeAnchor = true;
    links.updateDocument(documentState);
    const linkedPending = links.seekToTime("cell-1", target - 60_000);
    await settle(); await flushDisplay();
    const linked = await linkedPending; await settle();
    assert(linked.length === 2 && linked.every((item) => item.result.status === "located"), JSON.stringify(linked));
    for (const surface of surfaces.values()) {
      const logical = surface.getVisibleRange()?.logical;
      assert(logical && Math.abs((logical.from + logical.to) / 2 - 250) < 0.1, "linked target not centered");
    }
    // History can land after the navigation has settled. Its prepend changes
    // every logical index, but must preserve the selected source-time center.
    for (const store of stores) store.applyRange(rows(store.first()!.time - 100 * 60).slice(0, 100));
    await settle(); await flushDisplay(); await settle();
    const prepended = ids.map((id) => surfaces.get(id)!.getVisibleRange());
    for (const range of prepended) {
      assert(range?.logical && Math.abs((range.logical.from + range.logical.to) / 2 - 350) < 0.1,
        `late history displaced linked target: ${JSON.stringify(range)}`);
    }
    return { passed: true, scope: "Actual React navigation hook, chart canvas and window stores with synthetic seek transport; not full live runtime or native qualification", before, after, amended, independent, linked, prepended, requests };
  } finally { flushSync(() => root.unmount()); scheduler.dispose(); host.remove(); style.remove(); }
}
