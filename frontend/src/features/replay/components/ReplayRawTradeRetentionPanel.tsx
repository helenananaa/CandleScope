import { useEffect, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { RawTradePlan, RawTradeRetentionReply } from "../rawTradeRetention.js";
import { defaultReplayV2Api } from "../replayV2Api.js";

const MIB = 1024 * 1024;

function statusText(status: string, bytes: string) {
  switch (status) {
    case "POLICY_SAVED": return t("replay.rawRetention.saved");
    case "POLICY_RETAINS_DAY": return t("replay.rawRetention.held");
    case "POLICY_CONFLICT": return t("replay.rawRetention.conflict");
    case "STALE_RECEIPT": return t("replay.rawRetention.missing");
    case "UNMANAGED": return t("replay.rawRetention.unmanaged");
    case "STALE_PLAN": return t("replay.rawRetention.stale");
    case "RETENTION_NOT_AUTHORIZED": return t("replay.rawRetention.recheck");
    case "DAY_ACQUISITION_IN_PROGRESS":
    case "PARTITION_RETENTION_LEASE":
    case "ACTIVE_DATASET_PIN":
    case "SAVED_REFERENCES_PROTECTED": return t("replay.rawRetention.protected");
    case "RETIRED": return t("replay.rawRetention.retired");
    case "RECLAIM_PENDING": return t("replay.rawRetention.batch", { bytes });
    case "RECLAIMED": return t("replay.rawRetention.reclaimed", { bytes });
    case "RESTORED": return t("replay.rawRetention.restored");
    default: return t("replay.rawRetention.failed", { status });
  }
}

export default function ReplayRawTradeRetentionPanel({ disabled, formatBytes }: {
  readonly disabled: boolean;
  readonly formatBytes: (value: number) => string;
}) {
  useLocale();
  const [symbol, setSymbol] = useState("");
  const [day, setDay] = useState("");
  const [entry, setEntry] = useState<RawTradeRetentionReply | null>(null);
  const [permanent, setPermanent] = useState(true);
  const [cutoff, setCutoff] = useState("");
  const [batchMiB, setBatchMiB] = useState(64);
  const [files, setFiles] = useState(1);
  const [downloadMiB, setDownloadMiB] = useState(64);
  const [restoreMiB, setRestoreMiB] = useState(128);
  const [plan, setPlan] = useState<RawTradePlan | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [notice, setNotice] = useState<RawTradeRetentionReply | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    if (plan === null) return;
    const timer = setTimeout(() => {
      setPlan(null);
      setConfirmed(false);
    }, Math.max(0, plan.expires_ms - Date.now()));
    return () => clearTimeout(timer);
  }, [plan]);

  const normalized = symbol.trim().toUpperCase();
  const validDay = /^[A-Z0-9]{1,64}$/.test(normalized) && /^\d{4}-\d{2}-\d{2}$/.test(day);
  const item = entry?.item;
  const key = item ? { symbol: normalized, day, day_id: item.day_id } : null;
  const blocked = busy || disabled;
  const cutoffMs = Date.parse(`${cutoff}Z`);
  const hasSavedProtection = !entry?.saved_reference_scan_complete || (entry.saved_reference_count ?? 0) > 0;
  const policyAllowsPlan = entry?.policy?.retain_until_ms != null && entry.policy.retain_until_ms <= Date.now();
  const validBatch = Number.isSafeInteger(batchMiB) && batchMiB >= 1 && batchMiB <= 953_674
    && Number.isSafeInteger(files) && files >= 1 && files <= 8192;
  const validRecovery = Number.isSafeInteger(downloadMiB) && downloadMiB >= 1 && downloadMiB <= 2048
    && Number.isSafeInteger(restoreMiB) && restoreMiB >= 1 && restoreMiB <= 953_674;

  function clearPlan() {
    setPlan(null);
    setConfirmed(false);
  }

  function clearSelection() {
    setEntry(null);
    setNotice(null);
    clearPlan();
  }

  async function refresh(signal: AbortSignal) {
    const next = await defaultReplayV2Api.inspectRawTradeDay(normalized, day, signal);
    if (signal.aborted) return;
    setEntry(next.item ? next : null);
    if (!next.item) {
      clearPlan();
      setNotice(next);
      return;
    }
    if (plan && (next.item.day_id !== plan.day_id || next.policy?.revision !== plan.revision)) clearPlan();
    const retainUntil = next.policy?.retain_until_ms ?? null;
    setPermanent(retainUntil === null);
    setCutoff(retainUntil === null ? "" : new Date(retainUntil).toISOString().slice(0, 16));
  }

  async function perform(action: (signal: AbortSignal) => Promise<void>) {
    if (pending.current !== null || disabled) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setNotice(null);
    try {
      await action(controller.signal);
    } catch {
      if (!controller.signal.aborted) {
        clearPlan();
        setEntry(null);
        setNotice({ status: "REQUEST_FAILED" });
      }
    } finally {
      if (pending.current === controller) {
        pending.current = null;
        if (!controller.signal.aborted) setBusy(false);
      }
    }
  }

  const lookup = () => void perform(async (signal) => {
    clearSelection();
    await refresh(signal);
  });
  const save = () => void perform(async (signal) => {
    if (!key || (!permanent && !Number.isFinite(cutoffMs))) return;
    clearPlan();
    const result = await defaultReplayV2Api.saveRawTradePolicy({
      ...key, expected_revision: entry?.policy?.revision ?? 0, retain_until_ms: permanent ? null : cutoffMs,
    }, signal);
    if (signal.aborted) return;
    setNotice(result);
    await refresh(signal);
  });
  const makePlan = () => void perform(async (signal) => {
    if (!key || !validBatch || hasSavedProtection || !policyAllowsPlan) return;
    clearPlan();
    const result = await defaultReplayV2Api.planRawTradeRetention({
      ...key, max_files: files, max_bytes: batchMiB * MIB,
    }, signal);
    if (signal.aborted) return;
    if (result.plan?.day_id === key.day_id && result.plan.revision === entry?.policy?.revision) {
      setPlan(result.plan);
    } else {
      setNotice(result);
      await refresh(signal);
    }
  });
  const execute = () => void perform(async (signal) => {
    if (!key || !item || !plan || !confirmed || hasSavedProtection) return;
    if (plan.expires_ms <= Date.now()) {
      clearPlan();
      setNotice({ status: "STALE_PLAN" });
      return;
    }
    setConfirmed(false);
    const result = await defaultReplayV2Api.executeRawTradeRetention({
      ...key, plan_id: plan.plan_id, action: item.state === "COMMITTED" ? "RETIRE" : "RECLAIM",
    }, signal);
    if (signal.aborted) return;
    if (result.status !== "RETIRED" && result.status !== "RECLAIM_PENDING") clearPlan();
    setNotice(result);
    await refresh(signal);
  });
  const recover = () => void perform(async (signal) => {
    if (!key || !item || item.state !== "RETIRED" || (item.reclaim_started && !validRecovery)) return;
    clearPlan();
    const result = await defaultReplayV2Api.recoverRawTradeDay(item.reclaim_started ? {
      ...key, action: "REDOWNLOAD", max_download_bytes: downloadMiB * MIB, max_restore_bytes: restoreMiB * MIB,
    } : { ...key, action: "RESTORE" }, signal);
    if (signal.aborted) return;
    setNotice(result);
    await refresh(signal);
  });

  return (
    <section className="replay-storage-gc" aria-label={t("replay.rawRetention.title")}>
      <header>
        <h3>{t("replay.rawRetention.title")}</h3>
        <p>{t("replay.rawRetention.hint")}</p>
      </header>
      <div className="replay-storage-gc-form">
        <label>{t("replay.rawRetention.symbol")}
          <input value={symbol} maxLength={64} disabled={blocked}
            onChange={(event) => { setSymbol(event.target.value); clearSelection(); }} />
        </label>
        <label>{t("trade.history.date")}
          <input type="date" value={day} disabled={blocked}
            onChange={(event) => { setDay(event.target.value); clearSelection(); }} />
        </label>
        <button type="button" disabled={blocked || !validDay} onClick={lookup}>{t("replay.rawRetention.lookup")}</button>
      </div>
      {item && (
        <>
          <p data-raw-retention-state={item.state}>
            {t(item.state === "COMMITTED" ? "replay.rawRetention.committed" : "replay.rawRetention.detached",
              { files: item.files, bytes: formatBytes(item.logical_bytes) })}
            {" · "}
            {entry?.saved_reference_scan_complete
              ? t("replay.rawRetention.references", { count: entry.saved_reference_count ?? 0 })
              : t("replay.rawRetention.incomplete")}
          </p>
          <p>{entry?.policy ? t("replay.rawRetention.revision", { revision: entry.policy.revision })
            : t("replay.rawRetention.unmanaged")}</p>
          <div className="replay-storage-gc-form">
            <label>{t("replay.rawRetention.policy")}
              <select disabled={blocked} value={permanent ? "permanent" : "until"}
                onChange={(event) => { setPermanent(event.target.value === "permanent"); clearPlan(); }}>
                <option value="permanent">{t("replay.rawRetention.permanent")}</option>
                <option value="until">{t("replay.rawRetention.until")}</option>
              </select>
            </label>
            {!permanent && (
              <label>{t("replay.rawRetention.untilUtc")}
                <input type="datetime-local" value={cutoff} disabled={blocked}
                  onChange={(event) => { setCutoff(event.target.value); clearPlan(); }} />
              </label>
            )}
            <button type="button" disabled={blocked || (!permanent && !Number.isFinite(cutoffMs))} onClick={save}>
              {t("replay.rawRetention.save")}
            </button>
          </div>
          {item.files > 0 && (
            <div className="replay-storage-gc-form">
              <label>{t("replay.rawRetention.batchMib")}
                <input type="number" min={1} max={953_674} value={batchMiB} disabled={blocked}
                  onChange={(event) => { setBatchMiB(Number(event.target.value)); clearPlan(); }} />
              </label>
              <label>{t("replay.rawRetention.batchFiles")}
                <input type="number" min={1} max={8192} value={files} disabled={blocked}
                  onChange={(event) => { setFiles(Number(event.target.value)); clearPlan(); }} />
              </label>
              <button type="button" disabled={blocked || !validBatch || hasSavedProtection || !policyAllowsPlan}
                onClick={makePlan}>{t("replay.storage.plan")}</button>
            </div>
          )}
          {plan && (
            <div className="replay-storage-plan" data-raw-retention-plan={plan.plan_id}>
              <p>{t("replay.rawRetention.plan", {
                files: plan.max_files, bytes: formatBytes(plan.max_bytes),
                time: new Date(plan.expires_ms).toISOString().slice(11, 19),
              })}</p>
              <label className="replay-storage-confirm">
                <input type="checkbox" checked={confirmed} disabled={blocked}
                  onChange={(event) => setConfirmed(event.target.checked)} />
                {t(item.state === "COMMITTED" ? "replay.rawRetention.confirmRetire" : "replay.rawRetention.confirmReclaim")}
              </label>
              <button type="button" disabled={blocked || !confirmed || hasSavedProtection} onClick={execute}>
                {t(item.state === "COMMITTED" ? "replay.rawRetention.retire" : "replay.rawRetention.reclaim")}
              </button>
            </div>
          )}
          {item.state === "RETIRED" && (
            <div className="replay-storage-gc-form">
              {item.reclaim_started && (
                <>
                  <label>{t("replay.rawRetention.downloadMib")}
                    <input type="number" min={1} max={2048} value={downloadMiB} disabled={blocked}
                      onChange={(event) => setDownloadMiB(Number(event.target.value))} />
                  </label>
                  <label>{t("replay.rawRetention.restoreMib")}
                    <input type="number" min={1} max={953_674} value={restoreMiB} disabled={blocked}
                      onChange={(event) => setRestoreMiB(Number(event.target.value))} />
                  </label>
                </>
              )}
              <button type="button" disabled={blocked || (item.reclaim_started && !validRecovery)} onClick={recover}>
                {t(item.reclaim_started ? "replay.rawRetention.redownload" : "replay.rawRetention.restore")}
              </button>
            </div>
          )}
        </>
      )}
      {busy && <p role="status">{t("replay.storage.loading")}</p>}
      {notice && (
        <p role="status" data-raw-retention-status={notice.status}>
          {statusText(notice.status, formatBytes(notice.removed_logical_bytes ?? 0))}
        </p>
      )}
    </section>
  );
}
