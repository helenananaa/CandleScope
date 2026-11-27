import { useLayoutEffect, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import SingleChartPanes from "../components/SingleChartPanes.js";
import { useChartSurfaceRuntime, type ChartSurfaceActions, type ChartSurfaceVisibleRange } from "../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartTimeSeekResult } from "../features/market-data/chartTimeNavigation.js";
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
  // The runtime's seek callback keeps its identity while it commits; a new one
  // means a new data source and supersedes in-flight navigation.
  const marketData = ids.map((cellId, index) => partialMock<MarketDataRuntimeContract>({
    actions: partialMock<MarketDataRuntimeContract["actions"]>({
      seekToTime: async (timeMs) => {
        requests.push({ cellId, time: timeMs });
        await Promise.resolve();
        stores[index]!.replace(rows(timeMs / 1_000 - 250 * 60), {}, { rightEdgeCurrent: false });
        return { status: "located", requestedTimeMs: timeMs, actualTimeMs: timeMs, exact: true };
      },
    }),
  }));
  function Cell({ index }: { index: number }) {
    const cellId = ids[index]!, store = stores[index]!, surface = useChartSurfaceRuntime();
    useSyncExternalStore((listener) => store.subscribe(() => listener()), () => store.version);
    useLayoutEffect(() => { surfaces.set(cellId, surface.actions); });
    useChartTimeNavigation({ active: index === 0, enabled: true, cellId, workspaceId: "default", sessionKey: cellId,
      surface: surface.actions, links, marketData: marketData[index]! });
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
    const farFromLive = await checkFarJumpFromLiveWindow();
    return { passed: true, scope: "Actual React navigation hook, chart canvas and window stores with synthetic seek transport; not full live runtime or native qualification", before, after, amended, independent, linked, prepended, requests, farFromLive };
  } finally { flushSync(() => root.unmount()); scheduler.dispose(); host.remove(); style.remove(); }
}

/** RC 0be80267f: a jump from the live 1m window to a date months back collapsed
 * the zoom once history loaded to its left (spacing 1.51 -> 0.0055). The axis kept
 * the live tail's future carrier, so the view's right edge stayed at the live time. */
