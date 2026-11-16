import { Button, Disclosure, Drawer, InlineAlert, SegmentedControl } from "../../components/ui/index.js";
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
import { createActiveIndicatorPersistence } from "../indicators/activeIndicatorStore.js";
import { getStrategyStorage } from "../../shared/strategyStorage.js";
import { ResearchIndicatorScopeStore } from "./researchIndicatorScope.js";
import { ResearchIndicatorScopeControl } from "./ResearchIndicatorScopeControl.js";
import { useResearchIndicatorScopeResults } from "./useResearchIndicatorScopeResults.js";
import type { ResearchMarketInput } from "./strategyResearchBatch.js";
import { ResearchBatchResults, ResearchBatchSources } from "./ResearchBatchPanel.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { ResearchDataDrawer } from "../research-data/ResearchDataDrawer.js";
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
import { openPythonStrategyDraft, getChartStrategyDraftStore } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import { DEFAULT_STRATEGY_RUN_SETTINGS } from "../../shared/strategyRunSettings.js";
import { ResearchExternalModel } from "./ResearchExternalModel.js";
import { saveResearchTemplate } from "./strategyTemplateDraft.js";
import { readResearchHandoff } from "./strategyResearchHandoff.js";
import ResearchReturnButton from "./ResearchReturnButton.js";
import { StrategyResearchShell } from "./StrategyResearchShell.js";
import type { NativeFeedbackStatus } from "../backtest/native/nativeDiagnostics.js";
import { useStrategyResearchRun } from "./useStrategyResearchRun.js";
import { loadStrategyResearchHostHealth } from "./strategyResearchHostHealth.js";
import type { StrategyResearchNetworkDiagnostics } from "./strategyResearchHostHealth.js";
import { createStrategyResearchContextSearch } from "./strategyResearchAdvanced.js";
import StrategyResearchModeRail from "./StrategyResearchModeRail.js";
import {
  initialStrategyResearchMode,
  isResearchToolMode,
  researchModeForTask,
  researchTaskForMode,
  strategyResearchModeHref,
  STRATEGY_RESEARCH_MODES,
  type StrategyResearchMode,
} from "./strategyResearchMode.js";
import { ResearchModeRailContext } from "../backtest/research/researchModeRailContext.js";
import { StrategyResearchCompatNotice } from "./StrategyResearchCompatNotice.js";
import { ProfileRailIcon } from "../../app/marketRailIcons.js";
import { MarketDataWorkspaceProvider } from "../market-data/MarketDataWorkspaceProvider.js";
import { datasetIdentityChanged } from "../backtest/native/nativeExecutionSettings.js";

const BacktestResearchApp = lazy(() => import("../backtest/research/BacktestResearchApp.js"));
const StrategyResearchLiveChart = lazy(() => import("./StrategyResearchLiveChart.js"));
const NativeStrategyPanel = lazy(() => import("../backtest/native/NativeStrategyPanel.js"));
const NativeStrategyReport = lazy(() => import("../backtest/native/NativeStrategyReport.js").then((module) => ({ default: module.NativeStrategyReport })));
const StrategyResultReplay = lazy(() => import("./StrategyResultReplay.js"));
const StrategyRunHistory = lazy(() => import("./StrategyRunHistory.js"));
const SavedContinuousAccounts = lazy(() => import("../backtest/continuous/SavedContinuousAccounts.js"));
import {
  strategyResearchDeepLinkSearch,
  strategyResearchLaunchActions,
  strategyResearchVisualState,
  type StrategyResearchLaunchIntent,
} from "./strategyResearchLaunch.js";
import type { BacktestResultReplayCursor } from "../backtest/backtestTypes.js";
import { DEFAULT_REPLAY_DISPLAY, replayDisplayKey, type ReplayDisplay } from "./strategyResultReplayDisplay.js";
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

import { useControlCommands, usePageControlBridge } from "../app-control/useControlCommands.js";
import { settingsCommands } from "../app-control/settingsCommands.js";
import { libraryCommands } from "../app-control/libraryCommands.js";
import { command } from "../app-control/commandRegistry.js";
import { bool, choice, object, text } from "../app-control/commandSchema.js";

