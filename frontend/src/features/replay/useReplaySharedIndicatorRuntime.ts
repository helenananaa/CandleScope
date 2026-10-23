import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useReplayCanonicalIndicatorCompute } from "./useReplayCanonicalIndicatorCompute.js";
import { replayIndicatorPresentation } from "./replayIndicatorPresentation.js";
import { replayIndicatorCalculationKey } from "./replayCanonicalIndicators.js";

import {
  createActiveIndicatorPersistence,
} from "../indicators/activeIndicatorStore.js";
import type {
  IndicatorStorageLike,
  ActiveIndicatorPersistence,
} from "../indicators/activeIndicatorStore.js";
import type {
  IndicatorPanelMarketStudy,
} from "../indicators/IndicatorPanel.js";
import {
  createKlineOrderFlowProjectionMemo,
  resolveKlineOrderFlow,
} from "../indicators/klineOrderFlowProjection.js";
import {
  KLINE_ORDER_FLOW_INDICATOR_DEFINITIONS,
} from "../indicators/klineOrderFlowStudy.js";
import type {
  KlineOrderFlowIndicatorId,
  KlineOrderFlowIndicatorKey,
} from "../indicators/klineOrderFlowStudy.js";
import type {
  IndicatorRuntime,
} from "../indicators/indicatorRuntimeContract.js";
import {
  useProvidedBarsIndicatorRuntime,
} from "../indicators/useProvidedBarsIndicatorRuntime.js";
import type {
  KlineBar,
} from "../market-data/marketDataTypes.js";
import type { WindowDelta } from "../market-data/klineContracts.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type {
  ReplayRuntime,
} from "./useReplayRuntime.js";
import type {
  ReplayViewerRuntime,
} from "./useReplayViewerRuntime.js";
import {
  replayIndicatorStorageKey,
  replayOrderFlowStorageKey,
} from "./replaySharedIndicatorPreferences.js";
export {
  clearReplaySharedIndicatorPreferences,
  replayIndicatorStorageKey,
  replayOrderFlowStorageKey,
} from "./replaySharedIndicatorPreferences.js";
const DISABLED_CAPABILITIES = Object.freeze([
  "hosted-range",
  "indicator-websocket",
  "unsafe-script",
] as const);
export const REPLAY_INDICATOR_PLAYING_REFRESH_MS = 500;

interface ReplaySeriesProjectionRevision {
  readonly version: number;
  readonly structureRevision: number;
}

function requiresFullOrderFlowProjection(delta: WindowDelta): boolean {
  return delta.type !== "tick"
    || delta.appended === true
    || Number(delta.trimmedLeft || 0) !== 0
    || Number(delta.trimmedRight || 0) !== 0;
}

function createReplaySeriesProjectionRevisionSource(
  seriesStore: ReplayViewerRuntime["seriesStore"],
): {
  getSnapshot(): ReplaySeriesProjectionRevision;
  subscribe(listener: () => void): () => void;
} {
  let snapshot: ReplaySeriesProjectionRevision = Object.freeze({
    version: Number(seriesStore.version),
    structureRevision: 0,
  });
  return {
    getSnapshot: () => {
      const version = Number(seriesStore.version);
      if (version !== snapshot.version) {
        snapshot = Object.freeze({
          version,
          structureRevision: snapshot.structureRevision + 1,
        });
      }
      return snapshot;
    },
    subscribe: (listener) => seriesStore.subscribe((delta) => {
      snapshot = Object.freeze({
        version: Number(seriesStore.version),
        structureRevision: snapshot.structureRevision
          + (requiresFullOrderFlowProjection(delta) ? 1 : 0),
      });
      listener();
    }),
  };
}

interface ReplayOrderFlowPreferences {
  cvd: {
    added: boolean;
    visible: boolean;
  };
  delta: {
    added: boolean;
    visible: boolean;
  };
}

export interface ReplaySharedIndicatorRuntime {
  readonly view: IndicatorRuntime["view"];
  readonly actions: IndicatorRuntime["actions"];
  readonly status: IndicatorRuntime["status"] & {
    preparationText: string | null;
    readonly mode: "provided_bars_replay_safe";
    readonly sourceBarCount: number;
    readonly latestSourceTimeMs: number | null;
    readonly activeIndicatorCount: number;
    readonly visibleIndicatorCount: number;
    readonly orderFlowBarCount: number;
    readonly disabledCapabilities: typeof DISABLED_CAPABILITIES;
  };
  readonly marketStudies: readonly IndicatorPanelMarketStudy[];
  readonly marketStudyActions: {
    add(studyId: string): void;
    remove(studyId: string): void;
    toggleVisibility(studyId: string): void;
  };
}

