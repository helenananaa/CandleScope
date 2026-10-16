import { describeError } from "../../i18n/serverErrors.js";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { t } from "../../i18n/index.js";
import type { LoadMoreLeft } from "../market-data/useChartLoadMoreLeft.js";
import type { SurfaceViewportSnapshot } from "../chart-representation/chartRepresentationTypes.js";
import type { ReplayDigest } from "./replayTypes.js";
import {
  ReplayHistoryProtocolError,
  applyReplayHistoryPage,
  replayHistoryFirstPageBeforeMs,
  replayHistoryRevealRepairBeforeMs,
  replayHistoryStoreBeforeMs,
  replayHistoryViewportTransferNeedsLatestWindow,
  replayHistoryViewportTransferUnavailable,
  replayHistoryViewportBeforeMs,
} from "./replayHistoryProvider.js";
import { createReplayHistoryProvider } from "./replayTapeHistoryProvider.js";
import type {
  ReplayHistoryIdentity,
  ReplayHistoryPolicy,
} from "./replayHistoryProvider.js";
import type { ReplayRuntime } from "./useReplayRuntime.js";
import { defaultReplayV2Api } from "./replayV2Api.js";
import {
  rebuildReplayViewerSeries,
  replayUsesAuthoritativeSourceBucketProjection,
  replaceReplayViewerSeriesFromServer,
} from "./replayViewerProjection.js";
import type { ReplayViewerRuntime } from "./useReplayViewerRuntime.js";
import { replayHistoryNeedsWarmup } from "./replayHistoryWarmup.js";
import { ReplayHistoryLoadGate } from "./replayHistoryTransport.js";
import { recordPerfEvent } from "../../runtime/performance/perfMarks.js";
import { CANONICAL_HISTORY_REFRESH } from "./replayCanonicalIndicators.js";
import { TAPE_VIEWER_COMMIT } from "./replayTapeViewer.js";


export interface ReplayHistoryRuntime {
  readonly loading: boolean;
  readonly hasMore: boolean;
  readonly canRestoreLatestWindow: boolean;
  readonly error: string | null;
  readonly historyEpoch: ReplayDigest | null;
  readonly boundaryMs: number | null;
  readonly policy: ReplayHistoryPolicy | null;
  readonly notice: string | null;
  readonly viewportTransferUnavailable: boolean;
  readonly loadMoreLeft: LoadMoreLeft;
  readonly restoreLatestWindow: () => Promise<boolean>;
  readonly retryHistory: () => Promise<void>;
  readonly dismissNotice: () => void;
}

interface ReplayHistoryState {
  readonly key: string | null;
  readonly loading: boolean;
  readonly hasMore: boolean;
  readonly error: string | null;
  readonly historyEpoch: ReplayDigest | null;
  readonly boundaryMs: number | null;
  readonly policy: ReplayHistoryPolicy | null;
  readonly notice: string | null;
  readonly viewportTransferUnavailable: boolean;
}

function initialReplayHistoryState(key: string | null): ReplayHistoryState {
  return {
    key,
    loading: false,
    hasMore: true,
    error: null,
    historyEpoch: null,
    boundaryMs: null,
    policy: null,
    notice: null,
    viewportTransferUnavailable: false,
  };
}

