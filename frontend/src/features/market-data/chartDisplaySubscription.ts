import type { ChartWorkScheduler } from "./chartWorkScheduler.js";
import type { WindowDelta } from "./klineContracts.js";
import type { SeriesWindowView } from "./window/seriesWindowView.js";

export interface ChartDisplayScheduler {
  scheduler: ChartWorkScheduler;
  cellId: string;
}

/** One bounded display slot for already accepted data. The source remains the
 * synchronous truth; this object owns neither rows nor a writer. */
export function createChartDisplaySubscription(
  source: SeriesWindowView,
  { scheduler, cellId }: ChartDisplayScheduler,
  key: string,
) {
  const listeners = new Set<(delta: WindowDelta, reader: SeriesWindowView) => void>();
  let unsubscribe: (() => boolean) | null = null;
  let pending: WindowDelta | null = null;
  let version = source.version;
  const queue = (delta: WindowDelta) => {
    if (!delta.changed) return;
    if (!pending) pending = delta;
    else if (pending.type === "tick" && delta.type === "tick"
      && !pending.appended && !delta.appended && !pending.trimmedLeft && !delta.trimmedLeft
      && !pending.trimmedRight && !delta.trimmedRight && pending.bar?.time === delta.bar?.time) {
      pending = delta;
    } else {
      // More than one structural event can include deletion, trim or a reset.
      // Never pretend the last delta describes all skipped changes. Rebuild the
      // projection from the accepted reader and retain viewport compensation.
      pending = {
        type: "mid-merge", changed: true,
        trimmedLeft: (pending.trimmedLeft ?? 0) + (delta.trimmedLeft ?? 0),
        trimmedRight: (pending.trimmedRight ?? 0) + (delta.trimmedRight ?? 0),
      };
    }
    scheduler.enqueueFrame(cellId, "candle-display", key, () => {
      const committed = pending;
      pending = null;
      if (!committed || !listeners.size) return;
      version = source.version;
      const first = source.first(), last = source.last();
      const displayed = committed.type === "mid-merge" ? {
        ...committed,
        changedRanges: first && last ? [{ start: first.time, end: last.time, type: "mid-merge" as const }] : [],
      } : committed;
      for (const listener of [...listeners]) if (listeners.has(listener)) listener(displayed, source);
    });
  };
  return {
    getSnapshot: () => version,
    subscribe(listener: (delta: WindowDelta, reader: SeriesWindowView) => void) {
      listeners.add(listener);
      if (!unsubscribe) {
        unsubscribe = source.subscribe(queue);
        if (version !== source.version) queue({ type: "mid-merge", changed: true });
      }
      return () => {
        listeners.delete(listener);
        if (!listeners.size) {
          unsubscribe?.();
          unsubscribe = null;
          pending = null;
          scheduler.cancelDisplay(cellId, key);
        }
      };
    },
  };
}

export type ChartDisplaySubscription = ReturnType<typeof createChartDisplaySubscription>;
