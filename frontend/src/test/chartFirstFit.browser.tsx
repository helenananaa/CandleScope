import { useLayoutEffect, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import SingleChartPanes from "../components/SingleChartPanes.js";
import { useChartSurfaceRuntime, type ChartSurfaceActions, type ChartSurfaceVisibleRange } from "../chart-adapter/useChartSurfaceRuntime.js";
import { SeriesWindowStore } from "../features/market-data/window/seriesWindowStore.js";
import { getVisibleRangeForInterval, saveVisibleRangeForInterval } from "../features/chart-session/visibleRangeStorage.js";
import type { KlineBar } from "../features/market-data/marketDataTypes.js";
import type { VisibleRangeSnapshot } from "../features/chart-session/chartSessionTypes.js";

type Range = ChartSurfaceVisibleRange & { barSpacing: number; logical: { from: number; to: number }; time: { from: number; to: number } };

/** The chart's own spacing (chartPaneLifecycle timeScale.barSpacing). */
const DEFAULT_BAR_SPACING = 8;
const SAVE_DEBOUNCE_MS = 500;

function chartEvents(): unknown[] {
  const store = (window as unknown as { __CANDLESCOPE_PERF__?: { events?: Array<{ name: string; detail: unknown }> } }).__CANDLESCOPE_PERF__;
  return (store?.events ?? []).filter((event) => /viewport/.test(event.name)).slice(-8);
}
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(requestAnimationFrame); };
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
/** A deterministic market-like walk keyed on the minute, so overlapping windows agree. */
const mid = (minute: number) => 100 + 3 * Math.sin(minute / 37) + 1.5 * Math.sin(minute / 11.3) + 0.8 * Math.sin(minute / 3.7);
const bar = (time: number): KlineBar => {
  const minute = time / 60, open = mid(minute - 1), close = mid(minute);
  return { time: time as KlineBar["time"], open, close, volume: 10,
    high: Math.max(open, close) + 0.6 * Math.abs(Math.sin(minute * 7.1)),
    low: Math.min(open, close) - 0.6 * Math.abs(Math.cos(minute * 5.3)) };
};
const windowEnding = (last: number, count: number): KlineBar[] => Array.from(
  { length: count }, (_, i) => bar(last - (count - 1 - i) * 60));
/** LWC sets spacing to width / (to - from + 1) for a visible logical range. */
const plotWidth = (range: Range) => range.barSpacing * (range.logical.to - range.logical.from + 1);

/** Screenshots for review, taken only when the harness runs with --capture. */
async function capture(name: string) {
  if (!new URLSearchParams(location.search).has("capture")) return;
  const target = window as Window & { __replayNoteCapture?: string | null };
  target.__replayNoteCapture = name;
  const deadline = Date.now() + 20_000;
  while (target.__replayNoteCapture !== null && Date.now() < deadline) await sleep(50);
}

/** #572 1.0.x: a fresh profile sometimes opened the 1m chart on about nine
 * bars at about 85 px. The first fit ran while the window held about four
 * bars (the five-bar latest request on a slow network); the full history was
 * added on the left at that spacing, the spacing was saved, and every reopen
 * restored it. */
