import { diagnosticLocation, nativeRunFeedback, type NativeFeedbackStatus } from "./nativeDiagnostics.js";
import NativeStrategyComparison from "./NativeStrategyComparison.js";
import { recordStrategyRun, strategyRunIds, strategyInstanceScope, type NativeStrategyInstance } from "./nativeStrategyCollection.js";
import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { ChartStrategyTesterPanelProps } from "../chart-tester/ChartStrategyTesterPanel.js";
import type { ChartContextResolution } from "../backtestApi.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { nativeApi, nativeExportUrl, nativeTerminal, nativeTimeframe, type NativeCapabilities, type NativeRun } from "./nativeBacktestApi.js";
import { NativeStrategyReport } from "./NativeStrategyReport.js";
import "./nativeStrategy.css";
import { NativeAdvancedInputs } from "./NativeAdvancedInputs.js";
import { NativePreparationContexts } from "./NativePreparationContexts.js";
import { restorePreparationContexts, restorePreparationDate, type NativePreparationContext } from "./nativePreparationInputs.js";
import { automaticHostExecution, emptyAdvancedInputs, executionInputs, freezeAdvancedInputs, type AdvancedInputs, type InputDataset } from "./nativeInputs.js";
import { PreparationApiError, preparationRequest, waitForPreparation, type PreparationJob, type PreparationCapabilities } from "../../data-preparation/api.js";
import PreparationWaiting from "../../data-preparation/PreparationWaiting.js";
import { Icon } from "../../../components/icons/Icon.js";
import { reportAnalytics } from "./nativeReportAnalytics.js";
import { useNativeStrategyCollection, nativeStrategySwitcherActions, nativeStrategySwitcherItems, type NativeStrategyController } from "./useNativeStrategyCollection.js";
import { StrategyDockPane, StrategyDockSlot } from "../chart-tester/StrategyDockSlots.js";
import { StrategySwitcher } from "../chart-tester/StrategySwitcher.js";
import { strategyLanguageLabel } from "../chart-tester/strategyLanguageLabel.js";
import { datasetIdentityChanged, defaultExecutionDraft, executionSettingsChanged, restoreExecutionDraft, sameExecutionData, type NativeExecutionDraft } from "./nativeExecutionSettings.js";

const StrategyScriptWorkspace = lazy(() => import("../chart-tester/StrategyScriptWorkspace.js"));
import { useControlCommands } from "../../app-control/useControlCommands.js";
import { command, contextReference } from "../../app-control/commandRegistry.js";
import { array, bool, choice, empty, nullable, number as controlNumber, object, optional, record, text } from "../../app-control/commandSchema.js";
import { readControlFile, publishControlFile } from "../../app-control/controlFiles.js";

const NATIVE_TEMPLATES = {
  pine: '//@version=6\nstrategy("Native SMA", overlay=true, initial_capital=10000)\nfast = ta.sma(close, 3)\nslow = ta.sma(close, 5)\nif ta.crossover(fast, slow)\n    strategy.entry("L", strategy.long)\nif ta.crossunder(fast, slow)\n    strategy.close("L")\nplot(fast)\nplot(slow)\n',
};
const SESSION_TABS = ["overview", "trades", "script", "settings", "history"] as const;
const ignoreCursor = () => undefined;