function browserStorage(): IndicatorStorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

function emptyOrderFlowPreferences(): ReplayOrderFlowPreferences {
  return {
    cvd: { added: false, visible: true },
    delta: { added: false, visible: true },
  };
}

function isPreference(value: unknown): value is {
  added: boolean;
  visible: boolean;
} {
  return Boolean(value)
    && typeof value === "object"
    && !Array.isArray(value)
    && typeof (value as Record<string, unknown>).added === "boolean"
    && typeof (value as Record<string, unknown>).visible === "boolean";
}

export function loadReplayOrderFlowPreferences(
  runScope: string,
  storage: IndicatorStorageLike | null = browserStorage(),
): ReplayOrderFlowPreferences {
  if (!storage) return emptyOrderFlowPreferences();
  try {
    const parsed: unknown = JSON.parse(
      storage.getItem(replayOrderFlowStorageKey(runScope)) || "null",
    );
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return emptyOrderFlowPreferences();
    }
    const record = parsed as Record<string, unknown>;
    return {
      cvd: isPreference(record.cvd)
        ? { added: record.cvd.added, visible: record.cvd.visible }
        : { added: false, visible: true },
      delta: isPreference(record.delta)
        ? { added: record.delta.added, visible: record.delta.visible }
        : { added: false, visible: true },
    };
  } catch {
    return emptyOrderFlowPreferences();
  }
}

export function saveReplayOrderFlowPreferences(
  runScope: string,
  preferences: ReplayOrderFlowPreferences,
  storage: IndicatorStorageLike | null = browserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(
      replayOrderFlowStorageKey(runScope),
      JSON.stringify(preferences),
    );
  } catch {
    // View preferences are best effort and never alter replay evidence.
  }
}

function replayBarFinality(bar: KlineBar): boolean | null {
  const replayClosed = typeof bar.replayClosed === "boolean"
    ? bar.replayClosed
    : null;
  const transportClosed = typeof bar.is_closed === "boolean"
    ? bar.is_closed
    : null;
  if (replayClosed !== null && transportClosed !== null) {
    return replayClosed === transportClosed ? replayClosed : null;
  }
  if (replayClosed !== null) return replayClosed;
  if (transportClosed !== null) return transportClosed;
  return null;
}

/**
 * Pine and the replay-safe shared runtime consume an authoritative closed
 * prefix plus, at most, the single forming bar at the revealed right edge.
 * The forming bar is built only from base rows already revealed by the replay
 * cursor. Unknown or contradictory finality still fails closed.
 */
export function excludeIncompleteReplayHistory(rows: readonly KlineBar[], cursorMs: number | null): KlineBar[] {
  return rows.filter(row => !(cursorMs !== null && replayBarFinality(row) === false
    && typeof row.replayCloseTimeMs === "number" && row.replayCloseTimeMs < cursorMs
    && Number.isSafeInteger(row.replayComponentCount) && Number(row.replayComponentCount) > 0
    && Number.isSafeInteger(row.replayExpectedComponents)
    && Number(row.replayComponentCount) < Number(row.replayExpectedComponents)));
}

