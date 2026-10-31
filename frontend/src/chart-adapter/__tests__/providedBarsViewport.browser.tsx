import { act, createRef, useLayoutEffect } from "react";
import { createRoot } from "react-dom/client";
import { useProvidedBarsIndicatorRuntime } from "../../features/indicators/useProvidedBarsIndicatorRuntime.js";
import type { IndicatorRuntime } from "../../features/indicators/indicatorRuntimeContract.js";
import type { IndicatorComputeBatchExecutor } from "../../features/indicators/indicatorComputeController.js";
import type { IndicatorDefinition, IndicatorPayloadEnvelope } from "../../features/indicators/indicatorTypes.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";
import { structuralMock } from "../../test/testHelpers.js";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import type { ChartSurfaceHandle } from "../useChartSurfaceRuntime.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import fixture from "../../features/replay/__tests__/fixtures/builtin-parity.json";

const assert = (ok: unknown, message: string) => { if (!ok) throw new Error(message); };

export async function checkProvidedBarsViewport() {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const rows = Array.from({ length: 10_000 }, (_, i) => structuralMock<KlineBar>({
    time: 1_800_000_000 + i * 60, open: 100, high: 102, low: 99, close: 101, volume: 2, is_closed: true,
  }));
  const definitions: IndicatorDefinition[] = [
    { id: "rsi", engineName: "RSI", visible: true, params: { period: 14 } },
    { id: "script", script: "plot(close)", language: "pine", visible: true, params: {} },
  ];
  const persistence = { controlled: true, load: () => definitions, save: () => undefined };
  const template = fixture.cases.find(x => x.name === "RSI" && !Object.keys(x.params).length)!.canonical[0]!.result.payload;
  const calls: { mode: string; first: number; last: number; bars: number }[] = [];
  const computeBatch: IndicatorComputeBatchExecutor = async ({ jobs, signal }) => {
    signal?.throwIfAborted();
    const results = jobs.map(job => {
      calls.push({ mode: String(job.request.mode), first: job.request.ohlcv[0]!.time,
        last: job.request.ohlcv.at(-1)!.time, bars: job.request.ohlcv.length });
      const payload = structuralMock<IndicatorPayloadEnvelope>(structuredClone(template));
      const points = job.request.ohlcv.map(b => ({ time: b.time, value: 50 }));
      for (const line of payload.lines) line.data = points;
      for (const series of payload.series) series.data = points;
      return { clientId: job.clientId, jobKey: job.jobKey, payload };
    });
    return { ok: true, results };
  };
  let current: IndicatorRuntime | null = null;
  function Harness() {
    const runtime = useProvidedBarsIndicatorRuntime({ bars: rows, datasetKey: "viewport",
      sourceScopeKey: "viewport", sourceOrdinal: 1, computeBatch, persistence,
      exchange: "fixture", marketType: "spot", symbol: "FIXTURE", interval: "1m", visibleRangePriority: true });
    useLayoutEffect(() => { current = runtime; });
    return null;
  }
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  const settle = async (predicate: () => boolean) => {
    for (let i = 0; i < 200 && !predicate(); i++) await act(async () => { await new Promise(r => setTimeout(r, 10)); });
    assert(predicate(), `viewport work did not settle: ${JSON.stringify(calls)}`);
  };
  try {
    await act(async () => root.render(<Harness />));
    await settle(() => calls.some(c => c.mode === "builtin") && calls.some(c => c.mode === "script"));
    assert(calls.find(c => c.mode === "builtin")!.bars < 1000, "bootstrap must not compute all loaded bars");
    assert(calls.find(c => c.mode === "script")!.bars === 10_000, "script input must retain its complete caller-owned window");
    for (const [from, to] of [[3000, 3200], [3050, 3100], [8500, 8650], [3000, 3200]] as const) {
      const previous = calls.length;
      await act(async () => { current!.actions.ensureVisibleIndicatorRange({ time: { from: rows[from]!.time, to: rows[to]!.time } }); });
      await settle(() => calls.slice(previous).some(c => c.mode === "builtin" && c.last === rows[to]!.time));
      const recent = calls.slice(previous);
      assert(recent.filter(c => c.mode === "builtin").every(c => c.bars < 500), "pan/zoom requests must stay bounded");
      assert(recent.filter(c => c.mode === "script").every(c => c.bars === 10_000), "viewport must not truncate script input");
    }
    const previous = calls.length;
    await act(async () => { current!.actions.ensureVisibleIndicatorRange({ logical: { from: 1000, to: 6000 } }); });
    await settle(() => calls.slice(previous).some(c => c.mode === "builtin" && c.last === rows[6000]!.time));
    assert(calls.slice(previous).filter(c => c.mode === "builtin").every(c => c.first <= rows[1000]!.time && c.bars > 5000),
      "zooming out must cover the complete visible range instead of applying the generic 2000-bar tail cap");
    return { name: "real provided-bars React lifecycle prioritizes pan/zoom while preserving script input", status: "PASS", calls };
  } finally {
    await act(async () => root.unmount()); host.remove();
  }
}

