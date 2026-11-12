import ChartAccountOverlayMenu from "../features/trading-accounts/ChartAccountOverlayMenu.js";
import type { ChartAccountOverlaySettings } from "../features/chart-workspace/chartAccountOverlaySettings.js";
import { useChartTimeNavigation } from "../features/market-data/useChartTimeNavigation.js";
import { useHistoryStudy } from "../features/history-study/useHistoryStudy.js";
import { historyStudyOwner } from "../features/history-study/historyStudyOwner.js";
import "../features/history-study/historyStudy.css";
import { applicationSettingsPatch, nextCellChartSettings } from "../features/chart-workspace/chartWorkspaceChartSettings.js";
import { useCellChartTheme } from "../features/settings/chartAppearanceSettings.js";
import { ChartIntervalUnavailable } from "./ChartIntervalUnavailable.js";
import { resolveStrategyTesterMode } from "../features/backtest/chart-tester/chartStrategyMode.js";
import type { NativeStrategyCollection } from "../features/backtest/native/nativeStrategyCollection.js";
import { useIndicatorHistoryPreparation } from "../features/market-data/useIndicatorHistoryPreparation.js";
import { formatIntervalLabel, parseIntervalSeconds } from "../utils/intervals.js";
import { strategyTradeRange, type StrategyTradeFocus } from "../features/backtest/chart-tester/strategyTradeReview.js";
import React, {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type Dispatch,
  type CSSProperties,
  type ReactNode,
  type RefObject,
  type SetStateAction,
} from "react";
import { createPortal } from "react-dom";
import { captureChartPng } from "../features/trading-accounts/chartCapture.js";
import { useChartQuickReplay } from "./useChartQuickReplay.js";
import type { QuickReplayChange, UpdateChartQuickReplay } from "../features/chart-workspace/chartQuickReplayState.js";
import type { QuickReplayRequest } from "../features/trading-accounts/tradingTypes.js";
import { useTradingChartOverlay } from "../features/trading-accounts/useTradingChartOverlay.js";
import type { TradingRailBinding } from "./RightMarketRail.js";
import "../features/backtest/chart-tester/chartStrategyEntry.css";
import IntervalSelector from "../components/IntervalSelector.js";
import { useChartSurfaceRuntime } from "../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartSurfaceVisibleRange } from "../chart-adapter/useChartSurfaceRuntime.js";
import type { MainSeriesCrosshairValue } from "../chart-adapter/chartAdapterTypes.js";
import { useChartSession } from "../features/chart-session/useChartSession.js";
import type { ChartSession } from "../features/chart-session/chartSessionTypes.js";
import type {
  ChartCellCreationMode,
  ChartCellChartSettings,
  ChartCellId,
  ChartCellState,
  ChartStrategyAttachmentRecord,
  ChartLinkGroup,
  ChartWorkspaceCellRole,
  ChartWorkspaceId,
  ChartWindowId,
  ChartWorkspaceSplitDirection,
} from "../features/chart-workspace/chartWorkspaceTypes.js";
import { chartLinkGroupDisplayName } from "../features/chart-workspace/chartWorkspaceI18n.js";
import { chartCellStorageScope } from "../features/chart-workspace/chartWorkspaceLibrary.js";
import { chartCellDrawingScopeBaseFromCell } from "../features/chart-workspace/chartWorkspaceDrawingLink.js";
import { useChartViewportLink } from "../features/chart-workspace/useChartViewportLink.js";
import type { ChartLinkCoordinator } from "../features/chart-workspace/chartLinkCoordinator.js";
import {
  recordMultiChartCellCommit,
  recordMultiChartCellRender,
} from "../features/chart-workspace/multiChartRenderDiagnostics.js";
import { writeChartCellDragData } from "../features/chart-workspace/chartWorkspaceDrag.js";
import WorkspaceCellLayoutMenu from "../features/chart-workspace/WorkspaceCellLayoutMenu.js";
import {
  workspaceCellDensityForSize,
  type WorkspaceCellDensity,
} from "../features/chart-workspace/chartWorkspaceGeometry.js";
import { useMarketDataRuntime } from "../features/market-data/useMarketDataRuntime.js";
import { resolveKlineSeriesIdentity } from "../features/market-data/klineSeriesIdentity.js";
import { useLiveReferenceMarketChartSource } from "../features/market-chart-platform/useLiveReferenceMarketChartSource.js";
import {
  initialViewportCountBackCapForCellCount,
  shouldEnableWorkspaceIntervalPrefetch,
} from "../features/market-data/useChartInitialLoad.js";
import { useMarketDataWorkspaceResources } from "../features/market-data/marketDataWorkspaceContext.js";
import { ChartMarketController } from "../features/market-data/manager/chartMarketController.js";
import type { ForegroundPreloadGate } from "../features/market-data/foregroundPreloadGate.js";
import { useAdvancedMarketDataRuntime } from "../features/advanced-market-data/useAdvancedMarketDataRuntime.js";
import { useDrawingRuntime } from "../features/drawings/useDrawingRuntime.js";
import type { DrawingToolSelectionRuntime } from "../features/drawings/drawingToolState.js";
import { useChartIndicatorRuntime } from "../features/indicators/useChartIndicatorRuntime.js";
import { chartIndicatorSelection } from "../features/indicators/chartIndicatorInput.js";
import { backendSyntheticSourceFor } from "../features/market-chart-platform/marketChartSurfaceModel.js";
import { indicatorSignature, type ControlCellObservation } from "../features/app-control/controlModel.js";
import { useControlCommands } from "../features/app-control/useControlCommands.js";
import { chartCommands } from "../features/app-control/chartCommands.js";
import { drawingCommands } from "../features/app-control/drawingCommands.js";
import { command } from "../features/app-control/commandRegistry.js";
import { bool, choice, object } from "../features/app-control/commandSchema.js";
import type { ActiveIndicatorPersistence } from "../features/indicators/activeIndicatorStore.js";
import { useExportRuntime } from "../features/export/useExportRuntime.js";
import { exportCommands } from "../features/app-control/exportCommands.js";
import type { ChartSettingsRuntime } from "../features/settings/chartAppearanceSettings.js";
import { normalizeSettings } from "../features/settings/chartAppearanceSettings.js";
import { useOrderBookRuntime } from "../features/order-book/useOrderBookRuntime.js";
import { useTradeFlowRuntime } from "../features/trade-flow/useTradeFlowRuntime.js";
import type { WatchlistRuntime } from "../features/watchlist/useWatchlistRuntime.js";
import type { WatchlistSubscriptionContext } from "../features/watchlist/watchlistSubscriptionRuntime.js";
import { usePluginPlatformRuntime } from "../features/plugins/usePluginPlatformRuntime.js";
import { pluginCommands, PluginControlSession } from "../features/app-control/pluginCommands.js";
import { useExtensionService } from "../features/extensions/hooks.js";
import PluginPlatformSurfaces, { PluginUiErrorBoundary } from "../features/plugins/PluginPlatformSurfaces.js";
import PluginPlatformToolbar from "../features/plugins/PluginPlatformToolbar.js";
import PluginPlatformStatus from "../features/plugins/PluginPlatformStatus.js";
import PluginLiveControl from "../features/plugins/PluginLiveControl.js";
import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";
import { LIVE_RAIL_VIEW_IDS } from "../shared/marketRailLayout.js";
import { ALERT_PANEL_OPEN_REQUEST_EVENT } from "../features/alerts/alertDeliveryClient.js";
import { buildAppShellViewModel } from "./appShellViewModel.js";
import type {
  AlertsShellRuntime,
  IndicatorShellRuntime,
  PriceScaleShellRuntime,
  SettingsShellRuntime,
} from "./appShellContracts.js";
import type { ChartWorkspaceRailLayout } from "./ChartWorkspace.js";
import type { ReplayEntryCapabilityView } from "../features/replay/useReplayEntryCapability.js";
import { loadUserPrefs, updateUserPref } from "../features/chart-session/chartSessionModel.js";
import { preloadDrawingEngineHost } from "../features/drawings/drawingEngineLoader.js";
import { drawingToolWhenInteractionReady } from "./drawingInteractionReadiness.js";
import ChartCellCanvas from "./ChartCellCanvas.js";
import LazyFeatureSurfaces from "./LazyFeatureSurfaces.js";
import StatusBar from "./StatusBar.js";
import TopBar from "./TopBar.js";
import { CHART_STRATEGY_TESTER_ENABLED } from "../features/backtest/chart-tester/chartStrategyTesterFeature.js";
import type { ChartStrategyTesterEntryState } from "../features/backtest/chart-tester/chartStrategyTesterUiModel.js";
import type { ChartStrategyResultMarkerSource } from "../features/backtest/chart-tester/chartStrategyResultMarkerSource.js";
import { Icon } from "../components/icons/Icon.js";

