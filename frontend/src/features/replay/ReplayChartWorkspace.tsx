import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import MarketPageFrame from "../../app/MarketPageFrame.js";
import MarketChartWorkspace from "../../app/MarketChartWorkspace.js";
import { useChartSurfaceRuntime } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { ChartSurfaceVisibleRange } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { MainSeriesCrosshairValue } from "../../chart-adapter/chartAdapterTypes.js";
import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import { useChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import type { ChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import WorkspaceLayoutTree from "../chart-workspace/WorkspaceLayoutTree.js";
import WorkspacePanel from "../chart-workspace/WorkspacePanel.js";
import WorkspaceCellLayoutMenu from "../chart-workspace/WorkspaceCellLayoutMenu.js";
import { ChartLinkCoordinator } from "../chart-workspace/chartLinkCoordinator.js";
import { chartCellDrawingScopeBase } from "../chart-workspace/chartWorkspaceDrawingLink.js";
import { writeChartCellDragData } from "../chart-workspace/chartWorkspaceDrag.js";
import type { ChartCellState } from "../chart-workspace/chartWorkspaceTypes.js";
import type { ChartSettingsRuntime } from "../settings/chartAppearanceSettings.js";
import type { ActiveIndicatorPersistence } from "../indicators/activeIndicatorStore.js";
import { createReplayChartWorkspaceRepository } from "./replayChartWorkspaceRepository.js";
import { useSharedReplayChartRuntime } from "./replayChartRuntimePool.js";
import type { ReplayChartResourcePool } from "./replayChartRuntimePool.js";
import type { ReplayRuntime, ReplayRuntimeLifecycle } from "./useReplayRuntime.js";
import type { ReplayViewerRuntime } from "./useReplayViewerRuntime.js";
import { useReplayChartProjection } from "./replayChartProjection.js";
import { useReplaySharedIndicatorRuntime } from "./useReplaySharedIndicatorRuntime.js";
import { useReplayIntegrityRuntime } from "./useReplayIntegrityRuntime.js";
import type { ReplayIntegrityRuntime } from "./useReplayIntegrityRuntime.js";
import ReplayTrainingPageShell from "./ReplayTrainingPageShell.js";
import type { ReplayChartPageFrameProps } from "./ReplayTrainingPageShell.js";
import type { ReplayTrainingMarketTrack } from "./replayV2Types.js";
import { t } from "../../i18n/index.js";
import { defaultReplayV2Api } from "./replayV2Api.js";
import { useReplayCellViewport } from "./useReplayCellViewport.js";
import { useReplayWorkspacePreferences } from "./replayWorkspacePreferences.js";
import { replayWorkspaceDrawingCharts, useReplayWorkspaceDrawings } from "./useReplayWorkspaceDrawings.js";

type HostName = "topBar" | "intervalSelector" | "toolbar" | "rightRail" | "featureSurfaces" | "statusBar";
const HOST_NAMES: HostName[] = ["topBar", "intervalSelector", "toolbar", "rightRail", "featureSurfaces", "statusBar"];
type Hosts = Record<HostName, HTMLDivElement | null>;
const CellFrameContext = createContext<{ active: boolean; hosts: Hosts } | null>(null);

/** Cell canvases stay mounted; only the active cell supplies shared page controls. */
function ReplayCellFrame(props: ReplayChartPageFrameProps) {
  const context = useContext(CellFrameContext)!;
  return <>
    {props.workspace}
    {context.active && (Object.keys(context.hosts) as HostName[]).map((name) => {
      const host = context.hosts[name];
      return host ? createPortal(props[name], host, name) : null;
    })}
  </>;
}

function sameMarket(cell: ChartCellState, track: ReplayTrainingMarketTrack) {
  return cell.session.exchange === track.exchange && cell.session.marketType === track.market_type
    && cell.session.symbol === track.symbol;
}

interface CellProps {
  runId: string;
  cell: ChartCellState;
  track: ReplayTrainingMarketTrack;
  workspace: ChartWorkspaceRuntime;
  controller: ReplayViewerRuntime;
  pool: ReplayChartResourcePool<ReplayRuntimeLifecycle>;
  globalSettings: ChartSettingsRuntime;
  integrity: ReplayIntegrityRuntime;
  links: ChartLinkCoordinator;
  hosts: Hosts;
  controls: ReactNode;
  preferences: ReturnType<typeof useReplayWorkspacePreferences>;
  onOpenTrack(trackId: string, target: "current" | "new"): Promise<void>;
}

function ReplayChartCell({ runId, cell, track, workspace, controller, pool, globalSettings,
  integrity, links, hosts, controls, preferences, onOpenTrack }: CellProps) {
  const runtime = useSharedReplayChartRuntime(pool, track.adapter_session_id!);
  const projection = useReplayChartProjection(runtime, track.track_id, cell.session.interval);
  const active = workspace.view.activeCellId === cell.id;
  const scope = `replay:${runId}:${workspace.view.activeWorkspaceId}:${cell.id}`;
  const surface = useChartSurfaceRuntime();
  const saveViewport = useReplayCellViewport(`${scope}:${track.track_id}:${cell.session.interval}`, surface.actions);
  const bound = controller.viewerState?.selected_track_id === track.track_id;
  const tradeAuthority = useRef({ active, bound, controller, reviewing: integrity.review !== null });
  tradeAuthority.current = { active, bound, controller, reviewing: integrity.review !== null };
  const assertTradeAuthority = useCallback(() => {
    const current = tradeAuthority.current;
    if (!current.active || !current.bound || current.reviewing || current.controller.viewerPending || current.controller.controlPending) {
      throw new Error("Wait for the selected trading market to be ready");
    }
    return current.controller;
  }, []);
  const viewer = useMemo<ReplayViewerRuntime>(() => ({
    ...controller,
    viewerState: controller.viewerState === null ? null : {
      ...controller.viewerState, selected_track_id: track.track_id, display_interval: cell.session.interval,
    },
    seriesStore: projection.seriesStore,
    loading: projection.loading,
    error: projection.error ?? controller.error,
    viewerPending: controller.viewerPending || (active && !bound),
    actions: {
      ...controller.actions,
      setDisplayInterval: async (interval) => {
        workspace.actions.updateCellSession(cell.id, { ...cell.session, interval });
        return null;
      },
      openTrack: onOpenTrack,
      submitTrade: async (type, payload) => {
        return assertTradeAuthority().actions.submitTrade(type, payload);
      },
      previewOrder: (...args) => assertTradeAuthority().actions.previewOrder(...args),
      orderCapacity: (...args) => assertTradeAuthority().actions.orderCapacity(...args),
    },
  }), [active, bound, cell, controller, onOpenTrack, projection.error, projection.loading, projection.seriesStore, track.track_id, workspace.actions, assertTradeAuthority]);
  const persistence = useMemo<ActiveIndicatorPersistence>(() => ({
    controlled: true,
    load: () => cell.indicators,
    save: (indicators) => workspace.actions.updateCellIndicators(cell.id, indicators),
  }), [cell.id, cell.indicators, workspace.actions]);
  const indicators = useReplaySharedIndicatorRuntime(runtime, viewer, scope, persistence);
  const settings = useMemo<ChartSettingsRuntime>(() => ({
    ...globalSettings,
    settings: { ...globalSettings.settings, ...cell.chartSettings },
    setSettings: (update) => {
      const current = { ...globalSettings.settings, ...cell.chartSettings };
      workspace.actions.updateCellChartSettings(cell.id, typeof update === "function" ? update(current) : update);
    },
  }), [cell.chartSettings, cell.id, globalSettings, workspace.actions]);
  const cellIntegrity = useMemo<ReplayIntegrityRuntime>(() => integrity.review === null ? integrity : ({
    ...integrity,
    review: {
      ...integrity.review,
      projection: { ...integrity.review.projection,
        viewer_state: { ...integrity.review.projection.viewer_state,
          selected_track_id: track.track_id, display_interval: cell.session.interval },
      },
      // A legacy drawing document is bound to the recorded selected market.
      drawing_document: integrity.review.drawing_document?.documentSchemaVersion === 2
        ? replayWorkspaceDrawingCharts(integrity.review.drawing_document)[`${chartCellDrawingScopeBase(`replay:${runId}:${workspace.view.activeWorkspaceId}`, workspace.view.document, cell.id)}__main`] ?? null
        : integrity.review.projection.viewer_state.selected_track_id === track.track_id
          ? integrity.review.drawing_document : null,
    },
  }), [integrity, track.track_id, cell.session.interval, cell.id, runId, workspace.view.activeWorkspaceId, workspace.view.document]);
  useEffect(() => links.register(cell.id, surface.actions), [cell.id, links, surface.actions]);
  const cellOptions = useMemo(() => ({
    scope,
    drawingScope: chartCellDrawingScopeBase(`replay:${runId}:${workspace.view.activeWorkspaceId}`, workspace.view.document, cell.id),
    active, integrity: cellIntegrity, frame: ReplayCellFrame, controls, controlViewer: controller, preferences,
    priceScale: cell.priceScale,
    onPriceScaleChange: (value: ChartCellState["priceScale"]) => workspace.actions.updateCellPriceScale(cell.id, value),
    onCrosshairMove: (value: MainSeriesCrosshairValue | null) => {
      runtime.marketData.actions.onCrosshairMove(value);
      if (active) links.publishCrosshair(cell.id, value === null ? null : Number(value.time));
    },
    onVisibleRangeChange: (range: ChartSurfaceVisibleRange) => {
      saveViewport(range);
      if (!active) return;
      if (range.time) links.publishDateRange(cell.id, range.time);
      if (range.rightmostTime !== undefined) links.publishTimeAnchor(cell.id, range.rightmostTime);
    },
  }), [scope, runId, workspace.view.activeWorkspaceId, workspace.view.document, workspace.actions, cell.id, cell.priceScale, active, cellIntegrity, controls, controller, links, runtime.marketData.actions, saveViewport, preferences]);
  const frame = useMemo(() => ({ active, hosts }), [active, hosts]);
  return <CellFrameContext.Provider value={frame}>
    <span hidden data-replay-cell-diagnostics={cell.id} data-replay-track-id={track.track_id}
      data-replay-boundary-ms={projection.boundaryMs ?? ""} data-replay-cell-bars={projection.seriesStore.barCount}
      data-replay-cell-interval={cell.session.interval} data-replay-cell-error={projection.error ?? ""} />
    {projection.loading && <div role="status" className="replay-chart-loading">{t("replay.opening")}</div>}
    {projection.error && <div role="alert" className="replay-chart-error">{projection.error}
      <button type="button" onClick={projection.retry}>{t("replay.retry")}</button>
    </div>}
    <ReplayTrainingPageShell runtime={runtime} viewer={viewer} indicators={indicators}
      chartSurfaceRef={surface.ref} chartSurfaceActions={surface.actions}
      chartSettingsRuntime={settings} cell={cellOptions} />
  </CellFrameContext.Provider>;
}

export interface ReplayChartWorkspaceProps {
  runId: string;
  initialSession: ChartSession;
  runtime: ReplayRuntime;
  viewer: ReplayViewerRuntime;
  pool: ReplayChartResourcePool<ReplayRuntimeLifecycle>;
  chartSettingsRuntime: ChartSettingsRuntime;
}

export default function ReplayChartWorkspace({ runId, initialSession, runtime, viewer, pool, chartSettingsRuntime }: ReplayChartWorkspaceProps) {
  const [repository] = useState(() => createReplayChartWorkspaceRepository(runId, initialSession));
  const workspace = useChartWorkspaceRuntime({ repository, workspaceBus: null });
  const preferences = useReplayWorkspacePreferences(runId);
  const [links] = useState(() => new ChartLinkCoordinator(workspace.view.document));
  const [panelOpen, setPanelOpen] = useState(false);
  const focusStart = useRef<{ id: string; started: number } | null>(null);
  const [focusTiming, setFocusTiming] = useState<{ id: string; durationMs: number } | null>(null);
  const focusCell = useCallback((id: string) => {
    if (id !== workspace.view.activeCellId && focusStart.current?.id !== id && import.meta.env.DEV) {
      focusStart.current = { id, started: performance.now() };
    }
    workspace.actions.setActiveCell(id);
  }, [workspace.actions, workspace.view.activeCellId]);
  useLayoutEffect(() => {
    const pending = focusStart.current;
    if (!pending || pending.id !== workspace.view.activeCellId) return;
    let second = 0;
    const first = requestAnimationFrame(() => { second = requestAnimationFrame(() => {
      if (focusStart.current !== pending) return;
      focusStart.current = null;
      setFocusTiming({ id: pending.id, durationMs: performance.now() - pending.started });
    }); });
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); };
  }, [workspace.view.activeCellId]);
  const [error, setError] = useState<string | null>(null);
  const [hosts, setHosts] = useState<Hosts>({ topBar: null, intervalSelector: null, toolbar: null,
    rightRail: null, featureSurfaces: null, statusBar: null });
  const hostRefs = useMemo(() => Object.fromEntries(HOST_NAMES.map((name) => [name,
    (element: HTMLDivElement | null) => setHosts((current) => current[name] === element ? current : { ...current, [name]: element }),
  ])) as Record<HostName, (element: HTMLDivElement | null) => void>, []);
  const lastTracks = useRef(viewer.marketTracks);
  const lastView = useRef(viewer.viewerState);
  if (viewer.marketTracks !== null) lastTracks.current = viewer.marketTracks;
  if (viewer.viewerState !== null) lastView.current = viewer.viewerState;
  const controller = useMemo(() => ({ ...viewer,
    marketTracks: viewer.marketTracks ?? lastTracks.current,
    viewerState: viewer.viewerState ?? lastView.current,
    viewerPending: viewer.viewerPending || viewer.viewerState === null
      || viewer.marketTracks?.tracks.find((track) => track.track_id === viewer.viewerState?.selected_track_id)?.adapter_session_id !== runtime.store.sessionId,
  }), [viewer, runtime.store.sessionId]);
  const integrity = useReplayIntegrityRuntime(runtime, controller);
  const drawings = useReplayWorkspaceDrawings(runId, workspace.view.activeWorkspaceId, workspace.view.document, integrity);
  const selectionPending = useRef(false);
  const [selectionAttempt, setSelectionAttempt] = useState(0);
  const failedSelection = useRef<string | null>(null);
  const tracks = useMemo(() => controller.marketTracks?.tracks ?? [], [controller.marketTracks]);
  const activeTrack = tracks.find((track) => sameMarket(workspace.view.activeCell, track));
  useLayoutEffect(() => links.updateDocument(workspace.view.document,
    `replay:${runId}:${workspace.view.activeWorkspaceId}`), [links, runId, workspace.view.activeWorkspaceId, workspace.view.document]);
  useEffect(() => {
    if (integrity.review !== null) return;
    if (runtime.phase !== "ACTIVE" || !runtime.store.hasAuthoritativeSnapshot || runtime.store.sessionId === null || runtime.store.virtualTimeMs === null) return;
    if (!activeTrack || viewer.viewerState === null || selectionPending.current || controller.viewerPending || viewer.controlPending) return;
    if (viewer.viewerState.selected_track_id === activeTrack.track_id) return;
    const requestKey = `${activeTrack.track_id}:${selectionAttempt}`;
    if (failedSelection.current === requestKey) return;
    selectionPending.current = true;
    void viewer.actions.selectTrack(activeTrack.track_id).then(() => {
      setError(null);
      setSelectionAttempt((attempt) => attempt + 1);
    }).catch((reason: unknown) => { failedSelection.current = requestKey; setError(String(reason)); })
      .finally(() => { selectionPending.current = false; });
  }, [activeTrack, viewer, controller.viewerPending, integrity.review, selectionAttempt, runtime.phase, runtime.store.hasAuthoritativeSnapshot, runtime.store.sessionId, runtime.store.virtualTimeMs]);
  // A visible chart requires an advancing track. The server independently pins
  // positions/orders FULL, so hiding a chart never suspends financial processing.
  useEffect(() => {
    if (integrity.review !== null) return;
    if (runtime.phase !== "ACTIVE" || !runtime.store.hasAuthoritativeSnapshot || runtime.store.sessionId === null || runtime.store.virtualTimeMs === null) return;
    if (controller.viewerPending || viewer.controlPending || selectionPending.current) return;
    const needed = tracks.find((track) => track.subscription_tier !== "FULL"
      && workspace.view.layoutCellIds.some((id) => sameMarket(workspace.view.document.cells[id]!, track)));
    if (!needed) return;
    void viewer.actions.setSubscriptionTier(needed.track_id, "FULL").catch((reason: unknown) => setError(String(reason)));
  }, [tracks, viewer, controller.viewerPending, integrity.review, workspace.view.document, workspace.view.layoutCellIds, runtime.phase, runtime.store.hasAuthoritativeSnapshot, runtime.store.sessionId, runtime.store.virtualTimeMs]);
  const openTrack = useCallback(async (trackId: string, target: "current" | "new") => {
    const track = tracks.find((value) => value.track_id === trackId)
      ?? (await defaultReplayV2Api.tracksRun(runId)).tracks.find((value) => value.track_id === trackId);
    if (!track) throw new Error("Replay market is unavailable");
    const session = {
      ...workspace.view.activeCell.session, exchange: track.exchange, marketType: track.market_type, symbol: track.symbol,
    };
    if (target === "new") {
      if (workspace.view.layoutLocked || workspace.view.layoutCellIds.length >= workspace.view.maxCellsPerWindow) {
        throw new Error(t("replay.workspace.splitUnavailable"));
      }
      workspace.actions.splitCell(workspace.view.activeCellId, "columns", "copy", session);
    } else workspace.actions.updateCellSession(workspace.view.activeCellId, session);
  }, [runId, tracks, workspace.actions, workspace.view]);
  const controls = <button type="button" className="workspace-toolbar-trigger" onClick={() => setPanelOpen((value) => !value)}>
    {t("workspace.tab.workspaces")} · {workspace.view.layoutCellIds.length}
  </button>;
  return <>
    {import.meta.env.DEV && focusTiming && <span hidden data-replay-focus-cell={focusTiming.id} data-replay-focus-ms={focusTiming.durationMs} />}
    <MarketPageFrame
      topBar={<div ref={hostRefs.topBar} className="replay-workspace-host" />}
      intervalSelector={<div ref={hostRefs.intervalSelector} className="replay-workspace-host" />}
      workspace={<MarketChartWorkspace
        toolbar={<div ref={hostRefs.toolbar} className="replay-workspace-host" />}
        exportOverlay={null}
        rightRail={<div ref={hostRefs.rightRail} className="replay-workspace-host" />}
        chart={<WorkspaceLayoutTree tree={workspace.view.window.layoutTree}
          maximizedCellId={workspace.view.window.maximizedCellId} disabled={workspace.view.layoutLocked}
          onSplitRatioChange={workspace.actions.setLayoutRatio} onCellDrop={workspace.actions.swapCells}
          renderCell={(id, _role, obscured) => {
            const cell = workspace.view.document.cells[id]!;
            const track = tracks.find((value) => sameMarket(cell, value));
            return <section className={`multi-chart-cell replay-chart-cell${workspace.view.activeCellId === id ? " active" : ""}`}
              data-chart-cell-id={id} data-replay-track-id={track?.track_id} data-obscured={obscured}
              onDragOver={(event) => {
                if (event.dataTransfer.types.includes("application/x-candlescope-replay-track")) {
                  event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = "copy";
                }
              }}
              onDrop={(event) => {
                const trackId = event.dataTransfer.getData("application/x-candlescope-replay-track");
                if (!trackId) return;
                event.preventDefault(); event.stopPropagation();
                const dropped = tracks.find((candidate) => candidate.track_id === trackId);
                if (!dropped) return;
                workspace.actions.updateCellSession(id, { ...cell.session,
                  exchange: dropped.exchange, marketType: dropped.market_type, symbol: dropped.symbol });
                workspace.actions.setActiveCell(id);
              }}
              tabIndex={0} onPointerDown={() => focusCell(id)} onFocus={() => focusCell(id)}>
              <header className="multi-chart-cell-header" draggable={!workspace.view.layoutLocked}
                onDragStart={(event) => writeChartCellDragData(event.dataTransfer, id)}>
                <strong>{cell.session.symbol}</strong><span>{cell.session.interval}</span>
                <button type="button" onClick={() => workspace.actions.toggleMaximize(id)} aria-label={t("workspace.tab.layout")}>↗</button>
                <WorkspaceCellLayoutMenu portal cellId={id} layoutCellIds={workspace.view.layoutCellIds}
                  maxCellsPerWindow={workspace.view.maxCellsPerWindow} disabled={workspace.view.layoutLocked}
                  onSplit={workspace.actions.splitCell} onClose={workspace.actions.closeCell} onSwap={workspace.actions.swapCells} />
              </header>
              {track?.adapter_session_id ? <ReplayChartCell key={`${id}:${track.track_id}`} runId={runId} cell={cell} track={track}
                workspace={workspace} controller={controller} pool={pool} globalSettings={chartSettingsRuntime}
                integrity={integrity} links={links} hosts={hosts} controls={controls} preferences={preferences} onOpenTrack={openTrack} />
                : <div role="status">{cell.session.symbol} — {tracks.length === 0 ? t("replay.opening") : t("replay.watchlist.noCover")}
                  {tracks.filter((candidate) => candidate.adapter_session_id).map((candidate) => <button key={candidate.track_id}
                    type="button" onClick={() => workspace.actions.updateCellSession(id, { ...cell.session,
                      exchange: candidate.exchange, marketType: candidate.market_type, symbol: candidate.symbol })}>
                    {candidate.symbol}
                  </button>)}
                </div>}
            </section>;
          }} />}
      />}
      featureSurfaces={<><div ref={hostRefs.featureSurfaces} className="replay-workspace-host" />
        {drawings.error && <div role="alert">{drawings.error}<button type="button" onClick={drawings.retry}>{t("replay.retry")}</button></div>}
        {error && <div role="alert">{error}<button type="button" onClick={() => { setError(null); setSelectionAttempt((attempt) => attempt + 1); }}>{t("replay.retry")}</button></div>}
      </>}
      statusBar={<div ref={hostRefs.statusBar} className="replay-workspace-host" />}
    />
    <WorkspacePanel isOpen={panelOpen} onClose={() => setPanelOpen(false)} runtime={workspace}
      desktop={{ mode: "web", multiWindowEnabled: false, displayCount: 1, error: null }} viewportIssue={links.getViewportIssue()} />
  </>;
}