export async function checkChartFirstFit() {
  const host = document.createElement("div"), style = document.createElement("style");
  host.className = "qa-first-fit";
  style.textContent = ".qa-first-fit section{width:800px;height:400px;position:relative;display:flex}.qa-first-fit .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-first-fit .chart-pane{position:absolute;inset:0}";
  document.head.append(style); document.body.append(host);
  const failures: string[] = [];
  const expect = (value: unknown, message: string) => {
    if (!value) failures.push(`${message} events=${JSON.stringify(chartEvents())}`);
  };
  // An hour back keeps every row in the past for the live store's future policy.
  const now = Math.floor(Date.now() / 60_000) * 60 - 3_600;
  const scopeBase = `qa-first-fit-${crypto.randomUUID()}`;
  const saved = (scope: string) => getVisibleRangeForInterval("BTCUSDT", "1m", "spot", "binance", scope);

  async function mount(scope: string, savedVisibleRange: VisibleRangeSnapshot | null) {
    const root = createRoot(host);
    const store = new SeriesWindowStore({ seriesKey: scope, rightTruncatedFuturePolicy: "reject", intervalSeconds: 60 });
    let source = "initial-history";
    let surface: ChartSurfaceActions | null = null;
    const save = (range: unknown) => saveVisibleRangeForInterval("BTCUSDT", "1m", range, "spot", "binance", null, scope);
    function FirstFitCell() {
      const chart = useChartSurfaceRuntime();
      const version = useSyncExternalStore((listener) => store.subscribe(() => listener()), () => store.version);
      useLayoutEffect(() => { surface = chart.actions; });
      return <section><SingleChartPanes ref={chart.ref} seriesStore={store} datasetKey={scope}
        dataMeta={{ seriesKey: store.seriesKey, version, status: "ready", source, committedAt: null }}
        symbol="BTCUSDT" interval="1m" chartType="candlestick" theme="dark" customBg=""
        upColor="#22ab94" downColor="#f23645" drawingReadOnly followLatest={false}
        savedVisibleRange={savedVisibleRange} onVisibleRangeChange={save}
        rightWindowTruncated={store.rightTruncated} /></section>;
    }
    const commit = async (rows: KlineBar[], nextSource: string) => {
      source = nextSource;
      flushSync(() => store.replace(rows, { source: nextSource }));
      for (let i = 0; i < 4; i++) await settle();
    };
    const range = (label: string): Range => {
      const value = surface?.getVisibleRange();
      if (!value?.logical || !value.time || typeof value.barSpacing !== "number") {
        throw new Error(`${label}: missing range ${JSON.stringify(value)}`);
      }
      return value as Range;
    };
    // The page's beforeunload save reads the chart's current range.
    const saveOnUnload = () => save(surface?.getVisibleRange());
    flushSync(() => root.render(<FirstFitCell />));
    await settle();
    return { root, store, commit, range, saveOnUnload, surface: () => surface };
  }

  const results: Record<string, unknown> = {};
  try {
    // 1. Fresh profile: the first window holds four bars, then the full history arrives.
    {
      const scope = `${scopeBase}-fresh`;
      const cell = await mount(scope, null);
      await cell.commit(windowEnding(now, 4), "initial-history");
      const fewBars = cell.range("four-bar first window");
      const width = plotWidth(fewBars);
      expect(fewBars.time.from <= now - 3 * 60 && fewBars.time.to >= now,
        `the four-bar window is not on screen ${JSON.stringify(fewBars)}`);
      cell.saveOnUnload();
      await sleep(SAVE_DEBOUNCE_MS + 200);
      const savedFewBars = saved(scope);
      expect(!(Number(savedFewBars?.barSpacing) > DEFAULT_BAR_SPACING),
        `the four-bar fit's spacing was saved ${JSON.stringify({ fewBars, savedFewBars })}`);

      await cell.commit(windowEnding(now, 500), "backfill-completed");
      await capture("first-fit-history");
      const history = cell.range("after the full history");
      const fitSpacing = width / 505;
      expect(Math.abs(history.barSpacing - fitSpacing) < 0.05,
        `the full history did not refit: ${history.barSpacing.toFixed(2)} px a bar, fit is ${fitSpacing.toFixed(2)} ${JSON.stringify({ fewBars, history })}`);
      // The price axis can widen by a few pixels when it draws the whole
      // window, which trims a bar or two on the left (main's fit does too).
      expect(history.logical.from <= 5 && history.time.to >= now,
        `the full history is not on screen ${JSON.stringify(history)}`);
      await sleep(SAVE_DEBOUNCE_MS + 200);
      const savedHistory = saved(scope);
      expect(Math.abs(Number(savedHistory?.barSpacing) - history.barSpacing) < 0.05,
        `the full-history fit was not saved ${JSON.stringify({ history, savedHistory })}`);

      // A live bar after the full fit keeps the zoom and the newest bar on screen (#630).
      await cell.commit(windowEnding(now + 60, 501), "polling-latest");
      const live = cell.range("after a live bar");
      expect(Math.abs(live.barSpacing - history.barSpacing) < 0.05 && live.time.to >= now + 60,
        `a live bar after the full fit changed the view ${JSON.stringify({ history, live })}`);
      results.fresh = { width, fewBars, savedFewBars, history, savedHistory, live };
      flushSync(() => cell.root.unmount());
    }

    // 2. A zoom the user makes on the few-bar view stays through the history.
    let userSpacing: number | null = null;
    {
      const scope = `${scopeBase}-user`;
      const cell = await mount(scope, null);
      await cell.commit(windowEnding(now, 4), "initial-history");
      const before = cell.range("four-bar first window");
      const pane = host.querySelector("table canvas") ?? host.querySelector("canvas");
      const box = pane?.getBoundingClientRect();
      expect(pane && box, "no chart canvas to zoom");
      if (pane && box) {
        pane.dispatchEvent(new WheelEvent("wheel", {
          bubbles: true, cancelable: true, deltaY: 60, deltaMode: 0,
          clientX: box.left + box.width * 0.6, clientY: box.top + box.height / 2,
        }));
      }
      for (let i = 0; i < 4; i++) await settle();
      const zoomed = cell.range("after the user zoom");
      expect(Math.abs(zoomed.barSpacing - before.barSpacing) > 1, `the wheel did not zoom ${JSON.stringify({ before, zoomed })}`);
      await cell.commit(windowEnding(now, 500), "backfill-completed");
      const history = cell.range("user zoom after the full history");
      expect(Math.abs(history.barSpacing - zoomed.barSpacing) < 0.05,
        `the full history replaced the user's zoom ${JSON.stringify({ zoomed, history })}`);
      await sleep(SAVE_DEBOUNCE_MS + 200);
      const savedUser = saved(scope);
      expect(Math.abs(Number(savedUser?.barSpacing) - zoomed.barSpacing) < 0.05,
        `the user's zoom was not saved ${JSON.stringify({ zoomed, savedUser })}`);
      userSpacing = Number(savedUser?.barSpacing);
      results.user = { before, zoomed, history, savedUser };
      flushSync(() => cell.root.unmount());
    }

    // 3. A 1.0.0 profile saved the four-bar fit's spacing (about 85 px in
    // the smoke test). Reopening fits the history instead of restoring it.
    {
      const scope = `${scopeBase}-legacy`;
      const probe = await mount(`${scope}-probe`, null);
      await probe.commit(windowEnding(now - 60, 4), "initial-history");
      const fewBars = probe.range("the four-bar fit 1.0.0 saved");
      flushSync(() => probe.root.unmount());
      const legacy = { barSpacing: fewBars.barSpacing, rightOffset: 4, rightmostTime: now - 60, savedAt: Date.now() - 86_400_000 };
      const cell = await mount(scope, legacy);
      await cell.commit(windowEnding(now, 500), "initial-history");
      await capture("first-fit-reopen");
      const reopened = cell.range("reopened 1.0.0 profile");
      const fitSpacing = plotWidth(reopened) / 505;
      expect(Math.abs(reopened.barSpacing - fitSpacing) < 0.05,
        `the saved four-bar fit was restored: ${reopened.barSpacing.toFixed(2)} px a bar, fit is ${fitSpacing.toFixed(2)} ${JSON.stringify({ legacy, reopened })}`);
      results.legacy = { fewBars, legacy, reopened };
      flushSync(() => cell.root.unmount());
    }

    // 4. A deliberate zoom saved by the user is restored as saved.
    {
      const scope = `${scopeBase}-kept`;
      const kept = { barSpacing: userSpacing ?? 23.7, rightOffset: 3.25, rightmostTime: now, savedAt: Date.now() - 86_400_000 };
      const cell = await mount(scope, kept);
      await cell.commit(windowEnding(now, 500), "initial-history");
      const reopened = cell.range("reopened deliberate zoom");
      // The restore places the range at the pane width it reads before the
      // first draw, so a price axis that widens on that draw moves the
      // spacing a few percent (the same on main). A refit would be ~1.4 px.
      expect(Math.abs(reopened.barSpacing / kept.barSpacing - 1) < 0.05,
        `a deliberate zoom was not restored ${JSON.stringify({ kept, reopened })}`);
      results.kept = { kept, reopened };
      flushSync(() => cell.root.unmount());
    }
  } finally { host.remove(); style.remove(); }
  if (failures.length) throw new Error(failures.join("\n"));
  return { passed: true, scope: "Actual SingleChartPanes, chart canvas, live window store and visible-range storage with synthetic commits; not full live runtime or native qualification", ...results };
}