type NativeStrategyPanelProps = Pick<ChartStrategyTesterPanelProps, "session" | "cellScope" | "onClose" | "onLocateTrade" | "onReviewTrade" | "active" | "nativeStrategies" | "onNativeStrategiesChange"> & {
  dataset?: { datasetId: string; dataEpoch: string } | undefined;
  onRunChange?: (run: NativeRun | null) => void;
  onStatusChange?: (status: NativeFeedbackStatus) => void;
  externalReport?: boolean;
  docked?: boolean;
  onSelectPython?(): void;
  /** Supplied by the chart dock, which shows the strategy list in its header. */
  strategies?: NativeStrategyController;
};
export default function NativeStrategyPanel(props: NativeStrategyPanelProps) {
  useLocale();
  const own = useNativeStrategyCollection(props.nativeStrategies, props.onNativeStrategiesChange, props.cellScope);
  const strategies = props.strategies ?? own;
  const { collection, comparing } = strategies;
  const onStatusChange = props.onStatusChange;
  useEffect(() => {
    if (comparing || !collection.items.length) onStatusChange?.("idle");
  }, [comparing, collection.items.length, onStatusChange]);
  const contextParts = [props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval];
  const context = JSON.stringify(contextParts);
  useControlCommands(() => ({ id: `strategies:${props.cellScope}`, title: "Native strategy collection",
    context: () => ({ session: props.session, collection }),
    snapshot: () => ({ collection, storageError: strategies.storageError }), commands: [
      command("select", "Select a saved strategy instance.", object({ id: text(128) }), ({ id }) => {
        if (!collection.items.some((item) => item.id === id)) throw new Error("STRATEGY_UNAVAILABLE");
        strategies.select(id);
      }),
      command("add", "Create a strategy instance.", empty, () => strategies.add(false)),
      command("copy", "Copy the selected strategy and drafts.", empty, () => strategies.add(true), { available: () => !!strategies.selected }),
      command("rename", "Rename the selected strategy.", object({ name: text(80) }), ({ name }) => strategies.rename(name), { available: () => !!strategies.selected }),
      command("remove", "Remove an idle strategy instance.", empty, strategies.remove, { available: () => !!strategies.selected && !strategies.isBusy(strategies.selected.id) }),
      command("comparison", "Show or hide strategy comparison.", object({ visible: bool }), ({ visible }) => strategies.setComparing(visible)),
    ] }), props.active !== false);

  return <>
    {!props.strategies && <div className="native-strategy-collection">
      <StrategySwitcher items={nativeStrategySwitcherItems(strategies)} activeId={collection.activeId} onSelect={strategies.select}
        actions={nativeStrategySwitcherActions(strategies)} renaming={strategies.renaming} onRename={strategies.rename} />
    </div>}
    {strategies.storageError && <p role="alert">{strategies.storageError}</p>}
    <StrategyDockPane hidden={!comparing}>
      <StrategyDockSlot name="tabs"><strong className="strategy-dock-view-title">{t("strategyCompare.title")}</strong></StrategyDockSlot>
      <StrategyDockSlot name="actions"><button type="button" className="strategy-dock-button" onClick={() => strategies.setComparing(false)}>{t("chartTester.close")}</button></StrategyDockSlot>
      <NativeStrategyComparison items={collection.items}
        context={contextParts}
        saved={collection.comparisons?.[context]}
        onSave={(selection) => strategies.update((value) => ({ ...value, comparisons: { ...value.comparisons, [context]: selection } }))}
        onOpen={strategies.select} />
    </StrategyDockPane>
    {!collection.items.length && !comparing && <div className="strategy-dock-empty">
      <p>{t("strategyDock.empty")}</p>
      <button type="button" className="strategy-run-button" onClick={() => strategies.add(false)}><Icon name="plus" size={13} />{t("strategyCollection.add")}</button>
    </div>}
    {collection.items.map((item) => <StrategyDockPane key={item.id} hidden={comparing || item.id !== collection.activeId}>
      <NativeStrategyInstancePanel {...props} instance={item} onInstanceChange={strategies.updateInstance} onInstanceBusy={strategies.setInstanceBusy}
        cellScope={strategyInstanceScope(props.cellScope, item.id)} active={props.active !== false && !comparing && item.id === collection.activeId} />
    </StrategyDockPane>)}
  </>;
}
type InstanceProps = NativeStrategyPanelProps & {
  instance: NativeStrategyInstance;
  onInstanceChange(id: string, change: Partial<NativeStrategyInstance>): void;
  onInstanceBusy(id: string, busy: boolean): void;
};
function NativeStrategyInstancePanel(props: InstanceProps) {
  const [mode, setMode] = useState<"NATIVE" | "CANDLESCOPE">(props.instance.executionMode ?? "NATIVE");
  const [visited, setVisited] = useState(() => new Set([mode]));
  const switchMode = (next: typeof mode) => { props.onInstanceChange(props.instance.id, { executionMode: next }); setMode(next); setVisited((items) => new Set([...items, next])); };
  return <>{([...visited]).map((item) => <StrategyDockPane key={item} hidden={mode !== item}>
    <NativeStrategySession {...props} active={(props.active ?? true) && mode === item} executionMode={item} onExecutionModeChange={switchMode} />
  </StrategyDockPane>)}</>;
}
function NativeStrategySession(props: InstanceProps & { executionMode: "NATIVE" | "CANDLESCOPE"; onExecutionModeChange(mode: "NATIVE" | "CANDLESCOPE"): void }) {
  const locale = useLocale();
  const tabStorageKey = `candlescope.native-tab:${props.cellScope}:${props.executionMode}`;
  const [tab, setTab] = useState<"script" | "settings" | "overview" | "trades" | "history">(() => {
    try { const saved = localStorage.getItem(tabStorageKey) ?? localStorage.getItem(`candlescope.native-tab:${props.cellScope}`); return saved === "settings" || saved === "overview" || saved === "trades" || saved === "history" ? saved : "script"; } catch { return "script"; }
  });
  const navigationRevision = useRef(0);
  const pendingOverview = useRef<number | null>(null);
  const selectTab = useCallback((next: typeof tab) => {
    navigationRevision.current += 1;
    setTab(next);
    try { localStorage.setItem(tabStorageKey, next); } catch { /* Best effort. */ }
  }, [tabStorageKey]);
  const scrollPane = useRef<HTMLDivElement>(null);
  const scrollPositions = useRef<Partial<Record<typeof tab, number>>>({});
  useLayoutEffect(() => {
    if (scrollPane.current) scrollPane.current.scrollTop = scrollPositions.current[tab] ?? 0;
  }, [tab]);
  // A strategy has one selected language. Both execution panes stay mounted;
  // separate local selections let a hidden pane disagree with the switcher and
  // resurrect a different language when its mode becomes visible.
  const language = props.instance.language;
  const mode = props.executionMode;
  const importedDatasetId = props.dataset?.datasetId;
  const [hostSettings, setHostSettings] = useState(() => defaultExecutionDraft().hostSettings);
  const [fidelity, setFidelity] = useState("BAR_APPROX");
  const [fillRecalculation, setFillRecalculation] = useState(false);
  const [executionData, setExecutionData] = useState<unknown>(null);
  const [executionOrigin, setExecutionOrigin] = useState("");
  const [executionDataState, setExecutionDataState] = useState<"ready" | "loading" | "invalid" | "missing">("ready");
  const executionUpload = useRef(0);
  const [executionInputKey, setExecutionInputKey] = useState(0);
  const runPath = mode === "NATIVE" ? "/native/runs" : "/external/runs";
  const [source, setSource] = useState(NATIVE_TEMPLATES.pine);
  const [advanced, setAdvanced] = useState<AdvancedInputs>(emptyAdvancedInputs);
  const [parameters, setParameters] = useState("{}");
  const [capabilities, setCapabilities] = useState<NativeCapabilities | null>(null);
  const [run, setRun] = useState<NativeRun | null>(null);
  const [previousRun, setPreviousRun] = useState<NativeRun | null>(null);
  const [history, setHistory] = useState<NativeRun[]>([]);
  const [allHistory, setAllHistory] = useState(false);
  const [historicalRun, setHistoricalRun] = useState<NativeRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorFocus, setErrorFocus] = useState<{ line: number; column: number } | null>(null);
  const [resolution, setResolution] = useState<ChartContextResolution | null>(null);
  const [automatic, setAutomatic] = useState(false);
  const [automaticContexts, setAutomaticContexts] = useState<NativePreparationContext[]>([]);
  const [preparation, setPreparation] = useState<PreparationJob | null>(null);
  const [historyStart, setHistoryStart] = useState(() => new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10));
  const [historyEnd, setHistoryEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const preparationObserver = useRef<AbortController | null>(null);
  const preparationSubmission = useRef<{ body: string; key: string } | null>(null);
  const alive = useRef(true);
  const legacyStorageKey = `candlescope.native-draft:${props.cellScope}:${language}`;
  const storageKey = `${legacyStorageKey}:${mode}`;
  const executionDraftKey = `execution:${language}:${mode}`;
  const onRunChange = props.onRunChange;
  useEffect(() => { if (props.active !== false) onRunChange?.(historicalRun ?? run); }, [historicalRun, run, onRunChange, props.active]);
  const instanceRef = useRef(props.instance);
  instanceRef.current = props.instance;
  const patchInstance = useRef(props.onInstanceChange);
  patchInstance.current = props.onInstanceChange;
  useEffect(() => {
    const draft = restoreExecutionDraft(instanceRef.current.drafts[executionDraftKey]);
    setHostSettings(draft.hostSettings); setFidelity(draft.fidelity); setFillRecalculation(draft.fillRecalculation);
    executionUpload.current += 1;
    setExecutionInputKey((key) => key + 1);
    setExecutionData(null); setExecutionDataState(draft.uploaded ? "missing" : "ready");
  }, [executionDraftKey]);
  const saveExecution = (change: Partial<NativeExecutionDraft>) => {
    const draft: NativeExecutionDraft = { hostSettings, fidelity, fillRecalculation,
      uploaded: executionData !== null || executionDataState !== "ready", ...change };
    patchInstance.current(instanceRef.current.id, { drafts: { [executionDraftKey]: JSON.stringify(draft) } });
  };
  const runContext = JSON.stringify([mode, props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval]);
  const { onInstanceBusy } = props;
  const instanceId = props.instance.id;
  useEffect(() => { onInstanceBusy(`${instanceId}:${mode}`, busy); return () => onInstanceBusy(`${instanceId}:${mode}`, false); }, [busy, onInstanceBusy, instanceId, mode]);
  const receiveRun = useCallback((value: NativeRun) => {
    const item = instanceRef.current;
    if (item.runs[runContext] !== value.run_id || !item.runHistory?.[runContext]?.includes(value.run_id)) patchInstance.current(item.id, recordStrategyRun(item, runContext, value.run_id));
    setRun(value); setBusy(!nativeTerminal(value.state));
    if (nativeTerminal(value.state)) {
      setHistory((items) => [value, ...items.filter((item) => item.run_id !== value.run_id)]);
      if (value.state === "COMPLETED" && pendingOverview.current === navigationRevision.current) selectTab("overview");
      pendingOverview.current = null;
    }
  }, [selectTab, runContext]);
  useEffect(() => {
    const saved = instanceRef.current.runs[runContext];
    if (!saved) return;
    setBusy(true);
    const abort = new AbortController();
    void nativeApi<NativeRun>(`${runPath}/${encodeURIComponent(saved)}`, undefined, undefined, abort.signal)
      .then((value) => { if (!abort.signal.aborted) receiveRun(value); })
      .catch((reason) => { if (!abort.signal.aborted) { setError(String(reason)); setBusy(false); } });
    return () => abort.abort();
  }, [runContext, runPath, receiveRun]);
  useEffect(() => {
    alive.current = true;
    void nativeApi<NativeCapabilities>("/native/capabilities").then(setCapabilities).catch((reason) => setError(String(reason)));
    void preparationRequest<PreparationCapabilities>("/capabilities").then((value) => { if (alive.current) setAutomatic(value.enabled); }).catch(() => {});
    return () => { alive.current = false; preparationObserver.current?.abort(); };
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    void nativeApi<{ runs: NativeRun[] }>(runPath, undefined, undefined, abort.signal).then(async (value) => {
      const listed = new Set(value.runs.map((item) => item.run_id));
      const missing = [...strategyRunIds(instanceRef.current, mode)].filter((id) => !listed.has(id));
      const restored = await Promise.all(missing.map((id) => nativeApi<NativeRun>(`${runPath}/${encodeURIComponent(id)}`, undefined, undefined, abort.signal).catch(() => null)));
      if (abort.signal.aborted) return;
      setHistory((items) => [...new Map([...value.runs, ...restored.filter((item): item is NativeRun => item !== null), ...items].map((item) => [item.run_id, item])).values()]);
    })
      .catch((reason) => { if (!abort.signal.aborted) setError(String(reason)); });
    return () => abort.abort();
  }, [runPath, mode]);
  useEffect(() => {
    const defaultStart = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
    const defaultEnd = new Date().toISOString().slice(0, 10);
    try { const saved = instanceRef.current.drafts[`${language}:${mode}`] ?? localStorage.getItem(storageKey) ?? localStorage.getItem(legacyStorageKey); const draft: unknown = saved ? JSON.parse(saved) : null;
      if (saved && !instanceRef.current.drafts[`${language}:${mode}`]) patchInstance.current(instanceRef.current.id, { drafts: { [`${language}:${mode}`]: saved } });
      setSource(draft && typeof draft === "object" && "source" in draft && typeof draft.source === "string" ? draft.source : NATIVE_TEMPLATES[language]);
      setParameters(draft && typeof draft === "object" && "parameters" in draft && typeof draft.parameters === "string" ? draft.parameters : "{}");
      setAutomaticContexts(restorePreparationContexts(draft && typeof draft === "object" && "automaticContexts" in draft ? draft.automaticContexts : null));
      setHistoryStart(restorePreparationDate(draft && typeof draft === "object" && "historyStart" in draft ? draft.historyStart : null, defaultStart));
      setHistoryEnd(restorePreparationDate(draft && typeof draft === "object" && "historyEnd" in draft ? draft.historyEnd : null, defaultEnd));
      setExecutionOrigin(draft && typeof draft === "object" && "executionOrigin" in draft && draft.executionOrigin === "binance-futures"
        && "executionOriginDataset" in draft && draft.executionOriginDataset === importedDatasetId ? draft.executionOrigin : "");
    } catch { setSource(NATIVE_TEMPLATES[language]); setParameters("{}"); setAutomaticContexts([]); setHistoryStart(defaultStart); setHistoryEnd(defaultEnd); setExecutionOrigin(""); }
    setAdvanced(emptyAdvancedInputs());
  }, [storageKey, legacyStorageKey, language, mode, importedDatasetId]);
  useEffect(() => { setResolution(null); }, [props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval]);
  const save = (text: string, params: string, contexts = automaticContexts, start = historyStart, end = historyEnd, origin = executionOrigin) => {
    setSource(text); setParameters(params);
    const draft = JSON.stringify({ source: text, parameters: params, automaticContexts: contexts, historyStart: start, historyEnd: end,
      executionOrigin: origin, executionOriginDataset: importedDatasetId });
    const item = instanceRef.current;
    patchInstance.current(item.id, { drafts: { [`${language}:${mode}`]: draft } });
    try { localStorage.setItem(storageKey, draft); } catch { setError(t("native.saveFailed")); }
  };
  useEffect(() => {
    if (!run || nativeTerminal(run.state)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void nativeApi<NativeRun>(`${run.execution_mode === "CANDLESCOPE" ? "/external/runs" : "/native/runs"}/${run.run_id}`, undefined, undefined, controller.signal)
        .then((value) => { if (!controller.signal.aborted) receiveRun(value); })
        .catch((reason) => { if (!controller.signal.aborted) { setError(String(reason)); setBusy(false); } });
    }, 700);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [run, receiveRun]);
  const start = async (prepare = false) => {
    // A restored uploaded input requires an explicit re-selection or clearing,
    // including the automatic preparation entry point.
    if (mode === "CANDLESCOPE" && fidelity !== "BAR_APPROX" && executionDataState !== "ready") return;
    pendingOverview.current = !run?.result && !previousRun?.result ? navigationRevision.current : null;
    if (run?.result) setPreviousRun(run);
    setHistoricalRun(null); setBusy(true); setError(""); setRun(null); setPreparation(null); setResolution(null);
    try {
      let params: unknown;
      try { params = JSON.parse(parameters); } catch { throw new Error(t("native.parametersInvalid")); }
      if (!params || Array.isArray(params) || typeof params !== "object") throw new Error(t("native.parametersInvalid"));
      const context = props.session;
      const execution = executionInputs(mode, hostSettings, fidelity, fillRecalculation, executionData);
      const automaticExecution = automaticHostExecution(mode, hostSettings, fidelity, fillRecalculation, executionData);
      const prepareRun = async (route: string, submission: Record<string, unknown>) => {
        const body = JSON.stringify({ route, submission });
        if (preparationSubmission.current?.body !== body) preparationSubmission.current = { body, key: crypto.randomUUID() };
        preparationObserver.current?.abort();
        const observer = new AbortController();
        preparationObserver.current = observer;
        let initial = await preparationRequest<PreparationJob>(route, {
          method: "POST", headers: { "Content-Type": "application/json" }, signal: observer.signal,
          body: JSON.stringify({ ...submission, idempotency_key: preparationSubmission.current.key }),
        });
        if (["FAILED", "BLOCKED_STORAGE"].includes(initial.state)) {
          initial = await preparationRequest<PreparationJob>(`/${initial.id}/retry`, { method: "POST", signal: observer.signal });
        }
        if (initial.state === "CANCELLED") preparationSubmission.current = null;
        const ready = await waitForPreparation(initial, setPreparation, observer.signal);
        if (!ready.result?.native_run) throw new Error("Prepared strategy is missing its run");
        if (alive.current) receiveRun(ready.result.native_run);
      };
      if (automatic && automaticExecution !== undefined && !props.dataset && !advanced.contexts.length && !advanced.magnifier) {
        const startTime = Date.parse(`${historyStart}T00:00:00Z`);
        const endTime = Date.parse(`${historyEnd}T00:00:00Z`);
        if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || endTime <= startTime) throw new Error("INVALID_RANGE: select an increasing UTC date range");
        const inputs = await freezeAdvancedInputs(advanced, language, {
          start_time_ms: startTime, end_time_ms: endTime - 1, exchange: context.exchange, market_type: context.marketType,
        });
        const submission = { language, source, parameters: params, libraries: inputs.libraries,
          ...(automaticExecution === null ? {} : { execution: automaticExecution }),
          contexts: automaticContexts.map((row) => ({ ...row, binding_symbol: row.binding_symbol.trim() || undefined })),
          context: { exchange: context.exchange, market_type: context.marketType, symbol: context.symbol,
            interval: context.interval, range_mode: "CUSTOM", fidelity_preference: "FAST", start_time_ms: startTime, end_time_ms: endTime - 1 } };
        await prepareRun("/native-strategy", submission);
        return;
      }
      if (props.dataset) {
        const catalog = await nativeApi<{ datasets: Array<{ dataset_id: string; data_epoch: string; first_open_ms: number; last_close_ms: number }> }>("/datasets");
        const dataset = catalog.datasets.find((item) => item.dataset_id === props.dataset!.datasetId && item.data_epoch === props.dataset!.dataEpoch);
        if (!dataset) throw new Error("DATA_SNAPSHOT_MISMATCH: imported dataset changed");
        const prepareTrades = automatic && mode === "CANDLESCOPE" && fidelity === "TRADE_TAPE" && executionData === null;
        if (prepareTrades && context.exchange === "local" && executionOrigin !== "binance-futures") {
          throw new Error(t("native.external.originRequired"));
        }
        const market = prepareTrades && context.exchange === "local"
          ? { exchange: "binance", market_type: "futures" } : { exchange: context.exchange, market_type: context.marketType };
        const data = { dataset_id: dataset.dataset_id, data_epoch: dataset.data_epoch, start_time_ms: dataset.first_open_ms,
          end_time_ms: dataset.last_close_ms, interval: context.interval, ...market };
        const snapshot = await nativeApi<{ snapshot_hash: string }>("/datasets/snapshot", data);
        const inputs = await freezeAdvancedInputs(advanced, language, data);
        const payload = { ...data, ...inputs, ...execution, snapshot_hash: snapshot.snapshot_hash,
          language, source, parameters: params, context: { symbol: context.symbol, timeframe: nativeTimeframe(context.interval) } };
        if (prepareTrades) { await prepareRun("/external-strategy", { run: payload }); return; }
        const result = await nativeApi<NativeRun>(runPath, payload, crypto.randomUUID());
        if (alive.current) receiveRun(result);
        return;
      }
      const frozen = prepare && resolution ? await nativeApi<ChartContextResolution>("/chart-context/materialize", {
        resolution_token: resolution.resolution_token, user_confirmed: true, idempotency_key: crypto.randomUUID(),
      }) : await nativeApi<ChartContextResolution>("/chart-context/resolve", {
        exchange: context.exchange, market_type: context.marketType, symbol: context.symbol,
        interval: context.interval, range_mode: "ALL_AVAILABLE", fidelity_preference: "FAST",
      });
      if (!alive.current) return;
      setResolution(frozen);
      if (frozen.status !== "READY") { setBusy(false); return; }
      const inputs = await freezeAdvancedInputs(advanced, language, {
        start_time_ms: frozen.coverage.requested_start_ms ?? frozen.coverage.available_start_ms!,
        end_time_ms: frozen.coverage.requested_end_ms ?? frozen.coverage.available_end_ms!,
        exchange: context.exchange, market_type: context.marketType,
      });
      const result = await nativeApi<NativeRun>(runPath, { ...inputs, ...execution,
        language, source, parameters: params, dataset_id: frozen.dataset_id, data_epoch: frozen.data_epoch,
        snapshot_hash: frozen.snapshot_hash, start_time_ms: frozen.coverage.requested_start_ms ?? frozen.coverage.available_start_ms,
        end_time_ms: frozen.coverage.requested_end_ms ?? frozen.coverage.available_end_ms,
        interval: context.interval, exchange: context.exchange, market_type: context.marketType,
        context: { symbol: `${context.exchange.toUpperCase()}:${context.symbol}`, timeframe: nativeTimeframe(context.interval) },
      }, crypto.randomUUID());
      if (alive.current) receiveRun(result);
    } catch (reason) { if (alive.current) { setError(reason instanceof PreparationApiError ? `${reason.code}: ${reason.message}` : String(reason)); setBusy(false); } }
  };
  const ownedRunIds = strategyRunIds(props.instance, mode);
  const visibleHistory = allHistory ? history : history.filter((item) => ownedRunIds.has(item.run_id));
  const reportRun = historicalRun ?? (run?.result ? run : previousRun);
  const executionDataMatches = useMemo(() => executionDataState === "ready"
    && sameExecutionData(reportRun?.config?.execution_data, executionData), [executionDataState, reportRun?.config?.execution_data, executionData]);
  let parametersChanged = false;
  try { parametersChanged = JSON.stringify(reportRun?.config?.parameters ?? {}) !== JSON.stringify(JSON.parse(parameters)); } catch { parametersChanged = true; }
  const resultStale = !!reportRun && (reportRun !== run || reportRun.config?.source !== source || reportRun.config?.language !== language || parametersChanged
    || datasetIdentityChanged(reportRun.config, props.dataset)
    || (mode === "CANDLESCOPE" && (!reportRun.config || executionSettingsChanged(reportRun.config,
      { hostSettings, fidelity, fillRecalculation, uploaded: executionData !== null }, executionDataMatches))));
  const available = capabilities?.engines.find((item) => item.language === language);
  const engineReady = mode === "NATIVE" ? available?.available : available?.external_available;
  const runDisabled = busy || (mode === "CANDLESCOPE" && fidelity !== "BAR_APPROX" && executionDataState !== "ready") || !engineReady;
  const feedbackRun = historicalRun ?? run;
  const { status, errorDetails } = nativeRunFeedback({ current: run, historical: historicalRun,
    error, busy, preparationState: preparation?.state, needsData: !!resolution && resolution.status !== "READY" });
  const onStatusChange = props.onStatusChange;
  useEffect(() => {
    if (props.active !== false) onStatusChange?.(status);
  }, [onStatusChange, props.active, status]);
  const errorLocation = !historicalRun || (historicalRun.config?.source === source && historicalRun.config?.language === language)
    ? diagnosticLocation(errorDetails, source) : null;
  const summary = useMemo(() => reportRun?.result ? reportAnalytics(reportRun.result, reportRun.execution_mode === "CANDLESCOPE") : null, [reportRun]);
  const [codeVisited, setCodeVisited] = useState(!props.docked || tab === "script");
  useEffect(() => { if (tab === "script") setCodeVisited(true); }, [tab]);
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  const percent = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? "—" : `${number.format(value)}%`;
  const returnPercent = summary?.series.at(-1)?.returnPercent ?? null;
  const runNow = () => { if (!runDisabled) void start(); };
  const tabKey = (event: KeyboardEvent<HTMLButtonElement>, item: typeof tab) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next = SESSION_TABS[(SESSION_TABS.indexOf(item) + (event.key === "ArrowRight" ? 1 : -1) + SESSION_TABS.length) % SESSION_TABS.length]!;
    selectTab(next);
    const list = event.currentTarget.parentElement;
    requestAnimationFrame(() => list?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus());
  };
  useControlCommands(() => ({ id: `native:${props.cellScope}:${mode}`, title: "Native strategy draft, run and report",
    context: () => ({ session: props.session, dataset: props.dataset, mode, language, source, parameters, hostSettings, fidelity, fillRecalculation,
      historyStart, historyEnd, automaticContexts, executionOrigin, advanced: contextReference(advanced), executionData: contextReference(executionData), runId: run?.run_id, historicalRunId: historicalRun?.run_id, allHistory, busy, executionDataState }),
    snapshot: () => ({ session: props.session, dataset: props.dataset, mode, language, source, parameters, hostSettings, fidelity, fillRecalculation,
      historyStart, historyEnd, automaticContexts, executionOrigin, advanced, busy, error, capabilities, resolution, preparation, resultStale, tab,
      run: run ? { runId: run.run_id, state: run.state, runtimeIdentity: run.runtime_identity, error: run.error, reportHash: run.result?.report_hash,
        trades: run.result?.trades.length, orders: run.result?.orders.length } : null,
      allHistory, historicalRunId: historicalRun?.run_id ?? null, visibleHistory: visibleHistory.slice(0, 100).map((item) => item.run_id), history: history.slice(0, 100).map((item) => ({ runId: item.run_id, state: item.state, createdAt: item.created_at_ms })) }), commands: [
      command("draft", "Edit/save the active source and JSON parameters through the existing draft persistence action.",
        object({ source: optional(text(48000)), parameters: optional(record) }), (input) => save(input.source ?? source, input.parameters === undefined ? parameters : JSON.stringify(input.parameters)), { available: () => !busy }),
      command("language", "Switch draft language; saved language drafts are restored.", object({ language: choice(["pine"]) }), ({ language }) => props.onInstanceChange(props.instance.id, { language }), { available: () => !busy }),
      command("mode", "Switch native/external simulation execution mode.", object({ mode: choice(["NATIVE", "CANDLESCOPE"]) }), ({ mode }) => props.onExecutionModeChange(mode), { available: () => !busy }),
      command("range", "Set an increasing UTC preparation date range.", object({ start: text(10), end: text(10) }), ({ start, end }) => {
        const valid = (date: string) => /^\d{4}-\d{2}-\d{2}$/.test(date) && Number.isFinite(Date.parse(`${date}T00:00:00Z`)) && new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) === date;
        if (!valid(start) || !valid(end) || end <= start) throw new Error("INVALID_RANGE");
        setHistoryStart(start); setHistoryEnd(end); save(source, parameters, automaticContexts, start, end);
      }, { available: () => !busy && automatic && mode === "NATIVE" && !props.dataset }),
      command("hostSettings", "Configure external simulation account and fees.", object({ initial_balance: optional(controlNumber(0)), slippage_bps: optional(controlNumber(0)), taker_fee_bps: optional(controlNumber(0)), price_tick: optional(controlNumber(0)) }),
        (patch) => { const next = { ...hostSettings, ...patch }; setHostSettings(next); saveExecution({ hostSettings: next }); }, { available: () => !busy && mode === "CANDLESCOPE" }),
      command("datasets", "Read the current native input dataset catalog.", empty, () => nativeApi<{ datasets: InputDataset[] }>("/datasets"), { readOnly: true }),
      command("advancedInputs", "Select existing additional datasets by ID/epoch and edit Pine library source mapping. Run retains snapshot revalidation.", object({ contexts: array(object({ datasetId: text(128), dataEpoch: text(128), symbol: text(128) }), 16), magnifier: nullable(object({ datasetId: text(128), dataEpoch: text(128) })), libraries: record }), async ({ contexts, magnifier, libraries }) => {
        if (Object.values(libraries).some((item) => typeof item !== "string") || (language !== "pine" && (magnifier || Object.keys(libraries).length)) || (mode !== "NATIVE" && (magnifier || Object.keys(libraries).length))) throw new Error("NATIVE_INPUT_UNSUPPORTED");
        const { datasets } = await nativeApi<{ datasets: InputDataset[] }>("/datasets");
        const select = ({ datasetId, dataEpoch }: { datasetId: string; dataEpoch: string }) => { const item = datasets.find((row) => row.dataset_id === datasetId && row.data_epoch === dataEpoch); if (!item) throw new Error("DATA_SNAPSHOT_MISMATCH"); return item; };
        const selected = contexts.map((row) => ({ dataset: select(row), symbol: row.symbol.trim() }));
        if (new Set(selected.map((row) => `${row.symbol}@${nativeTimeframe(row.dataset.interval)}`)).size !== selected.length) throw new Error("DUPLICATE_CONTEXT");
        setAdvanced({ contexts: selected, magnifier: magnifier ? select(magnifier) : null, libraries: JSON.stringify(libraries) });
      }, { available: () => !busy }),
      command("preparationContexts", "Edit typed automatic data-preparation contexts and save the draft.", object({ contexts: array(object({ exchange: text(96), market_type: text(96), symbol: text(96), interval: text(24), binding_symbol: text(128, 0), warmup_bars: optional(controlNumber(0, 5000, true)) }), 16) }), ({ contexts }) => { setAutomaticContexts(contexts); save(source, parameters, contexts); }, { available: () => !busy && automatic && mode === "NATIVE" && !props.dataset }),
      command("fidelity", "Set the external simulation execution fidelity and fill recalculation; clears previous run exactly as the UI does.", object({ fidelity: choice(["BAR_APPROX", "TRADE_TAPE", "BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"]), fillRecalculation: bool }), ({ fidelity, fillRecalculation }) => { setFidelity(fidelity); setFillRecalculation(fillRecalculation); saveExecution({ fidelity, fillRecalculation }); setRun(null); setPreviousRun(null); }, { available: () => !busy && mode === "CANDLESCOPE" }),
      command("executionFile", "Load bounded JSON execution data through the same upload state and engine-side validation.", object({ fileRef: nullable(text(96)) }), async ({ fileRef }) => {
        const upload = ++executionUpload.current; setExecutionData(null); setExecutionDataState(fileRef ? "loading" : "ready"); saveExecution({ uploaded: !!fileRef });
        if (!fileRef) return;
        try { const value: unknown = JSON.parse(await (await readControlFile(fileRef)).text()); if (upload === executionUpload.current) { setExecutionData(value); setExecutionDataState("ready"); setError(""); } }
        catch (reason) { if (upload === executionUpload.current) { setExecutionDataState("invalid"); setError(String(reason)); } throw reason; }
      }, { available: () => !busy && mode === "CANDLESCOPE" && fidelity !== "BAR_APPROX" }),
      command("executionOrigin", "Choose the execution-data origin through the persisted draft flow.", object({ origin: choice(["", "binance-futures"]) }), ({ origin }) => {
        setExecutionOrigin(origin); save(source, parameters, automaticContexts, historyStart, historyEnd, origin);
      }, { available: () => !busy && automatic && !!props.dataset && props.session.exchange === "local" && fidelity === "TRADE_TAPE" && executionData === null }),
      command("historyScope", "Include all existing strategy run history or only this instance's history.", object({ all: bool }), ({ all }) => setAllHistory(all)),
      command("selectHistory", "Open an existing visible history run report.", object({ runId: nullable(text(128)) }), async ({ runId }) => {
        if (!runId) { setHistoricalRun(null); return; } if (!visibleHistory.some((row) => row.run_id === runId)) throw new Error("HISTORY_UNAVAILABLE");
        const value = await nativeApi<NativeRun>(`${runPath}/${encodeURIComponent(runId)}`); pendingOverview.current = null; setError(""); setHistoricalRun(value); selectTab("overview");
      }, { available: () => !busy }),
      command("exportReport", "Export the current native/external report through its existing backend export endpoint to a fileRef.", empty, async () => {
        if (!reportRun?.result) throw new Error("REPORT_UNAVAILABLE"); const response = await fetch(nativeExportUrl(reportRun.run_id, reportRun.execution_mode));
        if (!response.ok) throw new Error(`REPORT_EXPORT_FAILED:${response.status}`); return publishControlFile(await response.blob(), "strategy-report.json");
      }, { available: () => !!reportRun?.result }),
      command("run", "Start the existing run/preparation flow. Poll inspect for busy, error, resolution and run.state; acknowledgement does not mean completion.", empty,
        () => { void start(); return { submitted: true }; }, { available: () => !busy && !(mode === "CANDLESCOPE" && fidelity !== "BAR_APPROX" && executionDataState !== "ready") && !!(mode === "NATIVE" ? available?.available : available?.external_available) }),
      command("prepare", "Materialize the inspected missing-data resolution and start the run.", empty, () => { void start(true); return { submitted: true }; }, { available: () => !busy && !!resolution && resolution.status !== "READY" }),
      command("cancelRun", "Cancel the current strategy run.", empty, async () => receiveRun(await nativeApi<NativeRun>(`${runPath}/${run!.run_id}/cancel`, {})), { available: () => !!run && !nativeTerminal(run.state), interrupt: true }),
      command("cancelPreparation", "Cancel the current data preparation job.", empty, async () => {
        const value = await preparationRequest<PreparationJob>(`/${preparation!.id}/cancel`, { method: "POST" }); preparationSubmission.current = null; setPreparation(value);
      }, { available: () => !!preparation && !["READY", "CANCELLED"].includes(preparation.state) && preparation.stage !== "STARTING" && !preparation.cancel_requested, interrupt: true }),
      command("tab", "Select the strategy editor/settings/report/history tab.", object({ tab: choice(["script", "settings", "overview", "trades", "history"]) }), ({ tab }) => selectTab(tab)),
      command("report", "Read a bounded page of the current report; authority, stale status and hashes are retained.", object({ section: choice(["trades", "orders", "equity", "bars", "graphics"]), offset: optional(controlNumber(0, 1e9, true)), limit: optional(controlNumber(1, 500, true)) }),
        ({ section, offset = 0, limit = 100 }) => ({ runId: reportRun?.run_id, stale: resultStale, authority: reportRun?.result?.account_authority,
          reportHash: reportRun?.result?.report_hash, total: reportRun?.result?.[section].length ?? 0, items: reportRun?.result?.[section].slice(offset, offset + limit) ?? [] }), { readOnly: true }),
    ] }), props.active !== false);
  return <section className={`native-strategy-panel${props.docked ? " native-strategy-docked" : ""}`} aria-label={t("native.title")}>
    {!props.docked && <header><strong>{t(mode === "NATIVE" ? "native.title" : "native.external.title")}</strong><span>{props.session.symbol} · {props.session.interval}</span><button type="button" aria-label={t("backtest.close")} onClick={props.onClose}><Icon name="close" size={14} /></button></header>}
    {props.docked && <StrategyDockSlot name="tabs"><div className="strategy-tabs" role="tablist" aria-label={t("chartTester.tabsAria")}>
      {SESSION_TABS.map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} tabIndex={tab === item ? 0 : -1}
        onClick={() => selectTab(item)} onKeyDown={(event) => tabKey(event, item)}>{t(item === "history" ? "ux.history" : `chartTester.tab.${item}`)}</button>)}
    </div></StrategyDockSlot>}
    <StrategyDockSlot name="actions"><div className="strategy-dock-run">
      {summary && <button type="button" className="strategy-summary" data-stale={resultStale && !historicalRun} onClick={() => selectTab("overview")}
        title={resultStale && !historicalRun ? t("chartTester.result.staleGuidanceTitle") : t("chartTester.tab.overview")}>
        <span><small>{t("report.change")}</small><b className={returnPercent == null ? undefined : returnPercent < 0 ? "negative" : "positive"}>{percent(returnPercent)}</b></span>
        <span><small>{t("chartTester.result.maxDrawdown")}</small><b>{percent(summary.maxDrawdownPercent)}</b></span>
        <span><small>{t("report.winRate")}</small><b>{percent(summary.winRate)}</b></span>
      </button>}
      {status !== "idle" && <span role="status" className="strategy-run-status" data-status={status}><i aria-hidden="true" />{t(`strategyReview.status.${status}`)}</span>}
      {run && !nativeTerminal(run.state) && <button type="button" className="strategy-dock-button" onClick={() => void nativeApi<NativeRun>(`${runPath}/${run.run_id}/cancel`, {}).then(receiveRun).catch((reason) => setError(String(reason)))}>
        <Icon name="stop" size={11} filled />{t("native.cancel")}</button>}
      <button type="button" className="strategy-run-button" disabled={runDisabled} onClick={runNow}
        title={t(mode === "NATIVE" ? "native.run" : "native.external.run")}>
        <Icon name="play" size={11} filled />{t("chartTester.run")}</button>
    </div></StrategyDockSlot>
    <StrategyDockSlot name="notice">
      {preparation && !["READY", "CANCELLED"].includes(preparation.state) && <div className="strategy-notice" data-tone="info" role="status">
        <strong>{t("preparation.title")} · {preparation.completed}/{preparation.total}</strong>
        <PreparationWaiting job={preparation} />
        <button type="button" disabled={preparation.stage === "STARTING" || preparation.cancel_requested} onClick={() => void preparationRequest<PreparationJob>(`/${preparation.id}/cancel`, { method: "POST" }).then((value) => { preparationSubmission.current = null; setPreparation(value); }).catch((reason) => setError(String(reason)))}>{t("preparation.cancel")}</button>
      </div>}
      {resolution && resolution.status !== "READY" && <div className="strategy-notice" data-tone="warning" role="status">
        <strong>{t("strategyReview.status.needsData")}</strong><span>{resolution.status}</span>
        <button type="button" disabled={runDisabled} onClick={() => void start(true)}>{t("native.prepare")}</button>
      </div>}
      {errorDetails && <div className="strategy-notice" data-tone="error" role="alert">
        <strong>{t("strategyReview.status.failed")}</strong><span>{errorDetails.includes(t("native.parametersInvalid")) ? t("native.parametersInvalid")
          : errorDetails.includes(t("native.external.originRequired")) ? t("native.external.originRequired") : t("native.executionErrorHelp")}</span>
        {errorLocation && <button type="button" onClick={() => {
          selectTab("script");
          setErrorFocus({ line: errorLocation.line, column: errorLocation.column });
        }}>{t("native.jumpToError", { line: errorLocation.line, column: errorLocation.column })}</button>}
        <details><summary>{t("plugin.techDetails")}</summary><pre>{errorDetails}</pre></details>
      </div>}
      {capabilities && !engineReady && <div className="strategy-notice" data-tone="info" role="status">
        <span>{t("indicator.editor.runtimeUnavailableHelp")} {t("native.platformHelp")}</span>
        {available?.reason && <details><summary>{t("plugin.techDetails")}</summary><p>{available.reason}</p></details>}
      </div>}
      {historicalRun && <div className="strategy-notice" data-tone="info" role="status">
        <strong>{t("strategyHistory.viewing")}</strong><code>{historicalRun.run_id}</code>
        <button type="button" onClick={() => setHistoricalRun(null)}>{t("strategyHistory.latest")}</button>
      </div>}
    </StrategyDockSlot>
    <div className="native-dock-scroll" ref={scrollPane} onScroll={(event) => { scrollPositions.current[tab] = event.currentTarget.scrollTop; }}>
    <div hidden={props.docked && tab !== "script"} className="native-code">
      <div className="native-code-editor">
        {codeVisited && <Suspense fallback={<div className="chart-strategy-editor-loading">{t("chartTester.editorLoading")}</div>}>
          <StrategyScriptWorkspace key={language} source={source} language={language} cursor={errorFocus} issues={[]} focusIssue={null} focusOnMount={errorFocus !== null}
            readOnly={busy} ariaLabel={t("native.source")} onSourceChange={(value) => save(value, parameters)} onCursorChange={ignoreCursor} onRun={runNow} />
        </Suspense>}
      </div>
      <aside className="native-code-side">
        <div className="strategy-segmented" role="radiogroup" aria-label={t("native.language")}>
          {(["pine"] as const).map((item) => <button key={item} type="button" role="radio" aria-checked={language === item} disabled={busy}
            onClick={() => props.onInstanceChange(props.instance.id, { language: item })}>{t(`chartTester.language.${item}`)}</button>)}
          {props.onSelectPython && <button type="button" role="radio" aria-checked={false} disabled={busy} onClick={props.onSelectPython}>{strategyLanguageLabel("python")}</button>}
        </div>
        <label>{t("native.parameters")}<textarea value={parameters} disabled={busy} spellCheck={false} onChange={(event) => save(source, event.target.value)} /></label>
      </aside>
    </div>
    <div hidden={props.docked && tab !== "settings"} className="native-dock-settings">
      <section className="strategy-settings-section">
        <h3>{t("native.mode")}</h3>
        <div className="strategy-engine-options" role="radiogroup" aria-label={t("native.mode")}>
          {(["NATIVE", "CANDLESCOPE"] as const).map((engine) => <button key={engine} type="button" role="radio" aria-checked={mode === engine} disabled={busy}
            onClick={() => { if (mode !== engine) props.onExecutionModeChange(engine); }}>
            <strong>{t(engine === "NATIVE" ? "native.title" : "native.external.title")}</strong>
            <span>{t(engine === "NATIVE" ? "native.description" : "native.external.description")}</span>
          </button>)}
        </div>
      </section>
      {automatic && automaticHostExecution(mode, hostSettings, fidelity, fillRecalculation, executionData) !== undefined && !props.dataset && !advanced.contexts.length && !advanced.magnifier && <section className="strategy-settings-section">
        <h3>{t("chartTester.settings.date")}</h3>
        <div className="strategy-settings-grid">
          <label>{t("preparation.startDate")}<input type="date" disabled={busy} value={historyStart} onChange={(event) => { setHistoryStart(event.target.value); save(source, parameters, automaticContexts, event.target.value, historyEnd); }} /></label>
          <label>{t("preparation.endDate")}<input type="date" disabled={busy} value={historyEnd} onChange={(event) => { setHistoryEnd(event.target.value); save(source, parameters, automaticContexts, historyStart, event.target.value); }} /></label>
        </div>
        <NativePreparationContexts
          value={automaticContexts} onChange={(value) => { setAutomaticContexts(value); save(source, parameters, value); }} disabled={busy}
          exchange={props.session.exchange} marketType={props.session.marketType} symbol={props.session.symbol} />
      </section>}
      {mode === "CANDLESCOPE" && <section className="strategy-settings-section">
        <h3>{t("chartTester.settings.fee")}</h3>
        <div className="strategy-settings-grid">{(["initial_balance", "slippage_bps", "taker_fee_bps", "price_tick"] as const).map((field) => <label key={field}>{t(`native.external.${field}`)}
          <input type="number" min="0" step="any" disabled={busy} value={hostSettings[field]} onChange={(event) => {
            const next = { ...hostSettings, [field]: Number(event.target.value) }; setHostSettings(next); saveExecution({ hostSettings: next });
          }} />
        </label>)}</div>
      </section>}
      {mode === "CANDLESCOPE" && <section className="strategy-settings-section">
        <h3>{t("native.external.fidelity")}</h3>
        <div className="strategy-settings-grid">
          <label>{t("native.external.fidelity")}<select disabled={busy} value={fidelity} onChange={(event) => { setFidelity(event.target.value); saveExecution({ fidelity: event.target.value }); }}>
            <option value="BAR_APPROX">BAR_APPROX</option><option value="TRADE_TAPE">TRADE_TAPE</option><option value="BOOK_ASSISTED">BOOK_ASSISTED</option><option value="BOOK_DEPTH">BOOK_DEPTH</option>
            <option value="BOOK_SAMPLED">{t("native.external.sampledLabel")}</option>
          </select></label>
          {automatic && props.dataset && props.session.exchange === "local" && fidelity === "TRADE_TAPE" && executionData === null &&
            <label>{t("native.external.executionOrigin")}<select disabled={busy} value={executionOrigin} onChange={(event) => {
              setExecutionOrigin(event.target.value); save(source, parameters, automaticContexts, historyStart, historyEnd, event.target.value);
            }}><option value="">{t("native.external.originRequired")}</option><option value="binance-futures">{t("native.external.binanceUsdm")}</option></select></label>}
          {fidelity !== "BAR_APPROX" && <label>{t("native.external.executionData")}<input key={executionInputKey} type="file" accept="application/json,.json" disabled={busy} onChange={(event) => {
            const file = event.target.files?.[0];
            const upload = ++executionUpload.current;
            setExecutionData(null);
            setExecutionDataState(file ? "loading" : "ready");
            saveExecution({ uploaded: !!file });
            if (file) void file.text().then((text) => {
              if (upload !== executionUpload.current) return;
              setExecutionData(JSON.parse(text)); setExecutionDataState("ready"); setError("");
            }).catch((reason) => {
              if (upload !== executionUpload.current) return;
              setExecutionDataState("invalid"); setError(String(reason));
            });
          }} /></label>}
        </div>
        {fidelity !== "BAR_APPROX" && executionDataState === "missing" && <p role="status">{t("native.external.uploadMissing")}</p>}
        {fidelity !== "BAR_APPROX" && (executionData !== null || executionDataState !== "ready") && <button type="button" disabled={busy} onClick={() => {
          executionUpload.current += 1; setExecutionInputKey((key) => key + 1); setExecutionData(null); setExecutionDataState("ready"); setError(""); saveExecution({ uploaded: false });
        }}>{t("native.external.clearUpload")}</button>}
        {fidelity === "BOOK_DEPTH" && <p>{t("native.external.depthHint")}</p>}
        {fidelity === "BOOK_SAMPLED" && <p>{t("native.external.sampledHint")}</p>}
        {fidelity !== "BAR_APPROX" && <><label className="strategy-settings-check"><input type="checkbox" disabled={busy} checked={fillRecalculation} onChange={(event) => { setFillRecalculation(event.target.checked); saveExecution({ fillRecalculation: event.target.checked }); }} />{t("native.external.fillRecalculation")}</label><p>{t("native.external.fillHint")}</p>{fidelity !== "BOOK_SAMPLED" && <p>{t("native.external.dataHint")}</p>}</>}
      </section>}
      <details className="strategy-settings-section"><summary>{t("replay.hub.sectionAdvanced")}</summary>
        <NativeAdvancedInputs native={mode === "NATIVE"} value={advanced} onChange={setAdvanced} language={language} disabled={busy} exchange={props.session.exchange} />
      </details>
    </div>
    <div className="native-dock-report" data-view={tab} hidden={props.docked && tab !== "overview" && tab !== "trades"}>
      {resultStale && !historicalRun && <div className="strategy-notice" data-tone="warning" role="status">
        <strong>{t("chartTester.result.staleGuidanceTitle")}</strong>
        <button type="button" disabled={runDisabled} onClick={runNow}>{t("chartTester.run")}</button>
      </div>}
      {!reportRun?.result && props.docked && <div className="strategy-dock-empty">
        <p>{t("strategyDock.empty")}</p>
        <button type="button" className="strategy-run-button" disabled={runDisabled} onClick={runNow}><Icon name="play" size={11} filled />{t("chartTester.run")}</button>
      </div>}
      {reportRun?.result && !props.externalReport && <NativeStrategyReport key={reportRun.run_id} run={reportRun} onLocate={props.onLocateTrade} onReviewTrade={props.onReviewTrade} active={!historicalRun && props.active !== false && (!props.docked || tab === "trades")}
        stale={(!historicalRun && resultStale) || datasetIdentityChanged(reportRun.config, props.dataset)}
        view={props.docked ? (tab === "trades" ? "trades" : "overview") : "all"} />}
    </div>
    <div hidden={props.docked && tab !== "history"} className="native-history">
      <div className="native-history-head">
        <label className="strategy-settings-check"><input type="checkbox" checked={allHistory} onChange={(event) => setAllHistory(event.target.checked)} />{t("strategyHistory.all")}</label>
        <p>{t("strategyHistory.ownership")}</p>
      </div>
      {!visibleHistory.length && <p className="strategy-dock-empty">{t("strategyHistory.empty")}</p>}
      {visibleHistory.length > 0 && <ul className="native-history-list" aria-label={t(mode === "NATIVE" ? "native.history" : "native.external.history")}>
        {visibleHistory.map((item) => <li key={item.run_id}><button type="button" disabled={busy} aria-current={reportRun?.run_id === item.run_id}
          onClick={() => void nativeApi<NativeRun>(`${runPath}/${item.run_id}`).then((value) => { pendingOverview.current = null; setError(""); setHistoricalRun(value); selectTab("overview"); }).catch((reason) => setError(String(reason)))}>
          <time dateTime={new Date(item.created_at_ms).toISOString()}>{new Date(item.created_at_ms).toLocaleString(locale)}</time>
          <span>{item.runtime_identity.engine.package}</span>
          <span className="strategy-run-status" data-status={item.state === "COMPLETED" ? "completed" : item.state === "FAILED" || item.state === "INTERRUPTED" ? "failed" : item.state === "CANCELLED" ? "cancelled" : "running"}><i aria-hidden="true" />{item.state}</span>
        </button></li>)}
      </ul>}
      {feedbackRun?.config?.source && <details><summary>{t("native.source")}</summary><pre>{feedbackRun.config.source}</pre></details>}
    </div>
    </div>
  </section>;
}