async function checkFarJumpFromLiveWindow() {
  const host = document.createElement("div"), style = document.createElement("style");
  host.className = "qa-far-date-navigation";
  style.textContent = ".qa-far-date-navigation section{width:800px;height:400px;position:relative;display:flex}.qa-far-date-navigation .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-far-date-navigation .chart-pane{position:absolute;inset:0}";
  document.head.append(style); document.body.append(host);
  const root = createRoot(host);
  const series = (start: number, count: number): KlineBar[] => rows(start).slice(0, count);
  const live = Math.floor(Date.now() / 60_000) * 60;
  const liveRows = () => Array.from({ length: 505 }, (_, i) => ({ ...rows(live - 504 * 60)[0]!, time: (live - (504 - i) * 60) as KlineBar["time"] }));
  const store = new SeriesWindowStore({ seriesKey: "far-cell", rightTruncatedFuturePolicy: "reject", intervalSeconds: 60 });
  store.replace(liveRows());
  let surface: ChartSurfaceActions | null = null;
  let submit: ((timeMs: number) => Promise<Array<{ cellId: string; result: ChartTimeSeekResult }>>) | null = null;
  // Same commit as the runtime's seek: replace with a bounded, right-truncated window.
  const marketData = partialMock<MarketDataRuntimeContract>({ actions: partialMock<MarketDataRuntimeContract["actions"]>({
    seekToTime: async (timeMs) => {
      await Promise.resolve();
      store.replace(series(timeMs / 1_000 - 250 * 60, 501), { source: "date-seek" }, { rightEdgeCurrent: false });
      return { status: "located", requestedTimeMs: timeMs, actualTimeMs: timeMs, exact: true };
    },
  }) });
  const restoreLatestWindow = async () => { store.replace(liveRows(), { source: "right-window-restore" }); return true; };
  function FarCell() {
    const chart = useChartSurfaceRuntime();
    const version = useSyncExternalStore((listener) => store.subscribe(() => listener()), () => store.version);
    useLayoutEffect(() => { surface = chart.actions; });
    const navigation = useChartTimeNavigation({ active: true, enabled: true, cellId: "far-cell", workspaceId: "default",
      sessionKey: "far-cell", surface: chart.actions, links: null, marketData });
    useLayoutEffect(() => { submit = navigation.submit; });
    return <section><SingleChartPanes ref={chart.ref} seriesStore={store} datasetKey="far-cell"
      dataMeta={{ seriesKey: store.seriesKey, version, status: "ready", source: "date-seek", committedAt: null }}
      symbol="BTCUSDT" interval="1m" chartType="candlestick" theme="dark" customBg=""
      upColor="#00aa00" downColor="#aa0000" drawingReadOnly onRestoreLatestWindow={restoreLatestWindow}
      canRestoreLatestWindow rightWindowTruncated={store.rightTruncated} /></section>;
  }
  const span = (range: ChartSurfaceVisibleRange | null) => (range?.logical ? range.logical.to - range.logical.from : NaN);
  // Same visible bar count. Spacing may move slightly when price labels resize
  // the plot; the RC collapse was 270x.
  const sameZoom = (range: ChartSurfaceVisibleRange | null, reference: ChartSurfaceVisibleRange, label: string) => {
    assert(range?.logical && range.time, `${label}: missing range`);
    const spacing = (range.barSpacing ?? NaN) / (reference.barSpacing ?? NaN);
    assert(Math.abs(span(range) - span(reference)) < 1 && spacing > 0.95 && spacing < 1.05,
      `${label}: zoom changed ${JSON.stringify({ range, reference })}`);
  };
  const showsWindowAround = (range: ChartSurfaceVisibleRange | null, targetSec: number, label: string) => {
    assert(range?.time, `${label}: missing time range`);
    const halfSpanSec = span(range) / 2 * 60;
    assert(range.time.from <= targetSec && range.time.to >= targetSec
      && range.time.to <= targetSec + halfSpanSec + 120 && range.time.from >= targetSec - halfSpanSec - 120,
      `${label}: target bars not in view ${JSON.stringify(range)}`);
  };
  try {
    flushSync(() => root.render(<FarCell />));
    for (let i = 0; i < 4; i++) await settle();
    const liveView = surface!.getVisibleRange();
    assert(liveView?.logical && liveView.barSpacing && liveView.time && liveView.time.to >= live, `live view ${JSON.stringify(liveView)}`);
    const firstTarget = (live - 96 * 86_400) * 1_000;
    const first = await submit!(firstTarget); await settle();
    assert(first[0]?.result.status === "located", JSON.stringify(first));
    const jumped = surface!.getVisibleRange();
    sameZoom(jumped, liveView, "far jump");
    showsWindowAround(jumped, firstTarget / 1_000, "far jump");
    // The runtime then loads a left page; the view keeps its dates and zoom.
    store.applyRange(series(store.first()!.time - 500 * 60, 500));
    await settle(); await settle();
    const paged = surface!.getVisibleRange();
    sameZoom(paged, liveView, "left page after far jump");
    showsWindowAround(paged, firstTarget / 1_000, "left page after far jump");
    const secondTarget = (live - 54 * 86_400) * 1_000;
    const second = await submit!(secondTarget); await settle();
    assert(second[0]?.result.status === "located", JSON.stringify(second));
    const followUp = surface!.getVisibleRange();
    sameZoom(followUp, liveView, "follow-up jump");
    showsWindowAround(followUp, secondTarget / 1_000, "follow-up jump");
    const back = host.querySelector<HTMLButtonElement>(".chart-return-to-realtime");
    assert(back && !back.disabled, "back-to-live is not offered after a far jump");
    back.click();
    for (let i = 0; i < 10 && store.rightTruncated; i++) await settle();
    await settle(); await settle();
    const restored = surface!.getVisibleRange();
    assert(!store.rightTruncated && restored?.time && restored.time.to >= live && restored.time.from < live,
      `back to live did not reach the live tail ${JSON.stringify(restored)}`);
    return { liveView, jumped, paged, followUp, restored };
  } finally { flushSync(() => root.unmount()); host.remove(); style.remove(); }
}
