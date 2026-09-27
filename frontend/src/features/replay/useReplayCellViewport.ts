import { useCallback, useEffect, useRef } from "react";
import type { ChartSurfaceActions, ChartSurfaceVisibleRange } from "../../chart-adapter/useChartSurfaceRuntime.js";

/** Per-chart view preferences contain only public time coordinates. */
export function useReplayCellViewport(scope: string, surface: ChartSurfaceActions) {
  const key = `candlescope:replay-viewport:v1:${scope}`;
  const pending = useRef<ChartSurfaceVisibleRange["time"]>(undefined);
  const restoring = useRef(true);
  useEffect(() => {
    let saved: { from: number; to: number } | null = null;
    try {
      const value: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
      if (value && typeof value === "object" && "from" in value && "to" in value
        && typeof value.from === "number" && typeof value.to === "number"
        && Number.isFinite(value.from) && Number.isFinite(value.to) && value.from < value.to) {
        saved = { from: value.from, to: value.to };
      }
    } catch { /* Chart remains usable when browser storage is unavailable. */ }
    pending.current = saved ?? undefined;
    restoring.current = saved !== null;
    const restore = () => {
      if (!saved || surface.setLinkedVisibleTimeRange(saved)) {
        restoring.current = false;
        return true;
      }
      return false;
    };
    const unsubscribe = surface.subscribeLinkedViewportReady(restore);
    restore();
    const flush = () => {
      if (!pending.current) return;
      try { localStorage.setItem(key, JSON.stringify(pending.current)); } catch { /* Optional preference. */ }
    };
    const timer = setInterval(flush, 1000);
    window.addEventListener("pagehide", flush);
    return () => { flush(); clearInterval(timer); unsubscribe(); window.removeEventListener("pagehide", flush); };
  }, [key, surface]);
  return useCallback((range: ChartSurfaceVisibleRange) => {
    if (!restoring.current && range.time) pending.current = range.time;
  }, []);
}
