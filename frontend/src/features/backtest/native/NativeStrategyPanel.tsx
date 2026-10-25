import { pineContractMetadata } from "../../indicators/pineContractMetadata.js";
import { diagnosticLocation, nativeRunFeedback } from "./nativeDiagnostics.js";
import NativeStrategyComparison from "./NativeStrategyComparison.js";
import { recordStrategyRun, strategyRunIds, strategyInstanceScope, type NativeStrategyInstance } from "./nativeStrategyCollection.js";
import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { ChartStrategyTesterPanelProps } from "../chart-tester/ChartStrategyTesterPanel.js";
import type { ChartContextResolution } from "../backtestApi.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { nativeApi, nativeTerminal, nativeTimeframe, type NativeCapabilities, type NativeRun } from "./nativeBacktestApi.js";
import { NativeStrategyReport } from "./NativeStrategyReport.js";
import { pollNativeRun } from "./nativeRunPolling.js";
import "./nativeStrategy.css";
import { NativeAdvancedInputs } from "./NativeAdvancedInputs.js";
import { NativePreparationContexts } from "./NativePreparationContexts.js";
import { restorePreparationContexts, restorePreparationDate, type NativePreparationContext } from "./nativePreparationInputs.js";
import { automaticHostExecution, emptyAdvancedInputs, executionInputs, freezeAdvancedInputs, restoreAdvancedInputs, type AdvancedInputs } from "./nativeInputs.js";
import { PreparationApiError, preparationRequest, waitForPreparation, type PreparationJob, type PreparationCapabilities } from "../../data-preparation/api.js";
import PreparationWaiting from "../../data-preparation/PreparationWaiting.js";
import { Icon } from "../../../components/icons/Icon.js";
import { reportAnalytics } from "./nativeReportAnalytics.js";
import { useNativeStrategyCollection, nativeStrategySwitcherActions, nativeStrategySwitcherItems, type NativeStrategyController } from "./useNativeStrategyCollection.js";
import { StrategyDockPane, StrategyDockSlot } from "../chart-tester/StrategyDockSlots.js";
import { StrategySwitcher } from "../chart-tester/StrategySwitcher.js";
import { strategyLanguageLabel } from "../chart-tester/strategyLanguageLabel.js";
import { datasetIdentityChanged, defaultExecutionDraft, executionSettingsChanged, restoreExecutionDraft, sameExecutionData, type NativeExecutionDraft } from "./nativeExecutionSettings.js";
import { WorkbenchAccountSettings } from "./WorkbenchAccountSettings.js";
import { defaultWorkbenchAccount, parseAccountData, workbenchAccountError, type AccountInputState, type FrozenAccountData } from "./workbenchAccountInputs.js";

const StrategyScriptWorkspace = lazy(() => import("../chart-tester/StrategyScriptWorkspace.js"));

const NATIVE_TEMPLATES = {
  pine: '//@version=6\nstrategy("Native SMA", overlay=true, initial_capital=10000)\nfast = ta.sma(close, 3)\nslow = ta.sma(close, 5)\nif ta.crossover(fast, slow)\n    strategy.entry("L", strategy.long)\nif ta.crossunder(fast, slow)\n    strategy.close("L")\nplot(fast)\nplot(slow)\n',
  pyne: 'strategy("Native SMA", overlay=True, initial_capital=10000)\nfast = ta.sma(close, 3)\nslow = ta.sma(close, 5)\nstrategy.entry_when(ta.crossover(fast, slow), "L", strategy.long, qty=1)\nstrategy.close_when(ta.crossunder(fast, slow), "L")\nplot(fast, "Fast")\nplot(slow, "Slow")\n',
};
const SESSION_TABS = ["overview", "trades", "script", "settings", "history"] as const;
const ignoreCursor = () => undefined;