/** The real chart must publish ranges, not just a manually invoked hook action. */
export async function checkProvidedBarsChartViewport() {
  const rows = Array.from({ length: 10_000 }, (_, i) => structuralMock<KlineBar>({
    time: 1_800_000_000 + i * 60, open: 100, high: 102, low: 99, close: 101, volume: 2, is_closed: true,
  }));
  const store = new SeriesWindowStore({ seriesKey: "visible-chart" }); store.replace(rows);
  const surface = createRef<ChartSurfaceHandle>();
  const definitions: IndicatorDefinition[] = [{ id: "rsi", engineName: "RSI", visible: true, params: { period: 14 } }];
  const persistence = { controlled: true, load: () => definitions, save: () => undefined };
  const template = fixture.cases.find(x => x.name === "RSI" && !Object.keys(x.params).length)!.canonical[0]!.result.payload;
  const calls: { first: number; last: number; bars: number }[] = [];
  const computeBatch: IndicatorComputeBatchExecutor = async ({ jobs, signal }) => {
    signal?.throwIfAborted();
    return { ok: true, results: jobs.map(job => {
      calls.push({ first: job.request.ohlcv[0]!.time, last: job.request.ohlcv.at(-1)!.time, bars: job.request.ohlcv.length });
      const payload = structuralMock<IndicatorPayloadEnvelope>(structuredClone(template));
      const points = job.request.ohlcv.map(b => ({ time: b.time, value: 50 }));
      for (const line of payload.lines) line.data = points;
      for (const series of payload.series) series.data = points;
      return { clientId: job.clientId, jobKey: job.jobKey, payload };
    }) };
  };
  function Harness() {
    const indicators = useProvidedBarsIndicatorRuntime({ bars: rows, datasetKey: "visible-chart",
      sourceScopeKey: "visible-chart", sourceOrdinal: 1, computeBatch, persistence,
      exchange: "fixture", marketType: "spot", symbol: "FIXTURE", interval: "1m", visibleRangePriority: true });
    return <SingleChartPanes ref={surface} seriesStore={store} symbol="FIXTURE" interval="1m"
      datasetKey="visible-chart" theme="dark" customBg="" upColor="#00aa00" downColor="#aa0000"
      drawingReadOnly followLatest={false} subPanes={indicators.view.subPanes}
      onViewportRangeChange={indicators.actions.ensureVisibleIndicatorRange} />;
  }
  const host = document.createElement("div"), style = document.createElement("style");
  host.style.cssText = "width:700px;height:400px;position:relative;display:flex";
  host.className = "qa-visible-chart";
  style.textContent = ".qa-visible-chart .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-visible-chart .chart-pane{position:absolute;inset:0}";
  document.head.append(style); document.body.append(host);
  const root = createRoot(host);
  const frame = async () => { await act(async () => { await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }); };
  const settled = async (predicate: () => boolean) => {
    for (let i = 0; i < 120 && !predicate(); i++) await act(async () => { await new Promise(r => setTimeout(r, 10)); });
    assert(predicate(), `real chart did not request its viewport: ${JSON.stringify({ calls, range: surface.current?.getVisibleRange() })}`);
  };
  try {
    await act(async () => root.render(<Harness />)); await frame();
    for (const [from, to] of [[3000, 3200], [3050, 3100], [1000, 6000], [3000, 3200]] as const) {
      const previous = calls.length;
      await act(async () => { assert(surface.current?.setLinkedVisibleTimeRange({ from: Number(rows[from]!.time), to: Number(rows[to]!.time) }), "surface not ready"); });
      await frame();
      await settled(() => calls.slice(previous).some(c => c.first <= rows[from]!.time && c.last >= rows[to]!.time));
      assert(calls.at(-1)!.bars < to - from + 1200, "surface callback retained hidden suffix or full caller input");
    }
    const before = surface.current!.getVisibleRange();
    const canvas = host.querySelectorAll("canvas")[1]!;
    const rect = canvas.getBoundingClientRect();
    const start = { clientX: rect.left + 250, clientY: rect.top + 70 };
    const event = (type: string, dx = 0, buttons = 1) => new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, buttons, ...start, clientX: start.clientX + dx });
    await act(async () => { canvas.dispatchEvent(event("mouseenter")); canvas.dispatchEvent(event("mousedown")); });
    for (const dx of [10, 30, 60, 90, 120]) { await act(async () => { canvas.dispatchEvent(event("mousemove", dx)); }); await frame(); }
    await act(async () => { canvas.dispatchEvent(event("mouseup", 120, 0)); }); await frame();
    const after = surface.current!.getVisibleRange();
    assert(before?.logical && after?.logical && Math.abs(before.logical.from - after.logical.from) > 5,
      `continuous chart drag failed to pan: ${JSON.stringify({ before, after })}`);
    await settled(() => calls.at(-1)!.last !== rows[3200]!.time);
    return { name: "real chart viewport callback drives bounded indicators through zoom and continuous drag", status: "PASS", before, after, calls };
  } finally { await act(async () => root.unmount()); host.remove(); style.remove(); }
}
