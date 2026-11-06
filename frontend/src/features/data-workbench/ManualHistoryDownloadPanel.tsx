import { useExchangeCatalog } from "../chart-session/exchangeCatalogRuntime.js";
import { manualHistoryExchanges, manualHistoryMarkets } from "./manualHistoryMarkets.js";
import { describeError } from "../../i18n/serverErrors.js";
import { useEffect, useId, useMemo, useState } from "react";
import { useControlCommands } from "../app-control/useControlCommands.js";
import { command } from "../app-control/commandRegistry.js";
import { array, choice, empty, nullable, number, object, text } from "../app-control/commandSchema.js";
import { useLocale } from "../../i18n/useLocale.js";
import {
  canStartDownload,
  createEmptyManualHistoryForm,
  formHasEndTime,
  isGreenCompleteState,
  isPlanFirstReady,
  MANUAL_HISTORY_INTERVAL_CHOICES,
  normalizeCustomInterval,
  parentStateTone,
  parseSymbolList,
  toggleInterval,
  type ManualHistoryFormState,
} from "./manualHistoryForm.js";
import { manualHistoryText } from "./manualHistoryCopy.js";
import {
  cancelManualHistoryJob,
  archiveManualHistoryJob,
  createManualHistoryDownload,
  fetchManualHistoryCapabilities,
  getManualHistoryJob,
  listManualHistoryCollections,
  listManualHistoryJobs,
  planManualHistoryDownload,
  releaseManualHistoryCollection,
} from "../../services/manualHistoryApi.js";

interface ManualHistoryDownloadPanelProps {
  enabled?: boolean;
  symbols?: string[];
  intervals?: string[];
  exchange?: string;
  marketType?: string;
}

const ACTIVE_JOB_STATES = new Set([
  "QUEUED",
  "RUNNING",
  "SEALING",
  "BLOCKED_STORAGE",
  "CANCELLING",
]);

