import { chartStrategyRunDiagnostics, qualitySummaryFromImportedManifest, type ResearchRunSource } from "../backtest/chart-tester/chartStrategyRunRequest.js";
import type { ChartStrategyResultBundle } from "../backtest/chart-tester/chartStrategyResultCache.js";
import type { ChartStrategyRunRequest } from "../backtest/chart-tester/chartStrategyTesterUiModel.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import type { StrategyStorage } from "../../shared/strategyStorage.js";

const storageKey = "candlescope:strategy-research-batch:v1";
const statuses = ["QUEUED", "PREPARING", "RUNNING", "COMPLETED", "FAILED", "INTERRUPTED"] as const;
const maxJobs = 64;
export const RESEARCH_BATCH_MAX_INPUTS = 8;

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
      || (job.status === "COMPLETED" && !job.runId)
      || (job.runId !== null && (!/^bt_[\w-]{1,128}$/.test(job.runId) || !job.strategyRevisionId || !job.snapshotHash))) {
      throw new Error("RESEARCH_BATCH_STORAGE_INVALID");
    }
    ids.add(job.id);
  }
  return payload.jobs;
}

function importedSource(dataset: LocalDatasetManifest, request: ChartStrategyRunRequest): Extract<ResearchRunSource, { kind: "IMPORTED_DATASET" }> {
  return {
    kind: "IMPORTED_DATASET",
    datasetId: dataset.dataset_id,
    dataEpoch: dataset.data_epoch,
    interval: dataset.interval,
    symbol: dataset.symbol,
    startTimeMs: request.attachment.customRange?.startMs ?? dataset.first_open_ms,
    endTimeMs: request.attachment.customRange?.endMs ?? dataset.last_open_ms + 1,
    quality: qualitySummaryFromImportedManifest({
      rows: dataset.rows, excludedRangeCount: dataset.excluded_range_count, volumeAvailable: dataset.volume_available,
    }),
  };
}

type BatchManager = Pick<StrategyDataManager, "runResearch"> & {
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
      if (job.runId) this.resume(job.id);
      else void this.update(job.id, { status: "INTERRUPTED" });
    }
  }

  resume(id: string): void {
    const job = this.state.jobs.find(item => item.id === id);
    if (!job?.runId || job.status === "COMPLETED") return;
    const runId = job.runId;
    this.enqueue(id, async () => {
      await this.update(id, { status: "RUNNING", error: null });
      if (this.closed) return;
      const result = await this.manager.restoreRun(runId);
      if (result.run.run_id !== runId || result.run.dataset_id !== job.datasetId || result.run.data_epoch !== job.dataEpoch
        || result.run.snapshot_hash !== job.snapshotHash
        || result.config.strategy_revision_id !== job.strategyRevisionId) throw new Error("DATA_SNAPSHOT_MISMATCH");
      await this.update(id, { status: "COMPLETED" });
    });
  }

  async submit(request: ChartStrategyRunRequest, datasets: readonly LocalDatasetManifest[]): Promise<void> {
    if (this.closed || this.state.storageFailed) throw new Error("RESEARCH_BATCH_STORAGE_UNAVAILABLE");
    if (datasets.length < 2 || datasets.length > RESEARCH_BATCH_MAX_INPUTS || this.state.jobs.length + datasets.length > maxJobs
      || new Set(datasets.map(dataset => dataset.dataset_id)).size !== datasets.length) throw new Error("RESEARCH_BATCH_CAPACITY");
    if (request.attachment.fidelityPreference !== "FAST" || request.attachment.pythonBarExecution
      || (request.language === "python" && !request.pythonTrustedConfirmed)) throw new Error("RESEARCH_BATCH_UNSUPPORTED");
    const captured = structuredClone(request);
    const batchId = crypto.randomUUID();
    const tasks = datasets.map(dataset => {
      const source = importedSource(dataset, captured);
      const job: ResearchBatchJob = { id: crypto.randomUUID(), batchId, name: captured.displayName, datasetName: dataset.name,
        draftId: captured.draftId, draftContentRevision: captured.draftContentRevision, datasetId: source.datasetId, dataEpoch: source.dataEpoch,
        interval: source.interval, startMs: source.startTimeMs, endMs: source.endTimeMs, status: "QUEUED", runId: null,
        strategyRevisionId: null, snapshotHash: null, error: null };
      return { job, source, first: dataset.first_open_ms, last: dataset.last_open_ms };
    });
    const jobs = tasks.map(task => task.job);
    this.publish({ ...this.state, jobs: [...this.state.jobs, ...jobs] });
    try { await this.persist(jobs); }
    catch (error) {
      this.publish({ ...this.state, jobs: this.state.jobs.filter(job => job.batchId !== batchId) });
      throw error;
    }
    for (const { job, source, first, last } of tasks) this.enqueue(job.id, async () => {
      if (source.startTimeMs < first || source.endTimeMs > last + 1) throw new Error("DATA_COVERAGE_INCOMPLETE");
      await this.update(job.id, { status: "PREPARING" });
      if (this.closed) return;
      const result = await this.manager.runResearch({
        request: { ...captured, cellScope: `${captured.cellScope}:batch:${job.id}` },
        source,
        onRunCreated: (run, identity) => this.update(job.id, {
          status: "RUNNING", runId: run.run_id, strategyRevisionId: identity.strategyRevisionId, snapshotHash: identity.snapshotHash,
        }),
      });
      if (result.kind !== "TERMINAL") throw new Error(result.resolution.status);
      await this.update(job.id, { status: "COMPLETED" });
    });
  }

  dispose(): void {
    this.closed = true;
    this.queue.length = 0;
    this.listeners.clear();
  }
}