export function selectRevealedIndicatorBars(
  rows: readonly KlineBar[],
  cursorMs: number | null,
): KlineBar[] {
  if (cursorMs === null || !Number.isFinite(cursorMs)) return [];
  const prefix: KlineBar[] = [];
  let previousTime = -Infinity;
  let previousCloseTimeMs: number | null = null;
  for (const [index, bar] of rows.entries()) {
    const time = Number(bar.time);
    const openTimeMs = time * 1_000;
    const closeTimeMs = typeof bar.replayCloseTimeMs === "number"
      ? bar.replayCloseTimeMs
      : Number.NaN;
    const lastBaseOpenMs = typeof bar.replayLastBaseOpenMs === "number"
      ? bar.replayLastBaseOpenMs
      : Number.NaN;
    const finality = replayBarFinality(bar);
    if (
      !Number.isFinite(time)
      || time <= previousTime
      || !Number.isFinite(openTimeMs)
      || openTimeMs > cursorMs
      || !Number.isFinite(closeTimeMs)
      || closeTimeMs < openTimeMs
      || !Number.isFinite(lastBaseOpenMs)
      || lastBaseOpenMs < openTimeMs
      || lastBaseOpenMs > closeTimeMs
      || lastBaseOpenMs > cursorMs
      || finality === null
    ) {
      break;
    }
    if (finality) {
      if (closeTimeMs > cursorMs) break;
    } else if (index !== rows.length - 1 || closeTimeMs < cursorMs) {
      // closeTimeMs is inclusive. Exact tape can stop inside a same-ms
      // cohort at that final millisecond, so the builder may legitimately
      // retain a forming tail there. Keep its revealed values and finality;
      // do not drop it on restore or claim the remaining cohort is closed.
      break;
    }
    if (
      previousCloseTimeMs !== null
      && openTimeMs !== previousCloseTimeMs + 1
    ) {
      // Indicators are stateful. A declared exchange/source gap starts a new
      // calculation segment; carrying EMA/RSI/Pine state across it would be a
      // fabricated observation even though the chart correctly leaves a hole.
      prefix.length = 0;
    }
    prefix.push(bar);
    previousTime = time;
    previousCloseTimeMs = closeTimeMs;
  }
  return prefix;
}

function hasOrderFlow(bar: KlineBar): boolean {
  return resolveKlineOrderFlow(bar) !== null;
}

function orderFlowKey(
  studyId: string,
): KlineOrderFlowIndicatorKey | null {
  if (studyId === "trade-flow:cvd") return "cvd";
  if (studyId === "trade-flow:delta") return "delta";
  return null;
}

