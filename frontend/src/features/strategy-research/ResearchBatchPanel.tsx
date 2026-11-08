import { useState, type ReactNode } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import { RESEARCH_BATCH_MAX_INPUTS, supportsBatchSource, type ResearchBatchJob } from "./strategyResearchBatch.js";

function sourceKey(dataset: LocalDatasetManifest): string {
  return JSON.stringify([dataset.dataset_id, dataset.data_epoch]);
}

export function ResearchBatchSources({ datasets, precise, children }: {
  datasets: readonly LocalDatasetManifest[];
  precise: boolean;
  children(selected: readonly LocalDatasetManifest[]): ReactNode;
}) {
  useLocale();
  const [selection, setSelection] = useState<readonly string[]>([]);
  const available = datasets.filter(dataset => supportsBatchSource(dataset, false));
  const selected = available.filter(dataset => supportsBatchSource(dataset, precise) && selection.includes(sourceKey(dataset)));
  if (available.length < 2) return null;
  return <details className="chart-strategy-credibility-details">
    <summary>{t("researchBatch.sources")}</summary>
    <p>{t("researchBatch.help", { max: RESEARCH_BATCH_MAX_INPUTS })}</p>
    {precise && <p>{t("researchBatch.precise")}</p>}
    <fieldset>
      <legend>{t("researchBatch.sources")}</legend>
      {available.map(dataset => {
        const key = sourceKey(dataset);
        const eligible = supportsBatchSource(dataset, precise);
        const checked = eligible && selection.includes(key);
        return <div key={key}><label>
          <input type="checkbox" checked={checked} disabled={!eligible || (!checked && selected.length >= RESEARCH_BATCH_MAX_INPUTS)}
            onChange={(event) => {
              const keys = selected.map(sourceKey);
              setSelection(event.target.checked ? [...keys, key] : keys.filter(value => value !== key));
            }} /> {dataset.name} · {dataset.symbol} · {dataset.interval} · {t(dataset.market_trade_input ? "researchBatch.trades" : "researchBatch.bars")}
        </label></div>;
      })}
    </fieldset>
    {children(selected)}
  </details>;
}

const statusMessages = {
  QUEUED: "chartTester.status.queued",
  PREPARING: "researchBatch.preparing",
  RUNNING: "chartTester.status.running",
  COMPLETED: "chartTester.status.completed",
  FAILED: "researchBatch.failed",
  INTERRUPTED: "researchBatch.interrupted",
} as const;

export function ResearchBatchResults({ jobs, storageFailed, onOpen, onResume }: {
  jobs: readonly ResearchBatchJob[]; storageFailed: boolean;
  onOpen(job: ResearchBatchJob): void; onResume(id: string): void;
}) {
  const locale = useLocale();
  if (!jobs.length && !storageFailed) return null;
  return <section aria-label={t("researchBatch.jobs")} data-testid="research-batch-jobs">
    <h3>{t("researchBatch.jobs")}</h3>
    {storageFailed && <p role="alert">{t("researchBatch.storage")}</p>}
    <ul>
      {[...jobs].reverse().map(job => <li key={job.id} data-batch-job={job.id} data-status={job.status}>
        <strong>{job.name}</strong> · {job.datasetName} · {job.interval}
        <p>{new Date(job.startMs).toLocaleString(locale)} – {new Date(job.endMs).toLocaleString(locale)}</p>
        <p role="status">{t(statusMessages[job.status])}{job.error ? ` · ${job.error}` : ""}</p>
        {job.status === "COMPLETED" && job.runId && <button type="button" onClick={() => onOpen(job)}>{t("researchBatch.open")}</button>}
        {job.status === "FAILED" && job.runId && <button type="button" onClick={() => onResume(job.id)}>{t("researchBatch.resume")}</button>}
      </li>)}
    </ul>
  </section>;
}
