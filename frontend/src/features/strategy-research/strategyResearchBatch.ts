import { floorIntervalTime } from "../../utils/intervalTimeline.js";
import type { PreparationJob } from "../data-preparation/api.js";
import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import type { BacktestRunRecord } from "../backtest/backtestTypes.js";
import { chartStrategyRunDiagnostics, type ResearchRunSource } from "../backtest/chart-tester/chartStrategyRunRequest.js";
import type { ChartStrategyResultBundle } from "../backtest/chart-tester/chartStrategyResultCache.js";
import type { ChartStrategyRunRequest } from "../backtest/chart-tester/chartStrategyTesterUiModel.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import type { StrategyStorage } from "../../shared/strategyStorage.js";
import { importedResearchRange, importedResearchRunSource } from "./importedDatasetSource.js";

const storageKey = "candlescope:strategy-research-batch:v1";
const statuses = ["QUEUED", "PREPARING", "RUNNING", "COMPLETED", "FAILED", "INTERRUPTED"] as const;
const maxJobs = 64;
export const RESEARCH_BATCH_MAX_INPUTS = 8;

export interface ResearchMarketInput {
  session: Pick<ChartSession, "exchange" | "marketType" | "symbol" | "interval">;
  startMs: number;
  endMs: number;
}

export function marketInputKey({ session, startMs, endMs }: ResearchMarketInput): string {
  return JSON.stringify([session.exchange, session.marketType, session.symbol, session.interval, startMs, endMs]);
}

export function validMarketInput(input: ResearchMarketInput, through = Date.now()): boolean {
  const { session, startMs, endMs } = input;
  return [session.exchange, session.marketType, session.symbol, session.interval]
    .every(value => typeof value === "string" && value.length > 0 && value.length <= 128)
    && Number.isSafeInteger(startMs) && Number.isSafeInteger(endMs) && startMs > 0 && startMs < endMs && endMs <= through
    && [startMs, endMs].every(time => floorIntervalTime(session.interval, time / 1000) === time / 1000);
}

interface BatchPreparation {
  id: string;
  revision: number;
  completed: number;
  total: number;
  retryable: boolean;
  waitingUntil: number | null;
}

export interface ResearchBatchJob {
  id: string;
  batchId: string;
  name: string;
  datasetName: string;
  draftId: string;
  draftContentRevision: number;
  datasetId: string;
  dataEpoch: string;
  interval: string;
  startMs: number;
  endMs: number;
  status: (typeof statuses)[number];
  runId: string | null;
  strategyRevisionId: string | null;
  snapshotHash: string | null;
  error: string | null;
  market?: ResearchMarketInput["session"] & { scope: string };
  preparation?: BatchPreparation;
}

function readJobs(storage: StrategyStorage): ResearchBatchJob[] {
  const raw = storage.getItem(storageKey);
  if (raw === null) return [];
  if (raw.length > 256_000) throw new Error("RESEARCH_BATCH_STORAGE_INVALID");
  const payload = JSON.parse(raw) as { schema: number; jobs: ResearchBatchJob[] } | null;
  if (payload?.schema !== 1 || !Array.isArray(payload.jobs) || payload.jobs.length > maxJobs) {
    throw new Error("RESEARCH_BATCH_STORAGE_INVALID");
  }
  const ids = new Set<string>();
  for (const job of payload.jobs) {
    if (!job || typeof job.id !== "string" || !job.id || ids.has(job.id) || !statuses.includes(job.status)
      || ![job.batchId, job.name, job.datasetName, job.draftId, job.datasetId, job.dataEpoch, job.interval].every(value => typeof value === "string")
      || ![job.runId, job.strategyRevisionId, job.snapshotHash, job.error].every(value => value === null || typeof value === "string")
      || ![job.startMs, job.endMs, job.draftContentRevision].every(Number.isSafeInteger)
      || job.startMs < 0 || job.startMs >= job.endMs || job.endMs > 8640000000000000
      || (job.market !== undefined && (!job.market || typeof job.market.scope !== "string"
        || !validMarketInput({ session: job.market, startMs: job.startMs, endMs: job.endMs }, Infinity)))
      || (job.preparation !== undefined && (!job.market || !job.preparation || !/^[a-f0-9]{32}$/.test(job.preparation.id)
        || ![job.preparation.revision, job.preparation.completed, job.preparation.total].every(value => Number.isSafeInteger(value) && value >= 0)
        || typeof job.preparation.retryable !== "boolean"
        || (job.preparation.waitingUntil !== null && !Number.isSafeInteger(job.preparation.waitingUntil))))
      || (job.status === "COMPLETED" && !job.runId)
      || (job.runId !== null && (!/^bt_[\w-]{1,128}$/.test(job.runId) || !job.strategyRevisionId || !job.snapshotHash))) {
      throw new Error("RESEARCH_BATCH_STORAGE_INVALID");
    }
    ids.add(job.id);
  }
  return payload.jobs;
}

