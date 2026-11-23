import React, { useEffect, useState } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { ContinuousObservation, ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import { sameCommit } from "./continuousView.js";
import { repairProgress } from "./continuousRepairView.js";
import ContinuousAccountView from "./ContinuousAccountView.js";
import { readContinuousAccountRows } from "./continuousAccountRows.js";

const phases = { REQUESTED: "repair.preparing", PREPARING: "repair.preparing", READY: "repair.ready",
  COMMITTED: "repair.committed", FAILED: "repair.failed", CANCELLED: "repair.cancelled" } as const;
const connections = { loading: "continuous.loading", connected: "continuous.connected", reconnecting: "continuous.reconnecting",
  closed: "continuous.closed", error: "continuous.error" } as const;
function utc(value: number): string {
  return Number.isFinite(value) && Math.abs(value) <= 8640000000000000 ? new Date(value).toISOString().replace("T", " ").replace("Z", " UTC") : "—";
}

/**
 * One forward run's own ledger, read-only: its committed account, connection, staleness and any
 * repair in progress. It has no execution, source, editor or chart commands; the saved-accounts
 * reader and the accounts page (beside practice accounts, ADR-BACKTEST-015 P6e) both show it.
 */
export default function ContinuousRunAccount({ manager, runId }: { manager: ContinuousStrategyDataManager; runId: string }) {
  useLocale();
  const [observation, setObservation] = useState<(ContinuousObservation & { rows: ReturnType<typeof readContinuousAccountRows> }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setObservation(null); setError(null);
    try { return manager.observe(runId, (next) => setObservation({ ...next, rows: readContinuousAccountRows(manager, next.result) })); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
  }, [manager, runId]);
  const view = observation?.result?.identity.id === runId ? observation.result : null;
  const repair = observation?.repair?.run_id === runId ? observation.repair : null;
  const progress = repair ? repairProgress(repair) : null;
  const repairStatus = repair?.phase === "COMMITTED" && view?.stale
    ? sameCommit(repair.base_identity, view.identity) ? "repair.updatingView" : "repair.revisedAgain"
    : repair ? phases[repair.phase] : "repair.preparing";
  return <>
    {error && <p role="alert">{error}</p>}
    {observation?.error && <p role="alert">{observation.error.message}</p>}
    {observation && <p role="status">{t(connections[observation.connection])}</p>}
    {view && observation && <>
      <p>{t("reader.identity", { id: view.identity.id })} · {t("continuous.phase", { phase: view.run.phase })}</p>
      {!observation.initialReady && <p role="status">{t("reader.partial")}</p>}
      {view.stale && <p role="alert">{t("continuous.stale")}</p>}
      {repair && <section className="continuous-repair" aria-label={t("repair.title")} data-continuous-repair-phase={repair.phase}>
        <h3>{t("repair.title")}</h3><p role="status">{t(repairStatus)}</p>
        <dl><div><dt>{t("repair.from")}</dt><dd>{utc(repair.from_ms)}</dd></div>
          <div><dt>{t("repair.through")}</dt><dd>{utc(repair.through_ms)}</dd></div></dl>
        {progress && ["REQUESTED", "PREPARING", "READY"].includes(repair.phase) && <p>{t("repair.progress", progress)}</p>}
        {repair.error && <p role="alert">{repair.error.message}</p>}
      </section>}
      <ContinuousAccountView rows={observation.rows} view={view} />
    </>}
  </>;
}
