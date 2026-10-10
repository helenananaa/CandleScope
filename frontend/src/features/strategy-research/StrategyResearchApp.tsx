import { useNativeAvailability } from "../backtest/native/useNativeAvailability.js";
import { describeError } from "../../i18n/serverErrors.js";
import {
  Component,
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  useSyncExternalStore,
  type ErrorInfo,
  type ReactNode,
} from "react";

import type { MainSeriesCrosshairValue } from "../../chart-adapter/chartAdapterTypes.js";
const PreparationJobsPanel = lazy(() => import("../data-preparation/PreparationJobsPanel.js"));
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { ResearchDataDrawer } from "../research-data/ResearchDataDrawer.js";
import { RESEARCH_DATA_LIBRARY_ENABLED } from "../research-data/researchDataFlags.js";
import type { ResearchSourceKind } from "../research-data/researchDataTypes.js";
import { useResearchDataLibrary } from "../research-data/useResearchDataLibrary.js";
import {
  EMPTY_LOCAL_ANALYSIS_SNAPSHOT,
  LocalAnalysisEventStore,
} from "../local-data/localAnalysisStore.js";
import type {
  LocalAnalysisEvent,
  LocalAnalysisFocusRequest,
} from "../local-data/localAnalysisTypes.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import { useLocalIntervalSelection } from "../local-data/useLocalIntervalSelection.js";
import SettingsModal from "../settings/SettingsModal.js";
import { useChartSettingsRuntime } from "../settings/chartAppearanceSettings.js";
import {
  ImportedAnalysisPanel,
  ImportedDatasetIntervalStrip,
  StrategyResearchImportedWorkspace,
} from "./StrategyResearchChart.js";
import { StrategyResearchCurrentChart } from "./StrategyResearchCurrentChart.js";
import { StrategyResearchFirstOpen } from "./StrategyResearchFirstOpen.js";
import {
  importedDatasetSourceFromManifest,
  importedManifestForSource,
  preferredLibrarySelectedId,
} from "./importedDatasetSource.js";
import { StrategyResearchRuntime } from "./StrategyResearchRuntime.js";
import { StrategyResearchResultPanel } from "./StrategyResearchResultPanel.js";
import { StrategyResearchScriptPanel } from "./StrategyResearchScriptPanel.js";
import { getChartStrategyDraftStore } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import { saveResearchTemplate } from "./strategyTemplateDraft.js";
import { readResearchHandoff } from "./strategyResearchHandoff.js";
import { StrategyResearchShell } from "./StrategyResearchShell.js";
import { useStrategyResearchRun } from "./useStrategyResearchRun.js";
import { loadStrategyResearchHostHealth } from "./strategyResearchHostHealth.js";
import type { StrategyResearchNetworkDiagnostics } from "./strategyResearchHostHealth.js";
import { createStrategyResearchAdvancedHref } from "./strategyResearchAdvanced.js";
import { StrategyResearchCompatNotice } from "./StrategyResearchCompatNotice.js";
import { CapabilityRailIcon, ProfileRailIcon } from "../../app/marketRailIcons.js";
import { MarketDataWorkspaceProvider } from "../market-data/MarketDataWorkspaceProvider.js";

const BacktestResearchApp = lazy(() => import("../backtest/research/BacktestResearchApp.js"));
const StrategyResearchLiveChart = lazy(() => import("./StrategyResearchLiveChart.js"));
const NativeStrategyPanel = lazy(() => import("../backtest/native/NativeStrategyPanel.js"));
const NativeStrategyReport = lazy(() => import("../backtest/native/NativeStrategyReport.js").then((module) => ({ default: module.NativeStrategyReport })));
const StrategyRunHistory = lazy(() => import("./StrategyRunHistory.js"));
import {
  strategyResearchDeepLinkSearch,
  strategyResearchLaunchActions,
  strategyResearchVisualState,
  type StrategyResearchLaunchIntent,
} from "./strategyResearchLaunch.js";
import type { StrategyResearchState } from "./strategyResearchState.js";

class StrategyResearchDrawerBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  constructor(props: { children: ReactNode; fallback: ReactNode }) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Strategy research data drawer failed", error, info);
  }

  render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function dispatchImportedSource(
  dispatch: (action: Parameters<StrategyResearchRuntime["dispatch"]>[0]) => void,
  current: StrategyResearchState["source"]["source"],
  manifest: LocalDatasetManifest,
): void {
  const next = importedDatasetSourceFromManifest(manifest);
  if (
    current?.kind === "IMPORTED_DATASET"
    && current.datasetId === next.datasetId
    && current.dataEpoch === next.dataEpoch
  ) {
    return;
  }
  if (current?.kind === "IMPORTED_DATASET" && current.datasetId === next.datasetId) {
    dispatch({ type: "source/revisionChanged", source: next });
    return;
  }
  dispatch({ type: "source/select", source: next });
}

export default function StrategyResearchApp({
  intent,
  libraryEnabled = RESEARCH_DATA_LIBRARY_ENABLED,
}: {
  intent: StrategyResearchLaunchIntent;
  libraryEnabled?: boolean;
}) {
  const locale = useLocale();
  const availability = useNativeAvailability();
  const [selectedNativeMode, setNativeMode] = useState<boolean | null>(["advanced", "deep-link", "handoff"].includes(intent.kind) ? false : null);
  const nativeMode = selectedNativeMode ?? availability === "available";
  const [nativeRun, setNativeRun] = useState<import("../backtest/native/nativeBacktestApi.js").NativeRun | null>(null);
  const pageExportRef = useRef<HTMLDivElement | null>(null);
  const { settings, setSettings, resolvedTheme } = useChartSettingsRuntime();
  const library = useResearchDataLibrary();
  const handoff = useMemo(() => intent.kind === "handoff" ? readResearchHandoff(intent.id) : null, [intent]);
  const [runtime] = useState(() => {
    const created = new StrategyResearchRuntime({
      libraryEnabled,
      restoreWorkspace: intent.kind === "restore",
    });
    for (const action of strategyResearchLaunchActions(intent)) {
      created.dispatch(action);
    }
    if (handoff) {
      created.dispatch({ type: "source/select", source: handoff.source });
      created.dispatch({ type: "script/setDraft", draftId: handoff.draftId });
      created.dispatch({ type: "script/configure", configuration: handoff.configuration });
      if (handoff.runId) created.dispatch({ type: "result/setRun", runId: handoff.runId });
    }
    return created;
  });
  const [, bump] = useReducer((value: number) => value + 1, 0);
  const state: StrategyResearchState = runtime.state;
  useEffect(() => {
    if (intent.kind === "handoff" && handoff) window.history.replaceState(null, "", "/strategy.html");
  }, [handoff, intent.kind]);
  const visualState = strategyResearchVisualState(intent, state);
  const dispatch = useCallback((action: Parameters<StrategyResearchRuntime["dispatch"]>[0]) => {
    const previous = runtime.state;
    runtime.dispatch(action);
    if (runtime.state !== previous) bump();
  }, [runtime]);

  const launchImported = intent.kind === "imported" || intent.kind === "import";
  const source = state.source.source;
  const launchImportedBoundRef = useRef(source?.kind === "IMPORTED_DATASET");
  const {
    datasets: libraryDatasets,
    loadingLibrary: libraryLoading,
    selectedId: librarySelectedId,
    setSelectedId: setLibrarySelectedId,
  } = library;

  useEffect(() => {
    if (libraryLoading) return;
    const preferred = preferredLibrarySelectedId(source, libraryDatasets);
    if (preferred !== null && preferred !== librarySelectedId) {
      setLibrarySelectedId(preferred);
    }
  }, [libraryDatasets, libraryLoading, librarySelectedId, setLibrarySelectedId, source]);

  useEffect(() => {
    if (library.loadingLibrary || launchImportedBoundRef.current) return;
    if (!launchImported) return;
    if (source !== null) {
      launchImportedBoundRef.current = true;
      return;
    }
    if (library.selected === null) return;
    launchImportedBoundRef.current = true;
    dispatchImportedSource(dispatch, source, library.selected);
  }, [dispatch, launchImported, library.loadingLibrary, library.selected, source]);

  const [networkDiagnostics, setNetworkDiagnostics] = useState<StrategyResearchNetworkDiagnostics | null>(null);
  const [hostReady, setHostReady] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void loadStrategyResearchHostHealth(controller.signal).then((health) => {
      runtime.runtimeMode = health.runtimeMode;
      setHostReady(true);
      setNetworkDiagnostics(health.network);
      bump();
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      console.error("Strategy research host health failed", reason);
    });
    return () => controller.abort();
  }, [runtime]);

  const selectCurrentChart = useCallback(() => {
    return;
  }, []);

  const onSelectKind = useCallback((kind: ResearchSourceKind) => {
    if (kind === "CURRENT_CHART") {
      return;
    }
    dispatch({ type: "source/libraryOpen", open: true });
    if (kind === "IMPORTED_DATASET" && library.selected !== null) {
      dispatchImportedSource(dispatch, runtime.state.source.source, library.selected);
    }
  }, [dispatch, library.selected, runtime]);

  const onSelectDataset = useCallback((datasetId: string) => {
    const dataset = library.datasets.find((entry) => entry.dataset_id === datasetId);
    if (dataset === undefined) return;
    dispatchImportedSource(dispatch, runtime.state.source.source, dataset);
    dispatch({ type: "source/libraryOpen", open: false });
  }, [dispatch, library.datasets, runtime]);

  const handleRevisionActivated = useCallback((manifest: LocalDatasetManifest) => {
    const current = runtime.state.source.source;
    if (current?.kind !== "IMPORTED_DATASET") return;
    if (current.datasetId !== manifest.dataset_id) {
      setLibrarySelectedId(current.datasetId);
      return;
    }
    dispatchImportedSource(dispatch, current, manifest);
  }, [dispatch, runtime, setLibrarySelectedId]);

  const importedManifest = importedManifestForSource(source, library.selected);

  const { intervalScope, selectedInterval, handleIntervalSelect } = useLocalIntervalSelection(
    importedManifest,
    (message) => library.setError(message),
  );

  const analysisStore = useMemo(() => importedManifest === null ? null : new LocalAnalysisEventStore({
    datasetId: importedManifest.dataset_id,
    dataEpoch: importedManifest.data_epoch,
  }), [importedManifest]);
  const subscribeAnalysis = useCallback((listener: () => void) => (
    analysisStore?.subscribe(listener) ?? (() => undefined)
  ), [analysisStore]);
  const getAnalysisSnapshot = useCallback(() => (
    analysisStore?.getSnapshot() ?? EMPTY_LOCAL_ANALYSIS_SNAPSHOT
  ), [analysisStore]);
  const analysisSnapshot = useSyncExternalStore(
    subscribeAnalysis,
    getAnalysisSnapshot,
    () => EMPTY_LOCAL_ANALYSIS_SNAPSHOT,
  );

  const chartUiScope = importedManifest === null
    ? ""
    : `${importedManifest.dataset_id}:${importedManifest.data_epoch}:${selectedInterval ?? ""}`;
  const [indicatorPanel, setIndicatorPanel] = useState({ scope: "", open: false });
  const [indicatorCount, setIndicatorCount] = useState({ scope: "", count: 0 });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [crosshair, setCrosshair] = useState<{
    scope: string;
    value: MainSeriesCrosshairValue | null;
  }>({ scope: "", value: null });
  const [focusedAnalysis, setFocusedAnalysis] = useState<{
    scope: string;
    value: LocalAnalysisFocusRequest | null;
  }>({ scope: "", value: null });
  const indicatorPanelOpen = indicatorPanel.scope === chartUiScope && indicatorPanel.open;
  const activeIndicatorCount = indicatorCount.scope === chartUiScope ? indicatorCount.count : 0;
  const lastCrosshair = crosshair.scope === chartUiScope ? crosshair.value : null;
  const focusRequest = focusedAnalysis.scope === chartUiScope ? focusedAnalysis.value : null;

  const focusAnalysisEvent = useCallback((event: LocalAnalysisEvent) => {
    setFocusedAnalysis((current) => ({
      scope: chartUiScope,
      value: {
        requestId: (current.scope === chartUiScope ? current.value?.requestId ?? 0 : 0) + 1,
        time: event.time,
      },
    }));
  }, [chartUiScope]);
  const closeIndicatorPanel = useCallback(() => {
    setIndicatorPanel({ scope: chartUiScope, open: false });
  }, [chartUiScope]);
  const handleCrosshairMove = useCallback((value: MainSeriesCrosshairValue | null) => {
    if (value !== null) setCrosshair({ scope: chartUiScope, value });
  }, [chartUiScope]);
  const handleActiveIndicatorCountChange = useCallback((count: number) => {
    setIndicatorCount((current) => (
      current.scope === chartUiScope && current.count === count
        ? current
        : { scope: chartUiScope, count }
    ));
  }, [chartUiScope]);

  const capabilities = useMemo(
    () => (source
      ? runtime.capabilitiesFor(source.kind, locale)
      : runtime.capabilitiesFor("IMPORTED_DATASET", locale)),
    [locale, runtime, source],
  );

  const scriptDraft = state.script.draftId;
  const analysisEvents = importedManifest === null ? [] : analysisSnapshot.events;
  const handleRunId = useCallback((runId: string | null) => {
    dispatch({ type: "result/setRun", runId });
  }, [dispatch]);
  const handleDraftId = useCallback((draftId: string | null) => {
    setNativeMode(false);
    dispatch({ type: "script/setDraft", draftId });
  }, [dispatch]);
  const handleDraftRevision = useCallback((revision: number) => {
    dispatch({ type: "script/setContentRevision", revision });
  }, [dispatch]);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const selectingTemplateRef = useRef(false);
  const selectTemplate = useCallback((templateId: string) => {
    if (selectingTemplateRef.current) return;
    selectingTemplateRef.current = true;
    setSavingTemplate(true);
    void saveResearchTemplate(getChartStrategyDraftStore(), templateId).then((draft) => {
      dispatch({ type: "script/setDraft", draftId: draft.id });
      dispatch({ type: "source/libraryOpen", open: true });
    }).catch(() => library.setError(t("chartTester.autosave.error"))).finally(() => {
      selectingTemplateRef.current = false;
      setSavingTemplate(false);
    });
  }, [dispatch, library]);
  const researchRun = useStrategyResearchRun({
    source,
    imported: importedManifest,
    interval: source?.kind === "CURRENT_CHART" ? source.interval : selectedInterval,
    runtimeMode: hostReady ? runtime.runtimeMode : "LOCAL_OFFLINE",
    draftId: state.script.draftId,
    draftContentRevision: state.script.contentRevision,
    configuration: state.script.configuration,
    restoreRunId: state.result.runId,
    onRunId: handleRunId,
  });
  const [advancedError, setAdvancedError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  useEffect(() => { if (researchRun.inputStale && !state.result.stale) dispatch({ type: "result/invalidate" }); }, [dispatch, researchRun.inputStale, state.result.stale]);
  const openAdvanced = useCallback(() => {
    if (researchRun.session === null || source === null) {
      setAdvancedError(t("strategy.advancedNeedSource"));
      return;
    }
    if (state.script.draftId === null) {
      setAdvancedError(t("strategy.advancedNeedDraft"));
      return;
    }
    setAdvancedError(null);
    void createStrategyResearchAdvancedHref({
      source,
      session: researchRun.session,
      draftId: state.script.draftId,
      result: researchRun.result,
      configuration: state.script.configuration,
    }).then((href) => {
      window.location.assign(href);
    }).catch((reason: unknown) => {
      setAdvancedError(reason instanceof Error ? describeError(reason, reason.message) : String(reason));
    });
  }, [researchRun.result, researchRun.session, source, state.script.draftId, state.script.configuration]);

  const drawer = (
    <StrategyResearchDrawerBoundary
      fallback={<p className="strategy-research-error" role="alert">{t("strategy.drawerFailed")}</p>}
    >
      <ResearchDataDrawer
        open={state.source.libraryOpen}
        availableKinds={["IMPORTED_DATASET"]}
        runtimeMode={runtime.runtimeMode}
        capabilities={capabilities}
        libraryEnabled={runtime.libraryEnabled}
        library={library}
        settings={settings}
        events={analysisEvents}
        onSelectKind={onSelectKind}
        onSelectDataset={onSelectDataset}
        onRevisionActivated={handleRevisionActivated}
        onSettingsImported={setSettings}
        onImport={async (input) => {
          const dataset = await library.handleImport(input);
          if (dataset) {
            dispatchImportedSource(dispatch, runtime.state.source.source, dataset);
            dispatch({ type: "source/libraryOpen", open: false });
          }
        }}
        onClose={() => dispatch({ type: "source/libraryOpen", open: false })}
      />
    </StrategyResearchDrawerBoundary>
  );

  const script = (
    <div data-strategy-draft={scriptDraft ?? ""}>
      <nav className="native-mode-switch" aria-label={t("native.mode")}>
        <button aria-pressed={nativeMode} onClick={() => setNativeMode(true)}>{t("native.fullStrategies")}</button>
        <button aria-pressed={!nativeMode} onClick={() => setNativeMode(false)}>{t("native.hostMode")}</button>
      </nav>
      {!nativeMode && availability === "error" && <p role="status">{t("indicator.editor.runtimeUnavailableHelp")}</p>}
      {!nativeMode && availability === "unavailable" && <p role="status">{t("native.platformHelp")}</p>}
      {nativeMode ? researchRun.session ? <Suspense fallback={<p>{t("native.loading")}</p>}>
        <NativeStrategyPanel session={researchRun.session} cellScope="strategy-research-native" onClose={() => setNativeMode(false)}
          key={`${chartUiScope}:${researchRun.session.exchange}:${researchRun.session.marketType}:${researchRun.session.symbol}:${researchRun.session.interval}`} externalReport onRunChange={setNativeRun}
          dataset={importedManifest ? { datasetId: importedManifest.dataset_id, dataEpoch: importedManifest.data_epoch } : undefined}
          onLocateTrade={(timeMs) => setFocusedAnalysis((current) => ({ scope: chartUiScope, value: {
            requestId: (current.scope === chartUiScope ? current.value?.requestId ?? 0 : 0) + 1, time: Math.floor(timeMs / 1000),
          } }))} />
      </Suspense> : <p>{t("research.source.none")}</p> :
      <StrategyResearchScriptPanel
        cellScope="strategy-research"
        session={researchRun.session}
        sourceKind={source?.kind ?? null}
        draftId={state.script.draftId}
        barOnly={researchRun.barOnly}
        runStatus={researchRun.runStatus}
        needsData={researchRun.needsData}
        onDraftId={handleDraftId}
        onDraftRevision={handleDraftRevision}
        onRun={researchRun.onRun}
        onConfirmNeedsData={researchRun.onConfirmNeedsData}
        onOpenAdvanced={openAdvanced}
        configuration={state.script.configuration}
        onConfigure={(configuration) => dispatch({ type: "script/configure", configuration })}
      />}
    </div>
  );
  const result = nativeMode ? researchRun.session && nativeRun?.result ? <Suspense fallback={<p>{t("native.loading")}</p>}>
    <div className="native-strategy-report">
      <details><summary>{t("native.source")}</summary><pre>{nativeRun.config?.source}</pre></details>
      <NativeStrategyReport key={nativeRun.run_id} run={nativeRun} onLocate={(timeMs) => setFocusedAnalysis((current) => ({ scope: chartUiScope, value: {
        requestId: (current.scope === chartUiScope ? current.value?.requestId ?? 0 : 0) + 1, time: Math.floor(timeMs / 1000),
      } }))} />
    </div>
  </Suspense> : null : (
    <StrategyResearchResultPanel
      key={researchRun.result?.run.run_id ?? "pending"}
      result={researchRun.result}
      stale={researchRun.stale || state.result.stale}
      staleReasons={researchRun.staleReasons}
      barOnly={researchRun.barOnly}
      error={researchRun.error}
      runStatus={researchRun.runStatus}
      network={networkDiagnostics}
      dataResolution={researchRun.dataResolution}
      onOpenAdvanced={openAdvanced}
      onLocateTrade={(timeMs) => setFocusedAnalysis((current) => ({
        scope: chartUiScope,
        value: {
          requestId: (current.scope === chartUiScope ? current.value?.requestId ?? 0 : 0) + 1,
          time: Math.floor(timeMs / 1000),
        },
      }))}
    />
  );
  const advancedWorkspace = intent.kind === "advanced" || intent.kind === "deep-link";
  const controls = (
    <>
      <button type="button" className="research-header-btn ui-control" onClick={() => setHistoryOpen((open) => !open)} aria-expanded={historyOpen}>{t("ux.history")}</button>
      <button
        type="button"
        className="settings-btn indicator-toggle-btn"
        onClick={() => setSettingsOpen(true)}
        title={t("shell.settings")}
        aria-label={t("shell.settings")}
      >
        <span aria-hidden="true" style={{ display: "flex" }}><CapabilityRailIcon /></span>
      </button>
      <button
        type="button"
        className={`indicator-toggle-btn ${indicatorPanelOpen ? "active" : ""}`}
        disabled={importedManifest === null}
        onClick={() => setIndicatorPanel({ scope: chartUiScope, open: !indicatorPanelOpen })}
        title={t("shell.indicators")}
        aria-label={t("shell.indicators")}
      >
        <span aria-hidden="true" style={{ display: "flex" }}><ProfileRailIcon /></span>
        {activeIndicatorCount > 0 && (
          <span className="indicator-badge">{activeIndicatorCount}</span>
        )}
      </button>
    </>
  );
  const extraSurfaces = (
    <>
      {historyOpen && <aside className="research-data-drawer" role="dialog" aria-label={t("ux.history")}>
        <header><strong>{t("ux.history")}</strong><button type="button" onClick={() => setHistoryOpen(false)}>{t("backtest.close")}</button></header>
        <Suspense fallback={<p>{t("research.loading")}</p>}><StrategyRunHistory draftId={state.script.draftId} currentRunId={researchRun.result?.run.run_id ?? null} onOpen={(runId) => { dispatch({ type: "result/viewHistory", runId }); setHistoryOpen(false); }} /></Suspense>
        <Suspense fallback={null}><PreparationJobsPanel /></Suspense>
      </aside>}
      {intent.kind === "handoff" && !handoff && <p role="alert">{t("ux.handoffMissing")}</p>}
      {(intent.page === "local" || intent.page === "backtest") ? (
        <StrategyResearchCompatNotice page={intent.page} />
      ) : null}
      {library.error !== null && (
        <div className="local-global-error" role="alert">
          <span>{library.error}</span>
          <button type="button" onClick={() => library.setError(null)}>{t("backtest.close")}</button>
        </div>
      )}
      {advancedError !== null && (
        <div className="local-global-error" role="alert" data-testid="strategy-research-advanced-error">
          <span>{advancedError}</span>
          <button type="button" onClick={() => setAdvancedError(null)}>{t("backtest.close")}</button>
        </div>
      )}
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={settings}
        onUpdate={setSettings}
        currentSymbol={importedManifest?.symbol ?? ""}
        currentMarketType={importedManifest?.dataset_id ?? "local"}
        currentExchange="local"
        allowedCategories={["appearance", "about"]}
        backendFeaturesEnabled={false}
        dataWorkbenchEnabled={false}
      />
    </>
  );

  const shellShared = {
    visualState,
    source,
    ...(importedManifest ? { sourceLabel: `${importedManifest.name} · ${importedManifest.symbol}` }
      : source?.kind === "CURRENT_CHART" ? { sourceLabel: `${source.symbol} · ${source.interval} · ${source.exchange}` } : {}),
    libraryEnabled: runtime.libraryEnabled,
    libraryOpen: state.source.libraryOpen,
    currentChartEnabled: false,
    onOpenLibrary: () => dispatch({ type: "source/libraryOpen", open: true }),
    onSelectCurrentChart: selectCurrentChart,
    pageExportRef,
    controls,
    runtimeMode: runtime.runtimeMode,
    drawer,
    script,
    result,
    extraSurfaces,
  };

  if (intent.kind === "invalid") {
    return (
      <StrategyResearchShell
        {...shellShared}
        intervalSelector={null}
        toolbar={null}
        exportOverlay={null}
        chart={(
          <p className="strategy-research-error" role="alert" data-testid="strategy-research-deep-link-error">
            {intent.message}
          </p>
        )}
        analysis={null}
      />
    );
  }

  if (advancedWorkspace) {
    const advancedSearch = strategyResearchDeepLinkSearch(intent);
    // Advanced research owns its data, navigation and status. Nesting another
    // workspace here both reports an unrelated empty source and constrains it.
    return (
      <section className="strategy-research-advanced" data-testid="strategy-research-advanced">
        <MarketDataWorkspaceProvider>
          <Suspense fallback={<main className="research-status-page" data-state="loading" />}>
            {advancedSearch === null
              ? <BacktestResearchApp />
              : <BacktestResearchApp search={advancedSearch} />}
          </Suspense>
        </MarketDataWorkspaceProvider>
        {(intent.page === "local" || intent.page === "backtest") && (
          <StrategyResearchCompatNotice page={intent.page} />
        )}
      </section>
    );
  }

  if (importedManifest !== null && analysisStore !== null && selectedInterval !== null) {
    const analysis = (
      <ImportedAnalysisPanel
        manifest={importedManifest}
        snapshot={analysisSnapshot}
        eventStore={analysisStore}
        crosshair={lastCrosshair}
        onFocus={focusAnalysisEvent}
        onError={library.setError}
      />
    );
    return (
      <StrategyResearchImportedWorkspace
        key={importedManifest.data_epoch}
        manifest={importedManifest}
        interval={selectedInterval}
        indicatorPresets={library.indicatorPresets}
        eventStore={analysisStore}
        focusRequest={focusRequest}
        indicatorPanelOpen={indicatorPanelOpen}
        onCloseIndicatorPanel={closeIndicatorPanel}
        onCrosshairMove={handleCrosshairMove}
        onActiveIndicatorCountChange={handleActiveIndicatorCountChange}
        pageExportRef={pageExportRef}
        settings={settings}
        onSettingsChange={setSettings}
        resolvedTheme={resolvedTheme}
      >
        {({ toolbar, exportOverlay, chart, indicatorPanel }) => (
          <StrategyResearchShell
            {...shellShared}
            intervalSelector={(
              <ImportedDatasetIntervalStrip
                manifest={importedManifest}
                interval={selectedInterval}
                intervalScope={intervalScope}
                onSelect={handleIntervalSelect}
              />
            )}
            toolbar={toolbar}
            exportOverlay={exportOverlay}
            chart={chart}
            analysis={analysis}
            extraSurfaces={(
              <>
                {extraSurfaces}
                {indicatorPanel}
              </>
            )}
          />
        )}
      </StrategyResearchImportedWorkspace>
    );
  }

  return (
    <StrategyResearchShell
      {...shellShared}
      intervalSelector={null}
      toolbar={null}
      exportOverlay={null}
      chart={
        source?.kind === "CURRENT_CHART"
          ? hostReady && runtime.runtimeMode === "LIVE" && researchRun.session
            ? <MarketDataWorkspaceProvider><Suspense fallback={<p>{t("research.loading")}</p>}><StrategyResearchLiveChart session={researchRun.session} result={nativeMode ? null : researchRun.result} focusRequest={focusRequest} /></Suspense></MarketDataWorkspaceProvider>
            : <StrategyResearchCurrentChart />
          : (
            <StrategyResearchFirstOpen
              libraryEnabled={runtime.libraryEnabled}
              runtimeMode={runtime.runtimeMode}
              draftId={state.script.draftId}
              saving={savingTemplate}
              onSelectTemplate={selectTemplate}
              onOpenLibrary={() => dispatch({ type: "source/libraryOpen", open: true })}
            />
          )
      }
      analysis={null}
    />
  );
}
