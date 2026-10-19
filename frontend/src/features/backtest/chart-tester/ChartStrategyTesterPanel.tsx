import { useNativeAvailability, resolveAvailableStrategyMode } from "../native/useNativeAvailability.js";
import { resolveStrategyTesterMode } from "./chartStrategyMode.js";
import type { NativeStrategyCollection } from "../native/nativeStrategyCollection.js";
import type { StrategyTradeFocus } from "./strategyTradeReview.js";
import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import type { ChartSession } from "../../chart-session/chartSessionTypes.js";
import type { ChartStrategyAttachmentRecord } from "../../chart-workspace/chartWorkspaceTypes.js";
import type { ChartContextResolution } from "../backtestApi.js";
import type { RecentRunCompareV1 } from "../backtestTypes.js";
import { t } from "../../../i18n/index.js";
import { PineLibraryInputs } from "../../indicators/PineLibraryInputs.js";
import { StrategyLanguageControls } from "./StrategyLanguageControls.js";
import { strategyLanguageLabel } from "./strategyLanguageLabel.js";
import { StrategyConditionsEditor } from "./StrategyConditionsEditor.js";
import { StrategyParametersEditor } from "./StrategyParametersEditor.js";
import { validStrategyRunSettings } from "../../../shared/strategyRunSettings.js";
import { useLocale } from "../../../i18n/useLocale.js";
import {
  pendingStrategyDraftSave,
  type StrategyDraftAutoSaveState,
  type StrategyDraftCursor,
  type StrategyDraftRecord,
  type StrategyDraftStore,
} from "./StrategyDraftStore.js";
import {
  openPythonStrategyDraft,
  createChartStrategyDraftId,
  strategyDraftContentRevision,
} from "./chartStrategyTesterDrafts.js";
import { chartStrategyQuickPresetIdForMarket } from "./chartStrategyRunRequest.js";
import {
  CHART_STRATEGY_TEMPLATES,
  diagnoseChartStrategyDraft,
  type ChartStrategyDraftIssue,
  type ChartStrategyRunRequest,
  type ChartStrategyTesterEntryState,
} from "./chartStrategyTesterUiModel.js";
import type {
  ChartStrategyTesterState,
  ChartStrategyTesterStatus,
} from "./chartStrategyTesterState.js";
import type { ChartStrategyResultBundle } from "./chartStrategyResultCache.js";
import type { ChartStrategyAutoRunPauseReason } from "./chartStrategyAutoRunCoordinator.js";
import {
  ChartStrategyResultContextBar,
  ChartStrategyResultOverview,
  ChartStrategyTradeList,
  TradeExplanationPopover,
  type TradeExplanationSelection,
} from "./ChartStrategyResultViews.js";
import {
  CHART_STRATEGY_MAX_PANEL_HEIGHT,
  CHART_STRATEGY_MIN_PANEL_HEIGHT,
  clampChartStrategyPanelHeight,
  loadChartStrategyPanelPreferences,
  saveChartStrategyPanelPreferences,
  type ChartStrategyPanelTab,
} from "./chartStrategyPanelPreferences.js";

import {
  chartStrategyMaxDrawdown,
  chartStrategyMetricValue,
  chartStrategyWinRate,
  formatChartStrategyNumber,
} from "./chartStrategyResultModel.js";
import { Icon } from "../../../components/icons/Icon.js";
import {
  nativeStrategySwitcherActions,
  nativeStrategySwitcherItems,
  useNativeStrategyCollection,
} from "../native/useNativeStrategyCollection.js";

import StrategyDock from "./StrategyDock.js";
import { StrategyDockPane, StrategyDockSlot } from "./StrategyDockSlots.js";
import { StrategySwitcher, type StrategySwitcherItem } from "./StrategySwitcher.js";

const StrategyScriptWorkspace = lazy(() => import("./StrategyScriptWorkspace.js"));
const NativeStrategyPanel = lazy(() => import("../native/NativeStrategyPanel.js"));

type PanelTab = ChartStrategyPanelTab;
const PANEL_TABS: readonly PanelTab[] = ["overview", "trades", "script", "settings"];

const MIN_PANEL_HEIGHT = CHART_STRATEGY_MIN_PANEL_HEIGHT;
const MAX_PANEL_HEIGHT = CHART_STRATEGY_MAX_PANEL_HEIGHT;

function clampPanelHeight(value: number): number {
  return clampChartStrategyPanelHeight(value);
}

function attachmentForDraft(
  record: StrategyDraftRecord,
  session: ChartSession,
): ChartStrategyAttachmentRecord {
  return {
    schemaVersion: 1,
    strategyDraftId: record.id,
    strategyRevisionId: null,
    displayName: record.displayName,
    language: record.language,
    parameters: {},
    rangeMode: "ALL_AVAILABLE",
    customRange: null,
    fidelityPreference: "FAST",
    quickPresetId: chartStrategyQuickPresetIdForMarket(session.marketType),
    autoRun: record.language !== "python",
  };
}

function issueCopy(issue: ChartStrategyDraftIssue): { title: string; detail: string } {
  if (issue.code === "EMPTY_SOURCE") {
    return { title: t("chartTester.issue.emptyTitle"), detail: t("chartTester.issue.emptyDetail") };
  }
  if (issue.code === "UNDECLARED_TARGET") {
    return {
      title: t("chartTester.issue.location", { line: issue.line, column: issue.column }),
      detail: t("chartTester.issue.unknownVariable", { variable: issue.variable ?? "target" }),
    };
  }
  if (issue.code === "SERVER_DIAGNOSTIC") {
    return {
      title: t("chartTester.issue.location", { line: issue.line, column: issue.column }),
      detail: issue.message || t("chartTester.issue.serverDetail"),
    };
  }
  return {
    title: t("chartTester.issue.location", { line: issue.line, column: issue.column }),
    detail: t("chartTester.issue.delimiter", { delimiter: issue.variable ?? "?" }),
  };
}

