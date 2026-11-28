import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { floorIntervalTime } from "../../../utils/intervalTimeline.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { useMarketDataWorkspaceResources } from "../../market-data/marketDataWorkspaceContext.js";
import { resolveKlineSeriesIdentity } from "../../market-data/klineSeriesIdentity.js";
import type { ChartSession } from "../../chart-session/chartSessionTypes.js";
import { validStrategyRunSettings, type StrategyRunSettings, type StrategyExecutionOverrides, type StrategyInitializationSettings } from "../../../shared/strategyRunSettings.js";
import type { ContinuousObservation } from "../../market-data/manager/continuousStrategyDataManager.js";
import { strategyDraftContentRevision } from "../chart-tester/chartStrategyTesterDrafts.js";
import { backendContinuousReferences, type ContinuousRunReference } from "./continuousRunReference.js";
import { useStrategyDataManager } from "../../market-data/useStrategyDataManager.js";
import type { ContinuousAction, ContinuousCapabilities, ContinuousCreate, ContinuousCreation, ContinuousMode } from "./continuousTypes.js";
import type { SeriesWindowView } from "../../market-data/window/seriesWindowView.js";
import ContinuousBarBoundary from "./ContinuousBarBoundary.js";
import ContinuousParameterEditor from "./ContinuousParameterEditor.js";
import ContinuousAutoRepairSetting from "./ContinuousAutoRepairSetting.js";
import ContinuousRepairPanel from "./ContinuousRepairPanel.js";
import ContinuousAccountView from "./ContinuousAccountView.js";
import { forwardBarOpenMs, forwardIntervalMs, MINUTE_MS } from "./forwardInterval.js";
import { readContinuousAccountRows } from "./continuousAccountRows.js";
import {
  PRACTICE_ACCOUNT_RULES, defaultForwardFeeBps, defaultForwardLeverage, forwardAccountLeverage, forwardExecutionModel, forwardModelExecution, validForwardLeverage,
} from "./continuousAccountRules.js";
import type { StrategyOverlayRun } from "../runResult/useStrategyRunOverlay.js";
import { continuousMarketSupported } from "../../exchange-support/capabilityRoles.js";
import { useVenueRoles } from "../../exchange-support/useVenueRoles.js";
import "./continuousStrategy.css";

/** The backend's continuous-source rules (`continuous_definition.py`). */
const CONTINUOUS_SERIES_VARIANTS: ReadonlySet<string> = new Set(["native", "ohlcv"]);
const CONTINUOUS_VOLUME_SEMANTICS: ReadonlySet<string> = new Set(["base_asset", "shares"]);

export interface ContinuousStrategyPanelProps {
  signalChart?: import("../../../shared/strategyRunSettings.js").ChartSignalDefinition | undefined;
  scope: string; session: ChartSession; mode: Exclude<ContinuousMode, "HISTORY">;
  source: string; language: string; parameters: Record<string, unknown>;
  trusted: boolean; active: boolean; editor: (run: () => void) => ReactNode;
  initialization?: StrategyInitializationSettings;
  initialExecution?: StrategyExecutionOverrides;
  initialFromMs?: number;
  chartActive?: boolean;
  /**
   * The chart's market has live bars at its interval. A forward run follows live closed bars, so a
   * history-only source (Twelve Data's US equities) cannot run one (ADR-DATA-002 D2c).
   */
  liveBars?: boolean | undefined;
  marketWindow?: SeriesWindowView | null;
  /** The forward run the chart should overlay (ADR-BACKTEST-015 P2d), or null. */
  onOverlayRunChange?(run: StrategyOverlayRun | null): void;
  onLocateTrade?(timeMs: number): void;
  onDetach?(): Promise<void>;
  onOpenWorkspace?(settings: StrategyRunSettings): Promise<void>;
  saveDraft?(): Promise<void>;
  onParameterChange?(name: string, value: string | number | boolean): void;
  literalParameters?(disabled: boolean): ReactNode;
}
const connectionMessages = { loading: "continuous.loading", connected: "continuous.connected", reconnecting: "continuous.reconnecting",
  closed: "continuous.closed", error: "continuous.error" } as const;