export function supportsBatchSource(dataset: LocalDatasetManifest, precise: boolean): boolean {
  if (dataset.archived) return false;
  if (dataset.source === "user_market_trades") return dataset.market_trade_input !== undefined;
  return !precise && dataset.source === "local_dataset";
}

type BatchManager = Pick<StrategyDataManager, "runResearch"> & Partial<Pick<StrategyDataManager, "observeResearchPreparation">> & {
  restoreRun(id: string): Promise<Pick<ChartStrategyResultBundle, "run" | "config">>;
};
type BatchState = { jobs: readonly ResearchBatchJob[]; storageFailed: boolean };

export class StrategyResearchBatch {
  private state: BatchState = { jobs: [], storageFailed: false };
  private readonly listeners = new Set<() => void>();
  private readonly queue: Array<() => Promise<void>> = [];
  private readonly scheduled = new Set<string>();
  private running = 0;
  private started = false;
  private closed = false;
  private writes = Promise.resolve();

  constructor(private readonly manager: BatchManager, private readonly storage: StrategyStorage | null) {
    try {
      if (!storage) throw new Error("RESEARCH_BATCH_STORAGE_UNAVAILABLE");
      this.state = { jobs: readJobs(storage), storageFailed: false };
    } catch {
      this.state = { jobs: [], storageFailed: true };
    }
  }

  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private publish(state: BatchState): void {
    if (this.closed) return;
    this.state = state;
    this.listeners.forEach(listener => listener());
  }

  private persist(changes: readonly ResearchBatchJob[]): Promise<void> {
    const storage = this.storage;
    const write = async () => {
      if (!storage) throw new Error("RESEARCH_BATCH_STORAGE_UNAVAILABLE");
      const existing = new Map(readJobs(storage).map(job => [job.id, job]));
      for (const job of changes) {
        const previous = existing.get(job.id);
        // A second observer may still hold an older preparation or stream state.
        if (previous?.status === "COMPLETED" || (previous?.runId && !job.runId)) continue;
        existing.set(job.id, job);
      }
      if (existing.size > maxJobs) throw new Error("RESEARCH_BATCH_CAPACITY");
      await storage.setItem(storageKey, JSON.stringify({ schema: 1, jobs: [...existing.values()] }));
    };
    const pending = this.writes.then(async () => {
      if (globalThis.navigator?.locks) await navigator.locks.request(storageKey, write);
      else await write();
    });
    this.writes = pending.catch(() => { this.publish({ ...this.state, storageFailed: true }); });
    return pending;
  }

  private update(id: string, patch: Partial<ResearchBatchJob>): Promise<void> {
    if (this.closed) return Promise.resolve();
    const previous = this.state.jobs.find(job => job.id === id);
    if (!previous) return Promise.resolve();
    const next = { ...previous, ...patch };
    this.publish({ ...this.state, jobs: this.state.jobs.map(job => job.id === id ? next : job) });
    return this.persist([next]).catch(() => undefined);
  }

  private enqueue(id: string, task: () => Promise<void>): void {
    if (this.closed || this.scheduled.has(id)) return;
    this.scheduled.add(id);
    this.queue.push(async () => {
      try { await task(); }
      catch (error) {
        await this.update(id, { status: "FAILED", error: chartStrategyRunDiagnostics(error).message.slice(0, 512) });
      } finally {
        this.scheduled.delete(id);
      }
    });
    this.pump();
  }

  private pump(): void {
    while (!this.closed && this.running < 2 && this.queue.length) {
      const task = this.queue.shift()!;
      this.running += 1;
      void task().finally(() => { this.running -= 1; this.pump(); });
    }
  }

