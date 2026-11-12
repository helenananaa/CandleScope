import React, { useCallback, useEffect, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import { StrategyRunStreamError } from "../backtestRunStream.js";
import { sameCommit, type ContinuousView } from "./continuousView.js";
import { repairProgress } from "./continuousRepairView.js";
import { acknowledgeContinuousRepairIntent, readContinuousRepairIntent, saveContinuousRepairIntent,
  type ContinuousRepairIntent } from "./continuousRepairReference.js";
import type { ContinuousRepair, ContinuousRepairPlan } from "./continuousTypes.js";

const phaseMessages = { REQUESTED: "repair.preparing", PREPARING: "repair.preparing", READY: "repair.ready",
  COMMITTED: "repair.committed", FAILED: "repair.failed", CANCELLED: "repair.cancelled" } as const;
const reasonMessages = { INITIAL_SNAPSHOT_REVISED: "repair.initialChanged", NO_RETAINED_CHECKPOINT_BEFORE_REVISION: "repair.noAnchor",
  SOURCE_CONTINUITY_UNAVAILABLE: "repair.noSource", SOURCE_REVISION_NOT_LOCATABLE: "repair.unknownRange" } as const;
const pending = (repair: ContinuousRepair | null) => !!repair && ["REQUESTED", "PREPARING", "READY"].includes(repair.phase);
function utc(value: number) { return Number.isFinite(value) && Math.abs(value) <= 8640000000000000
  ? new Date(value).toISOString().replace("T", " ").replace("Z", " UTC") : "—"; }

export interface ContinuousRepairPanelProps {
  manager: ContinuousStrategyDataManager; view: ContinuousView;
  repair: ContinuousRepair | null; active: boolean; available: boolean;
}

/** This view owns only requests and consent, never execution or financial state. */
export default function ContinuousRepairPanel({ manager, view, repair, active, available }: ContinuousRepairPanelProps) {
  useLocale();
  const runId = view.identity.id;
  const point = useRef(view.identity); point.current = view.identity;
  const operation = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [intent, setIntent] = useState<ContinuousRepairIntent | null>(null);
  const [storageFailed, setStorageFailed] = useState(false);
  const [preview, setPreview] = useState<{ plan: ContinuousRepairPlan; requestKey: string; expiresAt: number } | null>(null);
  const [expired, setExpired] = useState(false), [consent, setConsent] = useState(false), [resumeAfter, setResumeAfter] = useState(false);
  const repairing = pending(repair), stale = view.stale || view.run.phase === "REPAIR_REQUIRED";
  const enabled = available && active;

  useEffect(() => {
    try { setIntent(readContinuousRepairIntent(localStorage, runId)); setStorageFailed(false); }
    catch { setStorageFailed(true); setError(t("continuous.storage")); }
    return () => { operation.current?.abort(); operation.current = null; };
  }, [runId]);
  useEffect(() => {
    if (!active) operation.current?.abort();
  }, [active]);
  useEffect(() => {
    if (!preview) return;
    setExpired(false);
    const timer = setTimeout(() => { setExpired(true); setConsent(false); }, Math.max(0, preview.expiresAt - Date.now()));
    return () => clearTimeout(timer);
  }, [preview]);
  useEffect(() => {
    if (preview && !sameCommit(preview.plan.expected, view.identity)) { setPreview(null); setConsent(false); }
  }, [preview, view.identity]);
  const acknowledge = useCallback((key: string) => {
    try { acknowledgeContinuousRepairIntent(localStorage, runId, key); setIntent(null); setStorageFailed(false); }
    catch { setStorageFailed(true); setError(t("continuous.storage")); }
  }, [runId]);
  useEffect(() => {
    if (repair?.request_key && repair.request_key === intent?.requestKey) {
      acknowledge(repair.request_key); setPreview(null); setConsent(false);
    }
  }, [repair?.request_key, intent?.requestKey, acknowledge]);
  useEffect(() => {
    if (repairing) { setPreview(null); setConsent(false); }
  }, [repairing]);

  async function perform(action: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller;
    setBusy(true); setError(null);
    try { await action(controller.signal); }
    catch (failure) {
      if (!controller.signal.aborted) {
        if (failure instanceof StrategyRunStreamError && ["CONTINUOUS_COMMIT_CONFLICT", "CONTINUOUS_NOT_READY"].includes(failure.code)) {
          setPreview(null); setConsent(false); setError(t("repair.refresh"));
        } else setError(failure instanceof Error ? failure.message : String(failure));
      }
    } finally {
      if (operation.current === controller) { operation.current = null; setBusy(false); }
    }
  }
  function inspectRange() {
    if (!enabled || !stale || repairing || storageFailed) return;
    void perform(async (signal) => {
      const { plan } = await manager.repairPreview(runId, { expected: point.current, resume_after: resumeAfter }, signal);
      if (!sameCommit(plan.expected, point.current) || !Number.isSafeInteger(plan.recompute_bars) || plan.recompute_bars < 0
        || !Number.isSafeInteger(plan.expires_in_seconds) || plan.expires_in_seconds < 1 || plan.expires_in_seconds > 300)
        throw new Error(t("repair.refresh"));
      let saved: ContinuousRepairIntent | null;
      try { saved = readContinuousRepairIntent(localStorage, runId); }
      catch { setStorageFailed(true); throw new Error(t("continuous.storage")); }
      setPreview({ plan, requestKey: saved?.requestKey ?? "repair/"+crypto.randomUUID(), expiresAt: Date.now()+plan.expires_in_seconds*1000 });
      setConsent(false);
    });
  }
  function submitPlan() {
    if (!enabled || !preview || expired || !consent || repairing || storageFailed || !sameCommit(preview.plan.expected, point.current)) return;
    void perform(async (signal) => {
      const next: ContinuousRepairIntent = { schema: 1, runId, requestKey: preview.requestKey, createdAtMs: Date.now(),
        body: { expected: preview.plan.expected, plan_id: preview.plan.plan_id, resume_after: preview.plan.resume_after, confirmed: true } };
      try { saveContinuousRepairIntent(localStorage, next); setIntent(next); }
      catch { setStorageFailed(true); throw new Error(t("repair.storage")); }
      await manager.repair(runId, next.requestKey, next.body, signal);
      acknowledge(next.requestKey); setPreview(null); setConsent(false);
    });
  }
  function recoverRequest(resend: boolean) {
    if (!intent || !active || (resend && !enabled)) return;
    void perform(async (signal) => {
      const response = resend ? await manager.repair(runId, intent.requestKey, intent.body, signal) : await manager.repairStatus(intent.requestKey, signal);
      if (response.repair.run_id !== runId) throw new Error(t("repair.refresh"));
      acknowledge(intent.requestKey); setPreview(null); setConsent(false);
    });
  }
  function cancel() {
    if (!enabled || !repair || !repairing) return;
    void perform(async (signal) => { await manager.cancelRepair(repair.request_key, repair.base_identity, signal); });
  }

  if (!stale && !repair && !intent) return null;
  const progress = repair ? repairProgress(repair) : null;
  const reason = preview?.plan.expanded_range_reason;
  const automaticReason = repair?.expanded_range_reason;
  const statusMessage = repair?.phase === "COMMITTED" && stale
    ? sameCommit(repair.base_identity, view.identity) ? "repair.updatingView" : "repair.revisedAgain"
    : repair ? phaseMessages[repair.phase] : "repair.preparing";
  return <section className="continuous-repair" aria-label={t("repair.title")} data-continuous-repair>
    <h3>{t("repair.title")}</h3><p>{t("repair.hint")}</p>
    {!enabled && <p role="status">{t("repair.unavailable")}</p>}
    {repair && <div aria-live="polite">
      <p role="status">{t(statusMessage)}{repair.automatic ? ` · ${t("repair.autoRequest")}` : ""}</p>
      {repair.automatic && <>
        <p>{t("repair.from")} {utc(repair.from_ms)} · {t("repair.through")} {utc(repair.through_ms)}</p>
        {automaticReason && <p>{t(reasonMessages[automaticReason as keyof typeof reasonMessages] ?? "repair.unknownRange")}</p>}
      </>}
      {repairing && progress && progress.total > 0 && <><progress max={progress.total} value={progress.done} aria-label={t("repair.preparing")} />
        <p>{t("repair.progress", progress)}</p></>}
      {repairing && repair.progress?.waiting && <p>{t("repair.waiting")}</p>}
      {repair.error && <p role="alert">{repair.error.message}</p>}
      {repair.progress?.cleanup_error && <p>{t("repair.cleanup")}</p>}
      {repairing && <button type="button" disabled={busy || !enabled} onClick={cancel}>{t("repair.cancel")}</button>}
    </div>}
    {intent && <div><p role="status">{t("repair.pendingRequest")}</p>
      <button type="button" disabled={busy || !active} onClick={() => recoverRequest(false)}>{t("repair.recover")}</button>
      <button type="button" disabled={busy || !enabled} onClick={() => recoverRequest(true)}>{t("repair.retryRequest")}</button>
    </div>}
    {stale && !repairing && <>
      <label><input type="checkbox" checked={resumeAfter} disabled={busy || !enabled} onChange={(event) => {
        setResumeAfter(event.target.checked); setPreview(null); setConsent(false);
      }} />{t("repair.resumeAfter")}</label>
      <button type="button" disabled={busy || !enabled || storageFailed} onClick={inspectRange}>{t("repair.preview")}</button>
    </>}
    {preview && !repairing && <div>
      <dl><div><dt>{t("repair.from")}</dt><dd>{utc(preview.plan.from_ms)}</dd></div>
        <div><dt>{t("repair.through")}</dt><dd>{utc(preview.plan.through_ms)}</dd></div></dl>
      <p>{t("repair.reused", { count: preview.plan.anchor_sequence })} · {t("repair.bars", { count: preview.plan.recompute_bars })}</p>
      {preview.plan.full_reinitialization && <p>{t("repair.full")}</p>}
      {reason && <p role="status">{t(reasonMessages[reason as keyof typeof reasonMessages] ?? "repair.unknownRange")}</p>}
      {expired && <p role="status">{t("repair.expired")}</p>}
      <label><input type="checkbox" checked={consent} disabled={busy || !enabled || expired} onChange={(event) => setConsent(event.target.checked)} />{t("repair.consent")}</label>
      <button type="button" disabled={busy || !enabled || expired || !consent || storageFailed} onClick={submitPlan}>{t("repair.confirm")}</button>
    </div>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
