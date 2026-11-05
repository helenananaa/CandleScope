import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { useMarketDataWorkspaceResources } from "../../market-data/marketDataWorkspaceContext.js";
import { resolveKlineSeriesIdentity } from "../../market-data/klineSeriesIdentity.js";
import type { ChartSession } from "../../chart-session/chartSessionTypes.js";
import type { ContinuousObservation } from "../../market-data/manager/continuousStrategyDataManager.js";
import { strategyDraftContentRevision } from "../chart-tester/chartStrategyTesterDrafts.js";
import { activateContinuousReference, listContinuousReferences, readContinuousReference, type ContinuousRunReference } from "./continuousRunReference.js";
import type { ContinuousAction, ContinuousCapabilities, ContinuousCreate, ContinuousCreation, ContinuousMode } from "./continuousTypes.js";
import "./continuousStrategy.css";

export interface ContinuousStrategyPanelProps {
  scope: string; session: ChartSession; mode: Exclude<ContinuousMode, "HISTORY">;
  source: string; language: string; parameters: Record<string, unknown>;
  trusted: boolean; active: boolean; editor: (run: () => void) => ReactNode;
}
const connectionMessages = { loading: "continuous.loading", connected: "continuous.connected", reconnecting: "continuous.reconnecting",
  closed: "continuous.closed", error: "continuous.error" } as const;
const empty: ContinuousObservation = { creation: null, result: null, initialReady: false, connection: "loading", error: null, repair: null };
function object(value: unknown): Record<string, unknown> { return value !== null && typeof value === "object" ? value as Record<string, unknown> : {}; }
function text(value: unknown): string { return typeof value === "number" || typeof value === "string" ? String(value) : "—"; }
function time(value: unknown): string {
  const number = Number(value);
  return value !== undefined && Number.isFinite(number) && Math.abs(number) <= 8640000000000000
    ? new Date(number).toISOString().replace("T", " ").replace(".000Z", " UTC") : "—";
}