  start(): void {
    if (this.started || this.closed) return;
    this.started = true;
    for (const job of this.state.jobs) {
      if (!["QUEUED", "PREPARING", "RUNNING"].includes(job.status)) continue;
      if (job.runId || job.preparation) this.resume(job.id);
      else void this.update(job.id, { status: "INTERRUPTED" });
    }
  }

  private async preparationProgress(id: string, progress: PreparationJob): Promise<void> {
    if (!/^[a-f0-9]{32}$/.test(progress.id)) throw new Error("STRATEGY_PREPARATION_IDENTITY_MISMATCH");
    const job = this.state.jobs.find(item => item.id === id);
    const scope = (progress.request.intent.strategy as { chart_cell_scope?: unknown } | undefined)?.chart_cell_scope;
    if (!job?.market || progress.request.consumer !== "STRATEGY" || scope !== job.market.scope) {
      throw new Error("STRATEGY_PREPARATION_IDENTITY_MISMATCH");
    }
    const previous = job.preparation;
    if (previous && previous.id !== progress.id) throw new Error("STRATEGY_PREPARATION_IDENTITY_MISMATCH");
    if (previous && previous.revision >= progress.revision) return;
    await this.update(id, { preparation: {
      id: progress.id, revision: progress.revision, completed: progress.completed, total: progress.total,
      retryable: !progress.cancel_requested && (progress.state === "BLOCKED_STORAGE" || progress.error?.retryable === true),
      waitingUntil: progress.waiting?.retry_at_ms ?? null,
    } });
  }

  private async recordRun(job: ResearchBatchJob, run: BacktestRunRecord, strategyRevisionId: string, snapshotHash: string) {
    if (job.market && (!run.dataset_id || !run.data_epoch || run.snapshot_hash !== snapshotHash)) {
      throw new Error("DATA_SNAPSHOT_MISMATCH");
    }
    await this.update(job.id, {
      status: "RUNNING", runId: run.run_id, strategyRevisionId, snapshotHash,
      datasetId: job.market ? run.dataset_id! : job.datasetId, dataEpoch: job.market ? run.data_epoch! : job.dataEpoch,
    });
  }

  resume(id: string, retry = false): void {
    const job = this.state.jobs.find(item => item.id === id);
    if (!job || job.status === "COMPLETED") return;
    if (!job.runId && (!job.market || !job.preparation || !this.manager.observeResearchPreparation)) return;
    this.enqueue(id, async () => {
      let expected = job;
      if (!expected.runId && job.market && job.preparation && this.manager.observeResearchPreparation) {
        await this.update(id, { status: "PREPARING", error: null });
        if (this.closed) return;
        const receipt = await this.manager.observeResearchPreparation(job.preparation.id, job.market.scope, retry,
          progress => this.preparationProgress(id, progress));
        const run = receipt.result?.strategy_run;
        const resolution = receipt.result?.resolution;
        const revision = (receipt.request.intent.strategy as { strategy_revision_id?: unknown } | undefined)?.strategy_revision_id;
        if (!run || !resolution || resolution.status !== "READY" || typeof revision !== "string"
          || !resolution.snapshot_hash || run.dataset_id !== resolution.dataset_id || run.data_epoch !== resolution.data_epoch) {
          throw new Error("STRATEGY_PREPARATION_IDENTITY_MISMATCH");
        }
        await this.recordRun(job, run, revision, resolution.snapshot_hash);
        expected = this.state.jobs.find(item => item.id === id) ?? job;
      }
      const runId = expected.runId;
      if (!runId || this.closed) return;
      await this.update(id, { status: "RUNNING", error: null });
      const result = await this.manager.restoreRun(runId);
      if (result.run.run_id !== runId || result.run.dataset_id !== expected.datasetId || result.run.data_epoch !== expected.dataEpoch
        || result.run.snapshot_hash !== expected.snapshotHash
        || result.config.strategy_revision_id !== expected.strategyRevisionId) throw new Error("DATA_SNAPSHOT_MISMATCH");
      await this.update(id, { status: "COMPLETED" });
    });
  }

