import { act, useLayoutEffect, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import { useChartSurfaceRuntime, type ChartSurfaceVisibleRange } from "../useChartSurfaceRuntime.js";
import { useReplayCellViewport } from "../../features/replay/useReplayCellViewport.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";
import type { MainChartType } from "../../shared/mainChartTypes.js";

/** Real synthetic surface + saved-view hook, including async left-page fill. */
export async function checkReplaySyntheticViewportLifecycle() {
  const samples: unknown[] = [];
  const assert = (condition: unknown, message: string) => { if (!condition) throw new Error(message); };
  const rows: KlineBar[] = Array.from({ length: 638 }, (_, index) => {
    const open = 110 + Math.sin(index * 0.13), close = open + Math.sin(index * 0.41) * 0.12;
    return { time: (1_800_000_000 + index * 300) as KlineBar["time"], open, close,
      high: Math.max(open, close) + 0.1, low: Math.min(open, close) - 0.1, volume: 10 };
  });
  const cases = (["renko", "point-and-figure", "kagi"] as MainChartType[]).flatMap(chartType => (
    (["automatic", "linked"] as const).flatMap(ownership => (
      [false, true].map(auxiliary => ({ chartType, ownership, auxiliary }))
    ))
  ));
  for (const { chartType, ownership, auxiliary } of cases) {
    const host = document.createElement("div"), style = document.createElement("style");
    host.style.cssText = "width:700px;height:400px;position:relative;display:flex";
    style.textContent = ".qa-synthetic-view .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-synthetic-view .chart-pane{position:absolute;inset:0}.qa-synthetic-view .pane-overlay-anchor{position:absolute;left:10px}";
    host.className = "qa-synthetic-view"; document.head.append(style); document.body.append(host);
    const scope = `qa-synthetic-${chartType}-${ownership}-${auxiliary}-${crypto.randomUUID()}`, key = `candlescope:replay-viewport:v1:${scope}`;
    let root = createRoot(host), surface: ReturnType<typeof useChartSurfaceRuntime> | null = null;
    let store = new SeriesWindowStore({ seriesKey: scope }); store.replace(rows.slice(ownership === "automatic" ? 0 : 500, 629));
    let loads = 0;
    let published: ChartSurfaceVisibleRange["time"];
    const load = async (before?: number | null) => {
      if (typeof before !== "number") return;
      await Promise.resolve(); loads++;
      store.applyRange(rows.filter(row => Number(row.time) < before));
    };
    function Probe() {
      const value = useChartSurfaceRuntime();
      const save = useReplayCellViewport(scope, value.actions);
      const source = useSyncExternalStore(listener => store.subscribe(() => listener()), () => store.snapshot());
      // Deterministic overlay/subpane geometry; indicator mathematics is tested
      // by canonical/live parity suites, not inferred from this chart fixture.
      const lines = auxiliary ? {
          main: [{ id: "fixture-ma", name: "Fixture overlay", data: source.map(row => ({ time: Number(row.time), value: Number(row.close) })) }],
          sub: [{ id: "fixture-rsi", label: "Fixture oscillator", lines: [{ id: "oscillator", pane: "separate", name: "Oscillator", data: source.map(row => ({ time: Number(row.time), value: 50 + Math.sin(Number(row.time) / 300) * 10 })) }] }],
        } : { main: [], sub: [] };
      useLayoutEffect(() => { surface = value; });
      return <SingleChartPanes ref={value.ref} seriesStore={store} datasetKey={scope}
        symbol="SOLUSDT" interval="5m" chartType={chartType} theme="dark" customBg=""
        upColor="#00aa00" downColor="#aa0000" drawingReadOnly followLatest
        mainOverlayLines={lines.main} subPanes={lines.sub}
        onNeedMoreLeft={load} onVisibleRangeChange={(range) => {
          published = range.time; save(range);
        }} />;
    }
    const settle = async () => {
      for (let frame = 0; frame < 8; frame++) await act(async () => {
        await new Promise(resolve => requestAnimationFrame(resolve));
      });
    };
    const handle = () => (surface as ReturnType<typeof useChartSurfaceRuntime> | null)!.actions;
    try {
      await act(async () => root.render(<Probe />)); await settle();
      assert(!host.querySelector(".chart-return-to-realtime"), `${chartType} initial surface is away from latest`);
      const initialSpacing = handle().getVisibleRange()?.barSpacing;
      for (const row of rows.slice(629)) {
        await act(async () => { store.applyTick(row); }); await settle();
        assert(!host.querySelector(".chart-return-to-realtime"), `${chartType} advance lost follow-latest without a chart gesture`);
        assert(Math.abs((handle().getVisibleRange()?.barSpacing ?? 0) - (initialSpacing ?? 0)) < 0.001,
          `${chartType} automatic follow changes zoom on each source commit`);
      }
      if (ownership === "linked") {
        await act(async () => { store.applyRange(rows.slice(0, 500)); }); await settle();
        const requested = { from: Number(rows[440]!.time), to: Number(rows[550]!.time) };
        await act(async () => {
          assert(handle().setLinkedVisibleTimeRange(requested), `${chartType} user range not applied`);
        }); await settle();
      }
      const beforeResize = handle().getVisibleRange();
      host.style.width = "550px"; host.style.height = "340px"; await settle();
      const smaller = handle().getVisibleRange();
      host.style.width = "700px"; host.style.height = "400px"; await settle();
      const before = handle().getVisibleRange();
      assert(Math.abs((beforeResize?.time?.from ?? 0) - (before?.time?.from ?? 0)) < 0.001
        && Math.abs((beforeResize?.time?.to ?? 0) - (before?.time?.to ?? 0)) < 0.001,
        `${chartType}/${ownership}/${auxiliary} resize round trip changed source window: ${JSON.stringify({ beforeResize, smaller, before })}`);
      // Observe the surface's normal debounced preference publication before
      // closing. This case tests replay restore, not a sub-500ms close gesture.
      for (let attempt = 0; attempt < 100
        && JSON.stringify(published) !== JSON.stringify(before?.time); attempt++) {
        await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
      }
      assert(JSON.stringify(published) === JSON.stringify(before?.time),
        `${chartType} surface never published its view: ${JSON.stringify({ before, published, current: handle().getVisibleRange(), loads })}`);
      await act(async () => root.unmount());
      assert(localStorage.getItem(key) !== null, `${chartType} range did not persist`);
      store = new SeriesWindowStore({ seriesKey: scope }); store.replace(rows.slice(-128));
      surface = null; root = createRoot(host);
      await act(async () => root.render(<Probe />)); await settle();
      const after = handle().getVisibleRange();
      assert(loads > 0, `${chartType} saved earlier viewport did not request missing history`);
      const close = (a: number | undefined, b: number | undefined) => a !== undefined && b !== undefined && Math.abs(a - b) < 0.001;
      assert(close(before?.time?.from, after?.time?.from) && close(before?.time?.to, after?.time?.to),
        `${chartType} cold restore changed elapsed viewport: ${JSON.stringify({ before, after, loads })}`);
      samples.push({ chartType, ownership, auxiliary, before, after, loads, restoredRows: store.barCount });
    } finally {
      await act(async () => root.unmount()); host.remove(); style.remove(); localStorage.removeItem(key);
    }
  }
  return { name: "real synthetic surfaces follow advances and restore source-time windows", status: "PASS", samples };
}