type NativeStrategyPanelProps = Pick<ChartStrategyTesterPanelProps, "session" | "cellScope" | "onClose" | "onLocateTrade" | "onReviewTrade" | "active" | "nativeStrategies" | "onNativeStrategiesChange"> & {
  dataset?: { datasetId: string; dataEpoch: string } | undefined;
  onRunChange?: (run: NativeRun | null) => void;
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
  const contextParts = [props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval];
  const context = JSON.stringify(contextParts);
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
  const [costSensitivityMode, setCostSensitivityMode] = useState<"AUTO" | "SKIP">("AUTO");
  const [accountDraft, setAccountDraft] = useState(defaultWorkbenchAccount);
  const [accountData, setAccountData] = useState<FrozenAccountData | null>(null);
  const [accountDataState, setAccountDataState] = useState<AccountInputState>("ready");
  const [accountInputKey, setAccountInputKey] = useState(0);
  const accountUpload = useRef(0);
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
    setCostSensitivityMode(draft.costSensitivityMode ?? "AUTO");
    setAccountDraft(draft.account ?? defaultWorkbenchAccount());
    accountUpload.current += 1;
    setAccountInputKey((key) => key + 1);
    setAccountData(null); setAccountDataState(draft.account?.uploaded ? "missing" : "ready");
    executionUpload.current += 1;
    setExecutionInputKey((key) => key + 1);
    setExecutionData(null); setExecutionDataState(draft.uploaded ? "missing" : "ready");
  }, [executionDraftKey]);
  const saveExecution = (change: Partial<NativeExecutionDraft>) => {
    const draft: NativeExecutionDraft = { hostSettings, fidelity, fillRecalculation, account: accountDraft, costSensitivityMode,
      uploaded: executionData !== null || executionDataState !== "ready", ...change };
    patchInstance.current(instanceRef.current.id, { drafts: { [executionDraftKey]: JSON.stringify(draft) } });
  };
  const uploadAccount = (file: File | null) => {
    const upload = ++accountUpload.current;
    const next = { ...accountDraft, uploaded: !!file };
    setAccountDraft(next); saveExecution({ account: next });
    setAccountData(null); setAccountDataState(file ? "loading" : "ready");
    if (!file) { setAccountInputKey((key) => key + 1); return; }
    if (file.size > 64 * 1024 * 1024) { setAccountDataState("invalid"); setError(t("native.account.invalidData")); return; }
    void file.text().then((text) => {
      if (upload !== accountUpload.current || !alive.current) return;
      setAccountData(parseAccountData(text)); setAccountDataState("ready"); setError("");
    }).catch((reason) => {
      if (upload !== accountUpload.current || !alive.current) return;
      setAccountDataState("invalid"); setError(String(reason));
    });
  };
  const accountOptions = { language, account: accountDraft, accountData, costSensitivityMode };
  const accountError = mode === "CANDLESCOPE" ? workbenchAccountError(accountDraft, accountData, accountDataState,
    language, fidelity, fillRecalculation, props.session.marketType) : "";
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
      setAdvanced(restoreAdvancedInputs(draft && typeof draft === "object" && "advanced" in draft ? draft.advanced : null));
    } catch { setSource(NATIVE_TEMPLATES[language]); setParameters("{}"); setAutomaticContexts([]); setHistoryStart(defaultStart); setHistoryEnd(defaultEnd); setExecutionOrigin(""); setAdvanced(emptyAdvancedInputs()); }
  }, [storageKey, legacyStorageKey, language, mode, importedDatasetId]);
  useEffect(() => { setResolution(null); }, [props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval]);
  const save = (text: string, params: string, contexts = automaticContexts, start = historyStart, end = historyEnd, origin = executionOrigin, advancedInputs = advanced) => {
    setSource(text); setParameters(params);
    const draft = JSON.stringify({ source: text, parameters: params, automaticContexts: contexts, historyStart: start, historyEnd: end,
      executionOrigin: origin, executionOriginDataset: importedDatasetId, advanced: advancedInputs });
    const item = instanceRef.current;
    patchInstance.current(item.id, { drafts: { [`${language}:${mode}`]: draft } });
    try { localStorage.setItem(storageKey, draft); } catch { setError(t("native.saveFailed")); }
  };
  useEffect(() => {
    if (!run || nativeTerminal(run.state)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void pollNativeRun(run, controller.signal)
        .then((value) => { if (!controller.signal.aborted) receiveRun(value); })
        .catch((reason) => { if (!controller.signal.aborted) { setError(String(reason)); setBusy(false); } });
    }, 700);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [run, receiveRun]);
  const start = async (prepare = false) => {
    // A restored uploaded input requires an explicit re-selection or clearing,
    // including the automatic preparation entry point.
    if (mode === "CANDLESCOPE" && fidelity !== "BAR_APPROX" && executionDataState !== "ready") return;
    if (accountError) return;
    pendingOverview.current = !run?.result && !previousRun?.result ? navigationRevision.current : null;
    if (run?.result) setPreviousRun(run);
    setHistoricalRun(null); setBusy(true); setError(""); setRun(null); setPreparation(null); setResolution(null);
    try {
      let params: unknown;
      try { params = JSON.parse(parameters); } catch { throw new Error(t("native.parametersInvalid")); }
      if (!params || Array.isArray(params) || typeof params !== "object") throw new Error(t("native.parametersInvalid"));
      const context = props.session;
      const pineMetadata = language === "pine" ? pineContractMetadata(advanced) : undefined;
      const execution = executionInputs(mode, hostSettings, fidelity, fillRecalculation, executionData, accountOptions);
      const automaticExecution = automaticHostExecution(mode, hostSettings, fidelity, fillRecalculation, executionData, accountOptions);
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
          ...("currency_rates" in inputs ? { currency_rates: inputs.currency_rates } : {}),
          ...(pineMetadata ? { chart_metadata: pineMetadata } : {}),
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
          language, source, parameters: params, context: { symbol: context.symbol, timeframe: nativeTimeframe(context.interval), ...(pineMetadata ? { metadata: pineMetadata } : {}) } };
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
        context: { symbol: `${context.exchange.toUpperCase()}:${context.symbol}`, timeframe: nativeTimeframe(context.interval), ...(pineMetadata ? { metadata: pineMetadata } : {}) },
      }, crypto.randomUUID());
      if (alive.current) receiveRun(result);
    } catch (reason) { if (alive.current) { setError(reason instanceof PreparationApiError ? `${reason.code}: ${reason.message}` : String(reason)); setBusy(false); } }
  };
  const ownedRunIds = strategyRunIds(props.instance, mode);
  const visibleHistory = allHistory ? history : history.filter((item) => ownedRunIds.has(item.run_id));
  const reportRun = historicalRun ?? (run?.result ? run : previousRun);
  const executionDataMatches = useMemo(() => executionDataState === "ready"
    && sameExecutionData(reportRun?.config?.execution_data, executionData), [executionDataState, reportRun?.config?.execution_data, executionData]);
  const accountDataMatches = useMemo(() => accountDataState === "ready"
    && sameExecutionData(reportRun?.config?.account_data, accountData), [accountDataState, reportRun?.config?.account_data, accountData]);
  let parametersChanged = false;
  try { parametersChanged = JSON.stringify(reportRun?.config?.parameters ?? {}) !== JSON.stringify(JSON.parse(parameters)); } catch { parametersChanged = true; }
  const resultStale = !!reportRun && (reportRun !== run || reportRun.config?.source !== source || reportRun.config?.language !== language || parametersChanged
    || datasetIdentityChanged(reportRun.config, props.dataset)
    || (mode === "CANDLESCOPE" && (!reportRun.config || executionSettingsChanged(reportRun.config,
      { hostSettings, fidelity, fillRecalculation: fillRecalculation && (language === "pine" || fidelity !== "BAR_APPROX"),
        uploaded: executionData !== null, account: accountDraft, costSensitivityMode: language === "pine" ? costSensitivityMode : "AUTO" }, executionDataMatches, accountDataMatches))));
  const available = capabilities?.engines.find((item) => item.language === language);
  const engineReady = mode === "NATIVE" ? available?.available : available?.external_available;
  const runDisabled = busy || !!accountError || (mode === "CANDLESCOPE" && fidelity !== "BAR_APPROX" && executionDataState !== "ready") || !engineReady;
  const feedbackRun = historicalRun ?? run;
  const { status, errorDetails } = nativeRunFeedback({ current: run, historical: historicalRun,
    error, busy, preparationState: preparation?.state, needsData: !!resolution && resolution.status !== "READY" });
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
          {(["pine", "pyne"] as const).map((item) => <button key={item} type="button" role="radio" aria-checked={language === item} disabled={busy}
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
      {automatic && automaticHostExecution(mode, hostSettings, fidelity, fillRecalculation, executionData, accountOptions) !== undefined && !props.dataset && !advanced.contexts.length && !advanced.magnifier && <section className="strategy-settings-section">
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
        <div className="strategy-settings-grid">{(["initial_balance", "slippage_bps", "taker_fee_bps", "price_tick"] as const).filter((field) => field !== "price_tick" || accountDraft.accountModel !== "LINEAR_PERP_ONE_WAY_V2").map((field) => <label key={field}>{t(`native.external.${field}`)}
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
        {(fidelity !== "BAR_APPROX" || language === "pine") && <><label className="strategy-settings-check"><input type="checkbox" disabled={busy} checked={fillRecalculation} onChange={(event) => { setFillRecalculation(event.target.checked); saveExecution({ fillRecalculation: event.target.checked }); }} />{t("native.external.fillRecalculation")}</label><p>{t("native.external.fillHint")}</p>{fidelity !== "BOOK_SAMPLED" && fidelity !== "BAR_APPROX" && <p>{t("native.external.dataHint")}</p>}</>}
      </section>}
      {mode === "CANDLESCOPE" && language === "pine" && <WorkbenchAccountSettings value={accountDraft} data={accountData}
        state={accountDataState} inputKey={accountInputKey} disabled={busy} error={accountError}
        onChange={(value) => { setAccountDraft(value); saveExecution({ account: value }); }} onFile={uploadAccount} />}
      {mode === "CANDLESCOPE" && language === "pine" && <section className="strategy-settings-section">
        <label className="strategy-settings-check"><input type="checkbox" checked={costSensitivityMode === "AUTO"} disabled={busy}
          onChange={(event) => { const value = event.target.checked ? "AUTO" : "SKIP"; setCostSensitivityMode(value); saveExecution({ costSensitivityMode: value }); }} />{t("native.cost.enable")}</label>
        <p>{t("native.cost.enableHelp")}</p>
      </section>}
      <details className="strategy-settings-section"><summary>{t("replay.hub.sectionAdvanced")}</summary>
        <NativeAdvancedInputs native={mode === "NATIVE"} value={advanced} onChange={(next) => {
          setAdvanced(next);
          save(source, parameters, automaticContexts, historyStart, historyEnd, executionOrigin, next);
        }} language={language} disabled={busy} exchange={props.session.exchange} />
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
