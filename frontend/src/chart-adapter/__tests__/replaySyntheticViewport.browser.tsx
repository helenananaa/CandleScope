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
  const rows: KlineBar[] = Array.from({ length: 640 }, (_, index) => {
    const open = 110 + Math.sin(index * 0.13), close = open + Math.sin(index * 0.41) * 0.12;
    return { time: (1_800_000_000 + index * 300) as KlineBar["time"], open, close,
      high: Math.max(open, close) + 0.1, low: Math.min(open, close) - 0.1, volume: 10 };
  });
  const cases = (["renko", "point-and-figure", "kagi", "line-break", "heikin-ashi"] as MainChartType[]).flatMap(chartType => (
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
          sub: [{ id: "fixture-rsi", label: "Fixture oscillator", lines: [{ id: "oscillator", pane: "separate", name: "Oscillator", color: "#a855f7", data: source.map(row => ({ time: Number(row.time), value: 50 + Math.sin(Number(row.time) / 300) * 10 })) }] }],
        } : { main: [], sub: [] };
      useLayoutEffect(() => { surface = value; });
      return <SingleChartPanes ref={value.ref} seriesStore={store} datasetKey={scope}
        dataMeta={{ seriesKey: store.seriesKey, version: store.version,
          status: "ready", source: "fixture-owned-projection", committedAt: null }}
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
      if (auxiliary) {
        let oscillatorPixels = 0;
        for (const canvas of host.querySelectorAll("canvas")) {
          const context = canvas.getContext("2d");
          if (!context) continue;
          const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
          for (let index = 0; index < pixels.length; index += 4) {
            if (pixels[index]! > 100 && pixels[index + 1]! < 120
              && pixels[index + 2]! > 150 && pixels[index + 3]! > 100) oscillatorPixels++;
          }
        }
        assert(oscillatorPixels > 20, `${chartType} auxiliary fixture did not paint an indicator curve`);
      }
      assert(!host.querySelector(".chart-return-to-realtime"), `${chartType} initial surface is away from latest`);
      const initialSpacing = handle().getVisibleRange()?.barSpacing;
      for (const row of rows.slice(629, 638)) {
        await act(async () => { store.applyTick(row); }); await settle();
        assert(!host.querySelector(".chart-return-to-realtime"), `${chartType} advance lost follow-latest without a chart gesture`);
        assert(Math.abs((handle().getVisibleRange()?.barSpacing ?? 0) - (initialSpacing ?? 0)) < 0.001,
          `${chartType} automatic follow changes zoom on each source commit`);
      }
      if (ownership === "linked") {
        const requested = { from: Number(rows[440]!.time), to: Number(rows[550]!.time) };
        await act(async () => {
          assert(handle().setLinkedVisibleTimeRange(requested), `${chartType} user range not applied`);
        }); await settle();
      }
      const beforeMoreSources = handle().getVisibleRange();
      for (const row of rows.slice(638)) {
        await act(async () => { store.applyTick(row); }); await settle();
        const current = handle().getVisibleRange();
        if (ownership === "linked") {
          assert(Math.abs((beforeMoreSources?.time?.from ?? 0) - (current?.time?.from ?? 0)) < 0.001
            && Math.abs((beforeMoreSources?.time?.to ?? 0) - (current?.time?.to ?? 0)) < 0.001,
          `${chartType} source recalibration moved a linked historical window: ${JSON.stringify({ beforeMoreSources, current })}`);
        }
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
      if (Number(before?.time?.from) < Number(rows.at(-128)!.time)) {
        assert(loads > 0, `${chartType} saved earlier viewport did not request missing history`);
      }
      // Numeric HA restores to the nearest source bar; fractional cold-reopen
      // pixels are optional preferences, not an exact-restart acceptance gate.
      const restoreToleranceSeconds = chartType === "heikin-ashi" ? 150 : 0.001;
      const close = (a: number | undefined, b: number | undefined) => a !== undefined && b !== undefined
        && Math.abs(a - b) <= restoreToleranceSeconds;
      assert(close(before?.time?.from, after?.time?.from) && close(before?.time?.to, after?.time?.to),
        `${chartType} cold restore changed elapsed viewport: ${JSON.stringify({ before, after, loads })}`);
      samples.push({ chartType, ownership, auxiliary, before, after, loads, restoredRows: store.barCount, restoreToleranceSeconds });
    } finally {
      await act(async () => root.unmount()); host.remove(); style.remove(); localStorage.removeItem(key);
    }
  }
  return { name: "real synthetic surfaces follow advances and restore source-time windows", status: "PASS", samples };
}