const empty = { creation: null, result: null, initialReady: false, connection: "loading", error: null, repair: null,
  rows: { fills: [], equity: [] },
} satisfies ContinuousObservation & { rows: ReturnType<typeof readContinuousAccountRows> };
function object(value: unknown): Record<string, unknown> { return value !== null && typeof value === "object" ? value as Record<string, unknown> : {}; }
function time(value: unknown): string {
  const number = Number(value);
  return value !== undefined && Number.isFinite(number) && Math.abs(number) <= 8640000000000000
    ? new Date(number).toISOString().replace("T", " ").replace(".000Z", " UTC") : "—";
}

export default function ContinuousStrategyPanel(props: ContinuousStrategyPanelProps) {
  useLocale();
  const manager = useMarketDataWorkspaceResources()?.dataManager.strategy.continuous;
  const strategyManager = useStrategyDataManager();
  const references = useMemo(() => strategyManager ? backendContinuousReferences(strategyManager, browserStorage()) : null, [strategyManager]);
  const [caps, setCaps] = useState<ContinuousCapabilities | null>(null);
  const [reference, setReference] = useState<ContinuousRunReference | null>(null);
  const [savedRuns, setSavedRuns] = useState<ContinuousRunReference[]>([]);
  const [creation, setCreation] = useState<ContinuousCreation | null>(null);
  const [state, setState] = useState<ContinuousObservation & { rows: ReturnType<typeof readContinuousAccountRows> }>(empty);
  const [error, setError] = useState<string | null>(null);
  const [storageFailed, setStorageFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const mounted = useRef(false);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const [attempt, setAttempt] = useState(0);
  const [from, setFrom] = useState(() => new Date(props.initialFromMs ?? Date.now() - 86400000).toISOString().slice(0, 16));
  const [balance, setBalance] = useState(props.initialExecution?.initialBalance ?? "10000"), [percent, setPercent] = useState(props.initialExecution?.equityPercent ?? "10");
  const [fee, setFee] = useState(() => defaultForwardFeeBps(props.initialExecution)), [slippage, setSlippage] = useState(props.initialExecution?.slippageBps ?? "1");
  const [output, setOutput] = useState<ContinuousCreate["provider"]["output_mode"]>(props.initialization?.outputMode ?? "SIGNAL");
  // ADR-BACKTEST-015 P6e: new forward runs trade on the practice account model (continuousAccountRules).
  const executionModel = forwardExecutionModel(props.initialization, reference);
  const spot = props.session.marketType === "spot";
  const [leverage, setLeverage] = useState(() => defaultForwardLeverage(props.session.marketType, props.initialExecution));
  const accountLeverage = forwardAccountLeverage(executionModel, props.session.marketType, leverage);
  const identity = resolveKlineSeriesIdentity(props.session.exchange, props.session);
  const venueRoles = useVenueRoles();
  const scope = JSON.stringify([props.scope, props.mode, props.session.exchange, props.session.marketType,
    props.session.symbol, props.session.interval, identity]);
  const inputRevision = useMemo(() => String(strategyDraftContentRevision(JSON.stringify([props.source, props.parameters, props.signalChart, balance, percent, fee, slippage, output, props.initialization, props.mode === "HISTORY_LIVE" ? from : null,
    ...(executionModel === "PRACTICE" ? [executionModel, accountLeverage] : [])]))),
    [props.source, props.parameters, props.signalChart, props.mode, props.initialization, balance, percent, fee, slippage, output, from, executionModel, accountLeverage]);
  const hasSource = useMemo(() => props.source.trim().length > 0, [props.source]);
  // ADR-DATA-002 D2c: the source's live bars and price semantics decide, not its asset class.
  const liveBarsUnavailable = props.liveBars === false;
  // B-333: the run advances on closed bars of the chart's interval, any fixed length of whole minutes.
  const barMs = forwardIntervalMs(props.session.interval);
  const qualified = props.language === "python" && hasSource && barMs !== null && !liveBarsUnavailable
    && continuousMarketSupported(venueRoles(props.session.exchange), props.session.marketType)
    && CONTINUOUS_SERIES_VARIANTS.has(identity.seriesVariant) && identity.priceAdjustment === "raw"
    && CONTINUOUS_VOLUME_SEMANTICS.has(identity.volumeSemantics);
  useEffect(() => {
    if (!references) return;
    let cancelled = false;
    void (async () => {
      try {
        const saved = await references.read(scope);
        const listed = await references.list(scope);
        if (cancelled) return;
        setReference(saved); setStorageFailed(false); setSavedRuns(listed);
        if (saved) {
          setFrom(saved.settings.from); setBalance(saved.settings.balance); setPercent(saved.settings.percent);
          setFee(saved.settings.fee); setSlippage(saved.settings.slippage); setOutput(saved.settings.output);
          if (saved.settings.leverage) setLeverage(saved.settings.leverage);
        }
      }
      catch { if (!cancelled) { setStorageFailed(true); setError(t("continuous.storage")); } }
    })();
    return () => { cancelled = true; };
  }, [references, scope]);
  useEffect(() => {
    if (!manager || !props.active) return;
    const controller = new AbortController();
    void manager.capabilities(controller.signal).then(setCaps).catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [manager, props.active]);
  const observe = props.active || props.chartActive;
  useEffect(() => {
    if (!manager || !observe || !reference?.runId) return;
    try {
      return manager.observe(reference.runId, (next) => {
        // Read against the commit being published. React may render after the
        // Manager has already advanced to a later checkpoint.
        setState({ ...next, rows: readContinuousAccountRows(manager, next.result) });
      });
    } catch (failure) { setError(String(failure)); }
  }, [manager, observe, reference?.runId, attempt]);
  const view = state.result?.identity.id === reference?.runId ? state.result : null;
  // The chart overlay draws the run's committed account from the run facade; a stale
  // (repair-required) account is not drawn.
  const overlayRunId = props.chartActive && view && !view.stale ? view.identity.id : null;
  const onOverlayRunChange = props.onOverlayRunChange;
  useEffect(() => {
    onOverlayRunChange?.(overlayRunId ? { family: "continuous", runId: overlayRunId } : null);
  }, [onOverlayRunChange, overlayRunId]);
  useEffect(() => () => onOverlayRunChange?.(null), [onOverlayRunChange]);

  // The chart's forward-run references live in the backend (ADR-BACKTEST-015 P3c).
  async function save(next: ContinuousRunReference) {
    try {
      if (!references) throw new Error(t("continuous.storage"));
      await references.activate(scope, next); setReference(next); setSavedRuns(await references.list(scope));
    }
    catch { setStorageFailed(true); throw new Error(t("continuous.storage")); }
  }
  const matchingPending = savedRuns.find((item) => !item.runId && item.inputRevision === inputRevision);
  const changedInputs = !!reference?.runId && reference.inputRevision !== inputRevision;
  async function initialize() {
    if (submitting.current || busy || storageFailed || !manager || !caps?.execution_enabled || !caps.python_editor_authorized || !props.trusted || !qualified) return;
    submitting.current = true;
    setBusy(true); setError(null);
    try {
      // A history start is the open of the bar it falls in, on the run's grid.
      const start = forwardBarOpenMs(props.session.interval, Date.parse(from + ":00Z")) ?? Number.NaN;
      if (![balance, percent, fee, slippage].every((value) => value.trim() && Number.isFinite(Number(value)))
        || Number(balance) <= 0 || Number(percent) <= 0 || Number(percent) > 100 || Number(fee) < 0 || Number(slippage) < 0
        || !validForwardLeverage(accountLeverage)
        || (props.mode === "HISTORY_LIVE" && (!Number.isSafeInteger(start) || start < 0 || start >= Date.now()))) throw new Error(t("continuous.invalid"));
      const next: ContinuousRunReference = reference && !reference.runId ? reference : matchingPending ?? { schema: 1, requestKey: "chart/" + crypto.randomUUID(), runId: null, inputRevision, createdAtMs: Date.now(),
        settings: { from, balance, percent, fee, slippage, output, ...(executionModel === "PRACTICE" ? { leverage: accountLeverage } : {}) } };
      if (next.inputRevision !== inputRevision) throw new Error(t("continuous.pending"));
      await props.saveDraft?.();
      if (!mounted.current) return;
      // Persist the request before submission while keeping a known account
      // selected until the backend acknowledges the replacement.
      if (reference?.runId) {
        try {
          if (!references) throw new Error(t("continuous.storage"));
          await references.archive(scope, next);
          setSavedRuns(await references.list(scope));
        } catch {
          setStorageFailed(true);
          throw new Error(t("continuous.storage"));
        }
      } else await save(next);
      const result = await manager.create(next.requestKey, { mode: props.mode,
        series: { exchange: props.session.exchange, market_type: props.session.marketType, symbol: props.session.symbol, interval: props.session.interval,
          identity: { provider_id: identity.providerId, venue: identity.venue, asset_class: identity.assetClass,
            series_variant: identity.seriesVariant, price_adjustment: identity.priceAdjustment, session_variant: identity.sessionVariant, volume_semantics: identity.volumeSemantics } },
        provider: { language: "python", source_text: props.source, parameters: props.parameters, output_mode: output, runtime_mode: "TRUSTED_LOCAL", trusted_confirmed: true },
        execution: { ...(props.signalChart ? { signal_chart: props.signalChart } : {}), account_model: props.session.marketType === "spot" ? "SPOT_CASH_V1" : "LINEAR_PERP_ONE_WAY_V1",
          initial_balance: balance, sizing_policy: "EQUITY_PERCENT_V1", equity_percent: percent, taker_fee_bps: fee, maker_fee_bps: fee, slippage_bps: slippage,
          ...forwardModelExecution(executionModel, accountLeverage) },
        ...(props.initialization ? { warmup_bars: props.initialization.warmupBars } : {}),
        ...(props.mode === "HISTORY_LIVE" ? { from_ms: start } : {}),
      });
      await save({ ...next, runId: result.creation.run_id }); setCreation(result.creation); setState(empty);
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { submitting.current = false; setBusy(false); }
  }
  async function recover() {
    if (!manager || !reference) return;
    setBusy(true); setError(null);
    try {
      const result = await manager.request(reference.requestKey);
      setCreation(result.creation); await save({ ...reference, runId: result.creation.run_id }); setAttempt((value) => value + 1);
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  }
  async function control(action: ContinuousAction) {
    const observed = state.creation ?? creation;
    if (!manager || !reference || !observed) return;
    setBusy(true); setError(null);
    try {
      // Initial HTTP results may still be waiting. Read control metadata on the
      // explicit action so initialization remains pausable without opening WS early.
      const latest = !view && reference.runId ? await manager.status(reference.runId) : null;
      const response = await manager.control(reference.requestKey, { action, revision: latest?.creation?.revision ?? observed.revision,
        ...(view ? { expected: view.identity } : latest?.identity ? { expected: latest.identity } : {}) });
      setCreation(response.creation);
    } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  }
  const observed = state.creation ?? creation;
  const start = props.mode === "HISTORY_LIVE" ? forwardBarOpenMs(props.session.interval, Date.parse(from + ":00Z")) ?? -1
    : (observed?.cutoff_ms ?? -1) + 1;
  const warmupBars = props.initialization?.warmupBars ?? 0;
  const researchSettings: StrategyRunSettings | null = view && !view.stale && observed?.run_id === view.identity.id && barMs !== null
    && start > 0 && start % MINUTE_MS === 0 && (view.identity.event_time_ms + 1 - start) % barMs === 0
    && view.identity.event_time_ms >= start + warmupBars * barMs ? {
      parameters: props.parameters, fidelityPreference: "FAST", rangeMode: "CUSTOM",
      customRange: { startMs: start, endMs: view.identity.event_time_ms },
      executionOverrides: { initialBalance: balance, equityPercent: percent, leverage: accountLeverage, feeBps: fee, slippageBps: slippage },
      pythonBarExecution: { outputMode: output, executionModel, warmupBars },
    } : null;

  async function openResearch() {
    if (submitting.current || busy || !props.onOpenWorkspace || !researchSettings
      || !validStrategyRunSettings(researchSettings) || !qualified) return;
    submitting.current = true;
    setBusy(true); setError(null);
    try { await props.onOpenWorkspace(researchSettings); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { submitting.current = false; setBusy(false); }
  }
  async function detach() {
    if (submitting.current || busy || !props.onDetach) return;
    submitting.current = true;
    setBusy(true); setError(null);
    try { await props.onDetach(); }
    catch (failure) { if (mounted.current) setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { submitting.current = false; if (mounted.current) setBusy(false); }
  }
  const phase = view?.run.phase ?? observed?.phase;
  const failure = object(view?.run.error ?? observed?.error);
  return <div className="continuous-strategy" data-continuous-strategy>
    <p>{t("continuous.hint")}</p><p>{t("continuous.scopeHint")}</p><p>{t("continuous.support")}</p>
    {savedRuns.length > 0 && <label>{t("continuous.savedRuns")}<select disabled={busy || storageFailed} value={reference?.requestKey ?? ""} onChange={(event) => {
      const selected = savedRuns.find((value) => value.requestKey === event.target.value);
      if (!selected) return;
      void save(selected).then(() => {
        setCreation(null); setState(empty); setError(null);
        setFrom(selected.settings.from); setBalance(selected.settings.balance); setPercent(selected.settings.percent);
        setFee(selected.settings.fee); setSlippage(selected.settings.slippage); setOutput(selected.settings.output);
        if (selected.settings.leverage) setLeverage(selected.settings.leverage);
      }, (failure: unknown) => setError(String(failure)));
    }}><option value="" disabled>{t("continuous.savedRuns")}</option>{savedRuns.map((saved) => <option key={saved.requestKey} value={saved.requestKey}>
      {time(saved.createdAtMs)} · {saved.runId?.slice(-8) ?? t("continuous.pendingRun")}
    </option>)}</select></label>}
    <div className="continuous-settings">
      {props.mode === "HISTORY_LIVE" && <label>{t("continuous.from")}<input type="datetime-local" value={from} onChange={(event) => setFrom(event.target.value)} /></label>}
      {([["continuous.balance", balance, setBalance], ["continuous.percent", percent, setPercent], ["continuous.fee", fee, setFee], ["continuous.slippage", slippage, setSlippage]] as const).map(([label, value, change]) =>
        <label key={label}>{t(label)}<input type="number" min="0" step="any" value={value} onChange={(event) => change(event.target.value)} /></label>)}
      {executionModel === "PRACTICE" && !spot && <label>{t("continuous.leverage")}<input type="number" min="1" max="125" step="1"
        value={leverage} onChange={(event) => setLeverage(event.target.value)} /></label>}
      <label>{t("continuous.output")}<select aria-label={t("continuous.output")} value={output} onChange={(event) => setOutput(event.target.value as typeof output)}>
        <option value="SIGNAL">{t("continuous.signal")}</option><option value="TARGET_POSITION">{t("continuous.target")}</option><option value="ORDER_INTENT">{t("continuous.order")}</option>
      </select></label>
    </div>
    {executionModel === "PRACTICE" && <p className="continuous-account-rules" data-account-rules={PRACTICE_ACCOUNT_RULES}>{t("continuous.practiceRules")}</p>}
    {props.onParameterChange && <ContinuousParameterEditor
      manager={manager} source={props.source} parameters={props.parameters}
      enabled={props.active && props.language === "python" && !!caps?.python_editor_authorized}
      disabled={busy} onChange={props.onParameterChange}
      fallback={props.literalParameters?.(busy)}
    />}
    {props.editor(() => { void initialize(); })}
    {!qualified && <p role="status">{liveBarsUnavailable
      ? t("continuous.liveBarsUnavailable", { symbol: props.session.symbol })
      : t("continuous.unsupported")}</p>}
    {reference && reference.inputRevision !== inputRevision && <p role="status">{t("continuous.edited")}</p>}
    {reference && !reference.runId && <p role="status">{t("continuous.pending")}</p>}
    <div className="continuous-actions">
      <Button size="sm" variant="primary" disabled={busy || storageFailed || !qualified || !props.trusted || !caps?.execution_enabled || !caps.python_editor_authorized || (!!reference && !reference.runId && reference.inputRevision !== inputRevision)} onClick={() => { void initialize(); }}>{t((reference && !reference.runId) || matchingPending ? "continuous.resubmit" : changedInputs ? "continuous.recalculate" : "continuous.start")}</Button>
      {props.onDetach && <Button size="sm" disabled={busy || !props.language} onClick={() => { void detach(); }}>{t("continuous.detach")}</Button>}
      {reference && <Button size="sm" disabled={busy} onClick={() => { void recover(); }}>{t(reference.runId ? "continuous.observe" : "continuous.recover")}</Button>}
      {observed && (["pause", "resume", "retry", "cancel"] as const).map((action) => <Button size="sm" key={action} disabled={busy || !caps?.execution_enabled}
        onClick={() => { void control(action); }}>{t(`continuous.${action}`)}</Button>)}
    </div>
    {props.onOpenWorkspace && <div className="continuous-actions">
      <Button size="sm" disabled={busy || !qualified || !validStrategyRunSettings(researchSettings)}
        onClick={() => { void openResearch(); }}>{t("ux.openWorkspace")}</Button>
      <small>{t("continuous.researchHint")}</small>
    </div>}
    {error && <p role="alert">{error}</p>}
    {state.error && <p role="alert">{state.error.message}</p>}
    {typeof failure.message === "string" && <p role="alert">{failure.message}</p>}
    {reference?.runId && <p role="status">{t(connectionMessages[state.connection])} · {t("continuous.phase", { phase: phase ?? "…" })}</p>}
    {reference?.runId && !state.initialReady && <p role="status">{t("continuous.initializing")}</p>}
    {(view?.stale || phase === "REPAIR_REQUIRED") && <p role="alert">{t("continuous.stale")}</p>}
    {manager && view && props.active && reference?.runId === view.identity.id
      && caps?.automatic_repair_available && caps.python_editor_authorized
      && <ContinuousAutoRepairSetting key={scope+":"+view.identity.id} manager={manager} runId={view.identity.id}
        canEnable={["PAUSED", "LIVE", "CATCHING_UP"].includes(view.run.phase)} />}
    {manager && view && reference?.runId === view.identity.id && <ContinuousRepairPanel key={scope+":"+view.identity.id}
      manager={manager} view={view} repair={state.repair} active={props.active}
      available={!!caps?.execution_enabled && !!caps.repair_available && !!caps.python_editor_authorized} />}
    {qualified && <ContinuousBarBoundary marketWindow={props.chartActive ? props.marketWindow ?? null : null} view={view} />}
    {view ? <ContinuousAccountView rows={state.rows} view={view}
      {...(props.chartActive && props.onLocateTrade ? { onLocateTrade(timeMs: number) {
        const barTime = floorIntervalTime(props.session.interval, timeMs / 1000);
        if (barTime !== null) props.onLocateTrade?.(barTime * 1000);
      } } : {})} /> : <p>{t("continuous.empty")}</p>}
  </div>;
}

/** The origin's browser storage, where references lived before ADR-BACKTEST-015 P3c; null when it is unavailable. */
function browserStorage(): Storage | null {
  try { return window.localStorage; } catch { return null; }
}