export default function StrategyResearchApp({
  intent,
  initialMode,
}: {
  intent: StrategyResearchLaunchIntent;
  /** Mode to open in; by default `?mode=` or what the launch intent implies. */
  initialMode?: StrategyResearchMode | null;
}) {
  const locale = useLocale();
  const availability = useNativeAvailability();
  const [selectedNativeMode, setNativeMode] = useState<boolean | null>(["advanced", "deep-link", "handoff"].includes(intent.kind) ? false : null);
  const [projectRestoreRevision, setProjectRestoreRevision] = useState(0);
  const [nativeRun, setNativeRun] = useState<import("../backtest/native/nativeBacktestApi.js").NativeRun | null>(null);
  const [nativeStatus, setNativeStatus] = useState<NativeFeedbackStatus>("idle");
  const pageExportRef = useRef<HTMLDivElement | null>(null);
  const { settings, setSettings, resolvedTheme } = useChartSettingsRuntime();
  const library = useResearchDataLibrary();
  usePageControlBridge();
  useControlCommands(() => settingsCommands({ settings, setSettings, resolvedTheme }, "strategy-settings"));
  useControlCommands(() => libraryCommands(library));
  const handoff = useMemo(() => intent.kind === "handoff" ? readResearchHandoff(intent.id) : null, [intent]);
  const [runtime] = useState(() => {
    const created = new StrategyResearchRuntime({
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
  const nativeMode = selectedNativeMode ?? (availability === "available" && source !== null && state.result.runId === null);
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
  const [indicatorScopes] = useState(() => new ResearchIndicatorScopeStore(getStrategyStorage()));
  const indicatorScopeState = useSyncExternalStore(indicatorScopes.subscribe, indicatorScopes.snapshot, indicatorScopes.snapshot);
  const indicatorResults = useResearchIndicatorScopeResults(indicatorScopeState.scopes, libraryDatasets);
  const localIndicatorPersistence = useMemo(() => importedManifest && createActiveIndicatorPersistence(
    `candlescope:local-indicators:v1:${importedManifest.dataset_id}:${importedManifest.data_epoch}`,
  ), [importedManifest]);
  const scopedIndicatorPersistence = useMemo(() => importedManifest && localIndicatorPersistence
    ? indicatorScopes.chartPersistence(importedManifest, indicatorScopeState.scopes, localIndicatorPersistence)
    : null, [importedManifest, indicatorScopes, indicatorScopeState.scopes, localIndicatorPersistence]);

  const { intervalScope, selectedInterval, handleIntervalSelect } = useLocalIntervalSelection(
    importedManifest,
    (message) => library.setError(message),
  );
  useControlCommands(() => ({ id: "research", title: "Strategy research source and mode",
    context: () => ({ source: state.source.source, nativeMode, selectedInterval }),
    snapshot: () => ({ state, nativeMode, selectedInterval, hostReady, runtimeMode: runtime.runtimeMode }), commands: [
      command("selectDataset", "Bind the research source to a current dataset through the existing drawer action.", object({ datasetId: text(128) }), ({ datasetId }) => {
        if (!library.datasets.some((item) => item.dataset_id === datasetId)) throw new Error("DATASET_UNAVAILABLE");
        library.setSelectedId(datasetId); onSelectDataset(datasetId);
      }),
      command("library", "Open/close the research data drawer.", object({ visible: bool }), ({ visible }) => dispatch({ type: "source/libraryOpen", open: visible })),
      command("nativeMode", "Switch between native strategies and the host strategy panel.", object({ native: bool }), ({ native }) => setNativeMode(native)),
      command("interval", "Select an imported dataset display interval.", object({ interval: text(24) }), ({ interval }) => handleIntervalSelect(interval), { available: () => importedManifest !== null }),
    ] }));

  const analysisStore = useMemo(() => { void projectRestoreRevision; return importedManifest === null ? null : new LocalAnalysisEventStore({
    datasetId: importedManifest.dataset_id,
    dataEpoch: importedManifest.data_epoch,
  }); }, [importedManifest, projectRestoreRevision]);
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
  useEffect(() => {
    let cancelled = false;
    if (scriptDraft) void getChartStrategyDraftStore().load(scriptDraft).then((view) => {
      if (!cancelled && view.record?.language === "python") setNativeMode(false);
    });
    return () => { cancelled = true; };
  }, [scriptDraft]);
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
      setNativeMode(false);
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
    restoreRunId: state.result.replay ? null : state.result.runId,
    onRunId: handleRunId,
  });
  const saveResultReplay = useCallback((replay: BacktestResultReplayCursor) => {
    dispatch({ type: "result/replay", replay });
  }, [dispatch]);
  const saveReplayDisplay = useCallback((key: string, display: ReplayDisplay) => {
    dispatch({ type: "result/replayDisplay", key, display });
  }, [dispatch]);
  const closeResultReplay = useCallback(() => dispatch({ type: "result/replay", replay: null }), [dispatch]);
  const savedResult = researchRun.result;
  const replaySnapshot = savedResult?.run.snapshot_hash;
  const replayReport = savedResult?.report.hashes.report;
  const canReplay = savedResult?.run.state === "COMPLETED"
    && savedResult.run.run_id === state.result.runId
    && savedResult.config.exchange === "local" && savedResult.config.market_type === "spot"
    && savedResult.config.account_model === "SPOT_CASH_V1"
    && (savedResult.run.fidelity_mode === "BAR_APPROX" || (savedResult.run.fidelity_mode === "AGG_TRADE_EXECUTION"
      && savedResult.report.data_quality?.source_quality === "user_market_trades"))
    && typeof replaySnapshot === "string" && typeof replayReport === "string";
  const openResultReplay = () => {
    if (canReplay) saveResultReplay({
      runId: savedResult.run.run_id, snapshotHash: replaySnapshot, reportHash: replayReport,
      cursor: 0, interval: savedResult.chart.interval,
    });
  };
  const [marketInputs, setMarketInputs] = useState<readonly ResearchMarketInput[]>([]);
  const marketBatchAvailable = hostReady && runtime.runtimeMode === "LIVE";
  const batchState = useSyncExternalStore(researchRun.batch.subscribe, researchRun.batch.snapshot, researchRun.batch.snapshot);
  const [batchError, setBatchError] = useState(false);
  const [advancedError, setAdvancedError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [accountsOpen, setAccountsOpen] = useState(false);
  useEffect(() => { if (researchRun.inputStale && !state.result.stale) dispatch({ type: "result/invalidate" }); }, [dispatch, researchRun.inputStale, state.result.stale]);
  // One page, several modes: 快速测试 and the research tools. `researchSearch` is the
  // research tools' launch context or deep link, kept while switching modes.
  const [mode, setMode] = useState<StrategyResearchMode | null>(() => initialMode !== undefined
    ? initialMode
    : initialStrategyResearchMode(intent, typeof window === "undefined" ? "" : window.location.search));
  const [researchSearch, setResearchSearch] = useState<string | null>(() => strategyResearchDeepLinkSearch(intent));
  const [modeSwitching, setModeSwitching] = useState(false);
  const showMode = useCallback((next: StrategyResearchMode, search: string | null) => {
    setMode(next);
    if (typeof window === "undefined") return;
    const params = next === "quick" ? {} : Object.fromEntries(new URLSearchParams(search ?? ""));
    window.history.replaceState(window.history.state, "", strategyResearchModeHref(next, params));
  }, []);
  const switchMode = useCallback((next: StrategyResearchMode) => {
    if (next === mode || modeSwitching) return;
    setAdvancedError(null);
    // Leaving 快速测试 carries its source, strategy draft and latest result to the tools.
    if (mode === "quick" && next !== "quick" && researchRun.session !== null && source !== null && state.script.draftId !== null) {
      setModeSwitching(true);
      void createStrategyResearchContextSearch({
        source,
        session: researchRun.session,
        draftId: state.script.draftId,
        result: researchRun.sourceResult,
        configuration: state.script.configuration,
      }).then((search) => {
        setResearchSearch(search);
        showMode(next, search);
      }).catch((reason: unknown) => {
        setAdvancedError(reason instanceof Error ? describeError(reason, reason.message) : String(reason));
      }).finally(() => setModeSwitching(false));
      return;
    }
    showMode(next, researchSearch);
  }, [mode, modeSwitching, researchRun.session, researchRun.sourceResult, researchSearch, showMode, source, state.script.draftId, state.script.configuration]);
  const openAdvanced = useCallback(() => switchMode("precise"), [switchMode]);
  const modeRail = <StrategyResearchModeRail mode={mode} pending={modeSwitching} onSelect={switchMode} />;

  useControlCommands(() => ({ id: "research-panels", title: "Strategy research panels", context: () => ({ chartUiScope, settingsOpen, indicatorPanel, historyOpen }), snapshot: () => ({ settingsOpen, indicatorPanel, historyOpen, advancedError, mode }), commands: [
    command("settings", "Open/close research settings.", object({ open: bool }), ({ open }) => setSettingsOpen(open)),
    command("indicators", "Open/close the indicator catalog for the selected chart scope.", object({ open: bool }), ({ open }) => setIndicatorPanel({ scope: chartUiScope, open })),
    command("history", "Open/close strategy run history.", object({ open: bool }), ({ open }) => setHistoryOpen(open)),
    command("mode", "Switch the page between 快速测试 and the research tools.", object({ mode: choice(STRATEGY_RESEARCH_MODES) }), ({ mode: next }) => switchMode(next)),
  ] }));
  const drawer = (
    <StrategyResearchDrawerBoundary
      fallback={<InlineAlert tone="danger" className="strategy-research-page-alert">{t("strategy.drawerFailed")}</InlineAlert>}
    >
      <ResearchDataDrawer
        open={state.source.libraryOpen}
        availableKinds={["IMPORTED_DATASET"]}
        runtimeMode={runtime.runtimeMode}
        capabilities={capabilities}
        library={library}
        settings={settings}
        events={analysisEvents}
        onSelectKind={onSelectKind}
        onSelectDataset={onSelectDataset}
        onRevisionActivated={handleRevisionActivated}
        onSettingsImported={setSettings}
        onProjectRestored={(manifest) => { dispatchImportedSource(dispatch, runtime.state.source.source, manifest); setProjectRestoreRevision((revision) => revision + 1); }}
        onMarketTradesImported={async (dataset) => {
          await library.refresh(dataset.dataset_id);
          dispatchImportedSource(dispatch, runtime.state.source.source, dataset);
          dispatch({ type: "source/libraryOpen", open: false });
        }}
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

  const [externalVisited, setExternalVisited] = useState(false);
  const [externalOpen, setExternalOpen] = useState(false);
  const script = (
    <div data-strategy-draft={scriptDraft ?? ""}>
      <SegmentedControl
        className="strategy-research-engine-switch"
        size="sm"
        fullWidth
        label={t("native.mode")}
        value={nativeMode ? "native" : "host"}
        onChange={(value) => setNativeMode(value === "native")}
        options={[
          { value: "native", label: t("native.fullStrategies") },
          { value: "host", label: t("native.hostMode") },
        ]}
      />
      {!nativeMode && availability === "error" && <p className="strategy-research-note" role="status">{t("indicator.editor.runtimeUnavailableHelp")}</p>}
      {!nativeMode && availability === "unavailable" && <p className="strategy-research-note" role="status">{t("native.platformHelp")}</p>}
      {nativeMode ? researchRun.session ? <Suspense fallback={<p className="strategy-research-note">{t("native.loading")}</p>}>
        <NativeStrategyPanel session={researchRun.session} cellScope="strategy-research-native" onClose={() => setNativeMode(false)}
          onSelectPython={() => {
            void openPythonStrategyDraft(getChartStrategyDraftStore(), scriptDraft).then((draft) => {
              dispatch({ type: "script/setDraft", draftId: draft.id });
              setNativeMode(false);
            });
          }}
          key={`${chartUiScope}:${researchRun.session.exchange}:${researchRun.session.marketType}:${researchRun.session.symbol}:${researchRun.session.interval}`} externalReport onRunChange={setNativeRun} onStatusChange={setNativeStatus}
          dataset={importedManifest ? { datasetId: importedManifest.dataset_id, dataEpoch: importedManifest.data_epoch } : undefined}
          onLocateTrade={(timeMs) => setFocusedAnalysis((current) => ({ scope: chartUiScope, value: {
            requestId: (current.scope === chartUiScope ? current.value?.requestId ?? 0 : 0) + 1, time: Math.floor(timeMs / 1000),
          } }))} />
      </Suspense> : <p className="strategy-research-note">{t("research.source.none")}</p> :
      <StrategyResearchScriptPanel
        cellScope="strategy-research"
        session={researchRun.session}
        sourceKind={source?.kind ?? null}
        draftId={state.script.draftId}
        barOnly={researchRun.barOnly}
        capitalAsset={importedManifest?.instrument?.quote_asset}
        runStatus={researchRun.runStatus}
        needsData={researchRun.needsData}
        onDraftId={handleDraftId}
        onDraftRevision={handleDraftRevision}
        onRun={researchRun.onRun}
        marketBatchAvailable={marketBatchAvailable}
        batchSession={marketBatchAvailable ? marketInputs[0]?.session ?? null : null}
        batchControls={(request) => <ResearchBatchSources datasets={libraryDatasets} precise={state.script.configuration?.fidelityPreference === "PRECISE"}
          marketEnabled={marketBatchAvailable} markets={marketInputs} onMarkets={setMarketInputs}>{(selected, exchange) => <>
          <div className="strategy-research-batch-actions">
            <Button variant="primary" size="sm" disabled={!request || (!exchange.length && selected.length < 2) || batchState.storageFailed}
              onClick={() => {
                if (!request) return;
                setBatchError(false);
                void researchRun.batch.submit(request, selected, exchange).catch(() => setBatchError(true));
              }}>{t("researchBatch.run")}</Button>
            {batchState.jobs.length > 0 && <Button size="sm" variant="ghost" onClick={() => setHistoryOpen(true)}>
              {t("researchBatch.jobs")} · {batchState.jobs.length}
            </Button>}
          </div>
          {batchState.storageFailed ? <InlineAlert tone="danger">{t("researchBatch.storage")}</InlineAlert>
            : batchError && <InlineAlert tone="danger">{t("researchBatch.submitFailed")}</InlineAlert>}
        </>}</ResearchBatchSources>}
        onConfirmNeedsData={researchRun.onConfirmNeedsData}
        onOpenAdvanced={openAdvanced}
        configuration={state.script.configuration}
        onConfigure={(configuration) => dispatch({ type: "script/configure", configuration })}
      />}
      {hostReady && importedManifest && !importedManifest.market_trade_input && selectedInterval && (
        <Disclosure className="strategy-research-external" summary={t("research.external.title")} open={externalOpen} onToggle={(open) => {
          setExternalOpen(open);
          if (open) {
            setExternalVisited(true);
            setNativeMode(false);
          }
        }}>
          {externalVisited && <ResearchExternalModel
            key={chartUiScope}
            manager={researchRun.historyManager}
            dataset={importedManifest}
            interval={selectedInterval}
            settings={state.script.configuration ?? DEFAULT_STRATEGY_RUN_SETTINGS}
            savedRun={savedResult && savedResult.run.run_id === state.result.runId ? savedResult.run : null}
            active={externalOpen}
            runBusy={["RESOLVING", "QUEUED", "RUNNING"].includes(researchRun.runStatus)}
            onRunCreated={handleRunId}
          />}
        </Disclosure>
      )}
    </div>
  );
  const result = nativeMode ? researchRun.session && nativeRun?.result ? <Suspense fallback={<p className="strategy-research-note">{t("native.loading")}</p>}>
    <div className="native-strategy-report">
      <Disclosure summary={t("native.source")}><pre className="strategy-research-source">{nativeRun.config?.source}</pre></Disclosure>
      <NativeStrategyReport key={nativeRun.run_id} run={nativeRun}
        stale={datasetIdentityChanged(nativeRun.config, importedManifest ? { datasetId: importedManifest.dataset_id, dataEpoch: importedManifest.data_epoch } : undefined)}
        onLocate={(timeMs) => setFocusedAnalysis((current) => ({ scope: chartUiScope, value: {
        requestId: (current.scope === chartUiScope ? current.value?.requestId ?? 0 : 0) + 1, time: Math.floor(timeMs / 1000),
      } }))} />
    </div>
  </Suspense> : null : (
    <>
    {researchRun.result?.run.state === "COMPLETED" && <ResearchReturnButton key={researchRun.result.run.run_id}
      runId={researchRun.result.run.run_id} origin={handoff ? { workspaceId: handoff.source.workspaceId, cellId: handoff.source.cellId }
        : researchRun.sourceResult && source?.kind === "CURRENT_CHART" ? { workspaceId: source.workspaceId, cellId: source.cellId } : null} />}
    <StrategyResearchResultPanel
      key={researchRun.result?.run.run_id ?? "pending"}
      result={researchRun.result}
      stale={researchRun.stale || state.result.stale}
      staleReasons={researchRun.staleReasons}
      barOnly={researchRun.result ? researchRun.result.run.fidelity_mode === "BAR_APPROX" : researchRun.barOnly}
      error={researchRun.error}
      runStatus={researchRun.runStatus}
      network={networkDiagnostics}
      dataResolution={researchRun.dataResolution}
      onOpenAdvanced={openAdvanced}
      {...(canReplay ? { onOpenReplay: openResultReplay } : {})}
      onLocateTrade={(timeMs) => setFocusedAnalysis((current) => ({
        scope: chartUiScope,
        value: {
          requestId: (current.scope === chartUiScope ? current.value?.requestId ?? 0 : 0) + 1,
          time: Math.floor(timeMs / 1000),
        },
      }))}
    />
    </>
  );
  const header = {
    actions: [
      { id: "saved-accounts", label: t("reader.title"), hasPopup: "dialog" as const, expanded: accountsOpen, onSelect: () => setAccountsOpen((open) => !open) },
      { id: "run-history", label: t("ux.history"), hasPopup: "dialog" as const, expanded: historyOpen, onSelect: () => setHistoryOpen((open) => !open) },
    ],
    panels: (
      <button
        type="button"
        className={`indicator-toggle-btn ${indicatorPanelOpen ? "active" : ""}`}
        disabled={importedManifest === null}
        onClick={() => setIndicatorPanel({ scope: chartUiScope, open: !indicatorPanelOpen })}
        title={t("shell.indicators")}
        aria-label={t("shell.indicators")}
        aria-expanded={indicatorPanelOpen}
      >
        <span aria-hidden="true" style={{ display: "flex" }}><ProfileRailIcon /></span>
        {activeIndicatorCount > 0 && (
          <span className="indicator-badge">{activeIndicatorCount}</span>
        )}
      </button>
    ),
    settings: { onOpen: () => setSettingsOpen(true) },
  };
  const extraSurfaces = (
    <>
      {/* Right-hand drawers on the overlay stack: opening one closes the others. */}
      <Drawer open={accountsOpen} onClose={() => setAccountsOpen(false)} title={t("reader.title")} className="strategy-research-drawer continuous-reader-drawer">
        <Suspense fallback={<p className="strategy-research-note">{t("reader.loading")}</p>}><SavedContinuousAccounts /></Suspense>
      </Drawer>
      <Drawer open={historyOpen} onClose={() => setHistoryOpen(false)} title={t("ux.history")} className="strategy-research-drawer">
        <Suspense fallback={<p className="strategy-research-note">{t("research.loading")}</p>}><StrategyRunHistory manager={researchRun.historyManager} draftId={state.script.draftId} currentRunId={researchRun.result?.run.run_id ?? null} onOpen={(runId) => { dispatch({ type: "result/viewHistory", runId }); setNativeMode(false); setHistoryOpen(false); }} /></Suspense>
        <ResearchBatchResults jobs={batchState.jobs} storageFailed={batchState.storageFailed}
          onResume={(id, retry) => researchRun.batch.resume(id, retry)}
          onOpen={job => {
            if (libraryDatasets.some(dataset => dataset.dataset_id === job.datasetId && dataset.data_epoch === job.dataEpoch)) {
              setLibrarySelectedId(job.datasetId);
              onSelectDataset(job.datasetId);
            }
            if (job.runId) dispatch({ type: "result/viewHistory", runId: job.runId });
            setNativeMode(false);
            setHistoryOpen(false);
          }} />
        <Suspense fallback={null}><PreparationJobsPanel /></Suspense>
      </Drawer>
      {intent.kind === "handoff" && !handoff && <InlineAlert tone="danger" className="strategy-research-page-alert">{t("ux.handoffMissing")}</InlineAlert>}
      {(intent.page === "local" || intent.page === "backtest") ? (
        <StrategyResearchCompatNotice page={intent.page} />
      ) : null}
      {library.error !== null && (
        <InlineAlert tone="danger" className="strategy-research-page-alert"
          action={<Button size="sm" variant="ghost" onClick={() => library.setError(null)}>{t("backtest.close")}</Button>}>
          {library.error}
        </InlineAlert>
      )}
      {advancedError !== null && (
        <InlineAlert tone="danger" className="strategy-research-page-alert"
          action={<Button size="sm" variant="ghost" onClick={() => setAdvancedError(null)}>{t("backtest.close")}</Button>}>
          <span data-testid="strategy-research-advanced-error">{advancedError}</span>
        </InlineAlert>
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
    nativeStatus: nativeMode ? nativeStatus : undefined,
    hostStatus: nativeMode ? undefined : researchRun.error ? "FAILED" as const : researchRun.runStatus,
    source,
    ...(importedManifest ? { sourceLabel: `${importedManifest.name} · ${importedManifest.symbol}` }
      : source?.kind === "CURRENT_CHART" ? { sourceLabel: `${source.symbol} · ${source.interval} · ${source.exchange}` } : {}),
    libraryOpen: state.source.libraryOpen,
    currentChartEnabled: false,
    marketBatchAvailable,
    onOpenLibrary: () => dispatch({ type: "source/libraryOpen", open: true }),
    onSelectCurrentChart: selectCurrentChart,
    pageExportRef,
    header,
    runtimeMode: runtime.runtimeMode,
    drawer,
    script,
    result,
    extraSurfaces,
  };

  const view = (() => {
    if (state.result.replay) {
      const displayKey = replayDisplayKey(state.result.replay);
      return <Suspense fallback={<p className="strategy-research-note" role="status">{t("research.loading")}</p>}>
        <StrategyResultReplay key={displayKey} initial={state.result.replay}
          manager={researchRun.historyManager} datasets={libraryDatasets} onCommit={saveResultReplay} onClose={closeResultReplay}
          display={state.replayDisplays?.[displayKey] ?? DEFAULT_REPLAY_DISPLAY} onDisplay={saveReplayDisplay} />
      </Suspense>;
    }

    if (intent.kind === "invalid") {
      return (
        <StrategyResearchShell
          {...shellShared}
          intervalSelector={null}
          toolbar={null}
          exportOverlay={null}
          chart={(
            <InlineAlert tone="danger" className="strategy-research-page-alert">
              <span data-testid="strategy-research-deep-link-error">{intent.message}</span>
            </InlineAlert>
          )}
          analysis={null}
        />
      );
    }

    if (isResearchToolMode(mode)) {
      // The research tools own their data, navigation and status; the mode rail stays.
      const task = mode === null ? null : researchTaskForMode(mode);
      return (
        <section className="strategy-research-advanced" data-testid="strategy-research-advanced" data-research-mode={mode ?? "pending"}>
          <MarketDataWorkspaceProvider>
            <Suspense fallback={<main className="research-status-page" data-state="loading" />}>
              <BacktestResearchApp
                {...(researchSearch === null ? {} : { search: researchSearch })}
                task={task}
                onTaskResolved={(resolved) => showMode(researchModeForTask(resolved), researchSearch)}
              />
            </Suspense>
          </MarketDataWorkspaceProvider>
          {(intent.page === "local" || intent.page === "backtest") && (
            <StrategyResearchCompatNotice page={intent.page} />
          )}
        </section>
      );
    }

    if (importedManifest !== null && analysisStore !== null && selectedInterval !== null && scopedIndicatorPersistence && localIndicatorPersistence) {
      const analysis = (
        <ImportedAnalysisPanel
          manifest={importedManifest}
          snapshot={analysisSnapshot}
          eventStore={analysisStore}
          crosshair={lastCrosshair}
          onFocus={focusAnalysisEvent}
          onError={library.setError}
          defaultOpen={false}
        />
      );
      return (
        <StrategyResearchImportedWorkspace
          key={`${importedManifest.dataset_id}:${importedManifest.data_epoch}:${projectRestoreRevision}`}
          manifest={importedManifest}
          interval={selectedInterval}
          indicatorPresets={library.indicatorPresets}
          indicatorPersistence={scopedIndicatorPersistence}
          indicatorScopeControls={indicator => <ResearchIndicatorScopeControl indicator={indicator} current={importedManifest}
            datasets={libraryDatasets} targets={indicatorScopeState.scopes.find(scope => scope.indicator.id === indicator.id)?.datasets ?? []}
            results={indicatorResults} storageError={indicatorScopeState.storageError} local={localIndicatorPersistence}
            apply={(definition, current, selected, local) => indicatorScopes.apply(definition, current, selected, local)} />}
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
              ? <MarketDataWorkspaceProvider><Suspense fallback={<p className="strategy-research-note">{t("research.loading")}</p>}><StrategyResearchLiveChart session={researchRun.session} result={nativeMode ? null : researchRun.sourceResult} focusRequest={focusRequest} /></Suspense></MarketDataWorkspaceProvider>
              : <StrategyResearchCurrentChart />
            : (
              <StrategyResearchFirstOpen
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
  })();
  return <ResearchModeRailContext.Provider value={modeRail}>{view}</ResearchModeRailContext.Provider>;
}