function runStatusKey(status: ChartStrategyTesterStatus) {
  switch (status) {
    case "DETACHED": return "chartTester.status.detached" as const;
    case "RESOLVING": return "chartTester.status.resolving" as const;
    case "NEEDS_DATA": return "chartTester.status.needs_data" as const;
    case "READY": return "chartTester.status.ready" as const;
    case "QUEUED": return "chartTester.status.queued" as const;
    case "RUNNING": return "chartTester.status.running" as const;
    case "COMPLETED": return "chartTester.status.completed" as const;
    case "STALE": return "chartTester.status.stale" as const;
    case "FAILED": return "chartTester.status.failed" as const;
    case "UNSUPPORTED": return "chartTester.status.unsupported" as const;
  }
}

function autoRunPauseKey(reason: ChartStrategyAutoRunPauseReason) {
  switch (reason) {
    case "FLAG_DISABLED": return "chartTester.autoRun.pause.flag" as const;
    case "USER_DISABLED": return "chartTester.autoRun.pause.user" as const;
    case "WAITING_DEBOUNCE": return "chartTester.autoRun.pause.debounce" as const;
    case "WORKSPACE_QUEUE": return "chartTester.autoRun.pause.queue" as const;
    case "PRECISE_REQUIRES_MANUAL": return "chartTester.autoRun.pause.precise" as const;
    case "NEEDS_DATA_CONFIRMATION": return "chartTester.autoRun.pause.data" as const;
    case "UNSUPPORTED_CONTEXT": return "chartTester.autoRun.pause.unsupported" as const;
    case "BACKEND_BUSY": return "chartTester.autoRun.pause.busy" as const;
    case "DRAFT_UNAVAILABLE": return "chartTester.autoRun.pause.draft" as const;
  }
}

export interface ChartStrategyTesterPanelProps {
  cellScope: string;
  session: ChartSession;
  attachment: ChartStrategyAttachmentRecord | null;
  nativeStrategies?: NativeStrategyCollection | undefined;
  strategyTesterMode?: "NATIVE" | "CANDLESCOPE" | undefined;
  onStrategyTesterModeChange?(value: "NATIVE" | "CANDLESCOPE"): void;
  onNativeStrategiesChange?(value: NativeStrategyCollection): void;
  draftStore: StrategyDraftStore;
  onAttachmentChange(attachment: ChartStrategyAttachmentRecord | null): void;
  onEntryStateChange(state: ChartStrategyTesterEntryState): void;
  onRunRequest(request: ChartStrategyRunRequest): void;
  runState: ChartStrategyTesterState;
  resolution: ChartContextResolution | null;
  sourceDiagnostics: Array<Record<string, unknown>>;
  pendingDataDraftRevision: number | null;
  result?: ChartStrategyResultBundle | null;
  resultLoading?: boolean;
  resultError?: string | null;
  comparison?: RecentRunCompareV1 | null;
  autoRunPauseReason?: ChartStrategyAutoRunPauseReason | null;
  selectedExplanation?: TradeExplanationSelection | null;
  onSelectExplanation?(selection: TradeExplanationSelection): void;
  onCloseExplanation?(): void;
  onLocateTrade?(timeMs: number): void;
  active?: boolean;
  onReviewTrade?(trade: StrategyTradeFocus | null): void;
  onPrepareData(): void;
  onStopObserving(): void;
  onResumeObserving(): void;
  onSourceDirty(): void;
  onClose(): void;
  onOpenAdvanced?(): void;
  onOpenBatchStudy?(): void;
  onOpenWorkspace?(): void;
}

const HOST_STRATEGY_ID = "__candlescope_host__";

