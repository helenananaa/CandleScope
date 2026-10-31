import { useLayoutEffect, useSyncExternalStore } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import { useChartSurfaceRuntime } from "../useChartSurfaceRuntime.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import { ChartWorkScheduler } from "../../features/market-data/chartWorkScheduler.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";

/** Exercise admission before paint using the actual component and shared frame scheduler. */
export async function checkStagedSessionViewport() {
  const samples: unknown[] = [];
  const rows: KlineBar[] = Array.from({ length: 1500 }, (_, i) => ({
    time: (1_000_000_000 + i * 5 * 86400) as KlineBar["time"],
    open: 100, high: 102, low: 98, close: 100 + Math.sin(i), volume: 10,
  }));
  for (const savedRange of [null, { barSpacing: 8, rightOffset: 4 }]) {
    for (const initialCount of [0, 1, 128]) {
      const host = document.createElement("div"), style = document.createElement("style");
      host.className = "qa-staged-viewport";
      host.style.cssText = "width:700px;height:400px;position:relative;display:flex";
      style.textContent = ".qa-staged-viewport .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-staged-viewport .chart-pane{position:absolute;inset:0}";
      document.head.append(style); document.body.append(host);
      let scope = `qa-staged-${initialCount}-${crypto.randomUUID()}`;
      let store = new SeriesWindowStore({ seriesKey: scope });
      store.replace(rows.slice(-128));
      let frameId = 0;
      const frames = new Map<number, () => void>();
      const scheduler = new ChartWorkScheduler({ now: () => 0,
        requestFrame: callback => { frames.set(++frameId, callback); return frameId; },
        cancelFrame: handle => { frames.delete(handle); },
      });
      scheduler.registerCell(scope);
      const driver = { scheduler, cellId: scope };
      let surface: ReturnType<typeof useChartSurfaceRuntime> | null = null;
      let phase = "memory-cache-hit";
      const root = createRoot(host);
      function Probe() {
        const value = useChartSurfaceRuntime();
        useSyncExternalStore(listener => store.subscribe(() => listener()), () => store.version);
        useLayoutEffect(() => { surface = value; });
        return <SingleChartPanes ref={value.ref} seriesStore={store} datasetKey={scope}
          displayScheduler={driver}
          dataMeta={{ seriesKey: store.seriesKey, version: store.version, status: "ready", source: phase, committedAt: null }}
          symbol="BTCUSDT" interval="5d" chartType="candlestick" theme="dark" customBg=""
          upColor="#00aa00" downColor="#aa0000" drawingReadOnly followLatest={false}
          savedVisibleRange={savedRange} />;
      }
      const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(requestAnimationFrame); };
      const handle = () => (surface as ReturnType<typeof useChartSurfaceRuntime> | null)!.actions;
      const flushDisplay = async () => {
        for (let i = 0; frames.size && i < 10; i++) {
          const callbacks = [...frames.values()]; frames.clear();
          flushSync(() => callbacks.forEach(callback => callback()));
          await settle();
        }
      };
      try {
        flushSync(() => root.render(<Probe />)); await settle();
        scope += "-next";
        store = new SeriesWindowStore({ seriesKey: scope });
        phase = "loading";
        flushSync(() => root.render(<Probe />)); await settle();
        if (initialCount) {
          phase = "memory-cache-hit";
          flushSync(() => store.replace(rows.slice(-initialCount))); await settle(); await flushDisplay();
        }
        phase = "initial-history";
        flushSync(() => { store.replace(rows.slice(-128)); root.render(<Probe />); });
        await settle();
        const admitted = handle().getVisibleRange();
        await flushDisplay();
        const painted = handle().getVisibleRange();
        samples.push({ initialCount, savedRange, admitted, painted });
        if (!painted?.logical || (painted.rightOffset ?? Infinity) > 8
          || (savedRange !== null && (Math.abs((painted.rightOffset ?? Infinity) - 4) > 0.01
            || Math.abs((painted.barSpacing ?? 0) - 8) > 0.3))) {
          throw new Error(`Admission/paint viewport mismatch: ${JSON.stringify(samples)}`);
        }
        flushSync(() => store.replace(rows.slice(-500))); await flushDisplay();
        const hydrated = handle().getVisibleRange();
        if (!hydrated || Math.abs((hydrated.rightOffset ?? Infinity) - (painted.rightOffset ?? 0)) > 0.01) {
          throw new Error(`500-bar hydration lost tail: ${JSON.stringify({ painted, hydrated })}`);
        }
        samples.push({ initialCount, savedRange, stage: "500 hydration", hydrated });
        const requested = { from: Number(rows[1100]!.time), to: Number(rows[1200]!.time) };
        if (!handle().setLinkedVisibleTimeRange(requested)) throw new Error("navigation rejected");
        await settle(); const before = handle().getVisibleRange();
        flushSync(() => store.replace(rows)); await flushDisplay();
        const after = handle().getVisibleRange();
        if (!before?.time || !after?.time || Math.abs(before.time.from - after.time.from) > 0.01
          || Math.abs(before.time.to - after.time.to) > 0.01) {
          throw new Error(`Hydration lost navigation: ${JSON.stringify({ before, after })}`);
        }
        samples.push({ initialCount, stage: "1500 hydration preserves navigation", before, after });
      } finally { flushSync(() => root.unmount()); scheduler.dispose(); host.remove(); style.remove(); }
    }
  }
  return { name: "staged admission waits for painted semantic viewport", status: "PASS", samples };
}