const ChartTimeNavigationDialog = lazy(() => import("../features/market-data/ChartTimeNavigationDialog.js"));
const ExportPanel = lazy(() => import("../features/export/ExportPanel.js"));
const DrawingToolbar = lazy(() => {
  preloadDrawingEngineHost();
  return import("../features/drawings/DrawingToolbar.js");
});
const RightMarketRail = lazy(() => import("./RightMarketRail.js"));
const QuickReplayOverlay = lazy(() => import("../features/trading-accounts/QuickReplayOverlay.js"));
const HistoryStudyOverlay = lazy(() => import("../features/history-study/HistoryStudyOverlay.js"));
const HistoryStudySetupDialog = lazy(() => import("../features/history-study/HistoryStudySetupDialog.js"));
const loadChartStrategyTesterCellBridge = () => import(
  "../features/backtest/chart-tester/ChartStrategyTesterCellBridge.js"
);
const ChartStrategyTesterCellBridge = lazy(loadChartStrategyTesterCellBridge);
let liveChartCellMountSequence = 0;

export interface WorkspacePortalHosts {
  topBar: HTMLElement | null;
  drawingToolbar: HTMLElement | null;
  rightRail: HTMLElement | null;
  featureSurfaces: HTMLElement | null;
  bottomPanel: HTMLElement | null;
  statusBar: HTMLElement | null;
}

export interface ActiveChartEnvironment {
  session: ChartSession;
  subscriptionContext: WatchlistSubscriptionContext;
  marketDataReady: boolean;
  cacheDiagnostics: () => Record<string, unknown>;
  trimCacheEntries: ReturnType<typeof useMarketDataRuntime>["status"]["trimCacheEntries"];
}

export interface LiveChartCellProps {
  onControlObservation?(cellId: string, observation: ControlCellObservation | null): void;
  workspaceId: ChartWorkspaceId;
  windowId: ChartWindowId;
  cell: ChartCellState;
  linkGroup: ChartLinkGroup | null;
  linkGroupControl?: ReactNode;
  linkedDrawingScopeBase: string;
  layoutRole: ChartWorkspaceCellRole | null;
  active: boolean;
  maximized: boolean;
  obscured: boolean;
  layoutCellIds: readonly ChartCellId[];
  maxCellsPerWindow: number;
  layoutEditingDisabled?: boolean;
  pageExportRef: RefObject<HTMLDivElement | null>;
  foregroundPreloadGate: ForegroundPreloadGate;
  drawingToolSelection: DrawingToolSelectionRuntime;
  globalSettings: ChartSettingsRuntime;
  watchlist: WatchlistRuntime;
  marketRail: ChartWorkspaceRailLayout;
  replayEntry: ReplayEntryCapabilityView;
  portalHosts: WorkspacePortalHosts;
  workspaceControls: ReactNode;
  linkCoordinator: ChartLinkCoordinator;
  onActivate(cellId: ChartCellId): void;
  onSplitCell(
    cellId: ChartCellId,
    direction: ChartWorkspaceSplitDirection,
    creationMode: ChartCellCreationMode,
  ): void;
  onCloseCell(cellId: ChartCellId): void;
  onSwapCells(firstCellId: ChartCellId, secondCellId: ChartCellId): void;
  onToggleMaximize(cellId: ChartCellId): void;
  onSessionChange(cellId: ChartCellId, session: ChartSession): void;
  onChartSettingsChange(cellId: ChartCellId, settings: ChartCellChartSettings): void;
  onQuickReplayChange(workspaceId: ChartWorkspaceId, cellId: ChartCellId, update: UpdateChartQuickReplay, change: QuickReplayChange): void;
  onAccountOverlayChange(cellId: ChartCellId, settings: ChartAccountOverlaySettings): void;
  onDrawingsHiddenChange(cellId: ChartCellId, hidden: boolean): void;
  onPriceScaleChange(cellId: ChartCellId, value: ChartCellState["priceScale"]): void;
  onIndicatorsChange(cellId: ChartCellId, indicators: ChartCellState["indicators"]): void;
  strategyPanelOpen: boolean;
  onStrategyPanelOpenChange(open: boolean): void;
  onStrategyTesterModeChange(cellId: ChartCellId, mode: "NATIVE" | "CANDLESCOPE"): void;
  onNativeStrategiesChange(cellId: ChartCellId, strategies: NativeStrategyCollection): void;
  onStrategyAttachmentChange(
    cellId: ChartCellId,
    attachment: ChartStrategyAttachmentRecord | null,
  ): void;
  onOpenReplayLauncher(): void;
  onActiveEnvironmentChange(cellId: ChartCellId, environment: ActiveChartEnvironment): void;
}