export default function ChartStrategyTesterPanel(props: ChartStrategyTesterPanelProps) {
  const [localMode, setMode] = useState(() => resolveStrategyTesterMode(props.strategyTesterMode, !!props.attachment));
  const availability = useNativeAvailability();
  const [modeChosen, setModeChosen] = useState(false);
  const mode = resolveAvailableStrategyMode(props.strategyTesterMode ?? localMode, availability, modeChosen);
  const [visited, setVisited] = useState(() => new Set([mode]));
  const strategies = useNativeStrategyCollection(props.nativeStrategies, props.onNativeStrategiesChange, props.cellScope);
  useLocale();
  const switchMode = (next: typeof mode) => {
    setModeChosen(true);
    setMode(next);
    props.onStrategyTesterModeChange?.(next);
    setVisited((items) => new Set([...items, mode, next]));
  };
  // The host-matching tester is one more strategy on this chart, not a separate mode to learn.
  const items: StrategySwitcherItem[] = [
    ...nativeStrategySwitcherItems(strategies),
    {
      id: HOST_STRATEGY_ID,
      name: props.attachment?.displayName ?? t("native.hostMode"),
      meta: props.attachment ? t("native.hostMode") : "",
      running: ["RESOLVING", "QUEUED", "RUNNING"].includes(props.runState.status),
    },
  ];
  const actions = nativeStrategySwitcherActions(strategies)
    .filter((action) => mode === "NATIVE" || action.id === "add" || action.id === "compare")
    .map((action) => ({ ...action, onSelect: () => { switchMode("NATIVE"); action.onSelect(); } }));
  const identity = <StrategySwitcher items={items} actions={actions}
    activeId={mode === "NATIVE" ? strategies.collection.activeId : HOST_STRATEGY_ID}
    onSelect={(id) => {
      if (id === HOST_STRATEGY_ID) { switchMode("CANDLESCOPE"); return; }
      strategies.select(id);
      switchMode("NATIVE");
    }}
    renaming={mode === "NATIVE" && strategies.renaming} onRename={strategies.rename} />;
  return <StrategyDock key={props.cellScope} scope={props.cellScope} identity={identity} onClose={props.onClose}>
    {(mode === "NATIVE" || visited.has("NATIVE")) && <StrategyDockPane hidden={mode !== "NATIVE"}>
      <Suspense fallback={<p className="strategy-dock-empty">{t("native.loading")}</p>}>
        <NativeStrategyPanel key={`${props.session.exchange}:${props.session.marketType}:${props.session.symbol}:${props.session.interval}`} {...props}
          onSelectPython={() => {
            void openPythonStrategyDraft(props.draftStore, props.attachment?.strategyDraftId ?? null).then((record) => {
              props.onAttachmentChange(attachmentForDraft(record, props.session));
              switchMode("CANDLESCOPE");
            });
          }}
          strategies={strategies} active={props.active !== false && mode === "NATIVE"} docked />
      </Suspense>
    </StrategyDockPane>}
    {(mode === "CANDLESCOPE" || visited.has("CANDLESCOPE")) && <StrategyDockPane hidden={mode !== "CANDLESCOPE"}>
      {availability === "error" && <StrategyDockSlot name="notice"><p className="strategy-notice" data-tone="info" role="status">{t("indicator.editor.runtimeUnavailableHelp")}</p></StrategyDockSlot>}
      {availability === "unavailable" && <StrategyDockSlot name="notice"><p className="strategy-notice" data-tone="info" role="status">{t("native.platformHelp")}</p></StrategyDockSlot>}
      <CandleScopeStrategyTesterPanel {...props} active={props.active !== false && mode === "CANDLESCOPE"} />
    </StrategyDockPane>}
  </StrategyDock>;
}

