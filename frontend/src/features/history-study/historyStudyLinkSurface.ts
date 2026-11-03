import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import type { ChartLinkSurface } from "../chart-workspace/chartLinkCoordinator.js";
import type { HistoryStudyPlayback } from "./historyStudyPlayback.js";
import { locateStudyViewportTime } from "./historyStudyNavigation.js";

/** Link the visible study surface, with its own revealed horizon. No drawing
 * revision or public/live series capability is exported from this facade. */
export function createStudyLinkSurface(playback: HistoryStudyPlayback, renderedVersion: () => number,
  actions: ChartSurfaceActions): ChartLinkSurface {
  const current = () => Number(playback.store.version) === renderedVersion();
  const locate = (seconds: number) => current() ? locateStudyViewportTime({ store: playback.store,
    interval: playback.input.series.interval, minimumMs: playback.minimumMs, cursorMs: playback.cursorMs }, Math.round(seconds * 1000)) : null;
  return {
    setLinkedCrosshairTime(time) {
      if (time === null) return actions.setLinkedCrosshairTime(null);
      const bucket = createIntervalTimeline(playback.input.series.interval)?.floor(time);
      if (!current() || !Number.isFinite(time) || time * 1000 > playback.cursorMs || time * 1000 < playback.minimumMs
        || bucket == null || !playback.store.hasTime(bucket)) {
        actions.setLinkedCrosshairTime(null); return false;
      }
      return actions.setLinkedCrosshairTime(bucket);
    },
    setLinkedVisibleTimeAnchor(time) {
      const result = locate(time);
      return result?.status === "located" ? actions.setLinkedVisibleTimeAnchor(result.actualTimeMs / 1000) : false;
    },
    setLinkedVisibleTimeRange(range) {
      const from = locate(range.from), to = locate(range.to);
      return from?.status === "located" && to?.status === "located" && from.actualTimeMs < to.actualTimeMs
        ? actions.setLinkedVisibleTimeRange({ from: from.actualTimeMs / 1000, to: to.actualTimeMs / 1000 }) : false;
    },
    subscribeLinkedViewportReady(listener) {
      let active = true;
      const release = actions.subscribeLinkedViewportReady(generation => {
        // Parent publication refs must finish committing before catch-up runs.
        queueMicrotask(() => { if (active) listener(generation); });
      });
      return () => { active = false; release(); };
    },
  };
}
