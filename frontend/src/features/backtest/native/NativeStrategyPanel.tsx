import NativeStrategyComparison from "./NativeStrategyComparison.js";
import { recordStrategyRun, strategyRunIds, normalizeNativeStrategies, copyNativeStrategy, strategyInstanceScope, type NativeStrategyInstance, type NativeStrategyCollection } from "./nativeStrategyCollection.js";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ChartStrategyTesterPanelProps } from "../chart-tester/ChartStrategyTesterPanel.js";
import type { ChartContextResolution } from "../backtestApi.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { nativeApi, nativeTerminal, nativeTimeframe, type NativeCapabilities, type NativeRun } from "./nativeBacktestApi.js";
import { NativeStrategyReport } from "./NativeStrategyReport.js";
import "./nativeStrategy.css";
import { NativeAdvancedInputs } from "./NativeAdvancedInputs.js";
import { NativePreparationContexts } from "./NativePreparationContexts.js";
import { restorePreparationContexts, restorePreparationDate, type NativePreparationContext } from "./nativePreparationInputs.js";
import { emptyAdvancedInputs, executionInputs, freezeAdvancedInputs, type AdvancedInputs } from "./nativeInputs.js";
import { preparationRequest, waitForPreparation, type PreparationJob, type PreparationCapabilities } from "../../data-preparation/api.js";
import PreparationWaiting from "../../data-preparation/PreparationWaiting.js";
import { Icon } from "../../../components/icons/Icon.js";

const NATIVE_TEMPLATES = {
  pine: '//@version=6\nstrategy("Native SMA", overlay=true, initial_capital=10000)\nfast = ta.sma(close, 3)\nslow = ta.sma(close, 5)\nif ta.crossover(fast, slow)\n    strategy.entry("L", strategy.long)\nif ta.crossunder(fast, slow)\n    strategy.close("L")\nplot(fast)\nplot(slow)\n',
  pyne: 'strategy("Native SMA", overlay=True, initial_capital=10000)\nfast = ta.sma(close, 3)\nslow = ta.sma(close, 5)\nstrategy.entry_when(ta.crossover(fast, slow), "L", strategy.long, qty=1)\nstrategy.close_when(ta.crossunder(fast, slow), "L")\nplot(fast, "Fast")\nplot(slow, "Slow")\n',
};