export function CandleScopeStrategyTesterPanel({
  cellScope,
  session,
  attachment,
  draftStore,
  onAttachmentChange,
  onEntryStateChange,
  onRunRequest,
  runState,
  resolution,
  sourceDiagnostics,
  pendingDataDraftRevision,
  result = null,
  resultLoading = false,
  resultError = null,
  comparison = null,
  autoRunPauseReason = null,
  selectedExplanation = null,
  onSelectExplanation = () => undefined,
  onCloseExplanation = () => undefined,
  onLocateTrade = () => undefined,
  onReviewTrade,
  active = true,
  onPrepareData,
  onStopObserving,
  onResumeObserving,
  onSourceDirty,
  onClose,
  onOpenAdvanced,
  onOpenBatchStudy,
  onOpenWorkspace,
}: ChartStrategyTesterPanelProps) {
  const locale = useLocale();
  const [focusMode, setFocusMode] = useState(false);
  const [height, setHeight] = useState(() => loadChartStrategyPanelPreferences(cellScope).height);
  const [activeTab, setActiveTab] = useState<PanelTab>(() => (
    attachment ? loadChartStrategyPanelPreferences(cellScope).activeTab : "script"
  ));
  const currentAttachment = attachment;
  const [draft, setDraft] = useState<StrategyDraftRecord | null>(null);
  const activeDraft = draft?.id === currentAttachment?.strategyDraftId ? draft : null;
  const [source, setSource] = useState("");
  const [pythonApproval, setPythonApproval] = useState<string | null>(null);
  const approvalKey = JSON.stringify([draft?.id, source]);
  const pythonTrustedConfirmed = pythonApproval === approvalKey;
  const [cursor, setCursor] = useState<StrategyDraftCursor | null>(null);
  const [saveState, setSaveState] = useState<StrategyDraftAutoSaveState>("IDLE");
  const [issues, setIssues] = useState<ChartStrategyDraftIssue[]>([]);
  const [focusIssue, setFocusIssue] = useState<ChartStrategyDraftIssue | null>(null);
  const [focusOnMount, setFocusOnMount] = useState(false);
  const [runReady, setRunReady] = useState(false);
  const [recentDrafts, setRecentDrafts] = useState<StrategyDraftRecord[]>([]);
  const resizeCleanupRef = useRef<(() => void) | null>(null);
  const pendingSaveRef = useRef<{
    draft: StrategyDraftRecord | null;
    source: string;
    cursor: StrategyDraftCursor | null;
  }>({ draft: null, source: "", cursor: null });
  useLayoutEffect(() => {
    pendingSaveRef.current = { draft: activeDraft, source, cursor };
  }, [activeDraft, cursor, source]);

  useEffect(() => () => resizeCleanupRef.current?.(), []);
  useEffect(() => {
    saveChartStrategyPanelPreferences(cellScope, { height, activeTab });
  }, [activeTab, cellScope, height]);
  const resultCacheKey = result?.cacheKey ?? null;
  useEffect(() => {
    if (!resultCacheKey) return undefined;
    const timer = window.setTimeout(() => setActiveTab("overview"), 0);
    return () => window.clearTimeout(timer);
  }, [resultCacheKey]);
  useEffect(() => {
    const flushPending = () => {
      const input = pendingStrategyDraftSave(pendingSaveRef.current);
      if (!input) return;
      void draftStore.save(input).catch(() => undefined);
    };
    window.addEventListener("beforeunload", flushPending);
    return () => {
      window.removeEventListener("beforeunload", flushPending);
      flushPending();
    };
  }, [draftStore]);

  useEffect(() => {
    const draftId = currentAttachment?.strategyDraftId;
    if (!draftId) return undefined;
    let cancelled = false;
    void draftStore.load(draftId).then((view) => {
      if (cancelled || !view.record) return;
      setDraft(view.record);
      setSource(view.record.source);
      setCursor(view.record.cursor);
      setIssues(diagnoseChartStrategyDraft(view.record.source));
      setSaveState(view.saveState);
    });
    const unsubscribe = draftStore.subscribe((id, view) => {
      if (id !== draftId || !view.record) return;
      setDraft(view.record);
      setSaveState(view.saveState);
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [currentAttachment?.strategyDraftId, draftStore]);

  useEffect(() => {
    if (!activeDraft
      || pendingStrategyDraftSave({ draft: activeDraft, source, cursor }) === null) return undefined;
    const timer = window.setTimeout(() => {
      void draftStore.save({
        id: activeDraft.id,
        displayName: activeDraft.displayName,
        language: activeDraft.language,
        source,
        cursor,
      }).catch(() => undefined);
    }, 550);
    return () => window.clearTimeout(timer);
  }, [activeDraft, cursor, draftStore, source]);

  useEffect(() => {
    if (!activeDraft) return undefined;
    const timer = window.setTimeout(() => setIssues(diagnoseChartStrategyDraft(source)), 320);
    return () => window.clearTimeout(timer);
  }, [activeDraft, source]);

  const serverIssues = useMemo<ChartStrategyDraftIssue[]>(() => sourceDiagnostics.map((item) => ({
    code: "SERVER_DIAGNOSTIC",
    line: Math.max(1, Number(item.line ?? 1)),
    column: Math.max(1, Number(item.column ?? 1)),
    endColumn: Math.max(2, Number(item.column ?? 1) + 1),
    variable: null,
    message: String(item.message ?? t("chartTester.issue.serverDetail")),
  })), [sourceDiagnostics]);
  const visibleIssues = activeDraft ? [...issues, ...serverIssues] : [];

  useEffect(() => {
    const primaryServerIssue = serverIssues[0];
    if (!primaryServerIssue) return;
    const timer = window.setTimeout(() => {
      setActiveTab("script");
      setFocusIssue(primaryServerIssue);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [serverIssues]);

  useEffect(() => {
    if (!currentAttachment) onEntryStateChange("unattached");
    else if (visibleIssues.length > 0 || runState.status === "FAILED" || runState.status === "UNSUPPORTED") {
      onEntryStateChange("error");
    }
    else if (saveState === "SAVING") onEntryStateChange("saving");
    else if (runReady || runState.status === "COMPLETED") onEntryStateChange("ready");
    else onEntryStateChange("editing");
  }, [currentAttachment, onEntryStateChange, runReady, runState.status, saveState, visibleIssues.length]);

  const refreshRecent = useCallback(() => {
    void draftStore.recent(8).then(setRecentDrafts).catch(() => setRecentDrafts([]));
  }, [draftStore]);

  useEffect(() => {
    refreshRecent();
  }, [refreshRecent]);

  const attachRecord = useCallback((
    record: StrategyDraftRecord,
    shouldFocus: boolean,
    nextSaveState: StrategyDraftAutoSaveState = "SAVED",
  ) => {
    const nextAttachment = attachmentForDraft(record, session);
    setDraft(record);
    setSource(record.source);
    setCursor(record.cursor);
    setIssues(diagnoseChartStrategyDraft(record.source));
    setSaveState(nextSaveState);
    setActiveTab("script");
    setFocusOnMount(shouldFocus);
    setRunReady(false);
    onAttachmentChange(nextAttachment);
  }, [onAttachmentChange, session]);

  const createDraft = useCallback(async (
    displayName: string,
    sourceText: string,
    shouldFocus: boolean,
    language: StrategyDraftRecord["language"] = "pyne",
  ) => {
    const id = createChartStrategyDraftId();
    try {
      const record = await draftStore.save({
        id,
        displayName,
        language,
        source: sourceText,
        cursor: { line: 1, column: 1 },
      });
      attachRecord(record, shouldFocus);
    } catch {
      const failed = draftStore.snapshot(id);
      if (failed.record) attachRecord(failed.record, shouldFocus, "ERROR");
    }
  }, [attachRecord, draftStore]);

  const run = useCallback(() => {
    if (!activeDraft || !currentAttachment) return;
    if (activeDraft.language === "python" && !pythonTrustedConfirmed) return;
    if (!validStrategyRunSettings({ ...currentAttachment, rangeMode: currentAttachment.rangeMode === "VISIBLE" ? "CUSTOM" : currentAttachment.rangeMode })) {
      setActiveTab("settings");
      return;
    }
    const nextIssues = diagnoseChartStrategyDraft(source, { requireSource: true });
    setIssues(nextIssues);
    setRunReady(false);
    if (nextIssues[0]) {
      setActiveTab("script");
      setFocusIssue(nextIssues[0]);
      onEntryStateChange("error");
      return;
    }
    onRunRequest({
      cellScope,
      session: { ...session },
      draftId: activeDraft.id,
      draftContentRevision: strategyDraftContentRevision(source),
      displayName: activeDraft.displayName,
      language: activeDraft.language,
      pythonTrustedConfirmed,
      source,
      attachment: {
        ...currentAttachment,
        parameters: { ...currentAttachment.parameters },
        quickPresetId: chartStrategyQuickPresetIdForMarket(session.marketType),
      },
    });
    setRunReady(true);
    onEntryStateChange("ready");
  }, [activeDraft, cellScope, currentAttachment, onEntryStateChange, onRunRequest, session, source, pythonTrustedConfirmed]);

  const retrySave = useCallback(() => {
    if (!activeDraft) return;
    void draftStore.save({
      id: activeDraft.id,
      displayName: activeDraft.displayName,
      language: activeDraft.language,
      source,
      cursor,
    }).catch(() => undefined);
  }, [activeDraft, cursor, draftStore, source]);

  const beginResize = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = height;
    const handleMove = (moveEvent: PointerEvent) => {
      setHeight(clampPanelHeight(startHeight + startY - moveEvent.clientY));
    };
    const finish = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", finish);
      resizeCleanupRef.current = null;
    };
    resizeCleanupRef.current?.();
    resizeCleanupRef.current = finish;
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", finish, { once: true });
  }, [height]);

  const handleResizeKey = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    const delta = event.key === "ArrowUp" ? 16 : event.key === "ArrowDown" ? -16 : 0;
    if (delta !== 0) {
      event.preventDefault();
      setHeight((current) => clampPanelHeight(current + delta));
    } else if (event.key === "Home") {
      event.preventDefault();
      setHeight(MIN_PANEL_HEIGHT);
    } else if (event.key === "End") {
      event.preventDefault();
      setHeight(clampPanelHeight(MAX_PANEL_HEIGHT));
    }
  }, []);

  const saveLabel = useMemo(() => {
    if (!currentAttachment) return t("chartTester.autosave.none");
    if (saveState === "ERROR") return t("chartTester.autosave.error");
    if (saveState === "SAVING") return t("chartTester.autosave.saving");
    if (activeDraft && activeDraft.source !== source) return t("chartTester.autosave.editing");
    return t("chartTester.autosave.saved");
  }, [activeDraft, currentAttachment, saveState, source]);

  const panelStyle = { "--chart-strategy-panel-height": `${height}px` } as CSSProperties;
  const showEditor = activeTab === "script" && activeDraft !== null;
  const runBusy = ["RESOLVING", "QUEUED", "RUNNING"].includes(runState.status);
  const pendingDataMatchesSource = runState.status === "NEEDS_DATA"
    && pendingDataDraftRevision === strategyDraftContentRevision(source);
  const runLabel = pendingDataMatchesSource
    ? t("chartTester.prepareDataRun")
    : runState.status === "RESOLVING"
      ? t("chartTester.run.resolving")
      : runState.status === "QUEUED"
        ? t("chartTester.run.queued")
        : runState.status === "RUNNING"
          ? t("chartTester.run.running")
          : t("chartTester.run");
  const canResume = Boolean(runState.activeRunId)
    && !runBusy
    && runState.status !== "COMPLETED";
  const costPreset = resolution?.cost_preset;
  const accountPreset = resolution?.account_execution_preset;
  const rangeText = resolution?.coverage.requested_start_ms != null
    && resolution.coverage.requested_end_ms != null
    ? t("chartTester.settings.dateAbsolute", {
      start: new Date(resolution.coverage.requested_start_ms).toLocaleDateString(locale),
      end: new Date(resolution.coverage.requested_end_ms).toLocaleDateString(locale),
    })
    : currentAttachment?.rangeMode === "ALL_AVAILABLE"
      ? t("chartTester.settings.allAvailable")
      : t("chartTester.settings.selectedRange");
  const actionableCopy = useMemo(() => {
    const code = runState.actionableError?.code ?? "";
    if (!code) return null;
    if (code.includes("FEE") || code.includes("PRESET")) {
      return { message: t("chartTester.error.fee"), action: t("chartTester.error.action.settings") };
    }
    if (code.includes("INTERVAL")) {
      return { message: t("chartTester.error.interval"), action: t("chartTester.error.action.interval") };
    }
    if (code.includes("FIDELITY")) {
      return { message: t("chartTester.error.fidelity"), action: t("chartTester.error.action.fast") };
    }
    if (code.includes("PROVIDER") || code.includes("SMOKE")) {
      return { message: t("chartTester.error.strategy"), action: t("chartTester.error.action.strategy") };
    }
    if (code.includes("DATA") || code.includes("SNAPSHOT") || code.includes("CONTEXT")) {
      return { message: t("chartTester.error.data"), action: t("chartTester.error.action.retry") };
    }
    if (code.includes("BUDGET") || code === "RUN_CAPACITY_EXCEEDED") {
      return { message: t("chartTester.error.busy"), action: t("chartTester.error.action.wait") };
    }
    return { message: t("chartTester.error.backend"), action: t("chartTester.error.action.retry") };
  }, [runState.actionableError?.code]);

  const stale = runState.status === "STALE" || !runState.projectionVisible;
  const saveVisible = currentAttachment !== null && (saveState === "ERROR" || saveState === "SAVING"
    || (activeDraft !== null && activeDraft.source !== source));
  const showStatus = !["READY", "DETACHED", "COMPLETED", "STALE"].includes(runState.status);
  const netPnl = result ? chartStrategyMetricValue(result.report.metrics.realized_net_pnl) : "—";
  const selectTab = (tab: PanelTab, event?: KeyboardEvent<HTMLButtonElement>) => {
    setActiveTab(tab);
    const list = event?.currentTarget.parentElement;
    if (list) requestAnimationFrame(() => list.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus());
  };

  return (
    <section
      id="chart-strategy-tester-panel"
      className="chart-strategy-tester-panel"
      style={panelStyle}
      aria-label={t("chartTester.panelAria")}
      data-chart-strategy-panel
      data-focus-mode={focusMode ? "true" : "false"}
      onKeyDownCapture={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        }
      }}
    >
      <div
        className="chart-strategy-resize-handle"
        role="separator"
        tabIndex={0}
        aria-label={t("chartTester.resize")}
        aria-orientation="horizontal"
        aria-valuemin={MIN_PANEL_HEIGHT}
        aria-valuemax={MAX_PANEL_HEIGHT}
        aria-valuenow={height}
        onPointerDown={beginResize}
        onKeyDown={handleResizeKey}
      />
      {currentAttachment && <StrategyDockSlot name="tabs">
        <div className="strategy-tabs" role="tablist" aria-label={t("chartTester.tabsAria")}>
          {PANEL_TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={activeTab === tab}
              tabIndex={activeTab === tab ? 0 : -1}
              onClick={() => selectTab(tab)}
              onKeyDown={(event) => {
                if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                event.preventDefault();
                const direction = event.key === "ArrowRight" ? 1 : -1;
                selectTab(PANEL_TABS[(PANEL_TABS.indexOf(tab) + direction + PANEL_TABS.length) % PANEL_TABS.length]!, event);
              }}
            >
              {t(`chartTester.tab.${tab}`)}
            </button>
          ))}
        </div>
      </StrategyDockSlot>}
      <StrategyDockSlot name="actions">
        <div className="strategy-dock-run">
          {result && (
            <button type="button" className="strategy-summary" data-stale={stale} onClick={() => setActiveTab("overview")}
              title={stale ? t("chartTester.result.stale") : t("chartTester.tab.overview")}>
              <span><small>{t("chartTester.result.netPnl")}</small><b className={Number(netPnl) < 0 ? "negative" : Number(netPnl) > 0 ? "positive" : undefined}>{formatChartStrategyNumber(result.report.metrics.realized_net_pnl)}</b></span>
              <span><small>{t("chartTester.result.maxDrawdown")}</small><b>{chartStrategyMaxDrawdown(result.report)}</b></span>
              <span><small>{t("chartTester.result.winRate")}</small><b>{chartStrategyWinRate(result.report.metrics.win_rate, locale)}</b></span>
            </button>
          )}
          {saveVisible && <span className={`chart-strategy-autosave state-${saveState.toLowerCase()}`}>{saveLabel}</span>}
          {saveState === "ERROR" && (
            <button type="button" className="strategy-dock-button" onClick={retrySave}>{t("chartTester.retrySave")}</button>
          )}
          {currentAttachment && showStatus && (
            <span role="status" className="strategy-run-status" data-status={runState.status.toLowerCase()} data-testid="chart-strategy-run-status">
              <i aria-hidden="true" />{t(runStatusKey(runState.status))}
            </span>
          )}
          {runBusy && runState.activeRunId && (
            <button type="button" className="strategy-dock-button" data-testid="chart-strategy-stop-observing" onClick={onStopObserving}>
              {t("chartTester.stopObserving")}
            </button>
          )}
          {canResume && (
            <button type="button" className="strategy-dock-button" onClick={onResumeObserving}>{t("chartTester.resumeObserving")}</button>
          )}
          {currentAttachment && (
            <button
              type="button"
              className="chart-strategy-run-button strategy-run-button"
              disabled={runBusy || (activeDraft?.language === "python" && !pythonTrustedConfirmed)}
              data-run-status={runState.status}
              onClick={pendingDataMatchesSource ? onPrepareData : run}
            >
              <Icon name="play" size={11} filled />{runLabel}
            </button>
          )}
          {currentAttachment && (
            <details className="strategy-dock-more">
              <summary aria-label={t("report.more")} title={t("report.more")}><Icon name="more" size={14} /></summary>
              <div role="menu">
                {onOpenWorkspace && <button type="button" role="menuitem" onClick={() => {
                  if (!activeDraft) return;
                  void draftStore.save({ id: activeDraft.id, displayName: activeDraft.displayName, language: activeDraft.language, source, cursor })
                    .then(onOpenWorkspace).catch(() => setSaveState("ERROR"));
                }}>{t("ux.openWorkspace")}</button>}
                {onOpenAdvanced && <button type="button" role="menuitem" onClick={onOpenAdvanced}>{t("chartTester.openAdvanced")}</button>}
                <button type="button" role="menuitemcheckbox" aria-checked={focusMode}
                  onClick={() => setFocusMode((focused) => !focused)}>{t("chartTester.focusMode")}</button>
              </div>
            </details>
          )}
        </div>
      </StrategyDockSlot>
      <StrategyDockSlot name="notice">
        {currentAttachment && autoRunPauseReason && (
          <div className="strategy-notice" data-tone="warning" role="status" data-auto-run-pause={autoRunPauseReason}>
            <strong>{t("chartTester.autoRun.paused")}</strong>
            <span>{t(autoRunPauseKey(autoRunPauseReason))}</span>
          </div>
        )}
        {!result && resultLoading && (
          <div className="strategy-notice" data-tone="info" role="status">{t("chartTester.result.loading")}</div>
        )}
        {!result && resultError && (
          <div className="strategy-notice" data-tone="error" role="alert">
            <strong>{t("chartTester.result.unavailable")}</strong>
            <span>{resultError}</span>
          </div>
        )}
      </StrategyDockSlot>

      <div className="chart-strategy-tester-body" role={currentAttachment ? "tabpanel" : undefined}>
        {!currentAttachment && (
          <div className="chart-strategy-start">
            <p className="chart-strategy-start-lead">{t("chartTester.startLead", { symbol: session.symbol, interval: session.interval })}</p>
            <div className="chart-strategy-start-columns">
              <section aria-label={t("chartTester.templateTitle")}>
                <h3>{t("chartTester.start.template")}</h3>
                <div className="chart-strategy-start-list">
                  {CHART_STRATEGY_TEMPLATES.map((template) => (
                    <button key={template.id} type="button" onClick={() => void createDraft(template.displayName, template.source, false, template.language)}>
                      <strong>{t(template.nameKey)}</strong>
                      <span>{t(template.descriptionKey)}</span>
                    </button>
                  ))}
                </div>
              </section>
              <section aria-label={t("chartTester.recentTitle")}>
                <h3>{t("chartTester.start.recent")}</h3>
                {recentDrafts.length === 0 ? (
                  <p className="chart-strategy-start-empty">{t("chartTester.recentEmpty")}</p>
                ) : (
                  <div className="chart-strategy-start-list">
                    {recentDrafts.map((record) => (
                      <button key={record.id} type="button" onClick={() => attachRecord(record, false)}>
                        <strong>{record.displayName}</strong>
                        <span>
                          {strategyLanguageLabel(record.language)}
                          {" · "}
                          <time dateTime={new Date(record.updatedAt).toISOString()}>{new Date(record.updatedAt).toLocaleString(locale)}</time>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </section>
            </div>
            <footer className="chart-strategy-start-footer">
              <button type="button" className="strategy-dock-button" onClick={() => void createDraft(t("chartTester.untitled"), "", true)}>
                <Icon name="plus" size={12} />{t("chartTester.start.paste")}
              </button>
              <p className="chart-strategy-privacy">{t("chartTester.privacy")}</p>
              {onOpenAdvanced ? (
                <button type="button" className="chart-strategy-advanced-link" onClick={onOpenAdvanced}>{t("chartTester.openAdvanced")}</button>
              ) : (
                <a href="/backtest.html" className="chart-strategy-advanced-link">{t("chartTester.openAdvanced")}</a>
              )}
            </footer>
          </div>
        )}

        {showEditor && activeDraft && (
          <div className="chart-strategy-editor-layout">
            <section className="chart-strategy-editor-shell" aria-label={t("chartTester.editorAria")}>
              <Suspense fallback={<div className="chart-strategy-editor-loading">{t("chartTester.editorLoading")}</div>}>
                <StrategyScriptWorkspace
                  source={source}
                  language={activeDraft.language}
                  cursor={cursor}
                  issues={visibleIssues}
                  focusIssue={focusIssue}
                  focusOnMount={focusOnMount}
                  onSourceChange={(value) => {
                    setSource(value);
                    setRunReady(false);
                    onSourceDirty();
                  }}
                  onCursorChange={setCursor}
                  onRun={run}
                />
              </Suspense>
            </section>
            <aside className="chart-strategy-problems" aria-label={t("chartTester.problemsAria")}>
              <StrategyLanguageControls language={activeDraft.language} confirmed={pythonTrustedConfirmed} onConfirm={(value) => setPythonApproval(value ? approvalKey : null)} onLanguage={(language) => {
                setPythonApproval(null);
                void draftStore.save({ ...activeDraft, language, source, cursor }).then((record) => attachRecord(record, false));
              }} />
              <StrategyParametersEditor source={source} onChange={(value) => { setSource(value); setRunReady(false); onSourceDirty(); }} />
              <div className="chart-strategy-problems-head">{t("chartTester.problems")}</div>
              <div className="chart-strategy-problems-body">
                {runState.status === "NEEDS_DATA" && resolution && (
                  <p className="chart-strategy-run-detail">{t("chartTester.status.needsDataDetail", {
                    bars: resolution.materialize.estimated_bars ?? t("chartTester.unknown"),
                  })}</p>
                )}
                {actionableCopy && runState.status === "FAILED" && (
                  <p className="chart-strategy-run-detail" data-tone="error">{actionableCopy.message} <small>{actionableCopy.action}</small></p>
                )}
                {visibleIssues.length === 0 ? (
                  <p className="chart-strategy-no-problems">
                    {runReady ? t("chartTester.readyForRun") : t("chartTester.noProblems")}
                  </p>
                ) : (
                  <>
                    <strong className="chart-strategy-problem-count">
                      {t("chartTester.problemCount", { count: visibleIssues.length })}
                    </strong>
                    {visibleIssues.map((issue, index) => {
                      const copy = issueCopy(issue);
                      return (
                        <div className="chart-strategy-problem" key={`${issue.code}:${issue.line}:${issue.column}:${index}`}>
                          <strong>{copy.title}</strong>
                          <p>{copy.detail}</p>
                          <button type="button" onClick={() => setFocusIssue({ ...issue })}>
                            {t("chartTester.goToLine", { line: issue.line })}
                          </button>
                        </div>
                      );
                    })}
                  </>
                )}
              </div>
            </aside>
          </div>
        )}

        {currentAttachment && activeTab === "overview" && (
          result ? (
            <>
              <ChartStrategyResultContextBar
                result={result}
                locale={locale}
                stale={stale}
                {...(onOpenAdvanced ? { onOpenAdvanced } : {})}
              />
              <ChartStrategyResultOverview
                result={result}
                stale={stale}
                comparison={comparison}
                onOpenTrades={() => setActiveTab("trades")}
                {...(onOpenAdvanced ? { onOpenAdvanced } : {})}
              />
            </>
          ) : (
            <div className="chart-strategy-run-overview" data-testid="chart-strategy-run-overview">
              <h2>{t(runStatusKey(runState.status))}</h2>
              <p>{runState.status === "COMPLETED"
                ? t("chartTester.result.loading")
                : runState.status === "NEEDS_DATA" && resolution
                  ? t("chartTester.status.needsDataDetail", { bars: resolution.materialize.estimated_bars ?? t("chartTester.unknown") })
                : t("chartTester.overview.pendingDetail")}</p>
              {runState.status === "NEEDS_DATA" && (
                <div className="chart-strategy-data-recovery">
                  <p>{t("chartTester.settings.date")}: {rangeText}</p>
                  <button type="button" className="strategy-run-button" onClick={onPrepareData} disabled={!pendingDataMatchesSource}>
                    {t("chartTester.prepareDataRun")}
                  </button>
                </div>
              )}
              {actionableCopy && (
                <div className="strategy-notice" data-tone="error">
                  <strong>{actionableCopy.message}</strong>
                  <span>{actionableCopy.action}</span>
                  <details>
                    <summary>{t("chartTester.error.details")}</summary>
                    <code>{runState.actionableError?.code}</code>
                  </details>
                </div>
              )}
            </div>
          )
        )}

        {activeTab === "settings" && currentAttachment && (
          <div className="chart-strategy-settings" data-testid="chart-strategy-quick-settings">
            {activeDraft?.language === "pine" && <PineLibraryInputs
              value={typeof currentAttachment.parameters.__pineLibrariesText === "string"
                ? currentAttachment.parameters.__pineLibrariesText
                : JSON.stringify(currentAttachment.parameters.__pineLibraries ?? {}, null, 2)}
              readOnly={false}
              onChange={(value) => {
                setRunReady(false);
                onSourceDirty();
                onAttachmentChange({ ...currentAttachment,
                  parameters: { ...currentAttachment.parameters, __pineLibrariesText: value } });
              }} />}
            <StrategyConditionsEditor
              settings={{ ...currentAttachment, rangeMode: currentAttachment.rangeMode === "VISIBLE" ? "CUSTOM" : currentAttachment.rangeMode }}
              marketType={session.marketType}
              onChange={(settings) => { const { executionOverrides: _previous, ...base } = currentAttachment; void _previous; onAttachmentChange({ ...base, ...settings }); }}
            />
            <section className="strategy-settings-section">
              <label className="strategy-settings-check chart-strategy-auto-run-setting">
                <input
                  type="checkbox"
                  checked={currentAttachment.autoRun}
                  onChange={(event) => onAttachmentChange({
                    ...currentAttachment,
                    autoRun: event.currentTarget.checked,
                  })}
                />
                <span>{t("chartTester.autoRun.label")}</span>
                <small>{currentAttachment.autoRun
                  ? t(currentAttachment.fidelityPreference === "FAST"
                    ? "chartTester.autoRun.enabled"
                    : "chartTester.autoRun.preciseManual")
                  : t("chartTester.autoRun.disabled")}</small>
              </label>
            </section>
            <details className="strategy-settings-section"><summary>{t("ux.resolvedConditions")}</summary>
              <dl className="chart-strategy-quick-settings">
                <div><dt>{t("chartTester.settings.capital")}</dt><dd>{accountPreset?.initial_cash ?? "10,000"} USDT</dd></div>
                <div><dt>{t("chartTester.settings.position")}</dt><dd>{t("chartTester.settings.positionValue", {
                  percent: accountPreset?.equity_percent ?? "10",
                  leverage: accountPreset?.leverage ?? "1",
                })}</dd></div>
                <div><dt>{t("chartTester.settings.fee")}</dt><dd>{costPreset?.fee_bps
                  ? t("chartTester.settings.feeValue", { fee: costPreset.fee_bps, slippage: costPreset.slippage_bps ?? "—" })
                  : t("chartTester.settings.feePending")}</dd></div>
                <div><dt>{t("chartTester.settings.date")}</dt><dd>{rangeText}</dd></div>
                <div><dt>{t("chartTester.settings.fidelity")}</dt><dd>{currentAttachment.fidelityPreference === "FAST"
                  ? t("chartTester.settings.fast")
                  : t("chartTester.settings.precise")}</dd></div>
              </dl>
              {onOpenBatchStudy && (
                <button type="button" className="chart-strategy-advanced-link" onClick={onOpenBatchStudy}>
                  {t("chartTester.settings.batchStudy")}
                </button>
              )}
            </details>
          </div>
        )}

        <div hidden={!currentAttachment || activeTab !== "trades"}>{result
            ? <ChartStrategyTradeList key={result.run.run_id} active={active && activeTab === "trades"}
              result={result}
              locale={locale}
              onLocateTrade={onLocateTrade}
              {...(onReviewTrade ? { onReviewTrade } : {})}
              onSelectExplanation={onSelectExplanation}
            />
            : (
              <div className="chart-strategy-placeholder">
                <strong>{t("chartTester.tab.trades")}</strong>
                <p>{resultError ?? t("chartTester.placeholder.trades")}</p>
              </div>
            )
        }</div>
      </div>
      {selectedExplanation && (
        <TradeExplanationPopover
          selection={selectedExplanation}
          onClose={onCloseExplanation}
        />
      )}
    </section>
  );
}
