import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { defaultReplayV2Api } from "./replayV2Api.js";
import {
  rebuildReplayViewerSeries,
  replaceReplayViewerSeriesFromServer,
  replayUsesAuthoritativeSourceBucketProjection,
} from "./replayViewerProjection.js";
import type { ReplayRuntime, ReplayRuntimeLifecycle } from "./useReplayRuntime.js";

interface ProjectionState {
  readonly loading: boolean;
  readonly error: string | null;
  readonly boundaryMs: number | null;
}

/** A cell owns its paged window; an old response can never replace a new dataset. */
export class ReplayChartProjection {
  readonly seriesStore = new SeriesWindowStore();
  private state: ProjectionState = { loading: true, error: null, boundaryMs: null };
  private listeners = new Set<() => void>();
  private unsubscribe: (() => void) | null = null;
  private request: AbortController | null = null;
  private authorityKey: string | null = null;
  private completedKey: string | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private leases = 0;

  constructor(
    private readonly lifecycle: ReplayRuntimeLifecycle,
    private readonly trackId: string,
    private readonly interval: string,
    private readonly api: Pick<typeof defaultReplayV2Api, "displayProjectionBySession"> = defaultReplayV2Api,
  ) {}

  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private publish(next: ProjectionState) {
    if (this.state.loading === next.loading && this.state.error === next.error
      && this.state.boundaryMs === next.boundaryMs) return;
    this.state = next;
    this.listeners.forEach((listener) => listener());
  }

  retain = () => {
    if (this.leases++ === 0) {
      this.unsubscribe = this.lifecycle.subscribe(this.schedule);
      this.refresh();
    }
    let released = false;
    return () => {
      if (released) return;
      released = true;
      if (--this.leases !== 0) return;
      this.unsubscribe?.();
      this.unsubscribe = null;
      if (this.timer !== null) clearTimeout(this.timer);
      this.timer = null;
      this.request?.abort();
      this.request = null;
    };
  };

  private schedule = () => {
    if (this.timer !== null) return;
    this.timer = setTimeout(() => { this.timer = null; this.refresh(); }, 0);
  };

  private refresh = () => {
    if (this.leases === 0) return;
    const { store } = this.lifecycle.getSnapshot();
    const config = store.sessionConfig;
    const boundary = store.virtualTimeMs;
    const epoch = store.dataEpoch;
    const sessionId = store.sessionId;
    const authorityKey = JSON.stringify([sessionId, epoch, store.generation]);
    if (this.authorityKey !== authorityKey || (boundary !== null && this.state.boundaryMs !== null && boundary < this.state.boundaryMs)) {
      this.authorityKey = authorityKey;
      this.request?.abort();
      this.request = null;
      this.completedKey = null;
      this.seriesStore.clear({ source: "replay-cell-authority-change" });
      this.publish({ loading: true, error: null, boundaryMs: null });
    }
    if (!config || boundary === null || epoch === null || sessionId === null) return;
    const source = this.lifecycle.store.seriesStore;
    const key = JSON.stringify([sessionId, epoch, store.generation, boundary, source.version]);
    if (this.completedKey === key) return;
    // A paged-back chart owns its historical window until the user returns to
    // the right edge. Advancing the clock must not replace it with the tail.
    if (this.seriesStore.rightTruncated && !this.seriesStore.isEmpty()) {
      this.completedKey = key;
      this.publish({ loading: false, error: null, boundaryMs: boundary });
      return;
    }
    if (!replayUsesAuthoritativeSourceBucketProjection(config.source_kind, config.base_interval, this.interval)) {
      try {
        rebuildReplayViewerSeries(this.seriesStore, source, config.base_interval, this.interval,
          { preserveContextHistory: !this.seriesStore.isEmpty(), publicTimeMs: boundary });
        this.completedKey = key;
        this.publish({ loading: false, error: null, boundaryMs: boundary });
      } catch (error) {
        this.seriesStore.clear({ source: "replay-cell-projection-error" });
        this.publish({ loading: false, error: String(error), boundaryMs: null });
      }
      return;
    }
    // Finish one bounded request, then catch up. Aborting at every tick starves fast playback.
    if (this.request !== null) return;
    const request = new AbortController();
    this.request = request;
    this.publish({ ...this.state, loading: this.state.boundaryMs === null });
    void this.api.displayProjectionBySession(sessionId, {
      trackId: this.trackId, displayInterval: this.interval,
      revealedBoundaryMs: boundary, dataEpoch: epoch,
    }, request.signal).then((response) => {
      if (request.signal.aborted || this.request !== request) return;
      const current = this.lifecycle.getSnapshot().store;
      if (current.dataEpoch !== epoch || current.generation !== store.generation
        || current.sessionId !== sessionId) return;
      if (response.session_id !== sessionId || response.track_id !== this.trackId
        || response.data_epoch !== epoch || response.display_interval !== this.interval
        || response.revealed_boundary_ms !== boundary
        || response.identity.symbol !== config.symbol
        || response.identity.exchange !== config.exchange
        || response.identity.market_type !== config.market_type) {
        throw new Error("Replay chart projection identity mismatch");
      }
      replaceReplayViewerSeriesFromServer(this.seriesStore, source, this.interval, response.bars, boundary);
      this.completedKey = key;
      this.publish({ loading: false, error: null, boundaryMs: boundary });
    }).catch((error: unknown) => {
      if (request.signal.aborted) return;
      this.seriesStore.clear({ source: "replay-cell-projection-error" });
      this.publish({ loading: false, error: error instanceof Error ? error.message : String(error), boundaryMs: null });
    }).finally(() => {
      if (this.request !== request) return;
      this.request = null;
      if (this.completedKey === key && this.leases > 0) this.schedule();
    });
  };

  retry = () => {
    this.completedKey = null;
    this.refresh();
  };
}

export function useReplayChartProjection(runtime: ReplayRuntime, trackId: string, interval: string) {
  // Only the source connection is pooled. Sharing a mutable paged SeriesWindowStore
  // would let one chart scrolling into history replace another chart's live edge.
  const projection = useMemo(() => new ReplayChartProjection(runtime.lifecycle, trackId, interval),
    [runtime.lifecycle, trackId, interval]);
  useEffect(() => projection.retain(), [projection]);
  const state = useSyncExternalStore(projection.subscribe, projection.getSnapshot, projection.getSnapshot);
  const subscribeSeries = useCallback((notify: () => void) => {
    const release = projection.seriesStore.subscribe(notify);
    return () => { release(); };
  }, [projection]);
  const seriesVersion = useCallback(() => projection.seriesStore.version, [projection]);
  useSyncExternalStore(subscribeSeries, seriesVersion, seriesVersion);
  return { ...state, seriesStore: projection.seriesStore, retry: projection.retry };
}
