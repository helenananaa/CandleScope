import { act, useLayoutEffect } from "react";
import { createRoot } from "react-dom/client";
import { useReplayCellViewport } from "../../features/replay/useReplayCellViewport.js";
import type { ChartSurfaceActions, ChartSurfaceVisibleRange } from "../useChartSurfaceRuntime.js";
import { structuralMock } from "../../test/testHelpers.js";

/** Exercise effect cleanup, surface readiness and in-place interval changes. */
export async function checkReplayCellViewportLifecycle() {
  const prefix = `qa-viewport-${crypto.randomUUID()}`;
  const key = (scope: string) => `candlescope:replay-viewport:v1:${prefix}:${scope}`;
  const assert = (value: unknown, message: string) => { if (!value) throw new Error(message); };
  const listeners = new Set<(generation: number) => void>();
  let ready = false, applications = 0;
  let view = { from: 300, to: 400 };
  let scope = "SOL:5m", market = "SOL";
  let save: ((range: ChartSurfaceVisibleRange) => void) | undefined;
  const surface = structuralMock<ChartSurfaceActions>({
    setLinkedVisibleTimeRange: (range: { from: number; to: number }) => {
      if (!ready) return false;
      applications++; view = { ...range }; return true;
    },
    subscribeLinkedViewportReady: (listener: (generation: number) => void) => {
      listeners.add(listener); return () => { listeners.delete(listener); };
    },
  });
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  function Probe() {
    const receive = useReplayCellViewport(`${prefix}:${scope}`, surface, `${prefix}:${market}`);
    useLayoutEffect(() => { save = receive; });
    return null;
  }
  const notify = () => listeners.forEach(listener => listener(1));
  try {
    localStorage.setItem(key("SOL:5m"), JSON.stringify({ from: 100, to: 200 }));
    localStorage.setItem(key("SOL:90m"), JSON.stringify({ from: 10, to: 20 }));
    localStorage.setItem(key("LTC:90m"), JSON.stringify({ from: 600, to: 700 }));
    await act(async () => root.render(<Probe />));
    assert(applications === 0, "saved view applied before chart readiness");
    ready = true;
    await act(async () => notify());
    assert(applications === 1 && view.from === 100, "saved view was not restored");
    view = { from: 120, to: 220 };
    save!({ time: view });
    await act(async () => { notify(); notify(); });
    assert(applications === 1 && view.from === 120, "history/clock readiness overwrote user view");
    // The existing surface transferred elapsed time before changing its period.
    scope = "SOL:90m"; view = { from: 130, to: 230 };
    await act(async () => root.render(<Probe />));
    await act(async () => notify());
    assert(applications === 1 && view.from === 130, "period's old preference overwrote transfer");
    assert(localStorage.getItem(key("SOL:5m")) === JSON.stringify({ from: 120, to: 220 }), "old period did not flush its last user view");
    scope = "LTC:90m"; market = "LTC";
    await act(async () => root.render(<Probe />));
    assert(applications === 2 && view.from === 600, "different market did not restore its own preference");
    await act(async () => root.unmount());
    assert(listeners.size === 0, "unmounted chart left a readiness observer");
    return { name: "replay viewport restores once and preserves period transfer", status: "PASS", applications };
  } finally {
    await act(async () => root.unmount()); host.remove();
    for (const value of ["SOL:5m", "SOL:90m", "LTC:90m"]) localStorage.removeItem(key(value));
  }
}
