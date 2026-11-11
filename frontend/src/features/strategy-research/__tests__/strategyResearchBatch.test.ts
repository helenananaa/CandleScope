import assert from "node:assert/strict";
import test from "node:test";
import type { StrategyStorage } from "../../../shared/strategyStorage.js";
import type { ChartStrategyRunOutcome } from "../../backtest/chart-tester/chartStrategyRunRequest.js";
import type { ChartStrategyRunRequest } from "../../backtest/chart-tester/chartStrategyTesterUiModel.js";
import type { ResultProjectionIdentity } from "../../backtest/chart-tester/chartStrategyTesterState.js";
import type { BacktestRunRecord } from "../../backtest/backtestTypes.js";
import type { LocalDatasetManifest } from "../../local-data/localDataTypes.js";
import type { StrategyDataManager } from "../../market-data/manager/strategyDataManager.js";
import { StrategyResearchBatch } from "../strategyResearchBatch.js";

function memory(): StrategyStorage {
  const values = new Map<string, string>();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value); } };
}
function dataset(id: string): LocalDatasetManifest {
  return { schema_version: 1, dataset_id: `local-${id}`, data_epoch: `epoch-${id}`, name: `Data ${id}`,
    source: "local_dataset", symbol: id, interval: "1m", volume_available: true, timezone: "UTC",
    timestamp_semantics: "bar_open", rows: 4, first_open_ms: 0, last_open_ms: 180000, all_rows_final: true,
    excluded_range_count: 0, sqlite_sha256: "fixture", imported_at: "2026-11-07T00:00:00Z" };
}
function request(): ChartStrategyRunRequest {
  return { cellScope: "research", session: { exchange: "local", marketType: "spot", symbol: "a", interval: "1m" },
    draftId: "draft", draftContentRevision: 7, displayName: "SMA", language: "python", pythonTrustedConfirmed: true,
    source: "original source", attachment: { schemaVersion: 1, strategyDraftId: "draft", strategyRevisionId: null,
      displayName: "SMA", language: "python", parameters: { size: 3 }, rangeMode: "ALL_AVAILABLE", customRange: null,
      fidelityPreference: "FAST", quickPresetId: "CRYPTO_SPOT_STANDARD_V1", autoRun: false } };
}
function dataRun(id: string, source: LocalDatasetManifest): BacktestRunRecord {
  return { run_id: `bt_${id}`, state: "RUNNING", dataset_id: source.dataset_id, data_epoch: source.data_epoch,
    snapshot_hash: `snapshot-${id}`, config_hash: "config", source_event_kind: "BAR", fidelity_mode: "BAR_APPROX" };
}
async function waitFor(predicate: () => boolean) {
  const deadline = Date.now() + 3000;
  while (!predicate()) {
    assert.ok(Date.now() < deadline, "timed out waiting for batch state");
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}
const done = { kind: "TERMINAL" } as ChartStrategyRunOutcome;

test("batch captures each source and strategy before queuing and isolates job completion and failure", async () => {
  const inputs = [dataset("a"), dataset("b"), dataset("c")];
  const draft = request();
  const storage = memory();
  const pending = new Map<string, () => void>();
  const seen: Array<Parameters<StrategyDataManager["runResearch"]>[0]> = [];
  let active = 0, maxActive = 0;
  const owner = new StrategyResearchBatch({
    async runResearch(input) {
      const selected = input.source;
      assert.equal(selected.kind, "IMPORTED_DATASET");
      seen.push(input);
      const source = inputs.find(item => item.dataset_id === selected.datasetId)!;
      const id = source.symbol;
      active += 1;
      maxActive = Math.max(maxActive, active);
      try {
        if (id === "b") throw new Error("fixture preparation failure");
        await input.onRunCreated?.(dataRun(id, source), { strategyRevisionId: `revision-${id}`, snapshotHash: `snapshot-${id}` } as ResultProjectionIdentity);
        await new Promise<void>(resolve => pending.set(id, resolve));
        return done;
      } finally {
        active -= 1;
      }
    },
    async restoreRun() { throw new Error("unexpected restore"); },
  }, storage);
  await owner.submit(draft, inputs);
  draft.source = "edited later";
  draft.attachment.parameters.size = 99;
  await waitFor(() => pending.size === 2);
  assert.equal(maxActive, 2);
  for (const input of seen) {
    assert.equal(input.request.source, "original source");
    assert.equal(input.request.attachment.parameters.size, 3);
    assert.notEqual(input.request.cellScope, draft.cellScope);
  }
  pending.forEach(resolve => resolve());
  await waitFor(() => owner.snapshot().jobs.filter(job => job.status === "COMPLETED").length === 2);
  assert.deepEqual(owner.snapshot().jobs.map(job => [job.datasetId, job.status, job.runId, job.snapshotHash]), [
    ["local-a", "COMPLETED", "bt_a", "snapshot-a"], ["local-b", "FAILED", null, null], ["local-c", "COMPLETED", "bt_c", "snapshot-c"],
  ]);
  const raw = storage.getItem("candlescope:strategy-research-batch:v1")!;
  assert.doesNotMatch(raw, /original source|pythonTrustedConfirmed/);
  owner.dispose();
});

test("restart follows a saved run and never recreates a task with an unknown outcome", async () => {
  const source = dataset("a");
  const storage = memory();
  const base = { batchId: "batch", name: "SMA", datasetName: source.name, draftId: "draft", draftContentRevision: 7,
    datasetId: source.dataset_id, dataEpoch: source.data_epoch, interval: "1m", startMs: 0, endMs: 180001, error: null };
  storage.setItem("candlescope:strategy-research-batch:v1", JSON.stringify({ schema: 1, jobs: [
    { ...base, id: "one", status: "RUNNING", runId: "bt_a", strategyRevisionId: "revision-a", snapshotHash: "snapshot-a" },
    { ...base, id: "two", status: "PREPARING", runId: null, strategyRevisionId: null, snapshotHash: null },
  ] }));
  const restored: string[] = [];
  const owner = new StrategyResearchBatch({
    async runResearch() { assert.fail("must not recreate a run"); },
    async restoreRun(id) {
      restored.push(id);
      return { run: { ...dataRun("a", source), state: "COMPLETED" }, config: { start_time_ms: 0, end_time_ms: 180001, strategy_revision_id: "revision-a" } };
    },
  }, storage);
  owner.start();
  owner.start();
  await waitFor(() => owner.snapshot().jobs.every(job => ["COMPLETED", "INTERRUPTED"].includes(job.status)));
  assert.deepEqual(restored, ["bt_a"]);
  assert.equal(owner.snapshot().jobs[1]?.status, "INTERRUPTED");
  owner.dispose();
});

test("batch submission performs no run when its initial durable write fails", async () => {
  const owner = new StrategyResearchBatch({
    async runResearch() { assert.fail("must not launch without a persisted task"); },
    async restoreRun() { assert.fail("must not restore"); },
  }, { getItem: () => null, setItem: () => { throw new Error("storage full"); } });
  await assert.rejects(owner.submit(request(), [dataset("a"), dataset("b")]), /storage full/);
  assert.deepEqual(owner.snapshot(), { jobs: [], storageFailed: true });
  owner.dispose();
});

test("precise batches keep each trade dataset's declared range and reject BAR-only inputs", async () => {
  const trades = (id: string, startMs: number, endMs: number): LocalDatasetManifest => ({
    ...dataset(id),
    source: "user_market_trades",
    first_open_ms: startMs,
    last_open_ms: endMs - 60000,
    market_trade_input: {
      schema_version: 1, kind: "MARKET_TRADE", timestamp_unit: "ms", timezone: "UTC",
      coverage_start_ms: startMs, coverage_end_ms_exclusive: endMs,
      sequence_policy: "CONTIGUOUS_SOURCE_SEQUENCE", row_count: 8,
    },
  });
  const a = trades("trades-a", 60000, 240000);
  const b = trades("trades-b", 120000, 360000);
  const bar = dataset("bars");
  const storage = memory();
  const seen: Array<[string, string, number, number, string, boolean | undefined]> = [];
  const owner = new StrategyResearchBatch({
    async runResearch({ source, request: selected, onRunCreated }) {
      assert.equal(source.kind, "IMPORTED_DATASET");
      const manifest = [a, b, bar].find(item => item.dataset_id === source.datasetId)!;
      seen.push([source.datasetId, source.dataEpoch, source.startTimeMs, source.endTimeMs,
        selected.attachment.fidelityPreference, source.marketTradeInput]);
      const run = dataRun(manifest.symbol, manifest);
      await onRunCreated?.(run, {
        strategyRevisionId: "revision", snapshotHash: run.snapshot_hash,
      } as ResultProjectionIdentity);
      return done;
    },
    async restoreRun() { assert.fail("must not recreate completed runs"); },
  }, storage);
  const draft = request();
  draft.attachment.fidelityPreference = "PRECISE";
  await assert.rejects(owner.submit(draft, [a, bar]), /RESEARCH_BATCH_UNSUPPORTED/);
  assert.deepEqual(owner.snapshot().jobs, []);
  await owner.submit(draft, [a, b]);
  draft.attachment.fidelityPreference = "FAST";
  await owner.submit(draft, [a, bar]);
  await waitFor(() => owner.snapshot().jobs.every(job => job.status === "COMPLETED"));
  assert.deepEqual(seen, [
    [a.dataset_id, a.data_epoch, 60000, 239999, "PRECISE", true],
    [b.dataset_id, b.data_epoch, 120000, 359999, "PRECISE", true],
    [a.dataset_id, a.data_epoch, 60000, 180001, "FAST", true],
    [bar.dataset_id, bar.data_epoch, 0, 180001, "FAST", false],
  ]);
  const reopened = new StrategyResearchBatch({
    async runResearch() { assert.fail("must not recreate completed runs"); },
    async restoreRun() { assert.fail("must not restore already completed jobs"); },
  }, storage);
  reopened.start();
  assert.deepEqual(reopened.snapshot().jobs.slice(0, 2).map(job => [job.endMs, job.status, job.dataEpoch]), [
    [240000, "COMPLETED", a.data_epoch], [360000, "COMPLETED", b.data_epoch],
  ]);
  owner.dispose();
  reopened.dispose();
});

test("mixed market preparation saves progress and reconnects to the original failed job after restart", async () => {
  const local = dataset("a");
  const prepared = { ...dataset("exchange"), data_epoch: "fixed-epoch" };
  const startMs = Date.UTC(2026, 0, 1), endMs = startMs + 5 * 60_000;
  const market = { session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "5m" }, startMs, endMs };
  const storage = memory();
  const id = "c".repeat(32);
  const revision = "revision-exchange";
  const run = dataRun("exchange", prepared);
  const progress = (scope: string, ready = false): import("../../data-preparation/api.js").PreparationJob => ({
    id, state: ready ? "READY" : "FAILED", stage: ready ? "READY" : "ACQUIRING",
    completed: ready ? 4 : 2, total: 4, revision: ready ? 6 : 3, cancel_requested: false,
    request: { consumer: "STRATEGY", requirements: [{ symbol: "BTCUSDT" }],
      intent: { strategy: { chart_cell_scope: scope, strategy_revision_id: revision } } },
    result: ready ? { strategy_run: run, resolution: {
      status: "READY", dataset_id: prepared.dataset_id, data_epoch: prepared.data_epoch, snapshot_hash: run.snapshot_hash,
    } as import("../../backtest/backtestApi.js").ChartContextResolution } : null,
    error: ready ? null : { code: "SOURCE_TEMPORARY", message: "Source temporarily unavailable", retryable: true },
  });
  const owner = new StrategyResearchBatch({
    async runResearch(input) {
      if (input.source.kind === "IMPORTED_DATASET") {
        await input.onRunCreated?.(dataRun("a", local), { strategyRevisionId: "revision-a", snapshotHash: "snapshot-a" } as ResultProjectionIdentity);
        return done;
      }
      assert.deepEqual(input.source, { kind: "MARKET_HISTORY", endTimeMsExclusive: endMs });
      assert.deepEqual(input.request.session, market.session);
      assert.deepEqual(input.request.attachment.customRange, { startMs, endMs });
      assert.equal(input.request.attachment.parameters.size, 3);
      await input.onPreparation?.(progress(input.request.cellScope));
      throw new Error("Source temporarily unavailable");
    },
    async restoreRun() { assert.fail("must not restore a run before preparation"); },
  }, storage);
  await owner.submit(request(), [local], [market]);
  await waitFor(() => owner.snapshot().jobs[0]?.status === "COMPLETED" && owner.snapshot().jobs[1]?.status === "FAILED");
  const failed = owner.snapshot().jobs[1]!;
  assert.equal(failed.preparation?.id, id);
  assert.equal(failed.preparation?.completed, 2);
  assert.equal(failed.preparation?.retryable, true);
  owner.dispose();

  const restored = new StrategyResearchBatch({
    async runResearch() { assert.fail("must not launch a second preparation"); },
    async observeResearchPreparation(jobId, scope, retry, onProgress) {
      assert.equal(jobId, id);
      assert.equal(scope, failed.market?.scope);
      assert.equal(retry, true);
      const ready = progress(scope, true);
      await onProgress(ready);
      return ready;
    },
    async restoreRun(runId) {
      assert.equal(runId, run.run_id);
      return { run: { ...run, state: "COMPLETED" }, config: { strategy_revision_id: revision, start_time_ms: startMs, end_time_ms: endMs - 1 } };
    },
  }, storage);
  restored.start();
  restored.resume(failed.id, true);
  await waitFor(() => restored.snapshot().jobs[1]?.status === "COMPLETED");
  const result = restored.snapshot().jobs[1]!;
  assert.equal(result.datasetId, prepared.dataset_id);
  assert.equal(result.dataEpoch, prepared.data_epoch);
  assert.equal(result.snapshotHash, run.snapshot_hash);
  assert.equal(result.preparation?.id, id);
  restored.dispose();
});