export function ManualHistoryDownloadPanel({
  enabled,
  symbols = [],
  intervals = [],
  exchange = "binance",
  marketType = "spot",
}: ManualHistoryDownloadPanelProps) {
  const [form, setForm] = useState<ManualHistoryFormState>(() => ({
    ...createEmptyManualHistoryForm(),
    exchange,
    marketType,
    symbols,
    intervals,
  }));
  const [symbolDraft, setSymbolDraft] = useState(symbols.join(", "));
  const [customIntervalDraft, setCustomIntervalDraft] = useState("");
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [job, setJob] = useState<Record<string, unknown> | null>(null);
  const [recentJobs, setRecentJobs] = useState<Record<string, unknown>[]>([]);
  const [collections, setCollections] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string>("");
  const [flagEnabled, setFlagEnabled] = useState(Boolean(enabled));
  const [archiveEnabled, setArchiveEnabled] = useState(false);
  const [archivingJob, setArchivingJob] = useState("");
  const [archiveResult, setArchiveResult] = useState<Record<string, string>>({});
  const locale = useLocale();

  const { exchangeCatalog, exchangeCatalogStatus } = useExchangeCatalog(flagEnabled);
  const exchangeChoices = manualHistoryExchanges(exchangeCatalog);
  const marketChoices = manualHistoryMarkets(exchangeCatalog, form.exchange);
  const selectionAvailable = marketChoices.some((market) => market.market_type === form.marketType);
  const startEnabled = flagEnabled && selectionAvailable && isPlanFirstReady(form) && canStartDownload(plan);
  const jobState = String(job?.state || "");
  const jobId = String(job?.job_id || "");
  const jobTargets = Array.isArray(job?.targets)
    ? job.targets.filter((item): item is Record<string, unknown> => (
      item != null && typeof item === "object" && !Array.isArray(item)
    ))
    : [];
  const tone = parentStateTone(jobState);
  const hasEnd = formHasEndTime(form);
  const copyText = (key: Parameters<typeof manualHistoryText>[1], vars?: Readonly<Record<string, string>>) =>
    manualHistoryText(locale, key, vars);

  const summary = useMemo(() => {
    const targetCount = form.symbols.length * form.intervals.length;
    return `${form.symbols.length} × ${form.intervals.length} = ${targetCount}`;
  }, [form.symbols, form.intervals]);

  const plannedTargets = Array.isArray(plan?.targets)
    ? plan.targets.filter((item): item is Record<string, unknown> => (
      item != null && typeof item === "object" && !Array.isArray(item)
    ))
    : [];
  const planStorage = plan?.storage != null && typeof plan.storage === "object" && !Array.isArray(plan.storage)
    ? plan.storage as Record<string, unknown>
    : null;

  useEffect(() => {
    if (enabled !== undefined) setFlagEnabled(Boolean(enabled));
    const controller = new AbortController();
    void fetchManualHistoryCapabilities(controller.signal).then((payload) => {
      if (enabled === undefined) setFlagEnabled(payload.enabled === true);
      const capability = payload.replay_import as Record<string, unknown> | undefined;
      setArchiveEnabled(capability?.enabled === true);
    }).catch(() => {
      if (enabled === undefined) setFlagEnabled(false);
    });
    return () => controller.abort();
  }, [enabled]);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      listManualHistoryJobs(controller.signal),
      listManualHistoryCollections(controller.signal),
    ]).then(([jobs, nextCollections]) => {
      setRecentJobs(jobs);
      setCollections(nextCollections);
      const active = jobs.find((item) => ACTIVE_JOB_STATES.has(String(item.state || "")));
      if (active) setJob(active);
    }).catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!jobId || !ACTIVE_JOB_STATES.has(jobState)) return undefined;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      void getManualHistoryJob(jobId, controller.signal).then((payload) => {
        const next = (payload.job || payload) as Record<string, unknown>;
        if (next && typeof next === "object") {
          setJob(next);
          setRecentJobs((current) => [
            next,
            ...current.filter((item) => item.job_id !== next.job_id),
          ]);
          if (!ACTIVE_JOB_STATES.has(String(next.state || ""))) {
            void listManualHistoryCollections().then(setCollections).catch(() => undefined);
          }
        }
      }).catch(() => undefined);
    }, 1000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [jobId, jobState]);

  async function onPlan() {
    setError("");
    if (form.startMs == null) {
      setError(copyText("startRequired"));
      return;
    }
    try {
      const next = await planManualHistoryDownload({
        exchange: form.exchange,
        marketType: form.marketType,
        symbols: form.symbols,
        intervals: form.intervals,
        startMs: form.startMs,
      });
      setPlan(next);
    } catch (reason) {
      setError(reason instanceof Error ? describeError(reason, reason.message) : String(reason));
    }
  }

  async function onStart() {
    if (!startEnabled || form.startMs == null) return;
    const hash = String(plan?.plan_hash || plan?.planHash || "");
    setError("");
    try {
      const created = await createManualHistoryDownload({
        exchange: form.exchange,
        marketType: form.marketType,
        symbols: form.symbols,
        intervals: form.intervals,
        startMs: form.startMs,
        planHash: hash,
        idempotencyKey: crypto.randomUUID(),
      });
      const nextJob = (created.job || {}) as Record<string, unknown>;
      setJob(nextJob);
      setRecentJobs((current) => [nextJob, ...current]);
    } catch (reason) {
      setError(reason instanceof Error ? describeError(reason, reason.message) : String(reason));
    }
  }

  async function onCancel() {
    if (!jobId) return;
    setError("");
    try {
      const next = await cancelManualHistoryJob(jobId);
      const nextJob = (next.job || next) as Record<string, unknown>;
      setJob(nextJob);
    } catch (reason) {
      setError(reason instanceof Error ? describeError(reason, reason.message) : String(reason));
    }
  }

  async function onArchive(id: string) {
    if (archivingJob) return;
    setArchivingJob(id);
    setArchiveResult((current) => ({ ...current, [id]: "" }));
    try {
      const result = await archiveManualHistoryJob(id);
      setArchiveResult((current) => ({ ...current, [id]: copyText("archiveSucceeded", {
        rows: String(result.rows ?? 0),
      }) }));
    } catch (reason) {
      setArchiveResult((current) => ({ ...current, [id]: copyText("archiveFailed", {
        reason: reason instanceof Error ? describeError(reason, reason.message) : String(reason),
      }) }));
    } finally {
      setArchivingJob("");
    }
  }

  function onAddCustomInterval() {
    const normalized = normalizeCustomInterval(customIntervalDraft);
    if (!normalized) {
      setError(copyText("customIntervalInvalid"));
      return;
    }
    setError("");
    setForm((current) => ({
      ...current,
      intervals: current.intervals.includes(normalized)
        ? current.intervals
        : [...current.intervals, normalized],
    }));
    setCustomIntervalDraft("");
    setPlan(null);
  }

  async function onReleaseCollection(collectionId: string) {
    setError("");
    try {
      await releaseManualHistoryCollection(collectionId);
      setCollections((current) => current.map((item) => (
        item.collection_id === collectionId
          ? { ...item, status: "RELEASED" }
          : item
      )));
    } catch (reason) {
      setError(reason instanceof Error ? describeError(reason, reason.message) : String(reason));
    }
  }

  const controlId = useId();
  useControlCommands(() => ({ id: `manual-history:${controlId}`, title: "Plan-first market history downloads", context: () => ({ form, plan, jobId, jobState, archivingJob, flagEnabled, archiveEnabled }),
    snapshot: () => ({ form, plan, job, recentJobs, collections, error, flagEnabled, archiveEnabled, archivingJob, archiveResult, startEnabled }), commands: [
      command("form", "Set a start-only download draft and invalidate its previous plan.", object({ exchange: text(64), marketType: text(32), symbols: array(text(96), 128), intervals: array(text(32), 128), startMs: nullable(number(0, 1e15, true)) }), (input) => { const normalized = input.intervals.map(normalizeCustomInterval); if (normalized.some((value) => !value) || new Set(input.symbols).size !== input.symbols.length || new Set(normalized).size !== normalized.length) throw new Error("DOWNLOAD_FORM_INVALID"); const symbols = parseSymbolList(input.symbols.join(",")); if (symbols.length !== input.symbols.length) throw new Error("DOWNLOAD_SYMBOL_INVALID"); setForm({ ...input, symbols, intervals: normalized as string[] }); setSymbolDraft(symbols.join(", ")); setPlan(null); }, { available: () => flagEnabled }),
      command("plan", "Inspect the download plan before starting.", empty, onPlan, { available: () => flagEnabled && isPlanFirstReady(form) }),
      command("start", "Start the currently inspected plan using its domain plan hash.", empty, onStart, { available: () => startEnabled }),
      command("cancel", "Cancel the active download job.", empty, onCancel, { available: () => !!jobId && ACTIVE_JOB_STATES.has(jobState), interrupt: true }),
      command("refresh", "Refresh download records and protected collections.", empty, async () => { const [jobs, nextCollections] = await Promise.all([listManualHistoryJobs(), listManualHistoryCollections()]); setRecentJobs(jobs); setCollections(nextCollections); if (jobId) { const payload = await getManualHistoryJob(jobId); setJob((payload.job || payload) as Record<string, unknown>); } }),
      command("selectJob", "Inspect a listed download job.", object({ jobId: text(128) }), async ({ jobId }) => { if (!recentJobs.some((item) => item.job_id === jobId)) throw new Error("JOB_UNAVAILABLE"); const payload = await getManualHistoryJob(jobId); setJob((payload.job || payload) as Record<string, unknown>); }),
      command("archive", "Import a completed eligible job into replay storage.", object({ jobId: text(128) }), ({ jobId }) => { const item = recentJobs.find((item) => item.job_id === jobId); if (!item || !isGreenCompleteState(String(item.state))) throw new Error("JOB_NOT_COMPLETE"); return onArchive(jobId); }, { available: () => archiveEnabled && !archivingJob }),
      command("releaseCollection", "Release a listed collection's protection with explicit confirmation.", object({ collectionId: text(128), confirmed: choice([true]) }), ({ collectionId }) => { const item = collections.find((item) => item.collection_id === collectionId); if (!item || item.status === "RELEASED") throw new Error("COLLECTION_UNAVAILABLE"); return onReleaseCollection(collectionId); }),
    ] }));
  if (!flagEnabled) {
    return (
      <section className="dw-manual dw-manual-disabled" data-testid="manual-history-download-disabled">
        {copyText("disabled")}
      </section>
    );
  }

  const statusMessage = !jobState
    ? null
    : isGreenCompleteState(jobState)
      ? copyText("succeeded")
      : jobState === "PARTIAL"
        ? copyText("partialNotComplete")
        : jobState === "BLOCKED_STORAGE"
          ? copyText("blocked")
          : jobState === "FAILED"
            ? copyText("failed")
            : copyText("jobState", { state: jobState });

  return (
    <section className="dw-manual" data-testid="manual-history-download-panel">
      <h3>{copyText("title")}</h3>
      <p>{copyText("hint")}</p>
      <p>{copyText("protected")}</p>
      <p data-testid="manual-history-target-count">{summary}</p>
      <label>
        {copyText("exchange")}
        <select
          data-testid="manual-history-exchange"
          value={form.exchange}
          disabled={exchangeCatalogStatus !== "ready"}
          onChange={(event) => {
            const exchange = event.target.value;
            const markets = manualHistoryMarkets(exchangeCatalog, exchange);
            setForm((current) => ({ ...current, exchange,
              marketType: markets.some((market) => market.market_type === current.marketType)
                ? current.marketType : markets[0]?.market_type || "spot" }));
            setPlan(null);
          }}
        >
          {!exchangeChoices.some((entry) => entry.id === form.exchange)
            ? <option value={form.exchange} disabled>{form.exchange}</option> : null}
          {exchangeChoices.map((entry) => <option key={entry.id} value={entry.id}>{entry.label}</option>)}
        </select>
      </label>
      <label>
        {copyText("marketType")}
        <select
          data-testid="manual-history-market"
          value={form.marketType}
          disabled={exchangeCatalogStatus !== "ready"}
          onChange={(event) => {
            setForm((current) => ({ ...current, marketType: event.target.value }));
            setPlan(null);
          }}
        >
          {!selectionAvailable ? <option value={form.marketType} disabled>{form.marketType}</option> : null}
          {marketChoices.map((market) => <option key={market.market_type} value={market.market_type}>
            {market.market_type === "spot" ? copyText("spot")
              : market.market_type === "futures" ? copyText("futures") : market.label}
          </option>)}
        </select>
      </label>
      <label>
        {copyText("symbols")}
        <textarea
          data-testid="manual-history-symbols"
          value={symbolDraft}
          onChange={(event) => {
            const value = event.target.value;
            setSymbolDraft(value);
            setForm((current) => ({ ...current, symbols: parseSymbolList(value) }));
            setPlan(null);
          }}
        />
      </label>
      <fieldset data-testid="manual-history-intervals">
        <legend>{copyText("intervals")}</legend>
        {MANUAL_HISTORY_INTERVAL_CHOICES.map((interval) => (
          <label key={interval}>
            <input
              type="checkbox"
              checked={form.intervals.includes(interval)}
              onChange={() => {
                setForm((current) => ({
                  ...current,
                  intervals: toggleInterval(current.intervals, interval),
                }));
                setPlan(null);
              }}
            />
            {interval}
          </label>
        ))}
        {form.intervals
          .filter((interval) => !MANUAL_HISTORY_INTERVAL_CHOICES.includes(
            interval as typeof MANUAL_HISTORY_INTERVAL_CHOICES[number],
          ))
          .map((interval) => (
            <label key={interval}>
              <input
                type="checkbox"
                checked
                onChange={() => {
                  setForm((current) => ({
                    ...current,
                    intervals: toggleInterval(current.intervals, interval),
                  }));
                  setPlan(null);
                }}
              />
              {interval}
            </label>
          ))}
      </fieldset>
      <label>
        {copyText("customInterval")}
        <input
          data-testid="manual-history-custom-interval"
          value={customIntervalDraft}
          placeholder="89m"
          onChange={(event) => setCustomIntervalDraft(event.target.value)}
        />
      </label>
      <button
        type="button"
        data-testid="manual-history-add-custom-interval"
        onClick={onAddCustomInterval}
      >
        {copyText("addCustomInterval")}
      </button>
      <label>
        {copyText("startTime")}
        <input
          data-testid="manual-history-start"
          type="datetime-local"
          onChange={(event) => {
            const value = event.target.value;
            setForm((current) => ({
              ...current,
              startMs: value ? Date.parse(value) : null,
            }));
            setPlan(null);
          }}
        />
      </label>
      {hasEnd ? <p>{copyText("endNotAllowed")}</p> : null}
      <button className="dw-button dw-button-secondary" type="button" data-testid="manual-history-plan" onClick={() => void onPlan()}>
        {copyText("previewPlan")}
      </button>
      <button
        type="button"
        className="dw-button dw-button-primary"
        data-testid="manual-history-start-download"
        disabled={!startEnabled}
        onClick={() => void onStart()}
      >
        {copyText("startDownload")}
      </button>
      <button
        type="button"
        className="dw-button dw-button-secondary"
        data-testid="manual-history-cancel"
        disabled={!jobId}
        onClick={() => void onCancel()}
      >
        {copyText("cancel")}
      </button>
      {ACTIVE_JOB_STATES.has(jobState) ? <p data-testid="manual-history-polling">{copyText("polling")}</p> : null}
      {error ? <p data-testid="manual-history-error">{error}</p> : null}
      {plan ? (
        <div data-testid="manual-history-plan-summary">
          <h4>{copyText("planSummary")}</h4>
          <p>{copyText("planCanStart", { value: plan.can_start === true ? copyText("yes") : copyText("no") })}</p>
          {planStorage ? (
            <p>
              {copyText("estimatedStorage", {
                value: String(planStorage.estimated_db_growth_bytes ?? copyText("unknown")),
              })}
            </p>
          ) : null}
          <ul>
            {plannedTargets.map((target) => (
              <li key={`${String(target.symbol)}:${String(target.canonical_interval)}`}>
                {String(target.symbol)} · {String(target.canonical_interval)} · {String(target.route_kind)}
                {target.source_interval !== target.canonical_interval
                  ? ` ← ${String(target.source_interval)}`
                  : ""}
                {` · ${copyText("effectiveStart")}: ${String(target.effective_start_ms ?? copyText("unknown"))}`}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {jobState ? (
        <div>
          <p data-testid="manual-history-job-state" data-tone={tone}>
            {statusMessage}
          </p>
          {jobTargets.length > 0 ? (
            <ul data-testid="manual-history-job-targets">
              {jobTargets.map((target) => (
                <li key={`${String(target.symbol)}:${String(target.canonical_interval)}`}>
                  {String(target.symbol)} · {String(target.canonical_interval)} · {String(target.state)}
                  {` · ${copyText("sealedEnd")}: ${String(target.sealed_end_open_ms ?? copyText("unknown"))}`}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div data-testid="manual-history-recent-jobs">
        <h4>{copyText("recentJobs")}</h4>
        <p>{copyText("archiveHint")}</p>
        {!archiveEnabled ? <p>{copyText("archiveUnavailable")}</p> : null}
        {recentJobs.length === 0 ? <p>{copyText("none")}</p> : (
          <ul>
            {recentJobs.map((item) => {
              const collection = collections.find((entry) => entry.collection_id === item.collection_id);
              const targets = Array.isArray(collection?.targets)
                ? collection.targets as Record<string, unknown>[] : [];
              const labels = targets.map((target) => `${String(target.symbol)}@${String(target.canonical_interval)}`);
              const hasMinuteHistory = targets.some((target) => target.canonical_interval === "1m");
              return (
              <li key={String(item.job_id)}>
                {String(item.state)} · {String(item.ready_targets ?? 0)}/{String(item.total_targets ?? 0)}
                {labels.length > 0 ? ` · ${labels.join(", ")}` : ""}
                {item.state === "SUCCEEDED" && hasMinuteHistory ? (
                  <button type="button" className="dw-button dw-button-secondary"
                    disabled={!archiveEnabled || Boolean(archivingJob)}
                    onClick={() => void onArchive(String(item.job_id))}>
                    {archivingJob === item.job_id ? copyText("archiving") : copyText("archiveAction")}
                  </button>
                ) : null}
                {archiveResult[String(item.job_id)] ? (
                  <p role="status">{archiveResult[String(item.job_id)]}</p>
                ) : null}
              </li>
              );
            })}
          </ul>
        )}
      </div>
      <div data-testid="manual-history-collections">
        <h4>{copyText("protectedCollections")}</h4>
        {collections.length === 0 ? <p>{copyText("none")}</p> : (
          <ul>
            {collections.map((item) => {
              const collectionId = String(item.collection_id || "");
              const released = String(item.status || "") === "RELEASED";
              const targetLabels = Array.isArray(item.targets)
                ? item.targets.map((target) => {
                  const record = target as Record<string, unknown>;
                  return `${String(record.symbol)}@${String(record.canonical_interval)}`;
                })
                : [];
              return (
                <li key={collectionId}>
                  {String(item.exchange)} · {String(item.market_type)} · {String(item.status)}
                  {targetLabels.length > 0 ? ` · ${targetLabels.join(", ")}` : ""}
                  <button
                    type="button"
                    className="dw-button dw-button-secondary dw-manual-release"
                    disabled={released}
                    onClick={() => void onReleaseCollection(collectionId)}
                  >
                    {released ? copyText("released") : copyText("releaseProtection")}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