export function useReplaySharedIndicatorRuntime(
  runtime: ReplayRuntime,
  viewer: ReplayViewerRuntime,
  runScope: string,
  cellPersistence?: ActiveIndicatorPersistence,
): ReplaySharedIndicatorRuntime {
  const locale = useLocale();
  const seriesStore = viewer.seriesStore;
  const seriesRevisionSource = useMemo(
    () => createReplaySeriesProjectionRevisionSource(seriesStore),
    [seriesStore],
  );
  const seriesProjectionRevision = useSyncExternalStore(
    seriesRevisionSource.subscribe,
    seriesRevisionSource.getSnapshot,
    seriesRevisionSource.getSnapshot,
  );
  const seriesRevision = seriesProjectionRevision.version;
  const seriesStructureRevision = seriesProjectionRevision.structureRevision;
  const tapeObservation = viewer.tapeObservation;
  const cursorMs = tapeObservation === undefined ? runtime.store.virtualTimeMs : tapeObservation?.virtualTimeMs ?? null;
  const sourceSequence = tapeObservation === undefined ? runtime.store.sourceSequence : tapeObservation?.sourceSequence ?? 0;
  const historyEpoch = tapeObservation?.historyEpoch;
  const playing = runtime.store.state === "PLAYING";
  // Capture input rows with this exact displayed observation. A delayed
  // calculation must never read a newer mutable window using an older cursor.
  const currentIndicatorBars = useMemo(() => {
    void seriesRevision;
    void sourceSequence;
    return selectRevealedIndicatorBars(excludeIncompleteReplayHistory(seriesStore.snapshot(), cursorMs), cursorMs);
  }, [cursorMs, seriesRevision, seriesStore, sourceSequence]);
  const latestIndicatorBoundaryRef = useRef({
    revision: seriesRevision,
    structureRevision: seriesStructureRevision,
    cursorMs,
    sourceSequence,
    historyEpoch,
    bars: currentIndicatorBars,
  });
  const [sampledIndicatorBoundary, setSampledIndicatorBoundary] = useState({
    revision: seriesRevision,
    structureRevision: seriesStructureRevision,
    cursorMs,
    sourceSequence,
    historyEpoch,
    bars: currentIndicatorBars,
  });
  const indicatorRefreshTimerRef = useRef<ReturnType<typeof globalThis.setTimeout> | null>(null);
  const canonicalPreparingRef = useRef(false);
  const wasPlayingRef = useRef(false);
  useEffect(() => {
    latestIndicatorBoundaryRef.current = {
      revision: seriesRevision,
      structureRevision: seriesStructureRevision,
      cursorMs,
      sourceSequence,
      historyEpoch,
      bars: currentIndicatorBars,
    };
    if (!playing) {
      wasPlayingRef.current = false;
      if (indicatorRefreshTimerRef.current !== null) {
        globalThis.clearTimeout(indicatorRefreshTimerRef.current);
        indicatorRefreshTimerRef.current = null;
      }
      return;
    }
    if (!wasPlayingRef.current) {
      wasPlayingRef.current = true;
      setSampledIndicatorBoundary(latestIndicatorBoundaryRef.current);
    }
    setSampledIndicatorBoundary(current => (
      current.historyEpoch !== historyEpoch || (current.cursorMs === null && cursorMs !== null)
        || (current.cursorMs !== null && (cursorMs === null || current.cursorMs > cursorMs))
        || current.sourceSequence > sourceSequence
        ? latestIndicatorBoundaryRef.current : current
    ));
    if (indicatorRefreshTimerRef.current !== null) return;
    indicatorRefreshTimerRef.current = globalThis.setTimeout(() => {
      indicatorRefreshTimerRef.current = null;
      // Finish the selected initial seed even when forward display samples
      // arrive faster than its history preparation. Rewinds/scope changes
      // still invalidate the compute controller through their normal keys.
      if (canonicalPreparingRef.current) return;
      const latest = latestIndicatorBoundaryRef.current;
      setSampledIndicatorBoundary((current) => (
        current.revision === latest.revision && current.cursorMs === latest.cursorMs && current.sourceSequence === latest.sourceSequence
          && current.historyEpoch === latest.historyEpoch
          ? current
          : latest
      ));
    }, REPLAY_INDICATOR_PLAYING_REFRESH_MS);
  }, [cursorMs, sourceSequence, historyEpoch, playing, seriesRevision, seriesStructureRevision, currentIndicatorBars]);
  useEffect(() => () => {
    if (indicatorRefreshTimerRef.current !== null) {
      globalThis.clearTimeout(indicatorRefreshTimerRef.current);
      indicatorRefreshTimerRef.current = null;
    }
  }, []);
  // Paused/review navigation always uses the exact current boundary in the
  // same render. During forward playback a trailing sample may be older, but
  // can never contain data newer than the authoritative replay cursor.
  const usePlaybackSample = playing && wasPlayingRef.current && cursorMs !== null
    && sampledIndicatorBoundary.cursorMs !== null && sampledIndicatorBoundary.cursorMs <= cursorMs
    && sampledIndicatorBoundary.sourceSequence <= sourceSequence && sampledIndicatorBoundary.historyEpoch === historyEpoch;
  const indicatorRevision = usePlaybackSample
    ? sampledIndicatorBoundary.revision
    : seriesRevision;
  const indicatorStructureRevision = usePlaybackSample
    ? sampledIndicatorBoundary.structureRevision
    : seriesStructureRevision;
  const indicatorCursorMs = usePlaybackSample
    ? sampledIndicatorBoundary.cursorMs
    : cursorMs;
  const indicatorSourceSequence = usePlaybackSample ? sampledIndicatorBoundary.sourceSequence : sourceSequence;
  const indicatorHistoryEpoch = usePlaybackSample ? sampledIndicatorBoundary.historyEpoch : historyEpoch;
  const indicatorBars = usePlaybackSample ? sampledIndicatorBoundary.bars : currentIndicatorBars;
  const selectedTrackId = viewer.viewerState?.selected_track_id ?? null;
  const selectedTrack = viewer.marketTracks?.tracks.find(
    (track) => track.track_id === selectedTrackId,
  ) ?? null;
  const config = runtime.store.sessionConfig;
  const exchange = selectedTrack?.exchange ?? config?.exchange ?? "binance";
  const marketType = selectedTrack?.market_type ?? config?.market_type ?? "spot";
  const symbol = selectedTrack?.symbol ?? config?.symbol ?? "UNKNOWN";
  const interval = viewer.viewerState?.display_interval
    ?? config?.base_interval
    ?? "1m";
  // ReplayApp keys the shared indicator surface by this scope. A session-to-run
  // identity transition therefore remounts the stores instead of saving the
  // previous scope's state into the newly discovered Run.
  const resolvedRunScope = runScope;
  const sourceScopeKey = [
    resolvedRunScope,
    selectedTrackId ?? "unselected",
    String(seriesStore.seriesKey ?? "uninitialized"),
    interval,
  ].join("|");
  const persistence = useMemo(
    () => createActiveIndicatorPersistence(
      replayIndicatorStorageKey(resolvedRunScope),
    ),
    [resolvedRunScope],
  );
  const first = indicatorBars.at(0);
  const last = indicatorBars.at(-1);
  const chartDataMeta = useMemo(() => ({
    ...runtime.marketData.view.meta,
    version: indicatorRevision,
    status: "ready" as const,
    source: "replay-indicator-revealed-prefix",
    seriesKey: seriesStore.seriesKey,
    interval,
    bars: indicatorBars.length,
    firstTime: first?.time ?? null,
    lastTime: last?.time ?? null,
  }), [
    indicatorBars.length,
    first?.time,
    interval,
    last?.time,
    runtime.marketData.view.meta,
    seriesStore.seriesKey,
    indicatorRevision,
  ]);
  const canonical = useReplayCanonicalIndicatorCompute(sourceScopeKey, seriesStore,
    config && runtime.store.sessionId && runtime.store.dataEpoch && selectedTrackId && indicatorCursorMs !== null ? {
      sessionId: runtime.store.sessionId, trackId: selectedTrackId, dataEpoch: runtime.store.dataEpoch,
      revealedBoundaryMs: indicatorCursorMs, sourceSequence: indicatorSourceSequence,
      ...(indicatorHistoryEpoch === undefined ? {} : { historyEpoch: indicatorHistoryEpoch }),
      ...(tapeObservation === undefined ? {} : { sourceBars: indicatorBars }),
      identity: { exchange, market_type: marketType, symbol,
        source_kind: config.source_kind === "agg_trade" ? "AGG_TRADE" : "BAR",
        base_interval: config.base_interval, display_interval: interval },
    } : null);
  canonicalPreparingRef.current = tapeObservation !== undefined && canonical.preparation.active > 0;
  useEffect(() => {
    if (playing && !canonical.preparation.active) {
      setSampledIndicatorBoundary(current => current === latestIndicatorBoundaryRef.current
        ? current : latestIndicatorBoundaryRef.current);
    }
  }, [canonical.preparation.active, playing]);
  const computeBatch = canonical.compute;
  const canonicalScopeKey = `${sourceScopeKey}|${canonical.sourceKey}`;
  const outputBarTimes = useMemo(() => indicatorBars.map(bar => bar.time), [indicatorBars]);
  const providedBars = useProvidedBarsIndicatorRuntime({
    visibleRangePriority: true,
    computeBatch,
    bars: indicatorBars,
    outputBarTimes,
    chartDataMeta,
    datasetKey: replayIndicatorCalculationKey(canonicalScopeKey, indicatorRevision,
      indicatorSourceSequence, indicatorCursorMs),
    exchange,
    interval,
    marketType,
    persistence: cellPersistence ?? persistence,
    seriesReady: indicatorRevision,
    sourceOrdinal: indicatorCursorMs ?? -1,
    sourceScopeKey: canonicalScopeKey,
    symbol,
    visibleThroughSeconds: indicatorCursorMs === null
      ? null
      : Math.floor(indicatorCursorMs / 1_000),
  });

  const [orderFlowPreferences, setOrderFlowPreferences] =
    useState<ReplayOrderFlowPreferences>(
      () => loadReplayOrderFlowPreferences(resolvedRunScope),
    );
  useEffect(() => {
    saveReplayOrderFlowPreferences(resolvedRunScope, orderFlowPreferences);
  }, [orderFlowPreferences, resolvedRunScope]);
  const orderFlowProjection = useMemo(
    () => {
      void sourceScopeKey;
      return createKlineOrderFlowProjectionMemo();
    },
    [sourceScopeKey],
  );
  const orderFlowEnabled = orderFlowPreferences.cvd.added
    || orderFlowPreferences.delta.added;
  const projectedOrderFlowPanes = useMemo(() => orderFlowProjection.project({
    bars: indicatorBars,
    enabled: orderFlowEnabled,
    forceFull: false,
    interval,
    intervalSeconds: seriesStore.intervalSeconds,
    structureRevision: indicatorStructureRevision,
  }), [
    indicatorBars,
    interval,
    orderFlowEnabled,
    orderFlowProjection,
    indicatorStructureRevision,
    seriesStore.intervalSeconds,
  ]);
  const visibleOrderFlowPanes = useMemo(() => (
    projectedOrderFlowPanes.filter((pane) => (
      (pane.id === "trade-flow-cvd"
        && orderFlowPreferences.cvd.added
        && orderFlowPreferences.cvd.visible)
      || (pane.id === "trade-flow-delta"
        && orderFlowPreferences.delta.added
        && orderFlowPreferences.delta.visible)
    ))
  ), [orderFlowPreferences, projectedOrderFlowPanes]);
  const orderFlowBarCount = indicatorBars.filter(hasOrderFlow).length;
  const orderFlowSupported = orderFlowBarCount > 0;

  const updateOrderFlow = useCallback((
    studyId: string,
    update: (
      current: ReplayOrderFlowPreferences[KlineOrderFlowIndicatorKey],
    ) => ReplayOrderFlowPreferences[KlineOrderFlowIndicatorKey],
  ) => {
    const key = orderFlowKey(studyId);
    if (key === null) return;
    setOrderFlowPreferences((current) => ({
      ...current,
      [key]: update(current[key]),
    }));
  }, []);
  const marketStudyActions = useMemo(() => ({
    add: (studyId: string) => updateOrderFlow(studyId, (current) => ({
      ...current,
      added: true,
      visible: true,
    })),
    remove: (studyId: string) => updateOrderFlow(studyId, (current) => ({
      ...current,
      added: false,
    })),
    toggleVisibility: (studyId: string) => updateOrderFlow(
      studyId,
      (current) => ({ ...current, visible: !current.visible }),
    ),
  }), [updateOrderFlow]);
  const marketStudies = useMemo<IndicatorPanelMarketStudy[]>(() => (
    KLINE_ORDER_FLOW_INDICATOR_DEFINITIONS.map((definition) => {
      const preference = orderFlowPreferences[definition.key];
      return {
        ...definition,
        name: t(definition.nameKey, {}, locale),
        description: t(definition.descriptionKey, {}, locale),
        added: preference.added,
        visible: preference.visible,
        supported: orderFlowSupported,
        unsupportedReason: orderFlowSupported
          ? null
          : t("replay.rt.noTaker", {}, locale),
        status: !orderFlowSupported
          ? "dormant"
          : preference.added && preference.visible
            ? "ready"
            : preference.added
              ? "dormant"
              : "idle",
        statusText: orderFlowSupported
          ? t("replay.rt.sharedFlow", {}, locale)
          : null,
        error: null,
      };
    })
  ), [locale, orderFlowPreferences, orderFlowSupported]);
  const presentation = useMemo(() => {
    void locale;
    return replayIndicatorPresentation(providedBars.view, canonical.preparation, providedBars.status.computing);
  }, [providedBars.view, providedBars.status.computing, canonical.preparation, locale]);
  const view = useMemo(() => ({
    ...presentation.view,
    subPanes: [...presentation.view.subPanes, ...visibleOrderFlowPanes],
  }), [presentation.view, visibleOrderFlowPanes]);
  const addedOrderFlowCount = Number(orderFlowPreferences.cvd.added)
    + Number(orderFlowPreferences.delta.added);
  const visibleOrderFlowCount = Number(
    orderFlowPreferences.cvd.added && orderFlowPreferences.cvd.visible,
  ) + Number(
    orderFlowPreferences.delta.added && orderFlowPreferences.delta.visible,
  );

  return {
    view,
    actions: providedBars.actions,
    status: {
      ...providedBars.status,
      computing: providedBars.status.computing || canonical.preparation.active > 0,
      preparationText: presentation.statusText,
      mode: "provided_bars_replay_safe",
      sourceBarCount: indicatorBars.length,
      latestSourceTimeMs: last === undefined ? null : Number(last.time) * 1_000,
      activeIndicatorCount:
        providedBars.view.activeIndicators.length + addedOrderFlowCount,
      visibleIndicatorCount: providedBars.view.activeIndicators.filter(
        (indicator) => indicator.visible !== false,
      ).length + visibleOrderFlowCount,
      orderFlowBarCount,
      disabledCapabilities: DISABLED_CAPABILITIES,
    },
    marketStudies,
    marketStudyActions,
  };
}
