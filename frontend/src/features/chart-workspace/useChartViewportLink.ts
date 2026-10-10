import { useEffect, useMemo } from "react";
import type { ChartSurfaceVisibleRange } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartLinkCoordinator } from "./chartLinkCoordinator.js";

/** Coalesce user gestures per frame; persistence and programmatic restores never enter this queue. */
export function createChartViewportLinkScheduler(
  links: Pick<ChartLinkCoordinator, "publishTimeAnchor" | "publishDateRange">,
  cellId: string,
  requestFrame: (callback: () => void) => number = (callback) => requestAnimationFrame(callback),
  cancelFrame: (handle: number) => void = (handle) => cancelAnimationFrame(handle),
) {
  let pending: ChartSurfaceVisibleRange | null = null;
  let frame: number | null = null;
  const flush = () => {
    frame = null;
    const range = pending;
    pending = null;
    if (!range) return;
    if (typeof range.rightmostTime === "number") links.publishTimeAnchor(cellId, range.rightmostTime);
    if (range.time) links.publishDateRange(cellId, range.time);
  };
  return {
    schedule(range: ChartSurfaceVisibleRange) {
      pending = range;
      if (frame === null) frame = requestFrame(flush);
    },
    cancel() {
      if (frame !== null) cancelFrame(frame);
      frame = null;
      pending = null;
    },
  };
}

export function useChartViewportLink(links: ChartLinkCoordinator, cellId: string, scope: string) {
  const scheduler = useMemo(() => createChartViewportLinkScheduler(links, cellId), [links, cellId]);
  useEffect(() => () => scheduler.cancel(), [scheduler, scope]);
  return scheduler.schedule;
}