type NativeStrategyPanelProps = Pick<ChartStrategyTesterPanelProps, "session" | "cellScope" | "onClose" | "onLocateTrade" | "onReviewTrade" | "active" | "nativeStrategies" | "onNativeStrategiesChange"> & {
  dataset?: { datasetId: string; dataEpoch: string } | undefined;
  onRunChange?: (run: NativeRun | null) => void;
  externalReport?: boolean;
  docked?: boolean;
};
export default function NativeStrategyPanel(props: NativeStrategyPanelProps) {
  useLocale();
  const [collection, setCollection] = useState(() => normalizeNativeStrategies(props.nativeStrategies));
  const current = useRef(collection);
  const persist = useRef(props.onNativeStrategiesChange);
  persist.current = props.onNativeStrategiesChange;
  const [busyIds, setBusyIds] = useState<Set<string>>(() => new Set());
  const [editing, setEditing] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [storageError, setStorageError] = useState("");
  const update = useCallback((change: (value: NativeStrategyCollection) => NativeStrategyCollection) => {
    const next = change(current.current);
    current.current = next; setCollection(next); persist.current?.(next);
  }, []);
  const updateInstance = useCallback((id: string, change: Partial<NativeStrategyInstance>) => {
    update((value) => ({ ...value, items: value.items.map((item) => item.id === id ? { ...item, ...change, drafts: { ...item.drafts, ...change.drafts }, runs: { ...item.runs, ...change.runs }, runHistory: { ...item.runHistory, ...change.runHistory } } : item) }));
  }, [update]);
  const setInstanceBusy = useCallback((id: string, busy: boolean) => {
    setBusyIds((old) => { const next = new Set(old); if (busy) next.add(id); else next.delete(id); return next; });
  }, []);
  const isBusy = (id: string) => [...busyIds].some((key) => key.startsWith(`${id}:`));
  const selected = collection.items.find((item) => item.id === collection.activeId)!;
  const name = (item: NativeStrategyInstance) => item.name || t("strategyCollection.default");
  const add = (copy: boolean) => {
    const id = crypto.randomUUID();
    if (copy && !selected) return;
    const drafts = { ...selected?.drafts };
    if (copy && selected) {
      try {
        for (const language of ["pine", "pyne"]) for (const mode of ["NATIVE", "CANDLESCOPE"]) {
          const key = `${language}:${mode}`;
          const prefix = `candlescope.native-draft:${strategyInstanceScope(props.cellScope, selected.id)}:${language}`;
          const saved = drafts[key] ?? localStorage.getItem(`${prefix}:${mode}`) ?? (selected.id === "default" ? localStorage.getItem(prefix) : null);
          if (saved) drafts[key] = saved;
        }
      } catch { setStorageError(t("native.saveFailed")); return; }
    }
    const item = copy && selected ? copyNativeStrategy({ ...selected, drafts }, id, `${name(selected)} · ${t("strategyCollection.copyName")}`)
      : { id, name: `${t("strategyCollection.default")} ${collection.items.length + 1}`, language: "pine" as const, drafts: {}, runs: {} };
    update((value) => ({ ...value, activeId: id, items: [...value.items, item] }));
    setEditing(false); setComparing(false);
  };
  return <>
    <div className="native-strategy-collection" aria-label={t("strategyCollection.list")}>
      <div className="native-strategy-switcher">
        {collection.items.length <= 5 ? collection.items.map((item) => <button key={item.id} aria-pressed={item.id === collection.activeId}
          onClick={() => { update((value) => ({ ...value, activeId: item.id })); setEditing(false); setComparing(false); }}>
          {name(item)}{isBusy(item.id) ? ` · ${t("strategyReview.status.running")}` : ""}</button>)
          : <select aria-label={t("strategyCollection.select")} value={collection.activeId} onChange={(event) => { update((value) => ({ ...value, activeId: event.target.value })); setComparing(false); }}>
            {collection.items.map((item) => <option key={item.id} value={item.id}>{name(item)}{isBusy(item.id) ? ` · ${t("strategyReview.status.running")}` : ""}</option>)}
          </select>}
      </div>
      <button aria-pressed={comparing} onClick={() => setComparing(!comparing)}>{t("strategyCompare.title")}</button>
      <button onClick={() => add(false)}>{t("strategyCollection.add")}</button>
      <details className="native-actions-menu"><summary>{t("report.more")}</summary><div>
      <button disabled={!selected} onClick={() => add(true)}>{t("strategyCollection.copy")}</button>
      <button disabled={!selected} aria-expanded={editing} onClick={() => setEditing(!editing)}>{t("strategyCollection.rename")}</button>
      <button disabled={!selected || isBusy(selected.id)} title={selected && isBusy(selected.id) ? t("strategyCollection.runningHint") : undefined}
        onClick={() => { if (!selected) return; update((value) => normalizeNativeStrategies({ ...value, items: value.items.filter((item) => item.id !== selected.id) })); setEditing(false); }}>{t("strategyCollection.remove")}</button>
      </div></details>
    </div>
    {editing && selected && <label className="native-strategy-name">{t("strategyCollection.name")}<input autoFocus maxLength={80} value={selected.name}
      placeholder={t("strategyCollection.default")} onChange={(event) => updateInstance(selected.id, { name: event.target.value })}
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === "Escape") setEditing(false); }} /></label>}
    {storageError && <p role="alert">{storageError}</p>}
    <div className="strategy-mode-pane" hidden={!comparing}><NativeStrategyComparison items={collection.items}
      context={[props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval]}
      saved={collection.comparisons?.[JSON.stringify([props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval])]}
      onSave={(selection) => update((value) => ({ ...value, comparisons: { ...value.comparisons, [JSON.stringify([props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval])]: selection } }))}
      onOpen={(id) => { update((value) => ({ ...value, activeId: id })); setComparing(false); }} /></div>
    {collection.items.map((item) => <div key={item.id} className="strategy-mode-pane" hidden={comparing || item.id !== collection.activeId}>
      <NativeStrategyInstancePanel {...props} instance={item} onInstanceChange={updateInstance} onInstanceBusy={setInstanceBusy}
        cellScope={strategyInstanceScope(props.cellScope, item.id)} active={props.active !== false && !comparing && item.id === collection.activeId} />
    </div>)}
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
  return <>{([...visited]).map((item) => <div key={item} className="strategy-mode-pane" hidden={mode !== item}>
    <NativeStrategySession {...props} active={(props.active ?? true) && mode === item} executionMode={item} onExecutionModeChange={switchMode} />
  </div>)}</>;
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
  const [language, setLanguage] = useState<"pine" | "pyne">(props.instance.language);
  const mode = props.executionMode;
  const [hostSettings, setHostSettings] = useState({ initial_balance: 10000, slippage_bps: 1, taker_fee_bps: 0, price_tick: 0.01 });
  const [fidelity, setFidelity] = useState("BAR_APPROX");
  const [fillRecalculation, setFillRecalculation] = useState(false);
  const [executionData, setExecutionData] = useState<unknown>(null);
  const [executionDataState, setExecutionDataState] = useState<"ready" | "loading" | "invalid">("ready");
  const executionUpload = useRef(0);
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
  const onRunChange = props.onRunChange;
  useEffect(() => { if (props.active !== false) onRunChange?.(run); }, [run, onRunChange, props.active]);
  const instanceRef = useRef(props.instance);
  instanceRef.current = props.instance;
  const patchInstance = useRef(props.onInstanceChange);
  patchInstance.current = props.onInstanceChange;
  const runContext = JSON.stringify([mode, props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval]);
  const { onInstanceBusy } = props;
  const instanceId = props.instance.id;
  useEffect(() => { onInstanceBusy(`${instanceId}:${mode}`, busy); return () => onInstanceBusy(`${instanceId}:${mode}`, false); }, [busy, onInstanceBusy, instanceId, mode]);
  useEffect(() => { patchInstance.current(instanceRef.current.id, { language }); }, [language]);
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
    } catch { setSource(NATIVE_TEMPLATES[language]); setParameters("{}"); setAutomaticContexts([]); setHistoryStart(defaultStart); setHistoryEnd(defaultEnd); }
    setAdvanced(emptyAdvancedInputs());
  }, [storageKey, legacyStorageKey, language, mode]);
  useEffect(() => { setResolution(null); }, [props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval]);
  const save = (text: string, params: string, contexts = automaticContexts, start = historyStart, end = historyEnd) => {
    setSource(text); setParameters(params);
    const draft = JSON.stringify({ source: text, parameters: params, automaticContexts: contexts, historyStart: start, historyEnd: end });
    const item = instanceRef.current;
    patchInstance.current(item.id, { drafts: { ...item.drafts, [`${language}:${mode}`]: draft } });
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
    pendingOverview.current = !run?.result && !previousRun?.result ? navigationRevision.current : null;
    if (run?.result) setPreviousRun(run);
    setHistoricalRun(null); setBusy(true); setError(""); setRun(null); setPreparation(null); setResolution(null);
    try {
      const params: unknown = JSON.parse(parameters);
      if (!params || Array.isArray(params) || typeof params !== "object") throw new Error(t("native.parametersInvalid"));
      const context = props.session;
      const execution = executionInputs(mode, hostSettings, fidelity, fillRecalculation, executionData);
      if (automatic && mode === "NATIVE" && !props.dataset && !advanced.contexts.length && !advanced.magnifier) {
        const startTime = Date.parse(`${historyStart}T00:00:00Z`);
        const endTime = Date.parse(`${historyEnd}T00:00:00Z`);
        if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || endTime <= startTime) throw new Error("INVALID_RANGE: select an increasing UTC date range");
        const inputs = await freezeAdvancedInputs(advanced, language, {
          start_time_ms: startTime, end_time_ms: endTime - 1, exchange: context.exchange, market_type: context.marketType,
        });
        const submission = { language, source, parameters: params, libraries: inputs.libraries,
          contexts: automaticContexts.map((row) => ({ ...row, binding_symbol: row.binding_symbol.trim() || undefined })),
          context: { exchange: context.exchange, market_type: context.marketType, symbol: context.symbol,
            interval: context.interval, range_mode: "CUSTOM", fidelity_preference: "FAST", start_time_ms: startTime, end_time_ms: endTime - 1 } };
        const body = JSON.stringify(submission);
        if (preparationSubmission.current?.body !== body) preparationSubmission.current = { body, key: crypto.randomUUID() };
        preparationObserver.current?.abort();
        const observer = new AbortController();
        preparationObserver.current = observer;
        let initial = await preparationRequest<PreparationJob>("/native-strategy", {
          method: "POST", headers: { "Content-Type": "application/json" }, signal: observer.signal,
          body: JSON.stringify({ ...submission, idempotency_key: preparationSubmission.current.key }),
        });
        if (["FAILED", "BLOCKED_STORAGE"].includes(initial.state)) {
          initial = await preparationRequest<PreparationJob>(`/${initial.id}/retry`, { method: "POST", signal: observer.signal });
        }
        if (initial.state === "CANCELLED") preparationSubmission.current = null;
        const ready = await waitForPreparation(initial, setPreparation, observer.signal);
        if (!ready.result?.native_run) throw new Error("Prepared native strategy is missing its run");
        if (alive.current) { receiveRun(ready.result.native_run); }
        return;
      }
      if (props.dataset) {
        const catalog = await nativeApi<{ datasets: Array<{ dataset_id: string; data_epoch: string; first_open_ms: number; last_close_ms: number }> }>("/datasets");
        const dataset = catalog.datasets.find((item) => item.dataset_id === props.dataset!.datasetId && item.data_epoch === props.dataset!.dataEpoch);
        if (!dataset) throw new Error("DATA_SNAPSHOT_MISMATCH: imported dataset changed");
        const data = { dataset_id: dataset.dataset_id, data_epoch: dataset.data_epoch, start_time_ms: dataset.first_open_ms,
          end_time_ms: dataset.last_close_ms, interval: context.interval, exchange: context.exchange, market_type: context.marketType };
        const snapshot = await nativeApi<{ snapshot_hash: string }>("/datasets/snapshot", data);
        const inputs = await freezeAdvancedInputs(advanced, language, data);
        const result = await nativeApi<NativeRun>(runPath, { ...data, ...inputs, ...execution, snapshot_hash: snapshot.snapshot_hash,
          language, source, parameters: params, context: { symbol: context.symbol, timeframe: nativeTimeframe(context.interval) } }, crypto.randomUUID());
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
    } catch (reason) { if (alive.current) { setError(String(reason)); setBusy(false); } }
  };
  const ownedRunIds = strategyRunIds(props.instance, mode);
  const visibleHistory = allHistory ? history : history.filter((item) => ownedRunIds.has(item.run_id));
  const reportRun = historicalRun ?? (run?.result ? run : previousRun);
  let parametersChanged = false;
  try { parametersChanged = JSON.stringify(reportRun?.config?.parameters ?? {}) !== JSON.stringify(JSON.parse(parameters)); } catch { parametersChanged = true; }
  const resultStale = !!reportRun && (reportRun !== run || reportRun.config?.source !== source || reportRun.config?.language !== language || parametersChanged);
  const available = capabilities?.engines.find((item) => item.language === language);
  return <section className={`native-strategy-panel${props.docked ? " native-strategy-docked" : ""}`} aria-label={t("native.title")}>
    {!props.docked && <header><strong>{t(mode === "NATIVE" ? "native.title" : "native.external.title")}</strong><span>{props.session.symbol} · {props.session.interval}</span><button type="button" aria-label={t("backtest.close")} onClick={props.onClose}><Icon name="close" size={14} /></button></header>}
    {props.docked && <nav className="native-dock-tabs" aria-label={t("chartTester.tabsAria")}>
      {(["overview", "trades", "script", "settings"] as const).map((item) => <button key={item} aria-pressed={tab === item}
        onClick={() => selectTab(item)}>{t(`chartTester.tab.${item}`)}</button>)}
    <details className="native-actions-menu"><summary>{t("report.more")}</summary><div><button aria-pressed={tab === "history"} onClick={(event) => { selectTab("history"); event.currentTarget.closest("details")?.removeAttribute("open"); }}>{t("native.history")}</button></div></details>
    </nav>}
    <div className="native-dock-actions">
    <div className="native-toolbar"><select aria-label={t("native.language")} value={language} disabled={busy} onChange={(event) => setLanguage(event.target.value as "pine" | "pyne")}>
      <option value="pine">{t("chartTester.language.pine")}</option><option value="pyne">{t("chartTester.language.pyne")}</option></select>
      <button disabled={busy || (mode === "CANDLESCOPE" && fidelity !== "BAR_APPROX" && executionDataState !== "ready") || !(mode === "NATIVE" ? available?.available : available?.external_available)} onClick={() => void start()}>{t(mode === "NATIVE" ? "native.run" : "native.external.run")}</button>
      {run && !nativeTerminal(run.state) && <button onClick={() => void nativeApi<NativeRun>(`${runPath}/${run.run_id}/cancel`, {}).then(receiveRun).catch((reason) => setError(String(reason)))}>{t("native.cancel")}</button>}
      <span role="status" className="native-run-status">{t(`strategyReview.status.${preparation?.state === "CANCELLED" || run?.state === "CANCELLED" ? "cancelled" : error || run?.state === "FAILED" || run?.state === "INTERRUPTED" ? "failed" : busy ? (run ? "running" : "preparing") : run?.state === "COMPLETED" ? "completed" : resolution && resolution.status !== "READY" ? "needsData" : "idle"}`)}</span></div>
    {available && !(mode === "NATIVE" ? available.available : available.external_available) && <p role="alert">{t("native.unavailable")} {available.reason}</p>}
    </div>
    <div className="native-dock-scroll" ref={scrollPane} onScroll={(event) => { scrollPositions.current[tab] = event.currentTarget.scrollTop; }}>
    {preparation && !["READY", "CANCELLED"].includes(preparation.state) && <p role="status">{t("preparation.title")} · {preparation.completed}/{preparation.total}
      <PreparationWaiting job={preparation} />
      <button disabled={preparation.stage === "STARTING" || preparation.cancel_requested} onClick={() => void preparationRequest<PreparationJob>(`/${preparation.id}/cancel`, { method: "POST" }).then((value) => { preparationSubmission.current = null; setPreparation(value); }).catch((reason) => setError(String(reason)))}>{t("preparation.cancel")}</button>
    </p>}
    {resolution && resolution.status !== "READY" && <p>{resolution.status} <button disabled={busy} onClick={() => void start(true)}>{t("native.prepare")}</button></p>}
    {(error || run?.error) && <pre role="alert">{error || `${run?.error?.message}\n${JSON.stringify(run?.error?.details ?? {}, null, 2)}`}</pre>}
    <div hidden={props.docked && tab !== "script"}>
    <div className="native-editor"><textarea aria-label={t("native.source")} value={source} disabled={busy} spellCheck={false} onChange={(event) => save(event.target.value, parameters)} />
      <label>{t("native.parameters")}<textarea value={parameters} disabled={busy} onChange={(event) => save(source, event.target.value)} /></label></div>
    </div>
    <div hidden={props.docked && tab !== "settings"} className="native-dock-settings">
    <div className="native-toolbar"><button aria-pressed={mode === "NATIVE"} disabled={busy} onClick={() => { props.onExecutionModeChange("NATIVE"); }}>{t("native.title")}</button>
      <button aria-pressed={mode === "CANDLESCOPE"} disabled={busy} onClick={() => { props.onExecutionModeChange("CANDLESCOPE"); }}>{t("native.external.title")}</button></div>
    <p>{t(mode === "NATIVE" ? "native.description" : "native.external.description")}</p>
    {automatic && mode === "NATIVE" && !props.dataset && !advanced.contexts.length && !advanced.magnifier && <div className="native-toolbar">
      <label>{t("preparation.startDate")}<input type="date" disabled={busy} value={historyStart} onChange={(event) => { setHistoryStart(event.target.value); save(source, parameters, automaticContexts, event.target.value, historyEnd); }} /></label>
      <label>{t("preparation.endDate")}<input type="date" disabled={busy} value={historyEnd} onChange={(event) => { setHistoryEnd(event.target.value); save(source, parameters, automaticContexts, historyStart, event.target.value); }} /></label>
    </div>}
    {automatic && mode === "NATIVE" && !props.dataset && !advanced.contexts.length && !advanced.magnifier && <NativePreparationContexts
      value={automaticContexts} onChange={(value) => { setAutomaticContexts(value); save(source, parameters, value); }} disabled={busy}
      exchange={props.session.exchange} marketType={props.session.marketType} symbol={props.session.symbol} />}
    {mode === "CANDLESCOPE" && <div className="native-toolbar">{(["initial_balance", "slippage_bps", "taker_fee_bps", "price_tick"] as const).map((field) => <label key={field}>{t(`native.external.${field}`)}
      <input type="number" min="0" step="any" disabled={busy} value={hostSettings[field]} onChange={(event) => setHostSettings((value) => ({ ...value, [field]: Number(event.target.value) }))} />
    </label>)}</div>}
    {mode === "CANDLESCOPE" && <div className="native-toolbar">
      <label>{t("native.external.fidelity")}<select disabled={busy} value={fidelity} onChange={(event) => { setFidelity(event.target.value); setRun(null); setPreviousRun(null); }}>
        <option value="BAR_APPROX">BAR_APPROX</option><option value="TRADE_TAPE">TRADE_TAPE</option><option value="BOOK_ASSISTED">BOOK_ASSISTED</option><option value="BOOK_DEPTH">BOOK_DEPTH</option>
        <option value="BOOK_SAMPLED">{t("native.external.sampledLabel")}</option>
      </select></label>
      {fidelity === "BOOK_DEPTH" && <p>{t("native.external.depthHint")}</p>}
      {fidelity === "BOOK_SAMPLED" && <p>{t("native.external.sampledHint")}</p>}
      {fidelity !== "BAR_APPROX" && <label>{t("native.external.executionData")}<input type="file" accept="application/json,.json" disabled={busy} onChange={(event) => {
        const file = event.target.files?.[0];
        const upload = ++executionUpload.current;
        setExecutionData(null);
        setExecutionDataState(file ? "loading" : "ready");
        if (file) void file.text().then((text) => {
          if (upload !== executionUpload.current) return;
          setExecutionData(JSON.parse(text)); setExecutionDataState("ready"); setError("");
        }).catch((reason) => {
          if (upload !== executionUpload.current) return;
          setExecutionDataState("invalid"); setError(String(reason));
        });
      }} /></label>}
      {fidelity !== "BAR_APPROX" && <><label><input type="checkbox" disabled={busy} checked={fillRecalculation} onChange={(event) => setFillRecalculation(event.target.checked)} />{t("native.external.fillRecalculation")}</label><p>{t("native.external.fillHint")}</p>{fidelity !== "BOOK_SAMPLED" && <p>{t("native.external.dataHint")}</p>}</>}
    </div>}
    <details><summary>{t("native.mode")}</summary>
    {<NativeAdvancedInputs native={mode === "NATIVE"} value={advanced} onChange={setAdvanced} language={language} disabled={busy} exchange={props.session.exchange} />}
    </details></div>
    <div className="native-dock-report" data-view={tab} hidden={props.docked && tab !== "overview" && tab !== "trades"}>
      {historicalRun && <p role="status">{t("strategyHistory.viewing")} <code>{historicalRun.run_id}</code> <button onClick={() => setHistoricalRun(null)}>{t("strategyHistory.latest")}</button></p>}
      {resultStale && !historicalRun && <p role="status">{t("chartTester.result.staleGuidanceTitle")}</p>}
      {!reportRun?.result && props.docked && <p className="native-dock-empty">{t("strategyDock.empty")}</p>}
      {reportRun?.result && !props.externalReport && <NativeStrategyReport key={reportRun.run_id} run={reportRun} onLocate={props.onLocateTrade} onReviewTrade={props.onReviewTrade} active={!historicalRun && props.active !== false && (!props.docked || tab === "trades")}
        view={props.docked ? (tab === "trades" ? "trades" : "overview") : "all"} />}
    </div>
    <div hidden={props.docked && tab !== "history"}>
    {run?.config?.source && <details><summary>{t("native.source")}</summary><pre>{run.config.source}</pre></details>}
    <label><input type="checkbox" checked={allHistory} onChange={(event) => setAllHistory(event.target.checked)} />{t("strategyHistory.all")}</label>
    <p>{t("strategyHistory.ownership")}</p>
    {!visibleHistory.length && <p>{t("strategyHistory.empty")}</p>}
    <details open={props.docked}><summary>{t(mode === "NATIVE" ? "native.history" : "native.external.history")}</summary>{visibleHistory.map((item) => <button key={item.run_id} disabled={busy} onClick={() => void nativeApi<NativeRun>(`${runPath}/${item.run_id}`).then((value) => { pendingOverview.current = null; setError(""); setHistoricalRun(value); selectTab("overview"); }).catch((reason) => setError(String(reason)))}>
      {new Date(item.created_at_ms).toLocaleString(locale)} · {item.runtime_identity.engine.package} · {item.state}</button>)}</details>
    </div>
    </div>
  </section>;
}