export default function ContinuousStrategyPanel(props: ContinuousStrategyPanelProps) {
  useLocale();
  const manager = useMarketDataWorkspaceResources()?.dataManager.strategy.continuous;
  const [caps, setCaps] = useState<ContinuousCapabilities | null>(null);
  const [reference, setReference] = useState<ContinuousRunReference | null>(null);
  const [savedRuns, setSavedRuns] = useState<ContinuousRunReference[]>([]);
  const [creation, setCreation] = useState<ContinuousCreation | null>(null);
  const [state, setState] = useState<ContinuousObservation>(empty);
  const [error, setError] = useState<string | null>(null);
  const [storageFailed, setStorageFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [attempt, setAttempt] = useState(0);
  const [from, setFrom] = useState(() => new Date(Date.now() - 86400000).toISOString().slice(0, 16));
  const [balance, setBalance] = useState("10000"), [percent, setPercent] = useState("10");
  const [fee, setFee] = useState("0"), [slippage, setSlippage] = useState("1");
  const [output, setOutput] = useState<ContinuousCreate["provider"]["output_mode"]>("SIGNAL");
  const identity = resolveKlineSeriesIdentity(props.session.exchange, props.session);
  const scope = JSON.stringify([props.scope, props.mode, props.session.exchange, props.session.marketType,
    props.session.symbol, props.session.interval, identity]);
  const inputRevision = useMemo(() => String(strategyDraftContentRevision(JSON.stringify([props.source, props.parameters, balance, percent, fee, slippage, output, props.mode === "HISTORY_LIVE" ? from : null]))),
    [props.source, props.parameters, props.mode, balance, percent, fee, slippage, output, from]);
  const hasSource = useMemo(() => props.source.trim().length > 0, [props.source]);
  const qualified = props.language === "python" && hasSource && props.session.interval === "1m"
    && (props.session.marketType === "spot" || (props.session.exchange === "binance" && props.session.marketType === "futures"))
    && identity.assetClass === "crypto" && identity.seriesVariant === "native" && identity.priceAdjustment === "raw"
    && identity.sessionVariant === "continuous" && identity.volumeSemantics === "base_asset";
  useEffect(() => {
    try {
      const saved = readContinuousReference(localStorage, scope); setReference(saved); setStorageFailed(false);
      setSavedRuns(listContinuousReferences(localStorage, scope));
      if (saved) {
        setFrom(saved.settings.from); setBalance(saved.settings.balance); setPercent(saved.settings.percent);
        setFee(saved.settings.fee); setSlippage(saved.settings.slippage); setOutput(saved.settings.output);
      }
    }
    catch { setStorageFailed(true); setError(t("continuous.storage")); }
  }, [scope]);
  useEffect(() => {
    if (!manager || !props.active) return;
    const controller = new AbortController();
    void manager.capabilities(controller.signal).then(setCaps).catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [manager, props.active]);
  useEffect(() => {
    if (!manager || !props.active || !reference?.runId) return;
    try { return manager.observe(reference.runId, setState); }
    catch (failure) { setError(String(failure)); }
  }, [manager, props.active, reference?.runId, attempt]);
  const view = state.result;
  const fills = useMemo(() => manager && view ? manager.rows(view.identity.id, "fills", view.identity, 100) : [], [manager, view]);
  const equity = useMemo(() => manager && view ? manager.rows(view.identity.id, "equity_curve", view.identity, 200) : [], [manager, view]);
  const values = equity.map((row) => Number(object(row).equity)).filter(Number.isFinite);
  const low = Math.min(...values), high = Math.max(...values);
  const points = values.map((value, index) => `${index * 600 / Math.max(1, values.length - 1)},${80 - (value - low) * 75 / Math.max(1e-12, high - low)}`).join(" ");

  function save(next: ContinuousRunReference) {
    try {
      activateContinuousReference(localStorage, scope, next); setReference(next); setSavedRuns(listContinuousReferences(localStorage, scope));
    }
    catch { setStorageFailed(true); throw new Error(t("continuous.storage")); }
  }
  async function initialize() {
    if (submitting.current || busy || storageFailed || !manager || !caps?.execution_enabled || !caps.python_editor_authorized || !props.trusted || !qualified) return;
    submitting.current = true;
    setBusy(true); setError(null);
    try {
      const start = Date.parse(from + ":00Z");
      if (![balance, percent, fee, slippage].every((value) => value.trim() && Number.isFinite(Number(value)))
        || Number(balance) <= 0 || Number(percent) <= 0 || Number(percent) > 100 || Number(fee) < 0 || Number(slippage) < 0
        || (props.mode === "HISTORY_LIVE" && (!Number.isSafeInteger(start) || start < 0 || start >= Date.now()))) throw new Error(t("continuous.invalid"));
      const next: ContinuousRunReference = reference && !reference.runId ? reference : { schema: 1, requestKey: "chart/" + crypto.randomUUID(), runId: null, inputRevision, createdAtMs: Date.now(),
        settings: { from, balance, percent, fee, slippage, output } };
      if (next.inputRevision !== inputRevision) throw new Error(t("continuous.pending"));
      // Persist the idempotency key before submitting; uncertain requests can be recovered after restart.
      save(next);
      const result = await manager.create(next.requestKey, { mode: props.mode,
        series: { exchange: props.session.exchange, market_type: props.session.marketType, symbol: props.session.symbol, interval: props.session.interval,
          identity: { provider_id: identity.providerId, venue: identity.venue, asset_class: identity.assetClass,
            series_variant: identity.seriesVariant, price_adjustment: identity.priceAdjustment, session_variant: identity.sessionVariant, volume_semantics: identity.volumeSemantics } },
        provider: { language: "python", source_text: props.source, parameters: props.parameters, output_mode: output, runtime_mode: "TRUSTED_LOCAL", trusted_confirmed: true },
        execution: { account_model: props.session.marketType === "spot" ? "SPOT_CASH_V1" : "LINEAR_PERP_ONE_WAY_V1",
          initial_balance: balance, sizing_policy: "EQUITY_PERCENT_V1", equity_percent: percent, taker_fee_bps: fee, maker_fee_bps: fee, slippage_bps: slippage },
        ...(props.mode === "HISTORY_LIVE" ? { from_ms: start } : {}),
      });
      setCreation(result.creation); setState(empty); save({ ...next, runId: result.creation.run_id });
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { submitting.current = false; setBusy(false); }
  }
  async function recover() {
    if (!manager || !reference) return;
    setBusy(true); setError(null);
    try {
      const result = await manager.request(reference.requestKey);
      setCreation(result.creation); save({ ...reference, runId: result.creation.run_id }); setAttempt((value) => value + 1);
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
  const phase = view?.run.phase ?? observed?.phase;
  const failure = object(view?.run.error ?? observed?.error);
  const valuation = object(view?.summary.valuation), account = object(view?.summary.account);
  return <div className="continuous-strategy" data-continuous-strategy>
    <p>{t("continuous.hint")}</p><p>{t("continuous.support")}</p>
    {savedRuns.length > 0 && <label>{t("continuous.savedRuns")}<select disabled={busy || storageFailed} value={reference?.requestKey ?? ""} onChange={(event) => {
      const selected = savedRuns.find((value) => value.requestKey === event.target.value);
      if (!selected) return;
      try {
        save(selected); setCreation(null); setState(empty); setError(null);
        setFrom(selected.settings.from); setBalance(selected.settings.balance); setPercent(selected.settings.percent);
        setFee(selected.settings.fee); setSlippage(selected.settings.slippage); setOutput(selected.settings.output);
      } catch (failure) { setError(String(failure)); }
    }}><option value="" disabled>{t("continuous.savedRuns")}</option>{savedRuns.map((saved) => <option key={saved.requestKey} value={saved.requestKey}>
      {time(saved.createdAtMs)} · {saved.runId?.slice(-8) ?? t("continuous.pendingRun")}
    </option>)}</select></label>}
    <div className="continuous-settings">
      {props.mode === "HISTORY_LIVE" && <label>{t("continuous.from")}<input type="datetime-local" value={from} onChange={(event) => setFrom(event.target.value)} /></label>}
      {([["continuous.balance", balance, setBalance], ["continuous.percent", percent, setPercent], ["continuous.fee", fee, setFee], ["continuous.slippage", slippage, setSlippage]] as const).map(([label, value, change]) =>
        <label key={label}>{t(label)}<input type="number" min="0" step="any" value={value} onChange={(event) => change(event.target.value)} /></label>)}
      <label>{t("continuous.output")}<select value={output} onChange={(event) => setOutput(event.target.value as typeof output)}>
        <option value="SIGNAL">{t("continuous.signal")}</option><option value="TARGET_POSITION">{t("continuous.target")}</option><option value="ORDER_INTENT">{t("continuous.order")}</option>
      </select></label>
    </div>
    {props.editor(() => { void initialize(); })}
    {!qualified && <p role="status">{t("continuous.unsupported")}</p>}
    {reference && reference.inputRevision !== inputRevision && <p role="status">{t("continuous.edited")}</p>}
    {reference && !reference.runId && <p role="status">{t("continuous.pending")}</p>}
    <div className="continuous-actions">
      <button type="button" disabled={busy || storageFailed || !qualified || !props.trusted || !caps?.execution_enabled || !caps.python_editor_authorized || (!!reference && !reference.runId && reference.inputRevision !== inputRevision)} onClick={() => { void initialize(); }}>{t(reference && !reference.runId ? "continuous.resubmit" : "continuous.start")}</button>
      {reference && <button type="button" disabled={busy} onClick={() => { void recover(); }}>{t(reference.runId ? "continuous.observe" : "continuous.recover")}</button>}
      {observed && (["pause", "resume", "retry", "cancel"] as const).map((action) => <button type="button" key={action} disabled={busy || !caps?.execution_enabled}
        onClick={() => { void control(action); }}>{t(`continuous.${action}`)}</button>)}
    </div>
    {error && <p role="alert">{error}</p>}
    {state.error && <p role="alert">{state.error.message}</p>}
    {typeof failure.message === "string" && <p role="alert">{failure.message}</p>}
    {reference?.runId && <p role="status">{t(connectionMessages[state.connection])} · {t("continuous.phase", { phase: phase ?? "…" })}</p>}
    {reference?.runId && !state.initialReady && <p role="status">{t("continuous.initializing")}</p>}
    {(view?.stale || phase === "REPAIR_REQUIRED") && <p role="alert">{t("continuous.stale")}</p>}
    {view ? <section aria-label={t("continuous.account")}>
      <dl className="continuous-account"><div><dt>{t("continuous.equity")}</dt><dd>{text(valuation.equity)}</dd></div>
        <div><dt>{t("continuous.position")}</dt><dd>{text(account.position_qty)}</dd></div>
        <div><dt>{t("continuous.sequence")}</dt><dd>{view.identity.sequence}</dd></div></dl>
      {values.length > 1 && <svg viewBox="0 0 600 90" role="img" aria-label={t("continuous.recentEquity")}><polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" /></svg>}
      <h3>{t("continuous.fills")}</h3><table><thead><tr>{(["continuous.time", "continuous.side", "continuous.quantity", "continuous.price"] as const).map((key) => <th key={key}>{t(key)}</th>)}</tr></thead>
        <tbody>{fills.map((value, index) => { const row = object(value); return <tr key={index}><td>{time(row.event_time_ms)}</td><td>{text(row.side)}</td><td>{text(row.qty)}</td><td>{text(row.price)}</td></tr>; })}</tbody></table>
    </section> : <p>{t("continuous.empty")}</p>}
  </div>;
}
