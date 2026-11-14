import { useState, type ReactNode } from "react";
import { Badge, Button, Checkbox, Disclosure, InlineAlert, type Tone } from "../../components/ui/index.js";
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
  return <Disclosure className="strategy-research-batch" summary={t(marketEnabled ? "researchBatch.allSources" : "researchBatch.sources")}>
    <p className="strategy-research-note">{t(marketEnabled ? "researchBatch.marketHelp" : "researchBatch.help", { max: RESEARCH_BATCH_MAX_INPUTS })}</p>
    {precise && <p className="strategy-research-note">{t("researchBatch.precise")}</p>}
    {available.length > 0 && <fieldset className="strategy-research-checklist">
      <legend>{t("researchBatch.sources")}</legend>
      {available.map(dataset => {
        const key = sourceKey(dataset);
        const eligible = supportsBatchSource(dataset, precise);
        const checked = eligible && selection.includes(key);
        return <Checkbox key={key} checked={checked} disabled={!eligible || (!checked && selected.length + exchange.length >= RESEARCH_BATCH_MAX_INPUTS)}
          label={`${dataset.name} · ${dataset.symbol} · ${dataset.interval}`}
          description={t(dataset.market_trade_input ? "researchBatch.trades" : "researchBatch.bars")}
          onChange={(event) => {
            const keys = selected.map(sourceKey);
            setSelection(event.target.checked ? [...keys, key] : keys.filter(value => value !== key));
          }} />;
      })}
    </fieldset>}
    {marketEnabled && <ResearchMarketInputs markets={markets} onChange={onMarkets} limit={RESEARCH_BATCH_MAX_INPUTS - selected.length} />}
    {children(selected, exchange)}
  </Disclosure>;
}

const statusMessages = {
  QUEUED: "chartTester.status.queued",
  PREPARING: "researchBatch.preparing",
  RUNNING: "chartTester.status.running",
  COMPLETED: "chartTester.status.completed",
  FAILED: "researchBatch.failed",
  INTERRUPTED: "researchBatch.interrupted",
} as const;

const statusTones: Record<ResearchBatchJob["status"], Tone> = {
  QUEUED: "neutral",
  PREPARING: "accent",
  RUNNING: "accent",
  COMPLETED: "success",
  FAILED: "danger",
  INTERRUPTED: "warning",
};

export function ResearchBatchResults({ jobs, storageFailed, onOpen, onResume }: {
  jobs: readonly ResearchBatchJob[]; storageFailed: boolean;
  onOpen(job: ResearchBatchJob): void; onResume(id: string, retry?: boolean): void;
}) {
  const locale = useLocale();
  if (!jobs.length && !storageFailed) return null;
  return <section className="strategy-research-batch-jobs" aria-label={t("researchBatch.jobs")} data-testid="research-batch-jobs">
    <h3>{t("researchBatch.jobs")}</h3>
    {storageFailed && <InlineAlert tone="danger">{t("researchBatch.storage")}</InlineAlert>}
    <ul className="strategy-history-list">
      {[...jobs].reverse().map(job => <li key={job.id} className="strategy-history-row" data-batch-job={job.id} data-status={job.status}>
        <div className="strategy-history-run">
          <strong>{job.name} · {job.datasetName} · {job.interval}</strong>
          <span>{new Date(job.startMs).toLocaleString(locale)} – {new Date(job.endMs).toLocaleString(locale)}</span>
          {job.error && <small>{job.error}</small>}
          {job.status === "PREPARING" && job.preparation && <small role="status">
            {job.preparation.completed}/{job.preparation.total}
            {job.preparation.waitingUntil && ` · ${t("researchBatch.marketWaiting", { time: new Date(job.preparation.waitingUntil).toLocaleString(locale) })}`}
          </small>}
        </div>
        <Badge tone={statusTones[job.status]}><span role="status">{t(statusMessages[job.status])}</span></Badge>
        <div className="strategy-history-actions">
          {job.status === "COMPLETED" && job.runId && <Button size="sm" onClick={() => onOpen(job)}>{t("researchBatch.open")}</Button>}
          {job.status === "FAILED" && !job.runId && job.preparation
            && <Button size="sm" onClick={() => onResume(job.id, job.preparation?.retryable)}>
              {t(job.preparation.retryable ? "preparation.retry" : "researchBatch.marketReconnect")}
            </Button>}
          {job.status === "FAILED" && job.runId && <Button size="sm" onClick={() => onResume(job.id)}>{t("researchBatch.resume")}</Button>}
        </div>
      </li>)}
    </ul>
  </section>;
}