function LiveChartCell({
  onControlObservation,
  workspaceId,
  windowId,
  cell,
  linkGroup,
  linkGroupControl,
  layoutRole,
  active,
  maximized,
  obscured,
  layoutCellIds,
  maxCellsPerWindow,
  layoutEditingDisabled = false,
  pageExportRef,
  foregroundPreloadGate,
  drawingToolSelection,
  globalSettings,
  watchlist,
  marketRail,
  replayEntry,
  portalHosts,
  workspaceControls,
  linkCoordinator,
  onActivate,
  onSplitCell,
  onCloseCell,
  onSwapCells,
  onToggleMaximize,
  onSessionChange,
  onChartSettingsChange,
  onQuickReplayChange,
  onAccountOverlayChange,
  onDrawingsHiddenChange,
  onPriceScaleChange,
  onIndicatorsChange,
  strategyPanelOpen,
  onStrategyPanelOpenChange,
  onStrategyAttachmentChange,
  onNativeStrategiesChange,
  onStrategyTesterModeChange,
  onOpenReplayLauncher,
  onActiveEnvironmentChange,
}: LiveChartCellProps) {
  recordMultiChartCellRender(cell.id);
  useLocale();
  const marketWorkspaceResources = useMarketDataWorkspaceResources();
  const updateQuickReplay = useCallback((update: UpdateChartQuickReplay, change: QuickReplayChange) => onQuickReplayChange(workspaceId, cell.id, update, change),
    [cell.id, onQuickReplayChange, workspaceId]);
  const replay = useChartQuickReplay(cell.quickReplay, updateQuickReplay);
  const { request: quickReplay, open: openSavedReplay, exit: exitQuickReplay, suspend: suspendQuickReplay } = replay;
  const studyOwner = historyStudyOwner(workspaceId, cell.id);
  const study = useHistoryStudy(studyOwner, marketWorkspaceResources?.dataManager ?? null);
  const moveStudyCursor = study.move;
  const captureStudyInput = study.capture;
  const selectStudyInput = study.select;
  const readStudyClock = study.readClock;
  const studyEditing = useRef(false);
  const pauseStudy = useRef<(() => void) | null>(null);
  const setStudyEditing = useCallback((editing: boolean) => { studyEditing.current = editing; }, []);
  const setStudyFollowReady = useCallback((pause: (() => void) | null) => { pauseStudy.current = pause; }, []);
  const clockPort = useMemo(() => ({ read: () => {
    const state = readStudyClock();
    // An acknowledged durable cut can be published while its restored surface
    // remounts. Receiving a peer cut still requires the local playback owner.
    return { ...state, followReady: pauseStudy.current !== null, editing: studyEditing.current };
  }, move: (cursorMs: number) => { pauseStudy.current?.(); return moveStudyCursor(cursorMs); },
  setMode: (active: boolean, cursorMs?: number) => {
    pauseStudy.current?.();
    const current = readStudyClock();
    if (current.active === active && (cursorMs === undefined || current.cursorMs === cursorMs)) return Promise.resolve(true);
    if (current.cursorMs === null || !current.studyId) return Promise.resolve(false);
    return moveStudyCursor(cursorMs ?? current.cursorMs, active);
  } }), [moveStudyCursor, readStudyClock]);
  useEffect(() => linkCoordinator.studyClocks.register(cell.id, clockPort, workspaceId), [cell.id, clockPort, linkCoordinator, workspaceId]);
  const cursorLinkIssue = useSyncExternalStore(linkCoordinator.studyClocks.subscribe,
    () => linkCoordinator.studyClocks.getIssue(cell.id, workspaceId), () => null);
  const retryCursorLink = useCallback(() => {
    const issue = linkCoordinator.studyClocks.getIssue(cell.id, workspaceId);
    const intent = linkCoordinator.studyClocks.beginUserAction(cell.id, workspaceId, issue?.operation === "mode" ? "mode" : "cursor");
    void linkCoordinator.studyClocks.publishUserMove(intent);
  }, [cell.id, linkCoordinator, workspaceId]);
  const startStudyClock = useCallback(() => {
    const intent = linkCoordinator.studyClocks.beginUserAction(cell.id, workspaceId);
    void linkCoordinator.studyClocks.publishUserMove(intent);
  }, [cell.id, linkCoordinator, workspaceId]);
  const commitStudyMode = useCallback(async (commit: () => Promise<boolean>) => {
    if (studyEditing.current) return false;
    const intent = linkCoordinator.studyClocks.beginUserAction(cell.id, workspaceId, "mode");
    try {
      const committed = await commit();
      if (committed) void linkCoordinator.studyClocks.publishUserMove(intent);
      else linkCoordinator.studyClocks.cancelUserAction(intent);
      return committed;
    } catch (error) { linkCoordinator.studyClocks.cancelUserAction(intent); throw error; }
  }, [cell.id, linkCoordinator, workspaceId]);
  const captureStudy = useCallback((...args: Parameters<typeof captureStudyInput>) =>
    commitStudyMode(() => captureStudyInput(...args)), [captureStudyInput, commitStudyMode]);
  const selectStudy = useCallback((id: string, action: "activate" | "remove") => action === "activate"
    ? commitStudyMode(() => selectStudyInput(id, action)) : selectStudyInput(id, action), [commitStudyMode, selectStudyInput]);
  const moveStudy = useCallback(async (cursorMs: number, active = true, automatic = false) => {
    if (studyEditing.current) return false;
    const intent = linkCoordinator.studyClocks.beginUserAction(cell.id, workspaceId, active ? automatic ? "tick" : "cursor" : "mode");
    try {
      const committed = await moveStudyCursor(cursorMs, active);
      if (committed) void linkCoordinator.studyClocks.publishUserMove(intent);
      else linkCoordinator.studyClocks.cancelUserAction(intent);
      return committed;
    } catch (error) { linkCoordinator.studyClocks.cancelUserAction(intent); throw error; }
  }, [cell.id, linkCoordinator, moveStudyCursor, workspaceId]);
  const advanceStudyAutomatically = useCallback((cursorMs: number) => {
    if (!linkCoordinator.studyClocks.canStartAutomatic(cell.id, workspaceId)) return Promise.resolve(false);
    return moveStudy(cursorMs, true, true);
  }, [cell.id, linkCoordinator, moveStudy, workspaceId]);
  const liveControlsEnabled = !replay.key && !study.masked && !study.pending && !study.busy;
  const marketController = useMemo(() => marketWorkspaceResources ? new ChartMarketController({
    data: marketWorkspaceResources.dataFlow.forChart(`chart:${cell.id}`), owner: `chart:${cell.id}`,
  }) : null, [cell.id, marketWorkspaceResources]);
  useEffect(() => () => marketController?.releaseAll(), [marketController]);
  const handleSelectionIntent = useCallback((transition: import("../features/chart-session/chartSessionTypes.js").ChartSessionTransition) => {
    marketController?.activate(transition.to);
  }, [marketController]);
  const handlePreviewSeries = useCallback((series: ChartSession, nativeIntervals: readonly string[]) => {
    marketController?.preview(series, nativeIntervals);
  }, [marketController]);
  const handleCancelPreview = useCallback(() => marketController?.cancelPreview(), [marketController]);
  const linkGroupName = linkGroup ? chartLinkGroupDisplayName(linkGroup) : null;
  const sectionRef = useRef<HTMLElement | null>(null);
  const [density, setDensity] = useState<WorkspaceCellDensity>("full");
  const strategyEntryRef = useRef<HTMLButtonElement | null>(null);
  const strategyAttachmentKey = cell.strategyAttachment
    ? cell.strategyAttachment.strategyDraftId ?? "__attached__"
    : "__detached__";
  const [strategyEntrySnapshot, setStrategyEntrySnapshot] = useState<{
    attachmentKey: string;
    state: ChartStrategyTesterEntryState;
  }>(() => ({
    attachmentKey: strategyAttachmentKey,
    state: cell.strategyAttachment ? "editing" : "unattached",
  }));
  const strategyEntryState = strategyEntrySnapshot.attachmentKey === strategyAttachmentKey
    ? strategyEntrySnapshot.state
    : cell.strategyAttachment ? "editing" : "unattached";
  const handleStrategyEntryStateChange = useCallback((state: ChartStrategyTesterEntryState) => {
    setStrategyEntrySnapshot({ attachmentKey: strategyAttachmentKey, state });
  }, [strategyAttachmentKey]);
  const closeStrategyPanel = useCallback(() => {
    onStrategyPanelOpenChange(false);
    globalThis.setTimeout(() => {
      const currentEntry = document.querySelector<HTMLButtonElement>(
        `[data-chart-strategy-entry="${CSS.escape(cell.id)}"]`,
      );
      (currentEntry ?? strategyEntryRef.current)?.focus();
    }, 0);
  }, [cell.id, onStrategyPanelOpenChange]);
  const openStrategyPanel = useCallback(() => {
    onStrategyPanelOpenChange(true);
  }, [onStrategyPanelOpenChange]);
  const handleStrategyAttachmentChange = useCallback((attachment: ChartStrategyAttachmentRecord | null) => {
    onStrategyAttachmentChange(cell.id, attachment);
  }, [cell.id, onStrategyAttachmentChange]);
  // The entry names what is on this chart; an empty chart just says "Chart strategy".
  const nativeEntryCount = cell.nativeStrategies?.items.length ?? 0;
  const nativeEntryName = cell.nativeStrategies?.items.find((item) => item.id === cell.nativeStrategies?.activeId)?.name ?? "";
  const strategyEntryLabel = resolveStrategyTesterMode(cell.strategyTesterMode, !!cell.strategyAttachment) === "CANDLESCOPE"
    ? cell.strategyAttachment
      ? strategyEntryState === "error" ? `${cell.strategyAttachment.displayName} · ${t("chartTester.entryState.error")}` : cell.strategyAttachment.displayName
      : null
    : [nativeEntryName, nativeEntryCount > 1 ? `+${nativeEntryCount - 1}` : ""].filter(Boolean).join(" ") || null;
  const strategyEntryControl = CHART_STRATEGY_TESTER_ENABLED ? (
    <button
      ref={strategyEntryRef}
      type="button"
      className="chart-strategy-entry-button ui-control"
      data-chart-strategy-entry={cell.id}
      title={t("chartTester.entryHint")}
      data-state={strategyEntryState}
      aria-expanded={strategyPanelOpen}
      aria-controls="chart-strategy-tester-panel"
      onPointerEnter={() => { void loadChartStrategyTesterCellBridge(); }}
      onMouseEnter={() => { void loadChartStrategyTesterCellBridge(); }}
      onFocus={() => { void loadChartStrategyTesterCellBridge(); }}
      onClick={() => onStrategyPanelOpenChange(!strategyPanelOpen)}
    >
      <i className="chart-strategy-entry-dot" aria-hidden="true" />
      {t("chartTester.entry")}
      {strategyEntryLabel && <span>{strategyEntryLabel}</span>}
    </button>
  ) : null;
  useLayoutEffect(() => {
    recordMultiChartCellCommit(cell.id);
  });
  const [mountToken] = useState(() => {
    liveChartCellMountSequence += 1;
    return `${cell.id}:${liveChartCellMountSequence}`;
  });
  useLayoutEffect(() => {
    const element = sectionRef.current;
    if (!element) return undefined;
    const update = () => {
      const rect = element.getBoundingClientRect();
      const next = workspaceCellDensityForSize(rect.width, rect.height);
      setDensity((current) => current === next ? current : next);
    };
    update();
    if (typeof ResizeObserver !== "function") return undefined;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const chartSurface = useChartSurfaceRuntime();
  const cellStorageScope = chartCellStorageScope(workspaceId, cell.id);
  const realtimePriceRef = useRef<number | null>(null);
  const handleSessionChange = useCallback((session: ChartSession) => {
    onSessionChange(cell.id, session);
  }, [cell.id, onSessionChange]);
  const chartSession = useChartSession({
    chartSurfaceActions: chartSurface.actions,
    initialSession: cell.session,
    controlledSession: cell.session,
    onSessionChange: handleSessionChange,
    onSelectionIntent: handleSelectionIntent,
    onPreviewSeries: handlePreviewSeries,
    onCancelPreview: handleCancelPreview,
    visibleRangeScope: cellStorageScope,
  });
  useEffect(
    () => study.masked ? undefined : linkCoordinator.register(cell.id, chartSurface.actions, workspaceId),
    [cell.id, chartSurface.actions, linkCoordinator, workspaceId, study.masked],
  );
  useEffect(
    () => study.masked ? undefined : chartSurface.actions.subscribeDrawingRevision((scopeKey, revision) => {
      linkCoordinator.publishDrawingRevision(cell.id, scopeKey, revision);
    }),
    [cell.id, chartSurface.actions, linkCoordinator, study.masked],
  );
  const plugins = usePluginPlatformRuntime({
    exchange: chartSession.view.exchange,
    marketType: chartSession.view.marketType,
    symbol: chartSession.view.symbol,
    interval: chartSession.view.interval,
  });
  useExtensionService(`charts.${cell.id}`, { session: chartSession, surface: chartSurface });
  const initialViewportCountBackCap = initialViewportCountBackCapForCellCount(
    layoutCellIds.length,
  );
  const marketData = useMarketDataRuntime({
    session: chartSession,
    realtimePriceRef,
    foregroundPreloadGate,
    backgroundPrefetchEnabled: active,
    intervalPrefetchEnabled: active
      && shouldEnableWorkspaceIntervalPrefetch(layoutCellIds.length),
    schedulerCellId: cell.id,
    workspaceId,
    windowId,
    ...(initialViewportCountBackCap === undefined
      ? {}
      : { initialViewportCountBackCap }),
  });
  const liveSourceSession = useMemo<ChartSession>(() => ({
    exchange: chartSession.view.exchange,
    marketType: chartSession.view.marketType,
    symbol: chartSession.view.symbol,
    interval: chartSession.view.interval,
    ...resolveKlineSeriesIdentity(
      chartSession.view.exchange,
      {
        ...(chartSession.view.providerId === undefined
          ? {} : { providerId: chartSession.view.providerId }),
        ...(chartSession.view.venue === undefined
          ? {} : { venue: chartSession.view.venue }),
        ...(chartSession.view.assetClass === undefined
          ? {} : { assetClass: chartSession.view.assetClass }),
        ...(chartSession.view.seriesVariant === undefined
          ? {} : { seriesVariant: chartSession.view.seriesVariant }),
        ...(chartSession.view.priceAdjustment === undefined
          ? {} : { priceAdjustment: chartSession.view.priceAdjustment }),
        ...(chartSession.view.sessionVariant === undefined
          ? {} : { sessionVariant: chartSession.view.sessionVariant }),
        ...(chartSession.view.volumeSemantics === undefined
          ? {} : { volumeSemantics: chartSession.view.volumeSemantics }),
      },
    ),
  }), [
    chartSession.view.exchange,
    chartSession.view.interval,
    chartSession.view.marketType,
    chartSession.view.providerId,
    chartSession.view.venue,
    chartSession.view.assetClass,
    chartSession.view.seriesVariant,
    chartSession.view.priceAdjustment,
    chartSession.view.sessionVariant,
    chartSession.view.volumeSemantics,
    chartSession.view.symbol,
  ]);
  const liveReferenceSource = useLiveReferenceMarketChartSource({
    sourceId: `live:${workspaceId}:${windowId}:${cell.id}`,
    session: liveSourceSession,
    datasetKey: chartSession.view.datasetKey,
    marketData,
    paused: obscured,
  });
  const sourceMarketData = liveReferenceSource.marketData;

  const workTier = obscured ? "hidden" : active ? "focused" : "visible-secondary";
  const workScheduler = marketWorkspaceResources?.workScheduler;
  useLayoutEffect(() => {
    if (!workScheduler) return undefined;
    return workScheduler.registerCell(cell.id);
  }, [cell.id, workScheduler]);
  useLayoutEffect(() => {
    workScheduler?.setCellTier(cell.id, workTier);
  }, [cell.id, workScheduler, workTier]);
  const advancedMarketData = useAdvancedMarketDataRuntime({
    session: chartSession,
    dataMeta: sourceMarketData.view.meta,
    seriesStore: sourceMarketData.view.seriesStore,
  });
  const drawingScopeBase = chartCellDrawingScopeBaseFromCell(
    workspaceId,
    cell,
    linkGroup,
    chartSession.view,
  );
  const drawingsHidden = cell.drawingsHidden === true;
  const setDrawingsHidden = useCallback((hidden: boolean) => onDrawingsHiddenChange(cell.id, hidden),
    [cell.id, onDrawingsHiddenChange]);
  const drawings = useDrawingRuntime({
    chartSurfaceActions: chartSurface.actions,
    drawingScopeBase,
    drawingToolSelection,
    session: chartSession,
    visibility: { hidden: drawingsHidden, setHidden: setDrawingsHidden },
  });

  const combinedSettings = useMemo(() => normalizeSettings({
    ...globalSettings.settings,
    ...cell.chartSettings,
  }), [cell.chartSettings, globalSettings.settings]);
  const resolvedTheme = useCellChartTheme(cell.chartSettings.theme, globalSettings.resolvedTheme);
  const combinedSettingsRef = useRef(combinedSettings);
  useLayoutEffect(() => {
    combinedSettingsRef.current = combinedSettings;
  }, [combinedSettings]);
  const setCombinedSettings = useCallback<Dispatch<SetStateAction<ReturnType<typeof normalizeSettings>>>>((action) => {
    const current = combinedSettingsRef.current;
    const next = normalizeSettings(typeof action === "function" ? action(current) : action);
    onChartSettingsChange(cell.id, nextCellChartSettings(cell.chartSettings, current, next));
    const applicationPatch = applicationSettingsPatch(current, next);
    if (Object.keys(applicationPatch).length) globalSettings.setSettings(previous => ({ ...previous, ...applicationPatch }));
  }, [cell.id, cell.chartSettings, globalSettings, onChartSettingsChange]);

  const priceScale = cell.priceScale;
  const setInvertScale = useCallback((invertScale: boolean) => {
    onPriceScaleChange(cell.id, { ...cell.priceScale, invertScale });
  }, [cell.id, cell.priceScale, onPriceScaleChange]);
  const setPriceScaleMode = useCallback((priceScaleMode: number) => {
    onPriceScaleChange(cell.id, { ...cell.priceScale, priceScaleMode });
  }, [cell.id, cell.priceScale, onPriceScaleChange]);

  const indicatorPersistence = useMemo<ActiveIndicatorPersistence>(() => ({
    controlled: true,
    load: () => cell.indicators,
    save: (indicators) => onIndicatorsChange(cell.id, indicators),
  }), [cell.id, cell.indicators, onIndicatorsChange]);

  const [showSettings, setShowSettings] = useState(false);
  const [showIndicatorPanel, setShowIndicatorPanel] = useState(false);
  const [showAlertsPanel, setShowAlertsPanel] = useState(false);
  const openIndicatorPanel = useCallback(() => setShowIndicatorPanel(true), []);
  const closeIndicatorPanel = useCallback(() => setShowIndicatorPanel(false), []);
  const toggleIndicatorPanel = useCallback(() => setShowIndicatorPanel((value) => !value), []);
  const openSettingsPanel = useCallback(() => setShowSettings(true), []);
  const closeSettingsPanel = useCallback(() => setShowSettings(false), []);
  const openAlertsPanel = useCallback(() => setShowAlertsPanel(true), []);
  const closeAlertsPanel = useCallback(() => setShowAlertsPanel(false), []);
  const toggleAlertsPanel = useCallback(() => setShowAlertsPanel((value) => !value), []);
  useEffect(() => {
    if (!active) return undefined;
    const handleOpenRequest = () => openAlertsPanel();
    window.addEventListener(ALERT_PANEL_OPEN_REQUEST_EVENT, handleOpenRequest);
    return () => window.removeEventListener(ALERT_PANEL_OPEN_REQUEST_EVENT, handleOpenRequest);
  }, [active, openAlertsPanel]);
  const indicatorStreamIdentity = useMemo(
    () => ({ workspaceId, windowId, cellId: cell.id }),
    [cell.id, windowId, workspaceId],
  );

  const indicators = useChartIndicatorRuntime({
    chart: chartIndicatorSelection(backendSyntheticSourceFor(liveReferenceSource), sourceMarketData.view.seriesStore, combinedSettings),
    // Workspace schema v8 persists an explicit indicator list for every cell.
    // An empty list is therefore intentional (and is required by capacity
    // scenarios such as S3), not a signal to inject the legacy VOL default.
    autoAddVolume: false,
    session: chartSession,
    marketData: sourceMarketData,
    candleUpColor: combinedSettings.upColor,
    candleDownColor: combinedSettings.downColor,
    getCurrentVisibleRange: chartSurface.actions.getVisibleRange,
    onIndicatorRemoved: drawings.actions.handleIndicatorRemoved,
    indicatorPersistence,
    realtimeEnabled: !obscured,
    streamIdentity: indicatorStreamIdentity,
    workSchedulerCellId: cell.id,
  });
  useIndicatorHistoryPreparation(
    sourceMarketData.status.historyPreparing === true,
    indicators.status.computing,
    sourceMarketData.actions.holdHistoryHydrationForIndicators,
  );
  useLayoutEffect(() => {
    if (study.masked && study.playback) return; // The visible study reports its own prefix below.
    if (cell.quickReplay && replay.key && !study.masked) {
      const trade = quickReplay?.trade;
      onControlObservation?.(cell.id, {
        mode: "quick-replay",
        session: trade ? { exchange: trade.exchange, marketType: trade.marketType, symbol: trade.symbol, interval: cell.quickReplay.interval } : cell.session,
        quickReplay: { cursorSec: cell.quickReplay.cursorSec ?? null, step: cell.quickReplay.step ?? cell.quickReplay.interval },
        indicatorSignature: "", marketReady: false, indicatorsReady: false, barCount: 0, loading: !quickReplay && !replay.error,
        initialHistoryPending: false, loadingMoreLeft: false, paused: true, computing: false,
        indicatorErrors: [], indicatorOutputPoints: [], error: replay.error,
      });
      return;
    }
    if (study.pending || study.masked || study.busy) {
      onControlObservation?.(cell.id, { mode: "restoring-study", session: cell.session,
        indicatorSignature: "", marketReady: false, indicatorsReady: false, barCount: 0, loading: true,
        initialHistoryPending: true, loadingMoreLeft: false, paused: true, computing: false,
        indicatorErrors: [], indicatorOutputPoints: [], error: study.error ? String(study.error) : null });
      return;
    }
    onControlObservation?.(cell.id, {
      mode: "live",
      session: { exchange: chartSession.view.exchange, marketType: chartSession.view.marketType,
        symbol: chartSession.view.symbol, interval: chartSession.view.interval },
      indicatorSignature: indicatorSignature(indicators.view.activeIndicators),
      marketReady: !obscured && sourceMarketData.status.barCount > 0 && !sourceMarketData.view.loading
        && !sourceMarketData.status.initialHistoryPending && !sourceMarketData.status.loadingMoreLeft,
      indicatorsReady: !indicators.status.computing && indicators.view.activeIndicators.every((indicator) =>
        !indicator.error && (indicator.visible === false || indicator.lines?.some((line) => line.data.length > 0))),
      barCount: sourceMarketData.status.barCount,
      loading: sourceMarketData.view.loading,
      initialHistoryPending: sourceMarketData.status.initialHistoryPending,
      loadingMoreLeft: sourceMarketData.status.loadingMoreLeft,
      paused: obscured,
      computing: indicators.status.computing,
      indicatorErrors: indicators.view.activeIndicators.flatMap((indicator) => indicator.error ? [indicator.error] : []),
      indicatorOutputPoints: indicators.view.activeIndicators.map((indicator) => indicator.lines?.reduce((count, line) => count + line.data.length, 0) ?? 0),
      error: sourceMarketData.view.error ? String(sourceMarketData.view.error) : null,
    });
  }, [cell.id, chartSession.view.exchange, chartSession.view.marketType, chartSession.view.symbol,
    chartSession.view.interval, indicators.view.activeIndicators, indicators.status.computing,
    sourceMarketData.status.barCount, sourceMarketData.view.loading, sourceMarketData.status.initialHistoryPending,
    sourceMarketData.status.loadingMoreLeft, sourceMarketData.view.error, obscured, onControlObservation,
    study.pending, study.masked, study.playback, study.busy, study.error, cell.session, cell.quickReplay, quickReplay, replay.error, replay.key]);
  useEffect(() => () => onControlObservation?.(cell.id, null), [cell.id, onControlObservation]);
  const exportFlow = useExportRuntime({
    indicators: indicators.view.activeIndicators,
    session: chartSession,
    resolvedTheme,
    chartSurfaceActions: chartSurface.actions,
    pageExportRef,
    drawings,
    loadUserPrefs,
    updateUserPref,
  });

  const orderBookOpen = active && marketRail.openViewIds.includes(LIVE_RAIL_VIEW_IDS.orderBook);
  const tradeFlowOpen = active && (
    marketRail.openViewIds.includes(LIVE_RAIL_VIEW_IDS.tape)
    || marketRail.openViewIds.includes(LIVE_RAIL_VIEW_IDS.profile)
  );
  const activeExchangeCapability = chartSession.view.exchangeCatalog[
    chartSession.view.exchange.toLowerCase()
  ]?.raw ?? null;
  const orderBook = useOrderBookRuntime({
    identity: {
      exchange: chartSession.view.exchange,
      marketType: chartSession.view.marketType,
      symbol: chartSession.view.symbol,
    },
    orderBookOpen,
    capability: activeExchangeCapability,
  });
  const tradeFlow = useTradeFlowRuntime({
    identity: {
      exchange: chartSession.view.exchange,
      marketType: chartSession.view.marketType,
      symbol: chartSession.view.symbol,
    },
    interval: chartSession.view.interval,
    seriesStore: sourceMarketData.view.seriesStore,
    buyColor: combinedSettings.upColor,
    sellColor: combinedSettings.downColor,
    tradeFlowOpen,
    capability: activeExchangeCapability,
  });

  const indicatorRuntime = useMemo<IndicatorShellRuntime>(() => ({
    view: { ...indicators.view, isPanelOpen: showIndicatorPanel },
    actions: {
      ...indicators.actions,
      openPanel: openIndicatorPanel,
      closePanel: closeIndicatorPanel,
      togglePanel: toggleIndicatorPanel,
    },
    status: indicators.status,
  }), [
    closeIndicatorPanel,
    indicators.actions,
    indicators.status,
    indicators.view,
    openIndicatorPanel,
    showIndicatorPanel,
    toggleIndicatorPanel,
  ]);
  const settingsRuntime = useMemo<SettingsShellRuntime>(() => ({
    view: {
      settings: combinedSettings,
      appearanceScope: "chart",
      resolvedTheme,
      isOpen: showSettings,
    },
    actions: {
      update: setCombinedSettings,
      openPanel: openSettingsPanel,
      closePanel: closeSettingsPanel,
    },
    status: {},
  }), [
    closeSettingsPanel,
    combinedSettings,
    resolvedTheme,
    openSettingsPanel,
    setCombinedSettings,
    showSettings,
  ]);
  const priceScaleRuntime = useMemo<PriceScaleShellRuntime>(() => ({
    view: priceScale,
    actions: { setInvertScale, setPriceScaleMode },
    status: {},
  }), [priceScale, setInvertScale, setPriceScaleMode]);
  const alertsRuntime = useMemo<AlertsShellRuntime>(() => ({
    view: { isOpen: showAlertsPanel },
    actions: {
      openPanel: openAlertsPanel,
      closePanel: closeAlertsPanel,
      togglePanel: toggleAlertsPanel,
    },
    status: {},
  }), [
    closeAlertsPanel,
    openAlertsPanel,
    showAlertsPanel,
    toggleAlertsPanel,
  ]);

  useControlCommands(() => chartCommands({ cellId: cell.id, session: chartSession, indicators,
    settings: { settings: combinedSettings, setSettings: setCombinedSettings, resolvedTheme },
    marketData: sourceMarketData, surface: chartSurface, drawings }), liveControlsEnabled);
  useControlCommands(() => drawingCommands(cell.id, chartSurface, drawings, chartSession.view.sessionKey), liveControlsEnabled);
  useControlCommands(() => exportCommands(cell.id, exportFlow), liveControlsEnabled);
  const [pluginControlSession] = useState(() => new PluginControlSession());
  useControlCommands(() => pluginCommands(cell.id, plugins, pluginControlSession), liveControlsEnabled);
  useControlCommands(() => ({ id: `panels:${cell.id}`, title: "Chart panels", context: () => ({ session: chartSession.view.sessionKey, historical: study.masked }),
    snapshot: () => ({ indicators: showIndicatorPanel, settings: showSettings, alerts: !study.masked && showAlertsPanel, strategy: !study.masked && strategyPanelOpen }), commands: [
      command("show", "Open/close a chart panel. Rediscover commands after opening lazy strategy or settings panels.",
        object({ panel: choice(["indicators", "settings", "alerts", "strategy"]), visible: bool }), ({ panel, visible }) => {
          if (study.masked && (panel === "alerts" || panel === "strategy")) throw new Error("HISTORICAL_STUDY_ACTIVE");
          if (panel === "indicators") setShowIndicatorPanel(visible);
          if (panel === "settings") setShowSettings(visible);
          if (panel === "alerts") setShowAlertsPanel(visible);
          if (panel === "strategy") onStrategyPanelOpenChange(visible);
        }),
    ] }));

  useExtensionService(`market.${cell.id}`, sourceMarketData);
  useExtensionService(`indicators.${cell.id}`, indicatorRuntime);
  useExtensionService(`drawings.${cell.id}`, drawings);
  const model = useMemo(() => buildAppShellViewModel({
    session: {
      view: chartSession.view,
      actions: chartSession.actions,
      status: chartSession.status,
    },
    marketData: sourceMarketData,
    advancedMarketData,
    drawings,
    indicators: indicatorRuntime,
    settings: settingsRuntime,
    priceScale: priceScaleRuntime,
    watchlist,
    orderBook,
    tradeFlow,
    marketRail,
    exportFlow,
    alerts: alertsRuntime,
    replayEntry,
    onOpenReplayLauncher,
  }), [
    advancedMarketData,
    alertsRuntime,
    chartSession.actions,
    chartSession.status,
    chartSession.view,
    drawings,
    exportFlow,
    indicatorRuntime,
    sourceMarketData,
    marketRail,
    onOpenReplayLauncher,
    orderBook,
    priceScaleRuntime,
    replayEntry,
    settingsRuntime,
    tradeFlow,
    watchlist,
  ]);

  const upstreamCrosshairMoveRef = useRef(
    model.chartWorkspace.chart.chartProps.onCrosshairMove,
  );
  useLayoutEffect(() => {
    upstreamCrosshairMoveRef.current = model.chartWorkspace.chart.chartProps.onCrosshairMove;
  }, [
    model.chartWorkspace.chart.chartProps.onCrosshairMove,
  ]);
  const handleLinkedCrosshairMove = useCallback((value: MainSeriesCrosshairValue | null) => {
    upstreamCrosshairMoveRef.current?.(value);
    linkCoordinator.publishCrosshair(
      cell.id,
      typeof value?.time === "number" ? value.time : null,
    );
  }, [cell.id, linkCoordinator]);
  const handleLinkedViewportRangeChange = useChartViewportLink(linkCoordinator, cell.id, cellStorageScope);
  const [strategyPanelVisited, setStrategyPanelVisited] = useState(false);
  useEffect(() => { if (active && strategyPanelOpen) setStrategyPanelVisited(true); }, [active, strategyPanelOpen]);
  const strategyMarkerSourceRef = useRef<ChartStrategyResultMarkerSource | null>(null);
  const strategyTradeFocusRef = useRef<{ trade: StrategyTradeFocus; interval: string } | null>(null);
  const [strategyMarkerSource, setStrategyMarkerSource] = useState<ChartStrategyResultMarkerSource | null>(null);
  const handleStrategyMarkerSourceChange = useCallback((source: ChartStrategyResultMarkerSource | null) => {
    strategyMarkerSourceRef.current = source;
    const focus = strategyTradeFocusRef.current;
    if (source && focus) source.setTradeFocus(focus.trade, focus.interval, t("chartTester.result.entry"), t("chartTester.result.exit"));
    setStrategyMarkerSource(source);
  }, []);
  const upstreamViewportRangeChangeRef = useRef(
    model.chartWorkspace.chart.chartProps.onViewportRangeChange,
  );
  useLayoutEffect(() => {
    upstreamViewportRangeChangeRef.current = model.chartWorkspace.chart.chartProps.onViewportRangeChange;
  }, [model.chartWorkspace.chart.chartProps.onViewportRangeChange]);
  const handleChartViewportRangeChange = useCallback((range: ChartSurfaceVisibleRange) => {
    upstreamViewportRangeChangeRef.current?.(range);
    strategyMarkerSourceRef.current?.setVisibleRange(range);
  }, []);
  const handleReviewStrategyTrade = useCallback((trade: StrategyTradeFocus | null) => {
    strategyTradeFocusRef.current = trade ? { trade, interval: liveSourceSession.interval } : null;
    strategyMarkerSourceRef.current?.setTradeFocus(trade, liveSourceSession.interval, t("chartTester.result.entry"), t("chartTester.result.exit"));
    if (!trade) return;
    chartSurface.actions.setLinkedVisibleTimeRange(strategyTradeRange(trade, parseIntervalSeconds(liveSourceSession.interval) ?? 60));
    chartSurface.actions.setLinkedCrosshairTime(trade.entryTimeMs / 1000);
  }, [chartSurface.actions, liveSourceSession.interval]);
  const handleLocateStrategyTrade = useCallback((timeMs: number) => {
    const timeSeconds = timeMs / 1_000;
    chartSurface.actions.setLinkedVisibleTimeAnchor(timeSeconds);
    chartSurface.actions.setLinkedCrosshairTime(timeSeconds);
  }, [chartSurface.actions]);


  const studyMaskedRef = useRef(study.masked);
  useLayoutEffect(() => {
    studyMaskedRef.current = study.masked;
    // Initial study recovery masks the live chart before its mode is known.
    // Only an acknowledged active study supersedes the saved trade replay.
    if (study.active && replay.key) suspendQuickReplay();
  }, [replay.key, study.active, study.masked, suspendQuickReplay]);
  const openTradeReplay = useCallback((request: QuickReplayRequest) => {
    if (!studyMaskedRef.current) openSavedReplay(request);
  }, [openSavedReplay]);
  const [studySetup, setStudySetup] = useState(false);
  const timeNavigation = useChartTimeNavigation({ active, enabled: !obscured && !replay.key && !study.masked,
    cellId: cell.id, workspaceId, sessionKey: chartSession.view.sessionKey,
    marketData: sourceMarketData, surface: chartSurface.actions, links: linkCoordinator });
  const lastClose = sourceMarketData.view.lastPrice?.close;
  const tradingBinding = useMemo<TradingRailBinding>(() => ({
    context: {
      exchange: chartSession.view.exchange,
      marketType: chartSession.view.marketType,
      symbol: chartSession.view.symbol,
      interval: chartSession.view.interval,
      lastPrice: typeof lastClose === "number" && Number.isFinite(lastClose) ? lastClose : null,
      captureImage: () => captureChartPng(chartSurface.actions.getExportSnapshot()),
      describeChart: () => ({
        visibleRange: chartSurface.actions.getVisibleRange(),
        indicators: cell.indicators.map((indicator) => ({
          id: indicator.id,
          name: indicator.name,
          params: indicator.params ?? {},
        })),
      }),
    },
    onOpenQuickReplay: openTradeReplay,
  }), [
    cell.indicators,
    chartSession.view.exchange,
    chartSession.view.interval,
    chartSession.view.marketType,
    chartSession.view.symbol,
    chartSurface.actions,
    lastClose,
    openTradeReplay,
  ]);
  const tradingOverlay = useTradingChartOverlay({
    enabled: true,
    ...(cell.accountOverlay ? { settings: cell.accountOverlay } : {}),
    exchange: chartSession.view.exchange,
    marketType: chartSession.view.marketType,
    symbol: chartSession.view.symbol,
    interval: chartSession.view.interval,
    seriesStore: sourceMarketData.view.seriesStore,
    upColor: combinedSettings.upColor,
    downColor: combinedSettings.downColor,
    themeKey: resolvedTheme,
  });
  const quickReplayStyle = useMemo(() => ({
    upColor: combinedSettings.upColor,
    downColor: combinedSettings.downColor,
    chartType: combinedSettings.chartType,
    theme: resolvedTheme,
    inheritApplicationTheme: cell.chartSettings.theme === undefined,
    customBg: combinedSettings.customBg,
  }), [
    cell.chartSettings.theme,
    combinedSettings.chartType,
    combinedSettings.customBg,
    combinedSettings.downColor,
    combinedSettings.upColor,
    resolvedTheme,
  ]);

  const chartModel = useMemo(() => ({
    ...model.chartWorkspace.chart,
    chartProps: {
      ...model.chartWorkspace.chart.chartProps,
      inheritApplicationTheme: cell.chartSettings.theme === undefined,
      ref: chartSurface.ref,
      ...(workScheduler ? { displayScheduler: { scheduler: workScheduler, cellId: cell.id } } : {}),
      drawingKeyBase: drawingScopeBase,
      drawingsHidden,
      paneLayoutScope: cellStorageScope,
      onCrosshairMove: handleLinkedCrosshairMove,
      onViewportRangeChange: handleChartViewportRangeChange,
      onUserViewportRangeChange: handleLinkedViewportRangeChange,
    },
  }), [
    cell.id,
    workScheduler,
    cellStorageScope,
    chartSurface.ref,
    drawingScopeBase,
    drawingsHidden,
    handleLinkedCrosshairMove,
    handleLinkedViewportRangeChange,
    handleChartViewportRangeChange,
    model.chartWorkspace.chart,
    cell.chartSettings.theme,
  ]);
  const featureSurfaces = useMemo(() => ({
    ...model.lazySurfaces,
    settingsModal: { ...model.lazySurfaces.settingsModal, plugins },
  }), [model.lazySurfaces, plugins]);
  const [drawingInteractionReady, setDrawingInteractionReady] = useState(false);
  const [drawingControlsHost, setDrawingControlsHost] = useState<HTMLSpanElement | null>(null);
  const drawingToolbarProps = useMemo(() => ({
    ...model.chartWorkspace.drawingToolbar,
    activeTool: drawingToolWhenInteractionReady(
      model.chartWorkspace.drawingToolbar.activeTool,
      drawingInteractionReady,
    ),
    drawingInteractionReady,
  }), [drawingInteractionReady, model.chartWorkspace.drawingToolbar]);

  useEffect(() => {
    if (!active) return;
    onActiveEnvironmentChange(cell.id, {
      session: liveSourceSession,
      subscriptionContext: {
        exchangeCatalog: chartSession.view.exchangeCatalog,
        exchangeCatalogStatus: chartSession.status.exchangeCatalogStatus,
        customIntervalRecords: chartSession.view.customIntervalRecords,
      },
      marketDataReady: chartSession.status.marketDataReady,
      cacheDiagnostics: sourceMarketData.status.cacheDiagnostics,
      trimCacheEntries: sourceMarketData.status.trimCacheEntries,
    });
  }, [
    active,
    cell.id,
    chartSession.status.exchangeCatalogStatus,
    chartSession.status.marketDataReady,
    chartSession.view.customIntervalRecords,
    chartSession.view.exchangeCatalog,
    liveSourceSession,
    sourceMarketData.status.cacheDiagnostics,
    sourceMarketData.status.trimCacheEntries,
    onActiveEnvironmentChange,
  ]);

  const activate = useCallback(() => onActivate(cell.id), [cell.id, onActivate]);
  const toggleMaximize = useCallback(() => {
    onActivate(cell.id);
    onToggleMaximize(cell.id);
  }, [cell.id, onActivate, onToggleMaximize]);

  return (
    <>
      <section
        ref={sectionRef}
        className={`multi-chart-cell${active ? " active" : ""}${maximized ? " maximized" : ""}`}
        data-chart-cell-id={cell.id}
        data-runtime-mount-token={mountToken}
        data-market-chart-source-mode={liveReferenceSource.mode}
        data-market-chart-source-state={obscured ? "PAUSED" : liveReferenceSource.lifecycle}
        data-density={density}
        data-rendering-paused={obscured ? "true" : "false"}
        data-market-data-ready={sourceMarketData.status.barCount > 0 ? "true" : "false"}
        data-market-data-settled={sourceMarketData.status.barCount > 0
          && !sourceMarketData.view.loading
          && !sourceMarketData.status.initialHistoryPending
          && !sourceMarketData.status.loadingMoreLeft
          ? "true"
          : "false"}
        data-work-tier={workScheduler?.tier(cell.id) || "fallback"}
        data-active={active ? "true" : "false"}
        data-layout-role={layoutRole ?? "standard"}
        data-link-group={cell.linkGroupId ?? "none"}
        role="group"
        aria-label={t("chart.aria", { symbol: chartSession.view.symbol, interval: formatIntervalLabel(chartSession.view.interval) })}
        tabIndex={obscured ? -1 : active ? 0 : -1}
        onFocus={activate}
        onPointerDown={activate}
      >
        <header className="multi-chart-cell-header" onDoubleClick={toggleMaximize}>
          <span className={`multi-chart-cell-status ${sourceMarketData.view.wsStatus}`} aria-hidden="true" />
          <button
            type="button"
            className="multi-chart-cell-drag-handle"
            draggable={!layoutEditingDisabled && !maximized && layoutCellIds.length > 1}
            aria-label={t("chart.dragAria", { n: cell.id.slice("cell-".length) })}
            aria-disabled={layoutEditingDisabled || maximized || layoutCellIds.length <= 1}
            title={layoutCellIds.length > 1 ? t("chart.dragTitle") : t("chart.dragNeedSplit")}
            onDragStart={(event) => {
              if (layoutEditingDisabled || maximized || layoutCellIds.length <= 1) {
                event.preventDefault();
                return;
              }
              writeChartCellDragData(event.dataTransfer, cell.id);
            }}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            <Icon name="grip" size={14} />
          </button>
          {layoutRole && (
            <span className={`multi-chart-cell-role role-${layoutRole}`}>
              {layoutRole === "main" ? t("chart.roleMain") : t("chart.roleConfirm")}
            </span>
          )}
          <strong>{chartSession.view.symbol}</strong>
          <span>{formatIntervalLabel(chartSession.view.interval)}</span>
          {chartSession.status.historyIntervalAvailable && !chartSession.status.realtimeIntervalAvailable && (
            <span role="status" style={{ color: "var(--text-warning)" }}>{t("interval.historyOnly")}</span>
          )}
          <span className="multi-chart-cell-market">
            {chartSession.view.exchange} · {chartSession.view.marketType}
          </span>
          {linkGroupControl ?? (linkGroup && (
            <span
              className="multi-chart-cell-link"
              data-link-group={linkGroup.id}
              style={{ "--chart-link-group-color": linkGroup.color } as CSSProperties}
              title={linkGroup.parentId
                ? t("chart.linkChild", { name: linkGroupName ?? linkGroup.name })
                : t("chart.linkRoot", { name: linkGroupName ?? linkGroup.name })}
            >
              <span className="multi-chart-cell-link-role" aria-hidden="true">
                {linkGroup.parentId ? "↓" : "↔"}
              </span>
              {linkGroupName}
            </span>
          ))}
          <ChartAccountOverlayMenu cellId={cell.id} settings={cell.accountOverlay} error={tradingOverlay.error}
            onChange={settings => onAccountOverlayChange(cell.id, settings)} />
          {(!replay.key || study.masked) && <button type="button" className="multi-chart-cell-drawing-visibility"
            aria-label={t(drawingsHidden ? "drawing.showAll" : "drawing.hideAll")}
            title={t(drawingsHidden ? "drawing.showAll" : "drawing.hideAll")}
            aria-pressed={drawingsHidden} onDoubleClick={event => event.stopPropagation()}
            onClick={drawings.actions.handleToggleDrawingsHidden}>
            <Icon name={drawingsHidden ? "eye-off" : "eye"} size={14} />
          </button>}
          <span className="chart-cell-drawing-controls" ref={setDrawingControlsHost} hidden={!!replay.key || study.masked} />
          <WorkspaceCellLayoutMenu
            cellId={cell.id}
            layoutCellIds={layoutCellIds}
            maxCellsPerWindow={maxCellsPerWindow}
            disabled={layoutEditingDisabled || maximized}
            onSplit={onSplitCell}
            onClose={onCloseCell}
            onSwap={onSwapCells}
          />
          <button
            type="button"
            className="multi-chart-cell-maximize"
            onClick={(event) => {
              event.stopPropagation();
              toggleMaximize();
            }}
            onDoubleClick={(event) => event.stopPropagation()}
            aria-label={maximized ? t("chart.restore") : t("chart.maximize")}
            title={maximized ? t("chart.restore") : t("chart.maximize")}
          >
            <Icon name={maximized ? "minimize" : "maximize"} size={14} />
          </button>
        </header>
        <div className="multi-chart-cell-canvas">
          {chartSession.status.exchangeCatalogStatus !== "loading" && !chartSession.status.historyIntervalAvailable ? (
            <ChartIntervalUnavailable
              session={chartSession.view}
              nativeIntervals={chartSession.status.exchangeCapabilityAvailable ? chartSession.view.nativeIntervals : []}
              onSelectInterval={chartSession.actions.selectInterval}
            />
          ) : <ChartCellCanvas
            chart={chartModel}
            source={liveReferenceSource}
            tradeFlow={tradeFlow}
            strategyMarkerSource={strategyMarkerSource}
            pluginMarkerSource={plugins.view.markerSource}
            accountMarkerSource={tradingOverlay.markerSource}
            accountPriceLineSource={tradingOverlay.priceLineSource}
            pluginChartLayerSource={plugins.view.chartLayerSource}
            drawingInteractionReady={drawingInteractionReady}
            drawingControlsHost={drawingControlsHost}
            onDrawingInteractionReadyChange={setDrawingInteractionReady}
            paused={obscured || !!replay.key || study.masked}
          />}
          {quickReplay && !study.masked && (
            <Suspense fallback={<div className="history-study-mask" role="status">{t("study.loading")}</div>}>
              <QuickReplayOverlay
                key={replay.key}
                request={quickReplay}
                active={active && !obscured}
                savedCursorSec={cell.quickReplay?.cursorSec}
                savedStep={cell.quickReplay?.step}
                onProgress={replay.save}
                onCursorChange={replay.move}
                accountOverlay={cell.accountOverlay}
                style={quickReplayStyle}
                indicatorDefinitions={cell.indicators}
                onExit={exitQuickReplay}
              />
            </Suspense>
          )}
          {replay.key && !quickReplay && !study.masked && <div className="history-study-mask" data-quick-replay-pending>
            <p role={replay.error ? "alert" : "status"}>{replay.error ?? t("study.loading")}</p>
            {replay.error && <button type="button" className="trading-button" onClick={replay.retry}>{t("trading.replay.retry")}</button>}
            <button type="button" className="trading-button" onClick={exitQuickReplay}>{t("trading.replay.exit")}</button>
          </div>}
          {study.masked && study.playback && marketWorkspaceResources && <Suspense fallback={<div className="history-study-mask">{t("study.loading")}</div>}>
            <HistoryStudyOverlay key={study.playback.input.id} playback={study.playback}
              cellId={cell.id} revision={study.view!.revision} onControlObservation={onControlObservation}
              drawingsHidden={drawingsHidden}
              accountOverlay={cell.accountOverlay}
              linkCoordinator={linkCoordinator} workspaceId={workspaceId}
              manager={marketWorkspaceResources.dataManager} style={quickReplayStyle} indicators={cell.indicators}
              active={active && !obscured} busy={study.busy ?? false} error={study.error} onMove={moveStudy} onRetry={study.retry}
              onAutomaticMove={advanceStudyAutomatically}
              onEditingChanged={setStudyEditing} onFollowReady={setStudyFollowReady} onPlayStart={startStudyClock}
              cursorLinkIssue={cursorLinkIssue} onRetryCursorLink={retryCursorLink} />
          </Suspense>}
          {study.masked && !study.playback && <div className="history-study-mask" role="status">
            {t(study.error ? "study.error" : "study.loading")}
            {study.error ? <button type="button" className="trading-button" onClick={study.retry}>{t("study.retry")}</button> : null}
          </div>}
          {!study.masked && study.error && <div className="study-recovery-message" role="alert">
            {t("study.error")} <button type="button" className="trading-button" onClick={study.retry}>{t("study.retry")}</button>
          </div>}
          {!study.masked && cursorLinkIssue?.operation === "mode" && <div className="study-recovery-message" role="alert">
            {t("study.modeLinkFailed", { count: cursorLinkIssue.failed.length })}
            <button type="button" className="trading-button" disabled={study.pending || study.busy} onClick={retryCursorLink}>{t("study.modeLinkRetry")}</button>
          </div>}
          {active && !study.masked && model.chartWorkspace.exportPanel.isOpen && (
            <Suspense fallback={null}>
              <ExportPanel {...model.chartWorkspace.exportPanel} />
            </Suspense>
          )}
        </div>
      </section>

      {CHART_STRATEGY_TESTER_ENABLED
        && (cell.strategyAttachment !== null || strategyPanelVisited || (active && strategyPanelOpen)) && (
          <Suspense fallback={null}>
            <ChartStrategyTesterCellBridge
              workspaceId={workspaceId}
              cellId={cell.id}
              session={liveSourceSession}
              attachment={cell.strategyAttachment}
              nativeStrategies={cell.nativeStrategies}
              strategyTesterMode={cell.strategyTesterMode}
              onStrategyTesterModeChange={(value) => onStrategyTesterModeChange(cell.id, value)}
              onNativeStrategiesChange={(value) => onNativeStrategiesChange(cell.id, value)}
              active={active}
              panelOpen={strategyPanelOpen && !study.masked}
              continuousChartActive={active && !obscured && !study.masked && quickReplay === null}
              bottomPanelHost={portalHosts.bottomPanel}
              seriesStore={sourceMarketData.view.seriesStore}
              getCurrentVisibleRange={chartSurface.actions.getVisibleRange}
              onMarkerSourceChange={handleStrategyMarkerSourceChange}
              onLocateTrade={handleLocateStrategyTrade}
              onReviewTrade={handleReviewStrategyTrade}
              onAttachmentChange={handleStrategyAttachmentChange}
              onEntryStateChange={handleStrategyEntryStateChange}
              onOpenPanel={openStrategyPanel}
              onClosePanel={closeStrategyPanel}
            />
          </Suspense>
        )}

      {active && portalHosts.topBar && createPortal(
        <TopBar
          {...model.topBar}
          {...(study.masked && study.playback ? { studyContext: study.playback.input.series } : {})}
          identityAccessory={strategyEntryControl}
          intervalControl={<IntervalSelector {...model.intervalSelector} variant="compact" />}
          extensionControls={(
            <>
              {workspaceControls}
              {!study.active && <button type="button" className="ui-control" disabled={study.pending || study.busy || !!replay.key}
                onClick={() => { if (!study.view) study.retry(); else setStudySetup(true); }}>{t("study.title")}</button>}
              {timeNavigation.available && <button type="button" className="ui-control"
                title={t("chartTime.shortcut")} onClick={() => timeNavigation.setOpen(true)}>{t("chartTime.title")}</button>}
              <PluginUiErrorBoundary>
                <PluginPlatformToolbar runtime={plugins} />
              </PluginUiErrorBoundary>
            </>
          )}
        />,
        portalHosts.topBar,
      )}
      {active && portalHosts.drawingToolbar && createPortal(
        <Suspense fallback={<div className="drawing-toolbar drawing-toolbar-loading" aria-hidden="true" />}>
          <DrawingToolbar {...drawingToolbarProps} />
        </Suspense>,
        portalHosts.drawingToolbar,
      )}
      {active && portalHosts.rightRail && createPortal(
        <Suspense fallback={<div className="right-market-rail market-rail-loading" aria-hidden="true" />}>
          <RightMarketRail
            watchlist={model.chartWorkspace.watchlist}
            orderBook={model.chartWorkspace.orderBook}
            tradeFlow={model.chartWorkspace.tradeFlow}
            openViewIds={marketRail.openViewIds}
            panelCollapsed={marketRail.panelCollapsed ?? false}
            onToggleView={marketRail.onToggleView}
            {...(marketRail.onCloseView === undefined
              ? {}
              : { onCloseView: marketRail.onCloseView })}
            {...(marketRail.onTogglePanelCollapsed === undefined
              ? {}
              : { onTogglePanelCollapsed: marketRail.onTogglePanelCollapsed })}
            viewHeights={marketRail.viewHeights}
            onViewHeightChange={marketRail.onViewHeightChange}
            {...(study.masked ? {} : { trading: tradingBinding })}
          />
        </Suspense>,
        portalHosts.rightRail,
      )}
      {active && portalHosts.featureSurfaces && createPortal(
        <>
          <LazyFeatureSurfaces surfaces={featureSurfaces} />
          {timeNavigation.open && <Suspense fallback={null}><ChartTimeNavigationDialog
            key={chartSession.view.sessionKey} cellId={cell.id} onClose={() => timeNavigation.setOpen(false)}
            onSubmit={timeNavigation.submit} /></Suspense>}
          {studySetup && marketWorkspaceResources && <Suspense fallback={null}><HistoryStudySetupDialog key={`${workspaceId}:${cell.id}`}
            owner={studyOwner} manager={marketWorkspaceResources.dataManager.historyStudy} onSelect={selectStudy}
            series={liveSourceSession} bars={sourceMarketData.view.bars} busy={study.busy ?? false} error={study.error}
            onCapture={captureStudy} onClose={() => setStudySetup(false)} /></Suspense>}
          <PluginUiErrorBoundary>
            <PluginLiveControl runtime={plugins} />
          </PluginUiErrorBoundary>
          <PluginPlatformSurfaces runtime={plugins} />
        </>,
        portalHosts.featureSurfaces,
      )}
      {active && portalHosts.statusBar && createPortal(
        <StatusBar
          status={model.statusBar}
          extensions={(
            <PluginUiErrorBoundary>
              <PluginPlatformStatus runtime={plugins} />
            </PluginUiErrorBoundary>
          )}
        />,
        portalHosts.statusBar,
      )}
    </>
  );
}

export default React.memo(LiveChartCell);
