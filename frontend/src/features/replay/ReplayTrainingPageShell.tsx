import { REVIEW_PREFIX_MAX_BARS, replayReviewDataMeta } from "./replayReviewPrefix.js";
import { ReplayReviewHistory } from "./replayReviewHistory.js";
import type { ReplayCanonicalBinding } from "./replayCanonicalIndicators.js";
import { useReplayReviewIndicators } from "./useReplayReviewIndicators.js";
import { describeError } from "../../i18n/serverErrors.js";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { TickMarkType } from "../../chart-adapter/chartAdapterTypes.js";
import MarketChartWorkspace from "../../app/MarketChartWorkspace.js";
import MarketPageFrame from "../../app/MarketPageFrame.js";
import MarketStatusBar from "../../app/MarketStatusBar.js";
import MarketTopBarFrame from "../../app/MarketTopBarFrame.js";
import { AlertRailIcon, ProfileRailIcon } from "../../app/marketRailIcons.js";
import type { ChartSurfaceActions, ChartSurfaceHandle, ChartSurfaceVisibleRange } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { RefObject, ComponentType, ReactNode } from "react";
import type { MarketPageFrameProps } from "../../app/MarketPageFrame.js";
import type { ReplayIntegrityRuntime } from "./useReplayIntegrityRuntime.js";
import type { MainSeriesCrosshairValue } from "../../chart-adapter/chartAdapterTypes.js";
import type { SurfaceViewportSnapshot } from "../chart-representation/chartRepresentationTypes.js";
import DrawingToolbar from "../../components/DrawingToolbar.js";
import IntervalSelector from "../../components/IntervalSelector.js";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import IndicatorPanel from "../indicators/IndicatorPanel.js";
import type { IndicatorHLine, IndicatorMarker } from "../indicators/indicatorTypes.js";
import type { IndicatorSubPane } from "../indicators/indicatorPaneProjection.js";
import {
  providedBarsIndicatorSupport,
} from "../indicators/useProvidedBarsIndicatorRuntime.js";
import { useCustomIntervals } from "../chart-session/customIntervalStore.js";
import { useIntervalNoticeRuntime } from "../chart-session/intervalNoticeRuntime.js";
import { loadUserPrefs } from "../chart-session/chartSessionModel.js";
import type { CustomIntervalRecord } from "../chart-session/chartSessionTypes.js";
import { useDrawingRuntime } from "../drawings/useDrawingRuntime.js";
import { drawingDocumentSessionRegistry } from "../drawings/core/drawingDocumentStore.js";
import type { ChartSettingsRuntime } from "../settings/chartAppearanceSettings.js";
import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import {
  intervalsSemanticallyEquivalent,
  parseIntervalSeconds,
} from "../../utils/intervals.js";
import type { IntervalString } from "../../utils/intervals.js";
import ReplayBottomControlDock from "./components/ReplayBottomControlDock.js";
import ReplayIntegrityReviewPanel from "./components/ReplayIntegrityReviewPanel.js";
import ReplayTrainingResultsPanel from "./components/ReplayTrainingResultsPanel.js";
import ReplayRightMarketRail from "./components/ReplayRightMarketRail.js";
import { buildReplayCapabilityModel } from "./replayCapabilityModel.js";
import {
  buildReplayIntervalCatalog,
  canProjectReplayDisplayInterval,
  replayIntervalUnavailableMessage,
} from "./replayIntervalPolicy.js";
import { defaultReplayApi } from "./replayApi.js";
import { defaultReplayV2Api } from "./replayV2Api.js";
import {
  type ReplayHistorySource,
} from "./replayHistoryProvider.js";
import { createReplayHistoryProvider } from "./replayTapeHistoryProvider.js";
import {
  isReplayContextHistoryBar,
} from "./replayViewerProjection.js";
import { handleReplayShortcut } from "./replayShortcuts.js";
import { buildReplayPositionHlines } from "./replayPositionHlines.js";
import {
  formatReplayTimeAxisLabel,
  replayTimeAxisMaxCharacterLength,
} from "./replayPublicTimeModel.js";
import { returnToTrainingHub } from "./trainingHubNavigation.js";
import { replayEffectiveTrainingState, replayOwnsController } from "./replayUiModel.js";
import { useReplayHistoryRuntime } from "./useReplayHistoryRuntime.js";
import { replayHistoryWarmupTarget } from "./replayHistoryWarmup.js";
import { useReplayIntegrityRuntime } from "./useReplayIntegrityRuntime.js";
import { useReplayPublicTimeRuntime } from "./useReplayPublicTimeRuntime.js";
import type {
  ReplaySharedIndicatorRuntime,
} from "./useReplaySharedIndicatorRuntime.js";
import type { ReplayRuntime } from "./useReplayRuntime.js";
import type { ReplayViewerRuntime } from "./useReplayViewerRuntime.js";
import { useReplayWorkspacePreferences } from "./replayWorkspacePreferences.js";
import {
  replayReviewDocumentHash,
  replayReviewPaneDocuments,
  replayReviewDrawingDocument,
  replayReviewDrawingRecord,
} from "./replayReviewDrawing.js";
import ReplayReviewRightRail from "./components/ReplayReviewRightRail.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { Icon } from "../../components/icons/Icon.js";


export interface ReplayTrainingPageShellProps {
  readonly runtime: ReplayRuntime;
  readonly indicators: ReplaySharedIndicatorRuntime;
  readonly chartSurfaceRef: RefObject<ChartSurfaceHandle | null>;
  readonly chartSurfaceActions: ChartSurfaceActions;
  readonly viewer: ReplayViewerRuntime;
  readonly chartSettingsRuntime: ChartSettingsRuntime;
  readonly cell?: {
    readonly scope: string;
    readonly drawingScope: string;
    readonly active: boolean;
    readonly priceScale: { readonly invertScale: boolean; readonly priceScaleMode: number };
    readonly onPriceScaleChange: (value: { invertScale: boolean; priceScaleMode: number }) => void;
    readonly integrity: ReplayIntegrityRuntime;
    readonly frame: ComponentType<ReplayChartPageFrameProps>;
    readonly controls: ReactNode;
    readonly controlViewer: ReplayViewerRuntime;
    readonly preferences: ReturnType<typeof useReplayWorkspacePreferences>;
    readonly onCrosshairMove: (value: MainSeriesCrosshairValue | null) => void;
    readonly onVisibleRangeChange: (range: ChartSurfaceVisibleRange) => void;
    readonly onUserViewportRangeChange: (range: ChartSurfaceVisibleRange) => void;
    readonly subscribeIntervalChange: (prepare: (interval: IntervalString) => void) => () => void;
  };
}

export interface ReplayChartPageFrameProps extends MarketPageFrameProps {
  toolbar?: ReactNode;
  rightRail?: ReactNode;
}

interface ReplayIntervalViewportTransfer {
  readonly snapshot: SurfaceViewportSnapshot;
  readonly targetInterval: IntervalString;
}


function ReplayStatePanel({ runtime }: { readonly runtime: ReplayRuntime }) {
  useLocale();
  if (runtime.phase === "ERROR" || runtime.phase === "ENTRY_ERROR") {
    return (
      <div className="chart-area" data-replay-state="error" data-replay-error={runtime.error?.code ?? "REPLAY_RUNTIME_ERROR"}>
        <div className="error-overlay">
          <div className="error-icon">!</div>
          <div className="error-message">
            <strong>{t("replay.shell.unavailable")}</strong><br />
            {runtime.error?.code ?? "REPLAY_RUNTIME_ERROR"}: {runtime.error?.message ?? "Unknown replay error"}
            <small>{t("replay.shell.failClosed")}</small>
          </div>
          {runtime.phase === "ERROR" && <button className="retry-btn" type="button" onClick={runtime.actions.retry}>{t("replay.shell.retryCaps")}</button>}
        </div>
      </div>
    );
  }
  const labels: Readonly<Record<string, string>> = {
    IDLE: t("replay.shell.idle"),
    LOADING_CAPABILITIES: t("replay.shell.loadingCaps"),
    VALIDATING_SESSION: t("replay.shell.validating"),
    CONNECTING_SESSION: t("replay.shell.connecting"),
    STOPPED: t("replay.shell.stopped"),
  };
  return (
    <div className="chart-area" data-replay-state="loading">
      <div className="error-overlay">
        <div className="replay-loading-spinner" />
        <div className="error-message"><strong>{t("replay.shell.replay")}</strong><br />{labels[runtime.phase] ?? t("replay.shell.recovering")}<small>{t("replay.shell.noLiveMock")}</small></div>
      </div>
    </div>
  );
}

