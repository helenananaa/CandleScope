import { lazy, Suspense, useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { preparationRequest, type PreparationJob } from "./api.js";
import type { NativeRun } from "../backtest/native/nativeBacktestApi.js";
import PreparationWaiting from "./PreparationWaiting.js";

const PreparedNativeRun = lazy(() => import("./PreparedNativeRun.js"));

interface CacheInventory {
  bytes: number;
  referenced_bytes: number;
  reserved_bytes: number;
  engine_owned_bytes: number;
  publication_bytes?: number;
  shared_host_bytes?: number;
  storage_inventory_state?: "SCANNING" | "READY" | "INCOMPLETE";
  cache_budget_bytes: number;
  prefetch_enabled: boolean;
}

export default function PreparationJobsPanel() {
  const [jobs, setJobs] = useState<PreparationJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [cache, setCache] = useState<CacheInventory | null>(null);
  const [budgetMiB, setBudgetMiB] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [nativeRun, setNativeRun] = useState<NativeRun | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const result = await preparationRequest<{ items: PreparationJob[] }>("", { signal: controller.signal });
        setJobs(result.items);
        if (!controller.signal.aborted) {
          const inventory = await preparationRequest<CacheInventory>("/cache", { signal: controller.signal });
          setCache(inventory);
        }
      } catch { /* Other backend profiles may not expose preparation. */ }
      if (!controller.signal.aborted) timer = setTimeout(() => void refresh(), 2000);
    };
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  if (!jobs.length && !cache) return null;
  const budgetValue = budgetMiB ?? (cache?.cache_budget_bytes ?? 2048 * 1024**2) / 1024**2;
  const action = async (job: PreparationJob, command: "retry" | "cancel" | "release-cache") => {
    setError(null);
    try {
      const updated = await preparationRequest<PreparationJob>(`/${job.id}/${command}`, { method: "POST" });
      if (command !== "release-cache") setJobs((current) => current.map((item) => item.id === job.id ? updated : item));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  const cacheAction = async (command: "cleanup" | "settings", prefetch = cache?.prefetch_enabled ?? false, saveBudget = false) => {
    if (!cache || busy) return;
    setBusy(true);
    setError(null);
    try {
      await preparationRequest(`/cache/${command}`, command === "cleanup" ? { method: "POST" } : {
        method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({ cache_budget_bytes: saveBudget ? budgetValue * 1024**2 : cache.cache_budget_bytes, prefetch_enabled: prefetch }),
      });
      setCache(await preparationRequest<CacheInventory>("/cache"));
      if (saveBudget) setBudgetMiB(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  return <section className="training-hub-summary-card" aria-label={t("preparation.title")}>
    <h3>{t("preparation.title")}</h3>
    <p>{t("preparation.background")}</p>
    {error && <p role="alert">{error}</p>}
    {jobs.slice(0, 20).map((job) => <div key={job.id} className="training-hub-create-actions">
      <span>{[...new Set(job.request.requirements.map((item) => item.symbol))].join(", ")}</span>
      <span>{job.state === "READY" ? t("preparation.ready") : job.state === "CANCELLED" ? t("preparation.cancelled") : `${job.completed}/${job.total}`}</span>
      {job.error && <span role="status">{job.error.message}</span>}
      <PreparationWaiting job={job} />
      {job.result?.run && <a href={`/replay.html?run=${encodeURIComponent(job.result.run.run_id)}`}>{t("preparation.open")}</a>}
      {job.result?.strategy_run && <a href={`/backtest.html?run=${encodeURIComponent(job.result.strategy_run.run_id)}`}>{t("ux.openResult")}</a>}
      {job.result?.native_run && <button type="button" onClick={() => setNativeRun(job.result!.native_run!)}>{t("ux.openResult")}</button>}
      {["FAILED", "BLOCKED_STORAGE"].includes(job.state) && <button type="button" onClick={() => void action(job, "retry")}>{t("preparation.retry")}</button>}
      {["QUEUED", "RUNNING", "BLOCKED_STORAGE"].includes(job.state) && <button type="button" disabled={job.cancel_requested || job.stage === "STARTING"} onClick={() => void action(job, "cancel")}>{t("preparation.cancel")}</button>}
      {["READY", "FAILED", "CANCELLED"].includes(job.state) && <button type="button" onClick={() => void action(job, "release-cache")}>{t("preparation.releaseCache")}</button>}
    </div>)}
    {nativeRun && <Suspense fallback={<p role="status">{t("native.loading")}</p>}>
      <PreparedNativeRun key={nativeRun.run_id} initial={nativeRun} onClose={() => setNativeRun(null)} />
    </Suspense>}
    {cache && <details onToggle={(event) => { if (event.currentTarget.open) setBudgetMiB(cache.cache_budget_bytes / 1024**2); }}>
      <summary>{t("preparation.cache")}</summary>
      <p>{t("preparation.cacheUsage", { used: (cache.bytes / 1024**2).toFixed(1), budget: (cache.cache_budget_bytes / 1024**2).toFixed(0) })}</p>
      <p>{t("preparation.publicationUsage", { used: ((cache.publication_bytes ?? 0) / 1024**2).toFixed(1) })}</p>
      <p>{t("preparation.sharedHostUsage", { used: ((cache.shared_host_bytes ?? 0) / 1024**2).toFixed(1) })}</p>
      {cache.storage_inventory_state === "SCANNING" && <p role="status">{t("preparation.inventoryScanning")}</p>}
      {cache.storage_inventory_state === "INCOMPLETE" && <p role="status">{t("preparation.inventoryIncomplete")}</p>}
      <p>{t("preparation.cacheHint")}</p>
      <label>{t("preparation.cacheBudget")} <input type="number" min={16} max={1048576} step={1}
        value={budgetValue} onChange={(event) => setBudgetMiB(Number(event.target.value))} /></label>
      <button type="button" disabled={busy || !Number.isInteger(budgetValue) || budgetValue < 16} onClick={() => void cacheAction("settings", cache.prefetch_enabled, true)}>{t("preparation.saveSettings")}</button>
      <label><input type="checkbox" checked={cache.prefetch_enabled} disabled={busy}
        onChange={(event) => void cacheAction("settings", event.target.checked)} />{t("preparation.prefetch")}</label>
      <button type="button" disabled={busy} onClick={() => void cacheAction("cleanup")}>{t("preparation.cleanCache")}</button>
    </details>}
  </section>;
}