/** Drawing anchors follow their price/auxiliary owner through async output gaps. */
export async function checkReplayDrawingIndicatorReplacement() {
  const { createDrawingDocument, createDrawingEntity } = await import("../../features/drawings/core/drawingDocument.js");
  const { drawingDocumentSessionRegistry: registry } = await import("../../features/drawings/core/drawingDocumentStore.js");
  const samples: unknown[] = [];
  const assert = (value: unknown, message: string) => { if (!value) throw new Error(message); };
  const rows: KlineBar[] = Array.from({ length: 160 }, (_, index) => ({
    time: (1_800_000_000 + index * 300) as KlineBar["time"],
    open: 110 + Math.sin(index * 0.13),
    high: 110 + Math.sin(index * 0.13) + 0.25, low: 110 + Math.sin(index * 0.13) - 0.25,
    close: 110 + Math.sin(index * 0.13) + Math.sin(index * 0.41) * 0.12, volume: 10,
  }));
  for (const chartType of ["renko", "point-and-figure", "kagi", "heikin-ashi"] as const) {
    const base = `qa-indicator-drawing-${chartType}-${crypto.randomUUID()}`;
    const host = document.createElement("div"), style = document.createElement("style");
    host.style.cssText = "width:700px;height:450px;position:relative;display:flex";
    host.className = "qa-indicator-drawing";
    style.textContent = ".qa-indicator-drawing .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-indicator-drawing .chart-pane{position:absolute;inset:0}";
    document.head.append(style); document.body.append(host);
    const store = new SeriesWindowStore({ seriesKey: base }); store.replace(rows);
    for (const [pane, prices, color] of [["main", [109.8, 110.2], "#f59e0b"], ["qa-rsi", [45, 55], "#22d3ee"]] as const) {
      const scopeKey = `${base}__${pane}`, documentStore = registry.getStore(scopeKey);
      const result = documentStore.loadDocument(createDrawingDocument({ scopeKey, entities: [createDrawingEntity({
        id: `line-${pane}`, kind: "line", geometry: { kind: "line", lineType: "line-segment",
          dataPoints: [{ time: Number(rows[120]!.time), price: prices[0] }, { time: Number(rows[150]!.time), price: prices[1] }] },
        style: { kind: "line", color, lineWidth: 2 },
      })] }));
      assert(result.ok, "fixture drawing document did not load"); registry.markLoaded(scopeKey, documentStore);
    }
    let phase: "ready" | "pending" | "replacement" = "ready";
    const root = createRoot(host);
    function Probe() {
      return <SingleChartPanes seriesStore={store} datasetKey={base} drawingKeyBase={base}
        dataMeta={{ seriesKey: store.seriesKey, version: store.version, status: "ready", source: "fixture-owned-projection", committedAt: null }}
        symbol="SOLUSDT" interval="5m" chartType={chartType} theme="dark" customBg="" upColor="#00aa00" downColor="#aa0000"
        mainOverlayLines={phase === "pending" ? [] : [{ id: `ma-${phase}`, name: "Overlay", color: "#808080", data: rows.map(row => ({ time: Number(row.time), value: 110 })) }]}
        subPanes={[{ id: "qa-rsi", label: "RSI", ...(phase === "pending" ? { statusText: "Computing" } : {}),
          lines: phase === "pending" ? [] : [{ id: `rsi-${phase}`, name: "RSI", color: "#a855f7", data: rows.map((row, index) => ({ time: Number(row.time), value: 50 + Math.sin(index * 0.2) * 10 })) }] }]} />;
    }
    const settle = async () => {
      for (let frame = 0; frame < 24; frame++) await act(async () => { await new Promise(requestAnimationFrame); });
    };
    const pixels = () => {
      let main = 0, auxiliary = 0;
      for (const canvas of host.querySelectorAll("canvas")) {
        const context = canvas.getContext("2d"); if (!context) continue;
        const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
        for (let at = 0; at < data.length; at += 4) {
          if (data[at]! > 190 && data[at + 1]! > 90 && data[at + 1]! < 210 && data[at + 2]! < 70 && data[at + 3]! > 90) main++;
          if (data[at]! < 80 && data[at + 1]! > 150 && data[at + 2]! > 190 && data[at + 3]! > 90) auxiliary++;
        }
      }
      return { main, auxiliary };
    };
    try {
      await act(async () => root.render(<Probe />)); await settle();
      const before = pixels();
      assert(before.main > 20 && before.auxiliary > 20, `${chartType} fixture drawings must both be visible`);
      phase = "pending"; await act(async () => root.render(<Probe />)); await settle();
      const pending = pixels();
      assert(pending.main > 20, `${chartType} overlay removal retired the price-owned drawing surface`);
      phase = "replacement"; await act(async () => root.render(<Probe />)); await settle();
      const after = pixels();
      assert(after.main > 20 && after.auxiliary > 20, `${chartType} replacement output did not restore both drawings`);
      samples.push({ chartType, before, pending, after });
    } finally { await act(async () => root.unmount()); host.remove(); style.remove(); }
  }
  return { name: "price-owned main drawings and auxiliary anchor replacement", status: "PASS", samples };
}