export default function ReplayTrainingPageShell({
  runtime,
  indicators,
  chartSurfaceRef,
  chartSurfaceActions,
  viewer,
  chartSettingsRuntime,
  cell,
}: ReplayTrainingPageShellProps) {
  const PageFrame = cell?.frame ?? MarketPageFrame;
  const locale = useLocale();
  const [returningToHub, setReturningToHub] = useState(false);
  const [returnToHubError, setReturnToHubError] = useState<string | null>(null);
  const [integrityOpen, setIntegrityOpen] = useState(false);
  const [trainingResultsOpen, setTrainingResultsOpen] = useState(false);
  const [indicatorPanelOpen, setIndicatorPanelOpen] = useState(false);
  const [intervalViewportTransfer, setIntervalViewportTransfer] = useState<ReplayIntervalViewportTransfer | null>(null);
  const subscribeIntervalChange = cell?.subscribeIntervalChange;
  useEffect(() => subscribeIntervalChange?.((targetInterval) => {
    const snapshot = chartSurfaceActions.captureViewportTransfer();
    setIntervalViewportTransfer(snapshot ? { snapshot, targetInterval } : null);
  }), [chartSurfaceActions, subscribeIntervalChange]);
  const intervalCommandOwnerRef = useRef<object | null>(null);
  const {
    customIntervalRecords,
    savedCustomIntervals,
    addCustomInterval,
    markIntervalUsed,
    removeCustomInterval,
    restoreCustomInterval,
    togglePinCustomInterval,
    clearCustomIntervals,
  } = useCustomIntervals();
  const { intervalNotice, showIntervalNotice } = useIntervalNoticeRuntime();
  const lastRemovedIntervalRef = useRef<CustomIntervalRecord | null>(null);
  const integrityToggleRef = useRef<HTMLButtonElement | null>(null);
  const integrityDrawerRef = useRef<HTMLElement | null>(null);
  const [priceScale] = useState(() => {
    const preferences = loadUserPrefs();
    return {
      invert: Boolean(preferences.invertScale),
      mode: typeof preferences.priceScaleMode === "number" ? preferences.priceScaleMode : 0,
    };
  });
  const { settings, setSettings, resolvedTheme } = chartSettingsRuntime;
  const drawings = useDrawingRuntime({ chartSurfaceActions, session: null });
  const activeIntervalViewportTransfer = intervalViewportTransfer !== null
    && intervalsSemanticallyEquivalent(
      viewer.viewerState?.display_interval
        ?? runtime.store.sessionConfig?.base_interval
        ?? "1m",
      intervalViewportTransfer.targetInterval,
    )
    ? intervalViewportTransfer.snapshot
    : null;
  const history = useReplayHistoryRuntime(runtime, viewer, activeIntervalViewportTransfer,
    replayHistoryWarmupTarget(indicators.view.activeIndicators));
  useEffect(() => {
    if (!history.viewportTransferUnavailable
      || activeIntervalViewportTransfer === null) return;
    setIntervalViewportTransfer((current) => (
      current?.snapshot === activeIntervalViewportTransfer ? null : current
    ));
  }, [activeIntervalViewportTransfer, history.viewportTransferUnavailable]);
  const ownIntegrity = useReplayIntegrityRuntime(runtime, viewer, integrityOpen, cell === undefined);
  const integrityRuntime = cell?.integrity ?? ownIntegrity;
  const review = integrityRuntime.review;
  useEffect(() => {
    if (review !== null && !trainingResultsOpen) setIntegrityOpen(true);
  }, [review, trainingResultsOpen]);
  useEffect(() => {
    if (review !== null) setIndicatorPanelOpen(false);
  }, [review]);
  useEffect(() => {
    if (!integrityOpen) return undefined;
    const drawer = integrityDrawerRef.current;
    const toggle = integrityToggleRef.current;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setIntegrityOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    requestAnimationFrame(() => drawer?.focus());
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      requestAnimationFrame(() => toggle?.focus());
    };
  }, [integrityOpen]);
  const liveDrawingScopeBase = cell?.drawingScope ?? (integrityRuntime.runId === null
    ? `replay-run:pending`
    : `replay-run:${integrityRuntime.runId}`);
  const reviewDrawingScopeBase = review === null
    ? null
    : `replay-review:${review.review_id}${cell ? `:${cell.scope}` : ""}`;
  const reviewDrawingDocument = review?.drawing_document ?? null;
  const reviewDrawingCursorRevision = review?.cursor_revision ?? null;
  const [reviewDrawingGeneration, setReviewDrawingGeneration] = useState(0);
  const reviewSelectedTrackId = review === null
    ? null
    : String(review.projection.viewer_state.selected_track_id ?? "");
  const reviewProjectedTrack = reviewSelectedTrackId === null
    ? undefined
    : review?.projection.tracks.find((item) => (
      item.track_id === reviewSelectedTrackId
    ));
  const reviewProjectedExchange = reviewProjectedTrack?.exchange;
  const reviewProjectedMarketType = reviewProjectedTrack?.market_type;
  const reviewProjectedSourceKind = reviewProjectedTrack?.source_kind;
  const reviewProjectedSymbol = reviewProjectedTrack?.symbol;
  const reviewProjectedInterval = review?.projection.viewer_state.display_interval;
  const reviewTrackCursor = reviewProjectedTrack?.cursor;
  const reviewSourceSequence = reviewTrackCursor && typeof reviewTrackCursor === "object" && !Array.isArray(reviewTrackCursor)
    && "source_sequence" in reviewTrackCursor && typeof reviewTrackCursor.source_sequence === "number"
    ? reviewTrackCursor.source_sequence : undefined;
  const reviewCursorVirtualTimeMs = review?.projection.cursor.virtual_time_ms ?? null;
  const reviewAdapterSessionId = viewer.marketTracks?.tracks.find(item => item.track_id === reviewSelectedTrackId)?.adapter_session_id;
  const drawingScopeBase = reviewDrawingScopeBase ?? liveDrawingScopeBase;
  const reviewSeriesStore = useMemo(() => new SeriesWindowStore({ maxBars: REVIEW_PREFIX_MAX_BARS }), []);
  const [reviewChartLoading, setReviewChartLoading] = useState(false);
  const [reviewChartError, setReviewChartError] = useState<string | null>(null);
  const [reviewChartBounded, setReviewChartBounded] = useState(false);
  const [reviewOlderLoading, setReviewOlderLoading] = useState(false);
  const [reviewOlderError, setReviewOlderError] = useState<string | null>(null);
  const [reviewHasMore, setReviewHasMore] = useState(false);
  const reviewHistoryRef = useRef<ReplayReviewHistory | null>(null);
  const loadReviewMoreLeft = useCallback(async () => { await reviewHistoryRef.current?.loadMoreLeft(); }, []);
  const reviewPrefixKey = review === null ? null : JSON.stringify([
    review.review_id, review.selected_timeline_sequence, reviewSelectedTrackId, reviewAdapterSessionId, reviewProjectedExchange, reviewProjectedMarketType,
    reviewProjectedSymbol, reviewProjectedSourceKind, reviewProjectedInterval, reviewCursorVirtualTimeMs,
  ]);
  const [reviewLoadedPrefixKey, setReviewLoadedPrefixKey] = useState<string | null>(null);
  const [reviewIndicatorBinding, setReviewIndicatorBinding] = useState<ReplayCanonicalBinding | null>(null);
  const reviewIndicators = useReplayReviewIndicators({ seriesStore: reviewSeriesStore,
    sourceBinding: reviewIndicatorBinding,
    requestedKey: reviewPrefixKey, loadedKey: reviewLoadedPrefixKey, cursorMs: reviewCursorVirtualTimeMs,
    definitions: indicators.view.activeIndicators,
    exchange: typeof reviewProjectedExchange === "string" ? reviewProjectedExchange : "",
    marketType: typeof reviewProjectedMarketType === "string" ? reviewProjectedMarketType : "",
    symbol: typeof reviewProjectedSymbol === "string" ? reviewProjectedSymbol : "",
    interval: typeof reviewProjectedInterval === "string" ? reviewProjectedInterval : "1m" });
  const [liveDrawingError, setLiveDrawingError] = useState<string | null>(null);
  const [reviewDrawingError, setReviewDrawingError] = useState<string | null>(null);
  const ownWorkspace = useReplayWorkspacePreferences(viewer.viewerState?.run_id ?? runtime.store.sessionId ?? "pending");
  const workspace = cell?.preferences ?? ownWorkspace;
  const config = runtime.store.sessionConfig;
  const active = runtime.phase === "ACTIVE" && config !== null && runtime.store.hasAuthoritativeSnapshot;
  const ownsController = replayOwnsController(runtime.store, runtime.clientInstanceId);
  const globalClock = viewer.marketTracks?.global_clock ?? null;
  const effectiveState = replayEffectiveTrainingState(
    globalClock?.state,
    runtime.store.state,
    runtime.store.controllerClientId,
  );
  const capabilities = useMemo(() => buildReplayCapabilityModel(config?.source_kind ?? "BAR"), [config?.source_kind]);
  const publicTimeline = (() => {
    const values = viewer.seriesStore.snapshot()
      .filter((bar) => !isReplayContextHistoryBar(bar))
      .map((bar) => Number(bar.time) * 1_000);
    if (runtime.store.virtualTimeMs !== null) values.push(runtime.store.virtualTimeMs);
    for (const order of runtime.store.orders) values.push(order.created_time_ms);
    for (const fill of runtime.store.fills) values.push(fill.event_time_ms);
    for (const entry of runtime.store.journal) values.push(entry.virtual_time_ms);
    for (const track of viewer.marketTracks?.tracks ?? []) {
      if (track.historical_book?.as_of_virtual_time_ms !== null
        && track.historical_book?.as_of_virtual_time_ms !== undefined) {
        values.push(track.historical_book.as_of_virtual_time_ms);
      }
    }
    return values;
  })();
  const publicTimePolicy = integrityRuntime.integrity?.effective_time_disclosure_policy
    ?? (config?.blind_mode === false ? "NONE" : "HIDE_ALL");
  const publicTimeRuntime = useReplayPublicTimeRuntime({
    runId: integrityRuntime.runId,
    policy: publicTimePolicy,
    originMs: integrityRuntime.integrity?.start_selection.public_start.timeline_ms
      ?? runtime.store.replayStartMs,
    timelineOriginMs: runtime.store.replayStartMs,
    timelineMs: publicTimeline,
  });
  const publicTime = runtime.store.virtualTimeMs === null
    ? (integrityRuntime.integrity?.public_time.label ?? "--")
    : publicTimeRuntime.formatTime(runtime.store.virtualTimeMs);
  const formatPublicTime = publicTimeRuntime.formatTime;
  const formatChartTime = useCallback(
    (timeSeconds: number) => formatPublicTime(timeSeconds * 1_000),
    [formatPublicTime],
  );
  const formatChartTick = useCallback(
    (timeSeconds: number, tickMarkType: TickMarkType) => formatReplayTimeAxisLabel(
      publicTimePolicy,
      formatPublicTime(timeSeconds * 1_000),
      tickMarkType,
    ),
    [formatPublicTime, publicTimePolicy],
  );
  const returnToHub = useCallback(async () => {
    const runId = viewer.viewerState?.run_id ?? null;
    if (runId === null || returningToHub) return;
    setReturningToHub(true);
    setReturnToHubError(null);
    try {
      await returnToTrainingHub(runId, defaultReplayV2Api);
    } catch (cause) {
      setReturnToHubError(cause instanceof Error ? describeError(cause, cause.message) : t("replay.shell.returnFailed", {}, locale));
      setReturningToHub(false);
    }
  }, [locale, returningToHub, viewer.viewerState?.run_id]);

  useEffect(() => {
    setLiveDrawingError(null);
    if (cell !== undefined) return;
    const runId = integrityRuntime.runId;
    if (runId === null || !integrityRuntime.drawingLoaded) return;
    const current = integrityRuntime.currentDrawing;
    if (current === null) {
      setLiveDrawingError(t("replay.shell.drawingMissing", {}, locale));
      return;
    }
    const scopeKey = `replay-run:${runId}__main`;
    const store = drawingDocumentSessionRegistry.getStore(scopeKey);
    try {
      if (current.document !== null && !store.dirty) {
        const document = replayReviewDrawingDocument(current.document, scopeKey);
        const loaded = store.loadDocument(document);
        if (!loaded.ok) throw new Error(loaded.error);
      }
      drawingDocumentSessionRegistry.markLoaded(scopeKey, store);
    } catch (cause) {
      setLiveDrawingError(
        cause instanceof Error ? describeError(cause, cause.message) : t("replay.shell.drawingRestoreFailed", {}, locale),
      );
    }
  }, [
    integrityRuntime.currentDrawing,
    cell,
    integrityRuntime.drawingLoaded,
    integrityRuntime.runId,
    locale,
  ]);

  useEffect(() => {
    if (cell !== undefined) return;
    const runId = integrityRuntime.runId;
    const currentDrawing = integrityRuntime.currentDrawing;
    if (runId === null
      || !integrityRuntime.drawingLoaded
      || currentDrawing === null
      || liveDrawingError !== null) return;
    const scopeKey = `replay-run:${runId}__main`;
    const store = drawingDocumentSessionRegistry.getStore(scopeKey);
    const recordDrawing = integrityRuntime.actions.recordDrawing;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;
    const schedule = () => {
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        const snapshot = store.getSnapshot();
        const revision = snapshot.documentRevision;
        void (async () => {
          const document = replayReviewDrawingRecord(snapshot, runId);
          const hash = await replayReviewDocumentHash(document);
          if (disposed) return;
          if (store.getSnapshot().documentRevision !== revision) {
            schedule();
            return;
          }
          await recordDrawing(document, hash, snapshot.entities.size);
          if (!disposed) store.acknowledgePersisted(scopeKey, revision);
        })().catch((cause) => {
          if (disposed) return;
          setLiveDrawingError(
            cause instanceof Error
              ? t("replay.shell.drawingSubmitFailedWith", { message: cause.message }, locale)
              : t("replay.shell.drawingSubmitFailed", {}, locale),
          );
        });
      }, 500);
    };
    const unsubscribe = store.subscribe(() => schedule());
    if ((store.dirty || currentDrawing.document === null)
      && store.getSnapshot().documentRevision > 0) schedule();
    return () => {
      disposed = true;
      unsubscribe();
      if (timer !== null) clearTimeout(timer);
    };
  }, [
    integrityRuntime.actions.recordDrawing,
    cell,
    integrityRuntime.currentDrawing,
    integrityRuntime.drawingLoaded,
    integrityRuntime.runId,
    liveDrawingError,
    locale,
  ]);

  useEffect(() => {
    setReviewDrawingError(null);
    if (reviewDrawingCursorRevision === null || reviewDrawingScopeBase === null) return;
    try {
      const documents = replayReviewPaneDocuments(reviewDrawingDocument, liveDrawingScopeBase,
        reviewDrawingScopeBase, drawingDocumentSessionRegistry.loadedScopes());
      let changed = false;
      for (const document of documents) {
        const store = drawingDocumentSessionRegistry.getStore(document.scopeKey);
        const loaded = store.loadDocument(document);
        if (!loaded.ok) throw new Error(loaded.error);
        changed ||= loaded.changed;
        drawingDocumentSessionRegistry.markLoaded(document.scopeKey, store);
      }
      // Publish after all pane stores are ready; rewinding may lower document revisions.
      if (changed) setReviewDrawingGeneration(generation => generation + 1);
    } catch (cause) {
      setReviewDrawingError(
        cause instanceof Error ? describeError(cause, cause.message) : t("replay.shell.reviewRestoreFailed", {}, locale),
      );
    }
  }, [
    locale,
    reviewDrawingCursorRevision,
    reviewDrawingDocument,
    reviewDrawingScopeBase,
    liveDrawingScopeBase,
  ]);

  useEffect(() => {
    setReviewLoadedPrefixKey(null);
    setReviewIndicatorBinding(null);
    setReviewOlderLoading(false);
    setReviewOlderError(null);
    setReviewHasMore(false);
    if (reviewSelectedTrackId === null || reviewCursorVirtualTimeMs === null) {
      setReviewChartLoading(false);
      setReviewChartError(null);
      setReviewChartBounded(false);
      return;
    }
    if (typeof reviewProjectedExchange !== "string"
      || typeof reviewProjectedMarketType !== "string"
      || typeof reviewProjectedSymbol !== "string"
      || typeof reviewProjectedSourceKind !== "string"
      || typeof reviewProjectedInterval !== "string"
      || parseIntervalSeconds(reviewProjectedInterval) === null
      || reviewAdapterSessionId === null
      || reviewAdapterSessionId === undefined) {
      setReviewChartLoading(false);
      setReviewChartBounded(false);
      setReviewChartError(t("replay.shell.reviewIdentityMissing", {}, locale));
      reviewSeriesStore.replace([], { source: "replay-review-unavailable" });
      return;
    }
    const adapterSessionId = reviewAdapterSessionId;
    const abort = new AbortController();
    let provider: ReplayHistorySource | null = null;
    let reviewHistory: ReplayReviewHistory | null = null;
    setReviewChartLoading(true);
    setReviewChartError(null);
    setReviewChartBounded(false);
    void (async () => {
      const session = await defaultReplayApi.getSession(
        adapterSessionId,
        abort.signal,
      );
      const config = session.snapshot.config;
      if (config.exchange !== reviewProjectedExchange
        || config.market_type !== reviewProjectedMarketType
        || config.symbol !== reviewProjectedSymbol
        || config.source_kind.toUpperCase() !== reviewProjectedSourceKind) {
        throw new Error(t("replay.shell.reviewIdentityMismatch", {}, locale));
      }
      provider = createReplayHistoryProvider({
        sessionId: adapterSessionId,
        trackId: reviewSelectedTrackId,
        sourceSequence: reviewSourceSequence,
        identity: {
          exchange: config.exchange,
          market_type: config.market_type,
          symbol: config.symbol,
          source_kind: config.source_kind === "agg_trade" ? "AGG_TRADE" : "BAR",
          base_interval: config.base_interval,
          display_interval: reviewProjectedInterval,
        },
      });
      const revealedBoundaryMs = reviewCursorVirtualTimeMs;
      if (abort.signal.aborted) return;
      reviewHistory = new ReplayReviewHistory(reviewSeriesStore, provider, session.snapshot.data_epoch, revealedBoundaryMs, state => {
        if (abort.signal.aborted) return;
        setReviewChartBounded(state.bounded);
        setReviewHasMore(state.hasMore);
        setReviewOlderLoading(state.loading);
        setReviewOlderError(state.error);
      });
      reviewHistoryRef.current = reviewHistory;
      await reviewHistory.initialize(reviewPrefixKey!);
      if (abort.signal.aborted) return;
      setReviewIndicatorBinding({ sessionId: adapterSessionId, trackId: reviewSelectedTrackId,
        dataEpoch: session.snapshot.data_epoch, revealedBoundaryMs,
        ...(provider.historyEpoch === null ? {} : { historyEpoch: provider.historyEpoch }),
        ...(reviewSourceSequence === undefined ? {} : { sourceSequence: reviewSourceSequence }),
        identity: { exchange: config.exchange, market_type: config.market_type, symbol: config.symbol,
          source_kind: config.source_kind === "agg_trade" ? "AGG_TRADE" : "BAR",
          base_interval: config.base_interval, display_interval: reviewProjectedInterval },
      });
      setReviewLoadedPrefixKey(reviewPrefixKey);
    })().catch((cause: unknown) => {
      if (abort.signal.aborted) return;
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      reviewSeriesStore.replace([], { source: "replay-review-fail-closed" });
      setReviewChartError(
        cause instanceof Error ? describeError(cause, cause.message) : t("replay.shell.reviewPrefixFailed", {}, locale),
      );
    }).finally(() => {
      if (!abort.signal.aborted) setReviewChartLoading(false);
    });
    return () => {
      abort.abort();
      reviewHistory?.cancel();
      if (reviewHistoryRef.current === reviewHistory) reviewHistoryRef.current = null;
      provider?.cancel();
    };
  }, [
    reviewCursorVirtualTimeMs,
    reviewPrefixKey,
    reviewProjectedInterval,
    reviewProjectedExchange,
    reviewProjectedMarketType,
    reviewProjectedSourceKind,
    reviewProjectedSymbol,
    locale,
    reviewSelectedTrackId,
    reviewSeriesStore,
    reviewAdapterSessionId,
    reviewSourceSequence,
  ]);

  const displayedSeriesStore = review === null ? viewer.seriesStore : reviewSeriesStore;
  const ensureIndicatorViewport = review === null
    ? indicators.actions.ensureVisibleIndicatorRange
    : reviewIndicators.actions.ensureVisibleIndicatorRange;
  const handleVisibleRangeChange = useCallback((range: ChartSurfaceVisibleRange) => {
    // Linked/restore ranges settle on the next draw. Also accept the persisted
    // range so display math follows programmatic navigation and review views.
    ensureIndicatorViewport(range);
    if (integrityRuntime.review !== null) return;
    runtime.marketData.actions.onVisibleRangeChange(range);
    cell?.onVisibleRangeChange(range);
    const value: Record<string, number> = {};
    if (range.logical !== undefined) {
      value.from_logical_ppm = Math.round(range.logical.from * 1_000_000);
      value.to_logical_ppm = Math.round(range.logical.to * 1_000_000);
    }
    if (range.barSpacing !== undefined) value.bar_spacing_ppm = Math.round(range.barSpacing * 1_000_000);
    if (range.rightOffset !== undefined) value.right_offset_ppm = Math.round(range.rightOffset * 1_000_000);
    integrityRuntime.actions.offerViewAction("VISIBLE_RANGE", "main-chart-range", value);
  }, [cell, ensureIndicatorViewport, integrityRuntime.actions, integrityRuntime.review, runtime.marketData.actions]);

  useEffect(() => {
    if (cell?.active === false) return;
    const listener = (event: KeyboardEvent) => {
      handleReplayShortcut(event, (action) => {
        if (integrityRuntime.review !== null
          || !ownsController || runtime.store.connectionState !== "connected"
          || runtime.pendingCommand !== null || viewer.controlPending !== null
          || viewer.viewerPending) return false;
        if (action === "toggle-play" && effectiveState === "PLAYING") {
          void viewer.actions.submitControl("pause", {}).catch(() => undefined);
          return true;
        }
        if (action === "toggle-play" && effectiveState === "PAUSED") {
          if (globalClock === null || !globalClock.playback_bases.includes(globalClock.basis)) {
            return false;
          }
          void viewer.actions.submitControl("play", {
            basis: globalClock.basis,
            rate: globalClock.rate,
          }).catch(() => undefined);
          return true;
        }
        if (action === "step" && effectiveState === "PAUSED") {
          if (globalClock === null || !globalClock.supported_bases.includes("DISPLAY_BAR")) {
            return false;
          }
          void viewer.actions.submitControl("advance", {
            basis: "DISPLAY_BAR",
            count: 1,
          }).catch(() => undefined);
          return true;
        }
        if (action === "advance-window" && effectiveState === "PAUSED") {
          if (globalClock === null || !globalClock.supported_bases.includes("BASE_BAR")) {
            return false;
          }
          void viewer.actions.submitControl("advance", {
            basis: "BASE_BAR",
            count: 5,
          }).catch(() => undefined);
          return true;
        }
        return false;
      });
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [cell?.active, effectiveState, globalClock, integrityRuntime.review, ownsController, runtime.pendingCommand, runtime.store.connectionState, viewer.actions, viewer.controlPending, viewer.viewerPending]);

  const interval = (viewer.viewerState?.display_interval ?? config?.base_interval ?? "1m") as IntervalString;
  const reviewSelectedTrack = review?.projection.tracks.find((track) => (
    track.track_id === review.projection.viewer_state.selected_track_id
  ));
  const activeSelectedTrack = viewer.marketTracks?.tracks.find((track) => (
    track.track_id === viewer.viewerState?.selected_track_id
  ));
  const projectedInterval = review?.projection.viewer_state.display_interval;
  const displayedInterval = (
    review !== null
      && typeof projectedInterval === "string"
      && parseIntervalSeconds(projectedInterval) !== null
      ? projectedInterval
      : interval
  ) as IntervalString;
  const displayedSymbol = review !== null && typeof reviewSelectedTrack?.symbol === "string"
    ? reviewSelectedTrack.symbol
    : activeSelectedTrack?.symbol ?? config?.symbol ?? "--";
  const baseInterval = (config?.base_interval ?? "1m") as IntervalString;
  const replayIntervalCatalog = useMemo(() => buildReplayIntervalCatalog({
    exchange: config?.exchange ?? "binance",
    marketType: config?.market_type ?? "spot",
    savedCustomIntervals,
  }), [
    config?.exchange,
    config?.market_type,
    savedCustomIntervals,
  ]);
  const intervalAvailability = useCallback((next: IntervalString): boolean => (
    canProjectReplayDisplayInterval(baseInterval, next)
  ), [baseInterval]);
  const unavailableIntervalMessage = useCallback((next: IntervalString): string => (
    replayIntervalUnavailableMessage(baseInterval, next)
  ), [baseInterval]);
  const setReplayDisplayInterval = useCallback((next: IntervalString): void => {
    if (intervalCommandOwnerRef.current !== null
      || intervalsSemanticallyEquivalent(interval, next)) return;
    const owner = {};
    intervalCommandOwnerRef.current = owner;
    const snapshot = chartSurfaceActions.captureViewportTransfer();
    const transfer = snapshot === null
      ? null
      : { snapshot, targetInterval: next } satisfies ReplayIntervalViewportTransfer;
    setIntervalViewportTransfer(transfer);
    void viewer.actions.setDisplayInterval(next)
      .catch(() => {
        setIntervalViewportTransfer((current) => current === transfer ? null : current);
      })
      .finally(() => {
        if (intervalCommandOwnerRef.current === owner) {
          intervalCommandOwnerRef.current = null;
        }
      });
  }, [chartSurfaceActions, interval, viewer.actions]);
  const settleReplayIntervalViewportTransfer = useCallback((
    transfer: SurfaceViewportSnapshot,
  ): void => {
    setIntervalViewportTransfer((current) => current?.snapshot === transfer ? null : current);
  }, []);
  const selectReplayInterval = useCallback((next: IntervalString): void => {
    if (review !== null || !intervalAvailability(next)) return;
    markIntervalUsed(next);
    setReplayDisplayInterval(next);
  }, [intervalAvailability, markIntervalUsed, review, setReplayDisplayInterval]);
  const createReplayCustomInterval = useCallback((next: IntervalString) => {
    if (review !== null) return { ok: false as const, message: t("replay.shell.intervalReadonly", {}, locale) };
    if (!intervalAvailability(next)) {
      return { ok: false as const, message: unavailableIntervalMessage(next) };
    }
    const result = addCustomInterval(next, { markUsed: true });
    if (!result.ok) return { ok: false as const, message: t("replay.shell.intervalInvalid", {}, locale) };
    setReplayDisplayInterval(result.value);
    showIntervalNotice({
      type: "success",
      text: t("replay.shell.intervalSaved", { interval: result.value }, locale),
    });
    return { ok: true as const, added: result.added };
  }, [
    addCustomInterval,
    intervalAvailability,
    locale,
    review,
    showIntervalNotice,
    unavailableIntervalMessage,
    setReplayDisplayInterval,
  ]);
  const removeReplayCustomInterval = useCallback((removedInterval: IntervalString): void => {
    if (review !== null) return;
    const removed = removeCustomInterval(removedInterval);
    if (removed === null) return;
    lastRemovedIntervalRef.current = removed;
    if (intervalsSemanticallyEquivalent(interval, removed.value)) {
      setReplayDisplayInterval(baseInterval);
    }
    showIntervalNotice({
      type: "warning",
      text: t("replay.shell.intervalRemoved", { interval: removed.value }, locale),
      actionLabel: t("replay.shell.undo", {}, locale),
      duration: 6500,
    });
  }, [
    baseInterval,
    interval,
    locale,
    removeCustomInterval,
    review,
    showIntervalNotice,
    setReplayDisplayInterval,
  ]);
  const restoreReplayCustomInterval = useCallback((): void => {
    const restored = restoreCustomInterval(lastRemovedIntervalRef.current);
    if (restored === null) return;
    lastRemovedIntervalRef.current = null;
    showIntervalNotice({ type: "success", text: t("replay.shell.intervalRestored", { interval: restored.value }, locale) });
  }, [locale, restoreCustomInterval, showIntervalNotice]);
  const clearReplayCustomIntervals = useCallback((): void => {
    if (review !== null) return;
    const removed = clearCustomIntervals();
    if (removed.length === 0) return;
    lastRemovedIntervalRef.current = removed.at(-1) ?? null;
    if (removed.some((record) => (
      intervalsSemanticallyEquivalent(interval, record.value)
    ))) {
      setReplayDisplayInterval(baseInterval);
    }
    showIntervalNotice({
      type: "warning",
      text: t("replay.shell.intervalCleared", { count: removed.length }, locale),
      actionLabel: t("replay.shell.undoLast", {}, locale),
      duration: 6500,
    });
  }, [
    baseInterval,
    clearCustomIntervals,
    interval,
    locale,
    review,
    showIntervalNotice,
    setReplayDisplayInterval,
  ]);
  const viewerLast = displayedSeriesStore.last();
  const viewerFirst = displayedSeriesStore.first();
  const viewerBarCount = displayedSeriesStore.barCount;
  // Paging older bars must leave the existing chart interactive. An empty
  // projection still needs an initial loading state while history is seeded.
  const historyBootstrapLoading = viewerBarCount === 0 && history.loading;
  const viewerVersion = Number(displayedSeriesStore.version);
  const viewerSeriesKey = displayedSeriesStore.seriesKey;
  const isReview = review !== null;
  const viewerDataMeta = useMemo(() => isReview ? replayReviewDataMeta(displayedSeriesStore, reviewChartLoading) : ({
    ...runtime.marketData.view.meta,
    version: viewerVersion,
    status: !isReview
      ? (viewer.loading ? "loading" : "ready")
      : (reviewChartLoading ? "loading" : "ready"),
    source: !isReview ? "replay-viewer-rebuild" : "replay-review-closed-prefix",
    seriesKey: viewerSeriesKey,
    interval: displayedInterval,
    bars: viewerBarCount,
    firstTime: viewerFirst?.time ?? null,
    lastTime: viewerLast?.time ?? null,
  }), [runtime.marketData.view.meta, viewerVersion, isReview, viewer.loading, reviewChartLoading, displayedSeriesStore,
    viewerSeriesKey, displayedInterval, viewerBarCount, viewerFirst?.time, viewerLast?.time]);
  const replayTradeMarkers = useMemo<IndicatorMarker[]>(() => [{
    id: "replay-trade-fills",
    pane: "main",
    data: runtime.store.fills.map((fill) => ({
      time: fill.event_time_ms / 1_000,
      position: fill.side === "BUY" ? "below" : "above",
      shape: fill.side === "BUY" ? "arrow_up" : "arrow_down",
      color: fill.side === "BUY" ? "#16a34a" : "#e11d48",
      text: `${fill.side === "BUY" ? t("replay.shell.buy", {}, locale) : t("replay.shell.sell", {}, locale)} ${fill.quantity} @ ${fill.price}`,
    })),
  }], [locale, runtime.store.fills]);
  const replayTradeHlines = useMemo<IndicatorHLine[]>(() => {
    const selectedTrackId = viewer.viewerState?.selected_track_id;
    const portfolio = viewer.marketTracks?.portfolio;
    const lines = buildReplayPositionHlines({
      selectedTrackId,
      positionMode: portfolio?.position_mode,
      positions: portfolio?.positions ?? [],
      instrumentRules: portfolio?.schema_version === "replay.training.portfolio.v2"
        ? portfolio.instrument_rules
        : [],
    });
    for (const order of runtime.store.orders) {
      if (order.status !== "OPEN" && order.status !== "PARTIALLY_FILLED") continue;
      const rawPrice = order.limit_price ?? order.stop_price;
      const orderPrice = Number(rawPrice ?? Number.NaN);
      if (!Number.isFinite(orderPrice) || orderPrice <= 0) continue;
      const protection = order.order_type === "STOP_MARKET"
        ? t("replay.shell.stopLoss", {}, locale)
        : order.order_type === "TAKE_PROFIT_MARKET"
          ? t("replay.shell.takeProfit", {}, locale)
          : t("replay.shell.order", {}, locale);
      lines.push({
        id: `replay-order-${order.order_id}`,
        pane: "main",
        price: orderPrice,
        title: `${protection} ${order.side === "BUY" ? t("replay.shell.buy", {}, locale) : t("replay.shell.sell", {}, locale)} ${order.remaining_quantity}`,
        color: order.order_type === "STOP_MARKET"
          ? "#e11d48"
          : order.order_type === "TAKE_PROFIT_MARKET"
            ? "#16a34a"
            : "#7c3aed",
        linestyle: "dashed",
        linewidth: 1,
      });
    }
    return lines;
  }, [locale, runtime.store.orders, viewer.marketTracks?.portfolio, viewer.viewerState?.selected_track_id]);
  const chartMarkers = useMemo(() => [
    ...indicators.view.markers,
    ...replayTradeMarkers,
  ], [indicators.view.markers, replayTradeMarkers]);
  const chartHlines = useMemo(() => [
    ...indicators.view.hlines,
    ...replayTradeHlines,
  ], [indicators.view.hlines, replayTradeHlines]);
  const last = viewerLast ?? runtime.store.lastPrice;
  const removeIndicator = indicators.actions.removeIndicator;
  const removeMarketStudy = indicators.marketStudyActions.remove;
  const removeSubPane = useCallback((pane: IndicatorSubPane) => {
    const owner = pane.owner;
    if (owner?.kind === "indicator") removeIndicator(owner.id);
    else if (owner?.kind === "trade-flow") removeMarketStudy(owner.id);
  }, [removeIndicator, removeMarketStudy]);
  const isUp = Number(last?.close ?? 0) >= Number(last?.open ?? 0);
  const chart = active && review === null && liveDrawingError !== null ? (
    <div className="chart-area" data-replay-state="drawing-error">
      <div className="error-overlay">
        <div className="error-icon">!</div>
        <div className="error-message">
          <strong>{t("replay.shell.drawingFailClosed")}</strong><br />
          {liveDrawingError}
          <small>{t("replay.shell.drawingFailHint")}</small>
        </div>
      </div>
    </div>
  ) : active && review !== null && (reviewChartError !== null || reviewDrawingError !== null) ? (
    <div className="chart-area" data-replay-state="review-error">
      <div className="error-overlay">
        <div className="error-icon">!</div>
        <div className="error-message">
          <strong>{t("replay.shell.reviewFailClosed")}</strong><br />
          {reviewChartError ?? reviewDrawingError}
          <small>{t("replay.shell.reviewFailHint")}</small>
        </div>
      </div>
    </div>
  ) : active && review !== null && (reviewChartLoading || reviewLoadedPrefixKey !== reviewPrefixKey) ? (
    <div className="chart-area" data-replay-state="review-loading">
      <div className="error-overlay">
        <div className="replay-loading-spinner" />
        <div className="error-message">
          <strong>{t("replay.shell.rebuildingPrefix")}</strong><br />
          {t("replay.shell.rebuildingHint")}
        </div>
      </div>
    </div>
  ) : active && config !== null ? (
    <SingleChartPanes
      ref={chartSurfaceRef}
      seriesStore={displayedSeriesStore}
      symbol={displayedSymbol}
      drawingKeyBase={drawingScopeBase}
      drawingReadOnly={review !== null}
      drawingDocumentGeneration={review === null ? 0 : reviewDrawingGeneration}
      paneLayoutScope={cell?.scope ?? null}
      interval={displayedInterval}
      loading={review === null
        && (runtime.marketData.view.loading || viewer.loading || historyBootstrapLoading)}
      onCrosshairMove={cell?.onCrosshairMove ?? runtime.marketData.actions.onCrosshairMove}
      onNeedMoreLeft={review === null ? history.loadMoreLeft : loadReviewMoreLeft}
      onNeedMoreRight={review === null ? history.restoreLatestWindow : null}
      canLoadMoreLeft={review === null ? history.hasMore : reviewHasMore && !reviewChartBounded}
      canRestoreLatestWindow={review === null && history.canRestoreLatestWindow}
      rightWindowTruncated={review === null
        ? viewer.seriesStore.rightTruncated
        : false}
      datasetKey={review === null
        ? String(displayedSeriesStore.seriesKey ?? "replay-viewer-uninitialized")
        : reviewPrefixKey!}
      datasetViewportTransfer={review === null ? activeIntervalViewportTransfer : null}
      onDatasetViewportTransferSettled={settleReplayIntervalViewportTransfer}
      followLatest={review === null}
      latestBarPosition={0.5}
      upColor={settings.upColor}
      downColor={settings.downColor}
      chartType={settings.chartType}
      renkoBoxSizeMode={settings.renkoBoxSizeMode}
      renkoAtrLength={settings.renkoAtrLength}
      renkoBoxSize={settings.renkoBoxSize}
      pointFigureBoxSizeMode={settings.pointFigureBoxSizeMode}
      pointFigureAtrLength={settings.pointFigureAtrLength}
      pointFigureBoxSize={settings.pointFigureBoxSize}
      pointFigureReversalAmount={settings.pointFigureReversalAmount}
      kagiReversalMode={settings.kagiReversalMode}
      kagiAtrLength={settings.kagiAtrLength}
      kagiReversalAmount={settings.kagiReversalAmount}
      lineBreakNumberOfLines={settings.lineBreakNumberOfLines}
      theme={resolvedTheme}
      customBg={settings.customBg}
      timezone={settings.timezone ?? "UTC"}
      timeFormatter={formatChartTime}
      tickMarkFormatter={formatChartTick}
      tickMarkMaxCharacterLength={replayTimeAxisMaxCharacterLength(publicTimePolicy)}
      dataMeta={viewerDataMeta}
      onViewportRangeChange={ensureIndicatorViewport}
      onVisibleRangeChange={handleVisibleRangeChange}
      onUserViewportRangeChange={review === null ? cell?.onUserViewportRangeChange ?? null : null}
      drawingTool={review === null ? drawings.view.drawingTool : null}
      onDrawingToolChange={review === null ? drawings.actions.setDrawingTool : null}
      penColor={drawings.view.penColor}
      penSize={drawings.view.penSize}
      textFontSize={drawings.view.textFontSize}
      textBold={drawings.view.textBold}
      textItalic={drawings.view.textItalic}
      fibLevels={drawings.view.fibLevels}
      fibInverted={drawings.view.fibInverted}
      positionSize={drawings.view.positionSize}
      drawingSnapEnabled={drawings.view.drawingSnapEnabled}
      drawingContinuousEnabled={drawings.view.drawingContinuousEnabled}
      drawingAutoSelectEnabled={drawings.view.drawingAutoSelectEnabled}
      onSelectedDrawingChange={drawings.actions.handleSelectedDrawingChange}
      mainOverlayLines={review === null ? indicators.view.mainOverlayLines : reviewIndicators.view.mainOverlayLines}
      subPanes={review === null ? indicators.view.subPanes : reviewIndicators.view.subPanes}
      indicatorStatusText={review === null ? indicators.status.preparationText : reviewIndicators.status.preparationText}
      indicatorMarkers={review === null ? chartMarkers : reviewIndicators.view.markers}
      indicatorFills={review === null ? indicators.view.fills : reviewIndicators.view.fills}
      indicatorHlines={review === null ? chartHlines : reviewIndicators.view.hlines}
      indicatorBgcolors={review === null ? indicators.view.bgcolors : reviewIndicators.view.bgcolors}
      indicatorBarcolors={review === null ? indicators.view.barcolors : reviewIndicators.view.barcolors}
      onRemoveSubPane={review === null ? removeSubPane : null}
      invertScale={cell?.priceScale.invertScale ?? priceScale.invert}
      priceScaleMode={cell?.priceScale.priceScaleMode ?? priceScale.mode}
      onInvertScaleChange={cell ? (invertScale) => cell.onPriceScaleChange({ ...cell.priceScale, invertScale }) : null}
      onPriceScaleModeChange={cell ? (priceScaleMode) => cell.onPriceScaleChange({ ...cell.priceScale, priceScaleMode }) : null}
    />
  ) : active ? (
    <div className="chart-area" data-replay-state={history.loading ? "history-loading" : "empty"}>
      <div className="error-overlay"><div className="error-message">
        {history.loading ? <span role="status">{t("replay.loadingOlder")}</span>
          : history.error ? <>
            <span role="alert">{history.error}</span>
            <button type="button" onClick={() => { void history.retryHistory(); }}>{t("replay.retry")}</button>
          </> : <><strong>{t("replay.shell.noBar")}</strong><br />{t("replay.shell.noBarHint")}</>}
      </div></div>
    </div>
  ) : <ReplayStatePanel runtime={runtime} />;

  const drawingToolbar = review !== null ? (
    <div className="drawing-toolbar replay-chart-toolbar" aria-label={t("replay.shell.reviewTools")}>
      <span>{t("replay.kicker.reviewReadOnly")}</span>
      <span>{t("replay.kicker.closedPrefix")}</span>
      <span>{t("replay.shell.drawingRevValue", { rev: review.projection.drawing_revision })}</span>
      {reviewChartBounded && <span role="status">{t("replay.shell.historyTruncated")}</span>}
      {reviewOlderLoading && <span role="status">{t("replay.loadingOlder")}</span>}
      {reviewOlderError && <><span role="alert">{reviewOlderError}</span>
        <button type="button" onClick={() => { void loadReviewMoreLeft(); }}>{t("replay.retry")}</button></>}
    </div>
  ) : (
    <DrawingToolbar
      activeTool={drawings.view.drawingTool}
      onToolChange={drawings.actions.setDrawingTool}
      penColor={drawings.view.penColor}
      onPenColorChange={drawings.actions.setPenColor}
      penSize={drawings.view.penSize}
      onPenSizeChange={drawings.actions.setPenSize}
      onClearAll={drawings.actions.handleClearDrawing}
      drawingsHidden={drawings.view.drawingsHidden}
      onToggleDrawingsHidden={drawings.actions.handleToggleDrawingsHidden}
      drawingSnapEnabled={drawings.view.drawingSnapEnabled}
      drawingContinuousEnabled={drawings.view.drawingContinuousEnabled}
      drawingAutoSelectEnabled={drawings.view.drawingAutoSelectEnabled}
      onDrawingSnapEnabledChange={drawings.actions.handleDrawingSnapEnabledChange}
      onDrawingContinuousEnabledChange={drawings.actions.handleDrawingContinuousEnabledChange}
      onDrawingAutoSelectEnabledChange={drawings.actions.handleDrawingAutoSelectEnabledChange}
      textFontSize={drawings.view.textFontSize}
      onTextFontSizeChange={drawings.actions.setTextFontSize}
      textBold={drawings.view.textBold}
      onTextBoldChange={drawings.actions.setTextBold}
      textItalic={drawings.view.textItalic}
      onTextItalicChange={drawings.actions.setTextItalic}
      fibLevels={drawings.view.fibLevels}
      onFibLevelsChange={drawings.actions.handleFibLevelsChange}
      fibInverted={drawings.view.fibInverted}
      onFibInvertedChange={drawings.actions.handleFibInvertedChange}
      positionSize={drawings.view.positionSize}
      onPositionSizeChange={drawings.actions.handlePositionSizeChange}
      selectedDrawing={drawings.view.selectedDrawing}
      onSelectedDrawingStyleChange={drawings.actions.handleSelectedDrawingStyleChange}
      chartType={settings.chartType}
      onChartTypeChange={(chartType) => setSettings((current) => ({ ...current, chartType }))}
    />
  );

  const rightRail = active ? (
    review !== null ? <ReplayReviewRightRail review={review} /> : <ReplayRightMarketRail
      runtime={runtime} viewer={viewer} indicators={indicators}
      preferences={workspace.preferences} actions={workspace.actions}
      upColor={settings.upColor} downColor={settings.downColor}
      formatTime={publicTimeRuntime.formatTime}
    />
  ) : null;
  const replayIntervalSelector = (
    <IntervalSelector
      interval={displayedInterval}
      capabilityReady={review === null
        && config !== null
        && viewer.viewerState !== null
        && !viewer.viewerPending
        && intervalViewportTransfer === null
        && replayIntervalCatalog.nativeIntervals.length > 0}
      capabilityLoading={config === null
        || viewer.loading
        || viewer.viewerPending
        || intervalViewportTransfer !== null}
      nativeIntervals={replayIntervalCatalog.nativeIntervals}
      intervalGroups={replayIntervalCatalog.intervalGroups}
      customIntervalRecords={customIntervalRecords}
      savedCustomIntervals={savedCustomIntervals}
      onSelectInterval={selectReplayInterval}
      onCreateCustomInterval={createReplayCustomInterval}
      onRemoveCustomInterval={removeReplayCustomInterval}
      onRestoreCustomInterval={restoreReplayCustomInterval}
      onTogglePinCustomInterval={togglePinCustomInterval}
      onClearCustomIntervals={clearReplayCustomIntervals}
      intervalAvailability={intervalAvailability}
      unavailableIntervalMessage={unavailableIntervalMessage}
      readOnlyReason={review === null ? null : t("replay.shell.intervalReadonly")}
      intervalNotice={intervalNotice ?? {
        type: viewer.error ? "error" : "info",
        text: review === null
          ? viewer.error ?? viewer.eventStopMessage ?? `ViewerState r${viewer.viewerState?.semantic_view_revision ?? "--"} · ${publicTime}`
          : `Review ViewerState r${String(review.projection.viewer_state.semantic_view_revision ?? "--")} · ${review.events.find((event) => event.event_id === review.selected_event_id)?.public_time.label ?? "--"}`,
      }}
      variant="compact"
    />
  );
  return (
    <PageFrame
      toolbar={drawingToolbar}
      rightRail={rightRail}
      topBar={(
        <MarketTopBarFrame
          source="replay"
          className="replay-top-bar"
          navigation={<span className="replay-mode-badge">{t("replay.kicker.training")}</span>}
          identity={config && (
            <button className="replay-identity-readonly" type="button" title={t("replay.shell.identityImmutable")}>
              {review === null
                ? `${activeSelectedTrack?.exchange ?? config.exchange} · ${activeSelectedTrack?.market_type ?? config.market_type} · ${displayedSymbol} · ${t("replay.shell.accountTracks", { count: viewer.marketTracks?.tracks.length ?? 1 })} · ${t("replay.baseInterval", { interval: config.base_interval })}`
                : t("replay.reviewIdentity", {
                  symbol: String(review.projection.tracks.find((track) => (
                    track.track_id === review.projection.viewer_state.selected_track_id
                  ))?.symbol ?? config.symbol),
                  interval: String(review.projection.viewer_state.display_interval ?? interval),
                })}
            </button>
          )}
          intervals={replayIntervalSelector}
          controls={<>
            {cell?.controls}
            <button
              className={`indicator-toggle-btn ${indicatorPanelOpen ? "active" : ""}`}
              type="button"
              disabled={review !== null}
              aria-expanded={indicatorPanelOpen}
              aria-controls="replay-indicator-panel"
              aria-label={`${t("shell.indicators")} ${review === null ? indicators.status.activeIndicatorCount : "R/O"}`}
              onClick={() => setIndicatorPanelOpen((open) => !open)}
              title={review === null ? t("replay.shell.manageIndicators") : t("replay.shell.reviewBlocksIndicators")}
            >
              <span aria-hidden="true" style={{ display: "flex" }}><ProfileRailIcon /></span>
              <span className="indicator-badge">
                {review === null ? indicators.status.activeIndicatorCount : "R/O"}
              </span>
            </button>
            <button className="indicator-toggle-btn alert-toggle-btn" type="button" disabled
              aria-label={t("shell.alerts")} title={capabilities.ALERTS.state}>
              <span aria-hidden="true" style={{ display: "flex" }}><AlertRailIcon /></span>
            </button>
          </>}
          quote={last && (
            <div className="price-info"><span className={`current-price ${isUp ? "price-up" : "price-down"}`}>{last.close}</span><span className="price-change">{isUp ? "▲" : "▼"} {t("replay.priceLabel")}</span></div>
          )}
          marketMetrics={(
            <div className="advanced-market-summary advanced-market-summary-unsupported" aria-label={t("replay.derivativesAria")}>
              {(["MARK_PRICE", "INDEX_PRICE", "BASIS"] as const).map((id) => (
                <div className="advanced-market-chip" key={id} data-market-metric={id.toLowerCase()} data-capability-state={capabilities[id].state}>
                  <span className="advanced-market-chip-label">{capabilities[id].label}</span>
                  <span className="advanced-market-chip-value">--</span>
                  <span className="advanced-market-chip-suffix">{capabilities[id].state}</span>
                </div>
              ))}
            </div>
          )}
          trailing={<>
            {active && (
              <button
                ref={integrityToggleRef}
                className="replay-integrity-toggle ui-control"
                type="button"
                data-replay-action="toggle-integrity"
                data-review-active={review === null ? "false" : "true"}
                aria-controls="replay-integrity-drawer"
                aria-expanded={integrityOpen}
                onClick={() => {
                  setTrainingResultsOpen(false);
                  setIntegrityOpen((open) => !open);
                }}
              >
                {review === null ? t("replay.shell.integrity") : t("replay.shell.reviewing")}
              </button>
            )}
            {active && integrityRuntime.runId !== null && (
              <button
                className="replay-integrity-toggle ui-control"
                type="button"
                data-replay-action="toggle-training-results"
                aria-controls="replay-training-results-drawer"
                aria-expanded={trainingResultsOpen}
                onClick={() => {
                  setIntegrityOpen(false);
                  setTrainingResultsOpen((open) => !open);
                }}
              >{t("replay.shell.results")}</button>
            )}
            {active && viewer.viewerState?.run_id !== undefined && <button className="replay-return-hub ui-control" type="button" disabled={returningToHub || review !== null} title={review !== null ? t("replay.shell.exitReviewFirst") : returnToHubError ?? t("replay.shell.returnHubHint")} onClick={() => void returnToHub()}>{returningToHub ? t("replay.shell.saving") : t("replay.shell.hub")}</button>}
            <a className="replay-live-link ui-control" href="/" target="_blank" rel="noopener noreferrer">{t("replay.shell.liveLink")}</a>
          </>}
        />
      )}
      intervalSelector={null}
      workspace={cell ? chart : (
        <MarketChartWorkspace
          toolbar={drawingToolbar}
          exportOverlay={null}
          chart={chart}
          rightRail={rightRail}
        />
      )}
      featureSurfaces={active ? <>
        {review === null && history.notice !== null && (
          <div className="replay-history-boundary-notice" role="status">
            <span>{history.notice}</span>
            <button type="button" onClick={history.dismissNotice} aria-label={t("replay.shell.dismissHistory")}><Icon name="close" size={14} /></button>
          </div>
        )}
        {review === null && <ReplayBottomControlDock runtime={runtime} viewer={cell?.controlViewer ?? viewer} publicTimeLabel={publicTime} independentCharts={cell !== undefined} />}
        {review === null && indicatorPanelOpen && (
          <div id="replay-indicator-panel" className="replay-shared-indicator-panel">
            <IndicatorPanel
              allowedScriptLanguages={["pyne", "pine", "frontend-js"]}
              allowedSecurityModes={["safe"]}
              isOpen
              onClose={() => setIndicatorPanelOpen(false)}
              activeIndicators={indicators.view.activeIndicators}
              paramSchemas={indicators.view.paramSchemas}
              onAddIndicator={indicators.actions.addIndicator}
              onRemoveIndicator={indicators.actions.removeIndicator}
              onToggleVisibility={indicators.actions.toggleVisibility}
              onUpdateParams={indicators.actions.updateIndicatorParams}
              onUpdateScript={indicators.actions.updateIndicatorScript}
              computing={indicators.status.computing}
              realtimeMode={null}
              onRecompute={indicators.actions.recompute}
              marketStudies={indicators.marketStudies}
              onAddMarketStudy={indicators.marketStudyActions.add}
              onRemoveMarketStudy={indicators.marketStudyActions.remove}
              onToggleMarketStudyVisibility={
                indicators.marketStudyActions.toggleVisibility
              }
              modeNotice={{
                label: t("replay.indicators.revealedPrefix"),
                description: t("replay.indicators.revealedPrefixHint"),
              }}
              resolveIndicatorSupport={providedBarsIndicatorSupport}
            />
          </div>
        )}
        {integrityOpen && (
          <aside
            ref={integrityDrawerRef}
            id="replay-integrity-drawer"
            className="replay-integrity-drawer"
            aria-label={t("replay.shell.integrity")}
            tabIndex={-1}
          >
            <ReplayIntegrityReviewPanel
              runtime={runtime}
              integrityRuntime={integrityRuntime}
              trainingState={effectiveState}
              onClose={() => setIntegrityOpen(false)}
            />
          </aside>
        )}
        {trainingResultsOpen && integrityRuntime.runId !== null && (
          <aside
            id="replay-training-results-drawer"
            className="replay-integrity-drawer replay-training-results-drawer"
            aria-label={t("replay.shell.results")}
            tabIndex={-1}
          >
            <ReplayTrainingResultsPanel
              runId={integrityRuntime.runId}
              integrityRuntime={integrityRuntime}
              trainingState={effectiveState}
              onClose={() => setTrainingResultsOpen(false)}
            />
          </aside>
        )}
      </> : null}
      statusBar={(
        <MarketStatusBar
          source="replay"
          className="replay-status-bar"
          connectionStatus={runtime.store.connectionState}
          dataAttributes={{
            "data-replay-generation": runtime.store.generation,
            "data-replay-session-state": review === null ? effectiveState ?? "" : "REVIEW",
            "data-replay-adapter-state": review === null ? runtime.store.state ?? "" : review.playback_state,
            "data-replay-source-sequence": review?.projection.cursor.source_sequence ?? runtime.store.sourceSequence,
            "data-replay-revision": runtime.store.revision,
            "data-replay-state-hash": review?.selected_state_hash ?? runtime.store.stateHash ?? "",
            "data-replay-cursor-ms": review?.projection.cursor.virtual_time_ms ?? runtime.store.virtualTimeMs ?? "",
            "data-replay-max-bar-ms": viewerLast?.time === undefined ? "" : Number(viewerLast.time) * 1_000,
            "data-replay-source-bar-count": runtime.replayStore.seriesStore.barCount,
            "data-replay-source-series-version": runtime.replayStore.seriesStore.version,
            "data-replay-source-series-key": runtime.replayStore.seriesStore.seriesKey ?? "",
            "data-replay-viewer-bar-count": viewer.seriesStore.barCount,
            "data-replay-viewer-series-version": viewer.seriesStore.version,
            "data-replay-viewer-series-key": viewer.seriesStore.seriesKey ?? "",
            "data-replay-viewer-error": viewer.error ?? "",
            "data-replay-viewer-loading": String(viewer.loading),
            "data-replay-viewer-state-ready": String(viewer.viewerState !== null),
            "data-replay-base-interval": config?.base_interval ?? "",
            "data-replay-source-interval-seconds": runtime.replayStore.seriesStore.intervalSeconds ?? "",
            "data-replay-last-bar-closed": String(viewerLast?.replayClosed ?? ""),
            "data-replay-order-count": review?.projection.orders.length ?? runtime.store.orders.length,
            "data-replay-fill-count": review?.projection.fills.length ?? runtime.store.fills.length,
            "data-replay-revealed": String(runtime.store.revealed),
            "data-replay-history-epoch": history.historyEpoch ?? "",
            "data-replay-history-right-truncated": String(
              review === null
                ? viewer.seriesStore.rightTruncated
                : displayedSeriesStore.rightTruncated,
            ),
            "data-replay-history-can-restore-latest": String(history.canRestoreLatestWindow),
            "data-replay-view-interval": displayedInterval,
            "data-replay-view-revision": review === null
              ? viewer.viewerState?.semantic_view_revision ?? ""
              : String(review.projection.viewer_state.semantic_view_revision ?? ""),
            "data-replay-clock-basis": review === null ? globalClock?.basis ?? "" : "",
            "data-replay-clock-rate": review === null ? globalClock?.rate ?? "" : "",
            "data-replay-control-pending": review === null
              ? viewer.controlPending?.type ?? ""
              : "",
            "data-replay-integrity-operation": integrityRuntime.operation ?? "",
            "data-replay-time-disclosure-policy": integrityRuntime.integrity?.effective_time_disclosure_policy ?? "",
            "data-replay-result-label": integrityRuntime.integrity?.result_label ?? "",
            "data-replay-public-time-projections": publicTimeRuntime.projectedCount,
            "data-replay-public-time-state": publicTimeRuntime.error === null
              ? (publicTimeRuntime.loading ? "loading" : "ready")
              : "relative-fallback",
            "data-replay-review-read-only": integrityRuntime.review?.read_only === true ? "true" : "false",
            "data-replay-review-timeline-sequence": review?.selected_timeline_sequence ?? "",
            "data-replay-review-chart-fidelity": review === null ? "" : "CLOSED_PREFIX_ONLY",
            "data-replay-review-original-verified": review?.immutability_proof.verified === true ? "true" : "",
          }}
          left={<>
            <span><span className={`status-dot ${runtime.store.connectionState === "connected" ? "connected" : "loading"}`} />{t("replay.shell.status")}</span>
            <span>{review === null ? effectiveState ?? runtime.phase : `REVIEW ${review.playback_state}`}</span>
            <span>{t("replay.displayBars", { count: viewerBarCount })}</span>
            {review === null && history.loading && <span>{t("replay.loadingOlder")}</span>}
            {review === null && history.historyEpoch !== null && !history.hasMore && !history.loading && !history.error && <span>{t("replay.shell.historyStart")}</span>}
            {review === null && history.error && <>
              <span className="replay-history-error">{history.error}</span>
              <button type="button" disabled={history.loading} onClick={() => { void history.retryHistory(); }}>{t("replay.retry")}</button>
            </>}
            {review !== null && <span>{t("replay.immutableEvent", { sequence: review.selected_timeline_sequence })}</span>}
            {review !== null && reviewChartBounded && <span>{t("replay.prefixBound")}</span>}
          </>}
          right={<>
            <span>{review === null ? t("replay.shell.controller", { who: ownsController ? t("replay.shell.controllerHere") : runtime.store.controllerClientId ? t("replay.shell.controllerOther") : t("replay.shell.controllerNone") }) : t("replay.originalControllerIsolated")}</span>
            <span>{config?.source_kind.toUpperCase() ?? "BAR"} · {config?.quality_mode.toUpperCase() ?? "EXACT"}</span>
            <span>{t("replay.shell.isolated")}</span>
          </>}
        />
      )}
    />
  );
}