export function useReplayHistoryRuntime(
  runtime: ReplayRuntime,
  viewer: ReplayViewerRuntime,
  viewportTransfer: SurfaceViewportSnapshot | null = null,
  warmupTargetBars = 0,
): ReplayHistoryRuntime {
  const retryRequestedRef = useRef(false);
  const [loadGate] = useState(() => new ReplayHistoryLoadGate());
  const tapeObservation = viewer.tapeObservation;
  const observedStore = tapeObservation === undefined ? runtime.store : { ...runtime.store,
    virtualTimeMs: tapeObservation?.virtualTimeMs ?? null, sourceSequence: tapeObservation?.sourceSequence ?? 0 };
  const storeRef = useRef(observedStore);
  storeRef.current = observedStore;
  const observedTimeMs = observedStore.virtualTimeMs;
  const displayReady = tapeObservation !== null;
  const config = runtime.store.sessionConfig;
  const sessionId = runtime.store.sessionId;
  const dataEpoch = runtime.store.dataEpoch;
  const runtimeGeneration = runtime.store.generation;
  const displayInterval = viewer.viewerState?.display_interval ?? null;
  const trackId = viewer.viewerState?.selected_track_id ?? null;
  const exchange = config?.exchange ?? null;
  const marketType = config?.market_type ?? null;
  const symbol = config?.symbol ?? null;
  const sourceKind = config?.source_kind ?? null;
  const baseInterval = config?.base_interval ?? null;
  const usesSourceBucketProjection = replayUsesAuthoritativeSourceBucketProjection(
    sourceKind,
    baseInterval,
    displayInterval,
  );
  // Each authoritative coarse interval owns a different source-bucket
  // mapping. A source-lineage anchor from 1D therefore cannot be compared with
  // the lineage of 1W. Let the authoritative projection restore the latest
  // window, and reserve targeted viewport paging for timelines with a shared
  // identity.
  const historyViewportTransfer = usesSourceBucketProjection
    ? null
    : viewportTransfer;
  const identity = useMemo<ReplayHistoryIdentity | null>(() => (
    exchange === null || marketType === null || symbol === null
      || sourceKind === null || baseInterval === null || displayInterval === null
      ? null
      : ({
    exchange,
    market_type: marketType,
    symbol,
    source_kind: sourceKind === "agg_trade" ? "AGG_TRADE" : "BAR",
    base_interval: baseInterval,
    display_interval: displayInterval,
  })), [baseInterval, displayInterval, exchange, marketType, sourceKind, symbol]);
  const provider = useMemo(() => (
    !displayReady || sessionId === null || identity === null || dataEpoch === null || trackId === null
      ? null
      : createReplayHistoryProvider({ sessionId, trackId, identity, sourceSequence: () => storeRef.current.sourceSequence })
  ), [dataEpoch, displayReady, identity, sessionId, trackId]);
  const historyKey = useMemo(() => (
    sessionId === null || identity === null || dataEpoch === null || trackId === null
      ? null
      : JSON.stringify([
        runtimeGeneration,
        sessionId,
        trackId,
        dataEpoch,
        identity.exchange,
        identity.market_type,
        identity.symbol,
        identity.source_kind,
        identity.base_interval,
        identity.display_interval,
      ])
  ), [dataEpoch, identity, runtimeGeneration, sessionId, trackId]);
  const [historyState, setHistoryState] = useState<ReplayHistoryState>(() => (
    initialReplayHistoryState(historyKey)
  ));
  const [, setViewerSeriesRevision] = useState(0);
  const currentState = historyState.key === historyKey
    ? historyState
    : initialReplayHistoryState(historyKey);
  const currentHistoryRef = useRef({ key: historyKey, state: currentState });
  currentHistoryRef.current = { key: historyKey, state: currentState };
  const loadingRef = useRef<{ key: string | null; loading: boolean }>({
    key: historyKey,
    loading: false,
  });
  const repairAttemptsRef = useRef(new Set<number>());
  const viewportAttemptsRef = useRef(new Set<number>());
  const olderCursorRef = useRef<{ oldest: number | null; next: number } | null>(null);
  const {
    loading,
    hasMore,
    error,
    historyEpoch,
    boundaryMs,
    policy,
    notice,
  } = currentState;

  useEffect(() => {
    retryRequestedRef.current = false;
    loadingRef.current = { key: historyKey, loading: false };
    repairAttemptsRef.current.clear();
    viewportAttemptsRef.current.clear();
    olderCursorRef.current = null;
    setHistoryState(initialReplayHistoryState(historyKey));
    return () => provider?.cancel();
  }, [historyKey, provider]);

  useEffect(() => {
    if (!provider || !tapeObservation || provider.historyEpoch === tapeObservation.historyEpoch) return;
    provider.adoptEpoch(tapeObservation.historyEpoch);
    setHistoryState(current => current.key === historyKey ? { ...current,
      historyEpoch: tapeObservation.historyEpoch, boundaryMs: tapeObservation.historyBoundaryMs,
      policy: tapeObservation.historyPolicy, hasMore: tapeObservation.hasMore } : current);
  }, [historyKey, provider, tapeObservation]);

  useEffect(() => {
    const unsubscribe = viewer.seriesStore.subscribe((delta) => {
      if ((delta.source === CANONICAL_HISTORY_REFRESH || delta.source === TAPE_VIEWER_COMMIT) && provider
        && delta.sessionId === sessionId && delta.trackId === trackId && delta.dataEpoch === dataEpoch
        && typeof delta.historyEpoch === "string" && /^sha256:[0-9a-f]{64}$/.test(delta.historyEpoch)) {
        const reset = provider.historyEpoch !== delta.historyEpoch || delta.source === CANONICAL_HISTORY_REFRESH || delta.historyWindowReset === true;
        provider.adoptEpoch(delta.historyEpoch as ReplayDigest);
        if (reset) {
          repairAttemptsRef.current.clear();
          viewportAttemptsRef.current.clear();
          olderCursorRef.current = null;
        }
        setHistoryState(current => current.key === historyKey ? { ...current, error: null,
          historyEpoch: delta.historyEpoch as ReplayDigest,
          boundaryMs: typeof delta.historyBoundaryMs === "number" ? delta.historyBoundaryMs : null,
          policy: delta.historyPolicy as ReplayHistoryPolicy,
          ...(reset ? { hasMore: delta.hasMore === true, notice: null, viewportTransferUnavailable: false } : {}),
        } : current);
      }
      if (delta.type === "replace" || delta.type === "clear") {
        setViewerSeriesRevision((current) => current + 1);
      }
    });
    return () => { unsubscribe(); };
  }, [dataEpoch, historyKey, provider, sessionId, trackId, viewer.seriesStore]);

  const revealRepairBeforeMs = replayHistoryRevealRepairBeforeMs(
    viewer.seriesStore,
    runtime.store.replayStartMs,
    observedTimeMs,
    displayInterval,
    { allowInitialPartialRepair: !usesSourceBucketProjection },
  );
  const revealRepairPending = revealRepairBeforeMs !== null
    && !repairAttemptsRef.current.has(revealRepairBeforeMs);
  const viewportBeforeMs = historyViewportTransfer !== null
    && historyViewportTransfer.datasetKey !== viewer.seriesStore.seriesKey
    ? replayHistoryViewportBeforeMs(viewer.seriesStore, {
        anchorSourceTime: historyViewportTransfer.anchorSourceTime,
        displayInterval,
        revealedBoundaryMs: observedTimeMs,
      })
    : null;
  const viewportPagePending = viewportBeforeMs !== null
    && !viewportAttemptsRef.current.has(viewportBeforeMs);
  const initialContextPagePending = usesSourceBucketProjection
    && provider?.historyEpoch === null
    && runtime.store.replayStartMs !== null
    && replayHistoryFirstPageBeforeMs(viewer.seriesStore, runtime.store.replayStartMs,
      displayInterval, true, viewer.historyBootstrapBeforeMs ?? null) !== null;
  const warmupPagePending = replayHistoryNeedsWarmup({
    barCount: viewer.seriesStore.barCount,
    targetBars: warmupTargetBars,
    hasMore,
    loading,
    error,
    rightTruncated: viewer.seriesStore.rightTruncated,
  });
  const viewportNeedsLatestRestore = replayHistoryViewportTransferNeedsLatestWindow(
    viewer.seriesStore,
    historyViewportTransfer,
    {
      displayInterval,
      revealedBoundaryMs: observedTimeMs,
    },
  );

  const performLoadMoreLeft = useCallback(async (release: () => void, contiguous = false) => {
    const store = storeRef.current;
    const startedAt = performance.now();
    const recordPage = (outcome: string) => recordPerfEvent("chart.viewport.historyPage", {
      outcome, bars: viewer.seriesStore.barCount, durationMs: performance.now() - startedAt,
    });
    const targetViewportBeforeMs = historyViewportTransfer !== null
      && historyViewportTransfer.datasetKey !== viewer.seriesStore.seriesKey
      ? replayHistoryViewportBeforeMs(viewer.seriesStore, {
          anchorSourceTime: historyViewportTransfer.anchorSourceTime,
          displayInterval,
          revealedBoundaryMs: store.virtualTimeMs,
        })
      : null;
    const pendingViewportBeforeMs = !contiguous && targetViewportBeforeMs !== null
      && !viewportAttemptsRef.current.has(targetViewportBeforeMs)
      ? targetViewportBeforeMs
      : null;
    const repairBeforeMs = replayHistoryRevealRepairBeforeMs(
      viewer.seriesStore,
      store.replayStartMs,
      store.virtualTimeMs,
      displayInterval,
      { allowInitialPartialRepair: !usesSourceBucketProjection },
    );
    // One page owns one purpose. A viewport page can end far before the
    // projection seam; validating/retiring the repair alongside it would
    // silently lose the independent tail-repair demand.
    const pendingRepairBeforeMs = !contiguous && pendingViewportBeforeMs === null && repairBeforeMs !== null
      && !repairAttemptsRef.current.has(repairBeforeMs)
      ? repairBeforeMs
      : null;
    if (provider === null
      || (loadingRef.current.key === historyKey && loadingRef.current.loading)
      || (!hasMore && !retryRequestedRef.current
        && pendingViewportBeforeMs === null
        && pendingRepairBeforeMs === null)
      || store.dataEpoch === null || store.virtualTimeMs === null
    ) {
      recordPage(provider === null ? "no-provider"
        : loadingRef.current.key === historyKey && loadingRef.current.loading ? "busy"
          : !hasMore ? "exhausted" : "no-source");
      return;
    }
    retryRequestedRef.current = false;
    // Context history belongs only to the display store. The frozen base store
    // remains the execution/broker cursor and is never expanded by scrolling.
    const storeBeforeMs = replayHistoryStoreBeforeMs(
      viewer.seriesStore,
    );
    const firstPageBeforeMs = replayHistoryFirstPageBeforeMs(
      viewer.seriesStore,
      store.replayStartMs,
      displayInterval,
      usesSourceBucketProjection,
      viewer.historyBootstrapBeforeMs ?? null,
    );
    // Source-bucket pages connect to the authoritative projection's exact
    // source phase. Other first pages retain the replay seam so history can
    // replace an overlapping partial warmup bucket. Later pages always
    // continue from the oldest display-owned row.
    const beforeMs = pendingViewportBeforeMs
      ?? pendingRepairBeforeMs
      ?? (provider.historyEpoch === null && firstPageBeforeMs !== null
        ? firstPageBeforeMs
        : olderCursorRef.current?.oldest === storeBeforeMs ? olderCursorRef.current.next : storeBeforeMs);
    if (beforeMs === null) { recordPage("no-cursor"); return; }
    if (pendingViewportBeforeMs !== null) {
      viewportAttemptsRef.current.add(pendingViewportBeforeMs);
    }
    loadingRef.current = { key: historyKey, loading: true };
    setHistoryState((current) => ({
      ...(current.key === historyKey ? current : initialReplayHistoryState(historyKey)),
      loading: true,
      error: null,
    }));
    try {
      const page = await provider.loadBefore({
        beforeMs,
        revealedBoundaryMs: store.virtualTimeMs,
        dataEpoch: store.dataEpoch,
        limit: 500,
      });
      const latest = storeRef.current;
      if (latest.sessionId !== sessionId
        || latest.generation !== runtimeGeneration
        || latest.dataEpoch !== page.data_epoch
        || latest.virtualTimeMs === null
        || page.revealed_boundary_ms > latest.virtualTimeMs) { recordPage("stale-generation"); return; }
      // A display-interval switch can start a viewport/repair page while the
      // source-bucket projection is still in flight.  Once that authoritative
      // projection arrives it may already cover the requested anchor.  Do not
      // let the older page reconnect against a cursor that is no longer the
      // active gap; a fresh render will request a different target if one is
      // still needed.
      if (pendingViewportBeforeMs !== null) {
        const latestViewportBeforeMs = historyViewportTransfer !== null
          ? replayHistoryViewportBeforeMs(viewer.seriesStore, {
              anchorSourceTime: historyViewportTransfer.anchorSourceTime,
              displayInterval,
              revealedBoundaryMs: latest.virtualTimeMs,
            })
          : null;
        if (latestViewportBeforeMs !== pendingViewportBeforeMs) { recordPage("stale-viewport"); return; }
      }
      if (pendingRepairBeforeMs !== null) {
        const latestRepairBeforeMs = replayHistoryRevealRepairBeforeMs(
          viewer.seriesStore,
          latest.replayStartMs,
          latest.virtualTimeMs,
          displayInterval,
          { allowInitialPartialRepair: !usesSourceBucketProjection },
        );
        if (latestRepairBeforeMs !== pendingRepairBeforeMs) { recordPage("stale-repair"); return; }
      }
      applyReplayHistoryPage(viewer.seriesStore, page, {
        expectedBeforeMs: beforeMs,
        contextHistory: true,
      });
      recordPage("applied");
      if (pendingRepairBeforeMs !== null) {
        repairAttemptsRef.current.add(pendingRepairBeforeMs);
      }
      if (pendingViewportBeforeMs === null && pendingRepairBeforeMs === null) {
        olderCursorRef.current = page.bars.length === 0 && page.has_more && page.next_before_ms < beforeMs
          ? { oldest: storeBeforeMs, next: page.next_before_ms } : null;
      }
      const nextHasMore = page.has_more;
      // A gap can invalidate the whole target display bucket even when the
      // original fine-grained anchor itself is outside the excluded range.
      // The targeted page gets one attempt; actual post-apply coverage is the
      // authoritative terminal check, including empty/exhausted pages.
      const viewportTransferUnavailable = replayHistoryViewportTransferUnavailable(
        viewer.seriesStore,
        historyViewportTransfer,
        pendingViewportBeforeMs,
      );
      const gapNotice = page.excluded_ranges.length > 0
        ? t("replay.history.excludedGaps", { count: page.excluded_ranges.length })
        : null;
      const nextNotice = !page.has_more
        ? (page.history_policy.visible_history_lookback.mode === "DURATION"
          ? t("replay.history.oldRunBound", {
            count: page.history_policy.visible_history_rows,
            interval: config?.base_interval ?? t("replay.history.baseInterval"),
          })
          : t("replay.history.archiveStart"))
        : gapNotice;
      setHistoryState((current) => current.key === historyKey ? {
        ...current,
        hasMore: nextHasMore,
        historyEpoch: page.history_epoch,
        boundaryMs: page.history_boundary_ms,
        policy: page.history_policy,
        notice: nextNotice,
        viewportTransferUnavailable,
      } : current);
    } catch (cause) {
      recordPage(cause instanceof DOMException && cause.name === "AbortError" ? "aborted" : "error");
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setHistoryState((current) => current.key === historyKey ? {
        ...current,
        error: cause instanceof ReplayHistoryProtocolError && cause.code === "HISTORY_DOWNLOAD_PENDING"
          ? t("replay.picker.downloading")
          : cause instanceof Error ? describeError(cause, cause.message) : t("replay.history.loadFailed"),
        hasMore: false,
        viewportTransferUnavailable: pendingViewportBeforeMs !== null,
      } : current);
    } finally {
      // Release before publishing loading=false: React can flush its next
      // warmup effect before this async function's promise has settled.
      release();
      if (loadingRef.current.key === historyKey) {
        loadingRef.current = { key: historyKey, loading: false };
      }
      setHistoryState((current) => current.key === historyKey
        ? { ...current, loading: false }
        : current);
    }
  }, [
    config?.base_interval,
    displayInterval,
    hasMore,
    historyKey,
    provider,
    runtimeGeneration,
    sessionId,
    usesSourceBucketProjection,
    viewer.seriesStore,
    viewer.historyBootstrapBeforeMs,
    historyViewportTransfer,
  ]);

  const performLoadRef = useRef(performLoadMoreLeft);
  performLoadRef.current = performLoadMoreLeft;
  const loadMoreLeft = useCallback<LoadMoreLeft>(async (oldestLoadedTime) => {
    if (typeof oldestLoadedTime === "number" && Number.isFinite(oldestLoadedTime)) {
      // An anchor/repair page may be correctly discarded after the source
      // projection arrives. Await it, then fulfill this separate contiguous
      // demand; joining that discarded page alone is not a successful fill.
      await loadGate.runAfterCurrent(historyKey, () => {
        const current = currentHistoryRef.current;
        const first = viewer.seriesStore.first()?.time;
        return current.key === historyKey && current.state.hasMore
          && current.state.error === null && first !== undefined && first >= oldestLoadedTime;
      }, (release) => performLoadRef.current(release, true));
    } else {
      await loadGate.run(historyKey, (release) => performLoadMoreLeft(release));
    }
  }, [historyKey, loadGate, performLoadMoreLeft, viewer.seriesStore]);

  useEffect(() => {
    if (
      provider === null
      || loading
      || error !== null
      || viewportNeedsLatestRestore
      || (!initialContextPagePending && !viewportPagePending && !revealRepairPending && !warmupPagePending)
      || runtime.store.dataEpoch === null
      || observedTimeMs === null
    ) return;
    void loadMoreLeft();
  }, [
    loadMoreLeft,
    loading,
    error,
    initialContextPagePending,
    provider,
    revealRepairBeforeMs,
    revealRepairPending,
    runtime.store.dataEpoch,
    observedTimeMs,
    viewportBeforeMs,
    viewportNeedsLatestRestore,
    viewportPagePending,
    warmupPagePending,
  ]);

  const restoreLatestWindow = useCallback(async (): Promise<boolean> => {
    if (
      (loadingRef.current.key === historyKey && loadingRef.current.loading)
      || config === null
      || displayInterval === null
      || !viewer.seriesStore.rightTruncated
    ) return false;
    provider?.cancel();
    if (sourceKind === "agg_trade" && viewer.actions.restoreLatestProjection) {
      return viewer.actions.restoreLatestProjection();
    }
    if (usesSourceBucketProjection
      && runtime.store.sessionId !== null
      && runtime.store.dataEpoch !== null
      && runtime.store.virtualTimeMs !== null
      && viewer.viewerState?.selected_track_id !== null
      && viewer.viewerState?.selected_track_id !== undefined) {
      const response = await defaultReplayV2Api.displayProjectionBySession(
        runtime.store.sessionId,
        {
          trackId: viewer.viewerState.selected_track_id,
          displayInterval,
          revealedBoundaryMs: runtime.store.virtualTimeMs,
          dataEpoch: runtime.store.dataEpoch,
        },
      );
      replaceReplayViewerSeriesFromServer(
        viewer.seriesStore,
        runtime.replayStore.seriesStore,
        displayInterval,
        response.bars,
        response.revealed_boundary_ms,
      );
    } else {
      rebuildReplayViewerSeries(
        viewer.seriesStore,
        runtime.replayStore.seriesStore,
        config.base_interval,
        displayInterval,
      );
    }
    loadingRef.current = { key: historyKey, loading: false };
    setHistoryState(initialReplayHistoryState(historyKey));
    return true;
  }, [
    config,
    displayInterval,
    historyKey,
    provider,
    runtime.replayStore.seriesStore,
    runtime.store.dataEpoch,
    runtime.store.sessionId,
    runtime.store.virtualTimeMs,
    usesSourceBucketProjection,
    sourceKind,
    viewer.actions,
    viewer.seriesStore,
    viewer.viewerState,
  ]);

  useEffect(() => {
    if (!viewportNeedsLatestRestore) return;
    void restoreLatestWindow();
  }, [restoreLatestWindow, viewportNeedsLatestRestore]);

  return {
    loading,
    hasMore,
    canRestoreLatestWindow: !loading
      && runtime.store.hasAuthoritativeSnapshot
      && runtime.store.connectionState === "connected"
      && viewer.seriesStore.rightTruncated,
    error,
    historyEpoch,
    boundaryMs,
    policy,
    notice,
    viewportTransferUnavailable: currentState.viewportTransferUnavailable,
    loadMoreLeft,
    restoreLatestWindow,
    retryHistory: async () => {
      retryRequestedRef.current = true;
      await loadMoreLeft();
    },
    dismissNotice: () => setHistoryState((current) => current.key === historyKey
      ? { ...current, notice: null }
      : current),
  };
}
