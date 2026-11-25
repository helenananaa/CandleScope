import { useLayoutEffect, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import SingleChartPanes from "../components/SingleChartPanes.js";
import { useChartSurfaceRuntime, type ChartSurfaceActions, type ChartSurfaceVisibleRange } from "../chart-adapter/useChartSurfaceRuntime.js";
import { SeriesWindowStore } from "../features/market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../features/market-data/marketDataTypes.js";
function chartEvents(): unknown[] {
  const store = (window as unknown as { __CANDLESCOPE_PERF__?: { events?: Array<{ name: string; detail: unknown }> } }).__CANDLESCOPE_PERF__;
  return (store?.events ?? []).filter((event) => /candleSeries|viewport|futureTimeAxis/.test(event.name)).slice(-8);
}
function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(`${message} events=${JSON.stringify(chartEvents())}`);
}
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(requestAnimationFrame); };
const bar = (time: number, i: number): KlineBar => ({
  time: time as KlineBar["time"], open: 100, close: 101 + Math.sin(i), high: 103, low: 99, volume: 10,
});
const windowEnding = (last: number, count: number): KlineBar[] => Array.from(
  { length: count }, (_, i) => bar(last - (count - 1 - i) * 60, i));

/** RC6 861bf22db: reopening the app 25 minutes after closing it painted the
 * stored 1m rows first and placed the view on their last bar. The missed bars
 * then arrived as window commits; the view stayed on the stored tail with
 * 回到实时 while the newest bars were off screen. */
export async function checkChartReopenLiveTail() {
  const host = document.createElement("div"), style = document.createElement("style");
  host.className = "qa-reopen-live-tail";
  style.textContent = ".qa-reopen-live-tail section{width:800px;height:400px;position:relative;display:flex}.qa-reopen-live-tail .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-reopen-live-tail .chart-pane{position:absolute;inset:0}";
  document.head.append(style); document.body.append(host);
  const root = createRoot(host);
  // An hour back keeps every row in the past for the live store's future policy.
  const now = Math.floor(Date.now() / 60_000) * 60 - 3_600;
  const storedLast = now - 25 * 60;
  const store = new SeriesWindowStore({ seriesKey: "reopen-cell", rightTruncatedFuturePolicy: "reject", intervalSeconds: 60 });
  store.replace(windowEnding(storedLast, 489), { source: "initial-history" });
  let surface: ChartSurfaceActions | null = null;
  function ReopenCell() {
    const chart = useChartSurfaceRuntime();
    const version = useSyncExternalStore((listener) => store.subscribe(() => listener()), () => store.version);
    useLayoutEffect(() => { surface = chart.actions; });
    return <section><SingleChartPanes ref={chart.ref} seriesStore={store} datasetKey="reopen-cell"
      dataMeta={{ seriesKey: store.seriesKey, version, status: "ready", source: "initial-history", committedAt: null }}
      symbol="BTCUSDT" interval="1m" chartType="candlestick" theme="dark" customBg=""
      upColor="#00aa00" downColor="#aa0000" drawingReadOnly followLatest={false}
      savedVisibleRange={{ barSpacing: 1.5, rightOffset: 5 }} rightWindowTruncated={store.rightTruncated} /></section>;
  }
  const range = (label: string): ChartSurfaceVisibleRange & { logical: { from: number; to: number }; time: { from: number; to: number } } => {
    const value = surface?.getVisibleRange();
    assert(value?.logical && value.time, `${label}: missing range`);
    return value as ReturnType<typeof range>;
  };
  const span = (value: ReturnType<typeof range>) => value.logical.to - value.logical.from;
  const backToLiveShown = () => Boolean(host.querySelector(".chart-return-to-realtime"));
  try {
    flushSync(() => root.render(<ReopenCell />));
    for (let i = 0; i < 4; i++) await settle();
    const stored = range("stored rows");
    assert(stored.time.from <= storedLast && stored.time.to >= storedLast,
      `first view is not on the stored tail ${JSON.stringify(stored)}`);
    const storedRightSpace = stored.logical.to - (store.barCount - 1);

    // The missed 25 minutes arrive as one window commit (pending-gap-poll).
    store.replace(windowEnding(now, 500), { source: "pending-gap-poll" });
    for (let i = 0; i < 4; i++) await settle();
    const filled = range("after the gap fill");
    assert(filled.time.from <= now && filled.time.to >= now,
      `newest bar is off screen after the gap fill ${JSON.stringify({ stored, filled })}`);
    assert(Math.abs(span(filled) - span(stored)) < 1, `zoom changed ${JSON.stringify({ stored, filled })}`);
    assert(Math.abs(filled.logical.to - (store.barCount - 1) - storedRightSpace) < 0.5,
      `right-edge space changed ${JSON.stringify({ stored, filled })}`);
    assert(!backToLiveShown(), "回到实时 is offered although the newest bar is on screen");

    // A view in history keeps its range when bars arrive on the right.
    assert(surface!.setLinkedVisibleTimeRange({ from: now - 400 * 60, to: now - 200 * 60 }), "history view failed");
    for (let i = 0; i < 2; i++) await settle();
    const history = range("history view");
    store.replace(windowEnding(now + 5 * 60, 500), { source: "pending-gap-poll" });
    for (let i = 0; i < 4; i++) await settle();
    const historyAfter = range("history view after new bars");
    assert(Math.abs(historyAfter.time.from - history.time.from) < 61 && Math.abs(historyAfter.time.to - history.time.to) < 61,
      `history view moved ${JSON.stringify({ history, historyAfter })}`);

    // A jumped-to window (right edge not current) keeps its range when its
    // right side is paged in, even with its last bar on screen.
    const jumpLast = now - 30 * 86_400;
    store.replace(windowEnding(jumpLast, 501), { source: "date-seek" }, { rightEdgeCurrent: false });
    for (let i = 0; i < 4; i++) await settle();
    assert(surface!.setLinkedVisibleTimeRange({ from: jumpLast - 300 * 60, to: jumpLast }), "jump view failed");
    for (let i = 0; i < 2; i++) await settle();
    const jumped = range("jumped window");
    store.replace(windowEnding(jumpLast + 20 * 60, 521), { source: "right-window-page" }, { rightEdgeCurrent: false });
    for (let i = 0; i < 4; i++) await settle();
    const paged = range("jumped window after a right page");
    assert(Math.abs(paged.time.to - jumped.time.to) < 61 && Math.abs(paged.time.from - jumped.time.from) < 61,
      `jumped window followed its new right rows ${JSON.stringify({ jumped, paged })}`);
    return { passed: true, scope: "Actual SingleChartPanes, chart canvas and live window store with synthetic commits; not full live runtime or native qualification",
      stored, filled, history, historyAfter, jumped, paged };
  } finally { flushSync(() => root.unmount()); host.remove(); style.remove(); }
}