  async submit(request: ChartStrategyRunRequest, datasets: readonly LocalDatasetManifest[],
    markets: readonly ResearchMarketInput[] = []): Promise<void> {
    if (this.closed || this.state.storageFailed) throw new Error("RESEARCH_BATCH_STORAGE_UNAVAILABLE");
    const inputCount = datasets.length + markets.length;
    if (inputCount < (markets.length ? 1 : 2) || inputCount > RESEARCH_BATCH_MAX_INPUTS || this.state.jobs.length + inputCount > maxJobs
      || new Set(datasets.map(dataset => dataset.dataset_id)).size !== datasets.length
      || new Set(markets.map(marketInputKey)).size !== markets.length) throw new Error("RESEARCH_BATCH_CAPACITY");
    if (datasets.some(dataset => !supportsBatchSource(dataset, request.attachment.fidelityPreference === "PRECISE"))
      || markets.some(market => !validMarketInput(market))
      || request.attachment.pythonBarExecution
      || (request.language === "python" && !request.pythonTrustedConfirmed)) throw new Error("RESEARCH_BATCH_UNSUPPORTED");
    const captured = structuredClone(request);
    const batchId = crypto.randomUUID();
    const newJob = (fields: Pick<ResearchBatchJob, "datasetName" | "datasetId" | "dataEpoch" | "interval" | "startMs" | "endMs">): ResearchBatchJob => ({
      ...fields, id: crypto.randomUUID(), batchId, name: captured.displayName, draftId: captured.draftId,
      draftContentRevision: captured.draftContentRevision, status: "QUEUED", runId: null, strategyRevisionId: null, snapshotHash: null, error: null,
    });
    const imported = datasets.map(dataset => {
      const { startMs, endMs } = importedResearchRange(dataset, captured.attachment);
      return { job: newJob({ datasetName: dataset.name, datasetId: dataset.dataset_id, dataEpoch: dataset.data_epoch,
        interval: dataset.interval, startMs, endMs }), dataset: structuredClone(dataset) };
    });
    const exchange = markets.map(({ session, startMs, endMs }) => {
      const job = newJob({ datasetName: `${session.exchange} · ${session.marketType} · ${session.symbol}`,
        datasetId: "", dataEpoch: "", interval: session.interval, startMs, endMs });
      const scope = `${captured.cellScope}:batch:${job.id}`;
      job.market = { ...session, scope };
      const input: ChartStrategyRunRequest = {
        ...captured, session: { ...session }, cellScope: scope,
        attachment: { ...captured.attachment, rangeMode: "CUSTOM", customRange: { startMs, endMs } },
      };
      return { job, input };
    });
    const jobs = [...imported.map(task => task.job), ...exchange.map(task => task.job)];
    this.publish({ ...this.state, jobs: [...this.state.jobs, ...jobs] });
    try { await this.persist(jobs); }
    catch (error) {
      this.publish({ ...this.state, jobs: this.state.jobs.filter(job => job.batchId !== batchId) });
      throw error;
    }
    for (const { job, dataset } of imported) this.enqueue(job.id, () => this.execute(job,
      { ...captured, cellScope: `${captured.cellScope}:batch:${job.id}` }, importedResearchRunSource(dataset, captured.attachment)));
    for (const { job, input } of exchange) this.enqueue(job.id, () => this.execute(job, input,
      { kind: "MARKET_HISTORY", endTimeMsExclusive: job.endMs }));
  }

  private async execute(job: ResearchBatchJob, request: ChartStrategyRunRequest, source: ResearchRunSource): Promise<void> {
    await this.update(job.id, { status: "PREPARING" });
    if (this.closed) return;
    const result = await this.manager.runResearch({
      request, source,
      ...(job.market ? { onPreparation: (progress: PreparationJob) => this.preparationProgress(job.id, progress) } : {}),
      onRunCreated: (run, identity) => this.recordRun(job, run, identity.strategyRevisionId, identity.snapshotHash),
    });
    if (result.kind !== "TERMINAL") {
      const warning = result.resolution.quality_warnings[0];
      throw new Error(warning ? `${warning.code}: ${warning.message}` : result.resolution.status);
    }
    if (job.market && !this.state.jobs.find(item => item.id === job.id)?.runId) throw new Error("DATA_SNAPSHOT_MISMATCH");
    await this.update(job.id, { status: "COMPLETED" });
  }

  dispose(): void {
    this.closed = true;
    this.queue.length = 0;
    this.listeners.clear();
  }
}
