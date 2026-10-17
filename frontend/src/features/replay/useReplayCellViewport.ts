import { useCallback, useEffect, useRef } from "react";
import type { ChartSurfaceActions, ChartSurfaceVisibleRange } from "../../chart-adapter/useChartSurfaceRuntime.js";

/** Readiness also fires after history/indicator updates. Restore only once. */
export function createReplayCellViewportRestore(
  saved: ChartSurfaceVisibleRange["time"],
  apply: ChartSurfaceActions["setLinkedVisibleTimeRange"],
): () => boolean {
  let pending = saved;
  return () => {
    if (!pending) return true;
    if (!apply(pending)) return false;
    pending = undefined;
    return true;
  };
}

/** Per-chart view preferences contain only public time coordinates. */
export function useReplayCellViewport(scope: string, surface: ChartSurfaceActions, restoreScope = scope) {
  const key = `candlescope:replay-viewport:v1:${scope}`;
  const pending = useRef<ChartSurfaceVisibleRange["time"]>(undefined);
  const restoring = useRef(true);
  const lastRestoreScope = useRef<string | null>(null);
  useEffect(() => {
    let saved: { from: number; to: number } | null = null;
    try {
      // A saved preference restores a reopened market. An in-place period
      // switch already owns an explicit source-time transfer and must not be
      // overwritten by that period's older saved view.
      const value: unknown = lastRestoreScope.current === restoreScope
        ? null : JSON.parse(localStorage.getItem(key) ?? "null");
      if (value && typeof value === "object" && "from" in value && "to" in value
        && typeof value.from === "number" && typeof value.to === "number"
        && Number.isFinite(value.from) && Number.isFinite(value.to) && value.from < value.to) {
        saved = { from: value.from, to: value.to };
      }
    } catch { /* Chart remains usable when browser storage is unavailable. */ }
    lastRestoreScope.current = restoreScope;
    pending.current = saved ?? undefined;
    restoring.current = saved !== null;
    const applySaved = createReplayCellViewportRestore(saved ?? undefined, surface.setLinkedVisibleTimeRange);
    const restore = () => {
      if (applySaved()) {
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
  }, [key, restoreScope, surface]);
  return useCallback((range: ChartSurfaceVisibleRange) => {
    if (!restoring.current && range.time) pending.current = range.time;
  }, []);
}
