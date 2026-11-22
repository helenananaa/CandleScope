import { useState, type ReactNode } from "react";
import { Badge, Button, Checkbox, Disclosure, InlineAlert, type Tone } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import { RESEARCH_BATCH_MAX_INPUTS, supportsBatchSource, type ResearchBatchJob, type ResearchMarketInput } from "./strategyResearchBatch.js";
import type { ExperimentMember, ExperimentMemberState, StrategyExperiment } from "../backtest/experiment/strategyExperiment.js";

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

const memberMessages = {
  PENDING: "researchExperiment.waiting",
  PREPARING: "researchBatch.preparing",
  QUEUED: "chartTester.status.queued",
  RUNNING: "chartTester.status.running",
  COMPLETED: "chartTester.status.completed",
  FAILED: "researchBatch.failed",
  CANCELLED: "researchExperiment.stopped",
} as const;

const memberTones: Record<ExperimentMemberState, Tone> = {
  PENDING: "neutral", PREPARING: "accent", QUEUED: "neutral", RUNNING: "accent", COMPLETED: "success", FAILED: "danger", CANCELLED: "warning",
};

function memberLabel(member: ExperimentMember): string {
  const input = member.input;
  const parts = input.kind === "IMPORTED_DATASET"
    ? [input.name, input.symbol, input.interval] : [input.exchange, input.marketType, input.symbol, input.interval];
  return parts.filter((part): part is string => typeof part === "string" && part.length > 0).join(" · ");
}

/** Batch runs kept by the backend as experiments (ADR-BACKTEST-015 P5b): each input's own progress, result or failure. */
export function ResearchExperimentResults({ experiments, onOpen, onCancel, onRetry }: {
  experiments: readonly StrategyExperiment[];
  onOpen(experiment: StrategyExperiment, member: ExperimentMember): void;
  onCancel(experimentId: string): void;
  onRetry(experimentId: string, ordinal: number): void;
}) {
  const locale = useLocale();
  if (!experiments.length) return null;
  const time = (value: unknown) => typeof value === "number" ? new Date(value).toLocaleString(locale) : "—";
  return <section className="strategy-research-batch-jobs" aria-label={t("researchBatch.jobs")} data-testid="research-experiments">
    <h3>{t("researchBatch.jobs")}</h3>
    {experiments.map((experiment) => <div key={experiment.experimentId} className="strategy-research-experiment"
      data-experiment={experiment.experimentId} data-state={experiment.state}>
      <div className="strategy-history-row">
        <div className="strategy-history-run">
          <strong>{experiment.name}</strong>
          <span>{time(experiment.createdAtMs)} · {t("researchExperiment.progress", { completed: experiment.counts.completed, total: experiment.counts.total })}</span>
        </div>
        {experiment.state === "CANCELLED" && <Badge tone="warning">{t("researchExperiment.stopped")}</Badge>}
        {!experiment.terminal && <Button size="sm" variant="ghost" onClick={() => onCancel(experiment.experimentId)}>{t("researchExperiment.stop")}</Button>}
      </div>
      <ul className="strategy-history-list">
        {experiment.members.map((member) => <li key={member.ordinal} className="strategy-history-row" data-experiment-member={member.ordinal} data-status={member.state}>
          <div className="strategy-history-run">
            <strong>{memberLabel(member)}</strong>
            <span>{time(member.input.startMs)} – {time(member.input.endMs)}</span>
            {member.error && <small>{member.error.message}</small>}
            {member.state === "PREPARING" && member.preparation && <small role="status">
              {member.preparation.completed}/{member.preparation.total}
              {typeof member.preparation.waiting?.retry_at_ms === "number"
                && ` · ${t("researchBatch.marketWaiting", { time: time(member.preparation.waiting.retry_at_ms) })}`}
            </small>}
          </div>
          <Badge tone={memberTones[member.state]}><span role="status">{t(memberMessages[member.state])}</span></Badge>
          <div className="strategy-history-actions">
            {member.state === "COMPLETED" && member.runId && <Button size="sm" onClick={() => onOpen(experiment, member)}>{t("researchBatch.open")}</Button>}
            {(member.state === "FAILED" || member.state === "CANCELLED") && experiment.state !== "CANCELLED"
              && <Button size="sm" onClick={() => onRetry(experiment.experimentId, member.ordinal)}>{t("researchExperiment.retry")}</Button>}
          </div>
        </li>)}
      </ul>
    </div>)}
  </section>;
}

export function ResearchBatchResults({ jobs, storageFailed, onOpen, onResume, title }: {
  jobs: readonly ResearchBatchJob[]; storageFailed: boolean;
  onOpen(job: ResearchBatchJob): void; onResume(id: string, retry?: boolean): void;
  /** Batch tasks this browser ran before experiments are listed under their own heading. */
  title?: string;
}) {
  const locale = useLocale();
  if (!jobs.length && !storageFailed) return null;
  return <section className="strategy-research-batch-jobs" aria-label={title ?? t("researchBatch.jobs")} data-testid="research-batch-jobs">
    <h3>{title ?? t("researchBatch.jobs")}</h3>
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
