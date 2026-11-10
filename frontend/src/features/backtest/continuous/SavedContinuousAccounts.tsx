import React, { useEffect, useState } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { StrategyDataManager } from "../../market-data/manager/strategyDataManager.js";
import type { ContinuousObservation, ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import type { ContinuousRun } from "./continuousTypes.js";
import { sameCommit } from "./continuousView.js";
import { repairProgress } from "./continuousRepairView.js";
import ContinuousAccountView from "./ContinuousAccountView.js";

const SELECTION = "candlescope.continuous-reader.v1";
const phases = { REQUESTED: "repair.preparing", PREPARING: "repair.preparing", READY: "repair.ready",
  COMMITTED: "repair.committed", FAILED: "repair.failed", CANCELLED: "repair.cancelled" } as const;
const connections = { loading: "continuous.loading", connected: "continuous.connected", reconnecting: "continuous.reconnecting",
  closed: "continuous.closed", error: "continuous.error" } as const;
function remembered(): string {
  try { const value = localStorage.getItem(SELECTION); return value && value.length <= 128 ? value : ""; }
  catch { return ""; }
}
function utc(value: number): string {
  return Number.isFinite(value) && Math.abs(value) <= 8640000000000000 ? new Date(value).toISOString().replace("T", " ").replace("Z", " UTC") : "—";
}

/** This independent view has no execution, source, editor or chart commands. */
export function SavedContinuousAccounts({ manager }: { manager: ContinuousStrategyDataManager }) {
  useLocale();
  const [runs, setRuns] = useState<ContinuousRun[]>([]), [selected, setSelected] = useState(remembered);
  const [observation, setObservation] = useState<ContinuousObservation | null>(null);
  const [error, setError] = useState<string | null>(null), [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const selectedExists = runs.some((run) => run.id === selected);
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError(null);
    void manager.catalog(abort.signal).then((catalog) => {
      if (abort.signal.aborted) return;
      setRuns(catalog.runs);
      setSelected((current) => catalog.runs.some((run) => run.id === current) ? current : catalog.runs[0]?.id ?? "");
    }).catch((failure: unknown) => {
      if (!abort.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure));
    }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [manager, refresh]);
  useEffect(() => {
    setObservation(null);
    if (!selected || !selectedExists) return;
    try { return manager.observe(selected, setObservation); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
  }, [manager, selected, selectedExists]);
  const view = observation?.result?.identity.id === selected ? observation.result : null;
  const repair = observation?.repair?.run_id === selected ? observation.repair : null;
  const progress = repair ? repairProgress(repair) : null;
  const repairStatus = repair?.phase === "COMMITTED" && view?.stale
    ? sameCommit(repair.base_identity, view.identity) ? "repair.updatingView" : "repair.revisedAgain"
    : repair ? phases[repair.phase] : "repair.preparing";
  return <section className="continuous-reader" data-continuous-reader>
    <p>{t("reader.readonly")}</p>
    <button type="button" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>{t("reader.refresh")}</button>
    {loading && <p role="status">{t("reader.loading")}</p>}
    {!loading && !runs.length && !error && <p role="status">{t("reader.empty")}</p>}
    {runs.length > 0 && <label>{t("reader.select")}<select aria-label={t("reader.select")} value={selected} onChange={(event) => {
      setSelected(event.target.value);
      try { localStorage.setItem(SELECTION, event.target.value); }
      catch { setError(t("continuous.storage")); }
    }}>{runs.map((run) => <option key={run.id} value={run.id}>{run.id} · {run.phase}</option>)}</select></label>}
    {error && <p role="alert">{error}</p>}
    {observation?.error && <p role="alert">{observation.error.message}</p>}
    {observation && <p role="status">{t(connections[observation.connection])}</p>}
    {view && <>
      <p>{t("reader.identity", { id: view.identity.id })} · {t("continuous.phase", { phase: view.run.phase })}</p>
      {!observation?.initialReady && <p role="status">{t("reader.partial")}</p>}
      {view.stale && <p role="alert">{t("continuous.stale")}</p>}
      {repair && <section className="continuous-repair" aria-label={t("repair.title")} data-continuous-repair-phase={repair.phase}>
        <h3>{t("repair.title")}</h3><p role="status">{t(repairStatus)}</p>
        <dl><div><dt>{t("repair.from")}</dt><dd>{utc(repair.from_ms)}</dd></div>
          <div><dt>{t("repair.through")}</dt><dd>{utc(repair.through_ms)}</dd></div></dl>
        {progress && ["REQUESTED", "PREPARING", "READY"].includes(repair.phase) && <p>{t("repair.progress", progress)}</p>}
        {repair.error && <p role="alert">{repair.error.message}</p>}
      </section>}
      <ContinuousAccountView manager={manager} view={view} />
    </>}
  </section>;
}

export default function SavedContinuousAccountsHost() {
  const [manager, setManager] = useState<ContinuousStrategyDataManager | null>(null);
  useEffect(() => {
    // Effect ownership also handles React StrictMode's setup/cleanup/setup.
    const owner = new StrategyDataManager(); setManager(owner.continuous);
    return () => owner.dispose();
  }, []);
  return manager ? <SavedContinuousAccounts manager={manager} /> : <p>{t("reader.loading")}</p>;
}
