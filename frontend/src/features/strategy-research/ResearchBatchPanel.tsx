import { useState, type ReactNode } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import { RESEARCH_BATCH_MAX_INPUTS, supportsBatchSource, type ResearchBatchJob, type ResearchMarketInput } from "./strategyResearchBatch.js";

import ResearchMarketInputs from "./ResearchMarketInputs.js";

function sourceKey(dataset: LocalDatasetManifest): string {
  return JSON.stringify([dataset.dataset_id, dataset.data_epoch]);
}

export function ResearchBatchSources({ datasets, precise, marketEnabled, markets, onMarkets, children }: {
  datasets: readonly LocalDatasetManifest[];
  precise: boolean;
  marketEnabled?: boolean;
  markets: readonly ResearchMarketInput[];
  onMarkets(next: readonly ResearchMarketInput[]): void;
  children(selected: readonly LocalDatasetManifest[], markets: readonly ResearchMarketInput[]): ReactNode;
}) {
  useLocale();
  const [selection, setSelection] = useState<readonly string[]>([]);
  const available = datasets.filter(dataset => supportsBatchSource(dataset, false));
  const selected = available.filter(dataset => supportsBatchSource(dataset, precise) && selection.includes(sourceKey(dataset)));
  if (available.length < 2 && !marketEnabled) return null;
  const exchange = marketEnabled ? markets : [];
  return <details className="chart-strategy-credibility-details">
    <summary>{t(marketEnabled ? "researchBatch.allSources" : "researchBatch.sources")}</summary>
    <p>{t(marketEnabled ? "researchBatch.marketHelp" : "researchBatch.help", { max: RESEARCH_BATCH_MAX_INPUTS })}</p>
    {precise && <p>{t("researchBatch.precise")}</p>}
    <fieldset>
      <legend>{t("researchBatch.sources")}</legend>
      {available.map(dataset => {
        const key = sourceKey(dataset);
        const eligible = supportsBatchSource(dataset, precise);
        const checked = eligible && selection.includes(key);
        return <div key={key}><label>
          <input type="checkbox" checked={checked} disabled={!eligible || (!checked && selected.length + exchange.length >= RESEARCH_BATCH_MAX_INPUTS)}
            onChange={(event) => {
              const keys = selected.map(sourceKey);
              setSelection(event.target.checked ? [...keys, key] : keys.filter(value => value !== key));
            }} /> {dataset.name} · {dataset.symbol} · {dataset.interval} · {t(dataset.market_trade_input ? "researchBatch.trades" : "researchBatch.bars")}
        </label></div>;
      })}
    </fieldset>
    {marketEnabled && <ResearchMarketInputs markets={markets} onChange={onMarkets} limit={RESEARCH_BATCH_MAX_INPUTS - selected.length} />}
    {children(selected, exchange)}
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
  onOpen(job: ResearchBatchJob): void; onResume(id: string, retry?: boolean): void;
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
        {job.status === "PREPARING" && job.preparation && <p role="status">
          {job.preparation.completed}/{job.preparation.total}
          {job.preparation.waitingUntil && ` · ${t("researchBatch.marketWaiting", { time: new Date(job.preparation.waitingUntil).toLocaleString(locale) })}`}
        </p>}
        {job.status === "COMPLETED" && job.runId && <button type="button" onClick={() => onOpen(job)}>{t("researchBatch.open")}</button>}
        {job.status === "FAILED" && !job.runId && job.preparation
          && <button type="button" onClick={() => onResume(job.id, job.preparation?.retryable)}>
            {t(job.preparation.retryable ? "preparation.retry" : "researchBatch.marketReconnect")}
          </button>}
        {job.status === "FAILED" && job.runId && <button type="button" onClick={() => onResume(job.id)}>{t("researchBatch.resume")}</button>}
      </li>)}
    </ul>
  </section>;
}
