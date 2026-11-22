import assert from "node:assert/strict";
import test from "node:test";
import { buildResearchExperimentMembers } from "../../backtest/chart-tester/chartStrategyRunRequest.js";
import type { ChartStrategyRunRequest } from "../../backtest/chart-tester/chartStrategyTesterUiModel.js";
import type { StrategyRevisionRecord } from "../../backtest/backtestApi.js";
import type { StrategyExperiment } from "../../backtest/experiment/strategyExperiment.js";
import type { LocalDatasetManifest } from "../../local-data/localDataTypes.js";
import { ResearchExperiments } from "../researchExperiments.js";

const HOUR = 3_600_000;
const START = Date.UTC(2026, 10, 20);

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

const revision = { revision_id: "srv2_batch", output_modes: ["TARGET_POSITION"] } as unknown as StrategyRevisionRecord;

test("one strategy revision serves every member: exchange history prepares, imported data runs its snapshot", async () => {
  const calls: string[] = [];
  const market = { session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" }, startMs: START, endMs: START + 6 * HOUR };
  const imported = dataset("a");
  const { members } = await buildResearchExperimentMembers({
    api: {
      async createStrategyRevision(body) { calls.push(`revision ${String(body.language)}`); return revision; },
      async previewSnapshot(body) {
        calls.push(`preview ${body.dataset_id}`);
        return { data_epoch: body.data_epoch, snapshot_hash: "sha256:" + "c".repeat(64), coverage_start_ms: body.start_time_ms,
          coverage_end_ms: body.end_time_ms, row_count: 4, fidelity_capabilities: ["BAR_APPROX"] } as never;
      },
      async smokeStrategyRevision(revisionId, body) { calls.push(`smoke ${revisionId} ${String(body.dataset_id)}`); return {} as never; },
      async validate() { calls.push("validate"); return {} as never; },
    },
    request: request(),
    inputs: [
      { input: { kind: "EXCHANGE_SERIES" }, source: { kind: "MARKET_HISTORY", ...market } },
      { input: { kind: "IMPORTED_DATASET" }, source: { kind: "IMPORTED_DATASET", datasetId: imported.dataset_id, dataEpoch: imported.data_epoch,
        interval: "1m", symbol: "a", startTimeMs: 0, endTimeMs: 240_000, quality: { status: "ok", rows: 4, excludedRangeCount: 0, volumeAvailable: true } } as never },
    ],
  });
  assert.deepEqual(calls, ["revision PYTHON_EDITOR", "preview local-a", "smoke srv2_batch local-a", "validate"],
    "one revision; each imported snapshot is smoked and validated before the experiment, as a single run is");
  const preparation = members[0]!.preparation as { context: Record<string, unknown>; strategy: Record<string, unknown> };
  assert.deepEqual([preparation.context.symbol, preparation.context.range_mode, preparation.context.start_time_ms, preparation.context.end_time_ms],
    ["BTCUSDT", "CUSTOM", START, START + 6 * HOUR - 1], "the range is the input's, with an inclusive end on the wire");
  assert.equal(preparation.strategy.strategy_revision_id, "srv2_batch");
  assert.equal(preparation.strategy.python_trusted_confirmed, true);
  const run = members[1]!.run as Record<string, unknown>;
  assert.deepEqual([run.dataset_id, run.snapshot_hash, run.strategy_revision_id, run.exchange], ["local-a", "sha256:" + "c".repeat(64), "srv2_batch", "local"]);
  assert.deepEqual(members.map((member) => member.input), [{ kind: "EXCHANGE_SERIES" }, { kind: "IMPORTED_DATASET" }]);
});

function experiment(id: string, terminal: boolean, createdAtMs = 1): StrategyExperiment {
  return { experimentId: id, name: "SMA", kind: "INPUTS", strategy: {}, createdAtMs, cancelledAtMs: null,
    state: terminal ? "COMPLETED" : "RUNNING", terminal, counts: { total: 1, completed: terminal ? 1 : 0, failed: 0, cancelled: 0, active: terminal ? 0 : 1 },
    members: [], study: null };
}

test("the page lists experiments, follows the running ones, and builds inputs from its sources", async () => {
  const watched: string[] = [];
  const created: Array<{ request: ChartStrategyRunRequest; inputs: readonly { input: Record<string, unknown> }[] }> = [];
  const robust: Array<{ request: ChartStrategyRunRequest; dataset: Record<string, unknown>; fields: Record<string, unknown> }> = [];
  const owner = new ResearchExperiments({
    async listExperiments() { return [experiment("ex_done", true, 2), experiment("ex_running", false, 1)]; },
    watchExperiment(id) { watched.push(id); return new Promise(() => undefined); },
    async createResearchExperiment(input) { created.push(input); return experiment("ex_new", false, 3); },
    async cancelExperiment(id) { return { ...experiment(id, true), state: "CANCELLED" }; },
    async retryExperimentMember(id) { return experiment(id, false); },
    async createRobustnessExperiment(input) { robust.push(input); return { ...experiment("ex_robust", false, 4), kind: "ROBUSTNESS" }; },
    async revealExperimentHoldout(id) { return experiment(id, false, 5); },
  });
  owner.start();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(owner.snapshot().experiments.map((item) => item.experimentId), ["ex_done", "ex_running"]);
  assert.deepEqual(watched, ["ex_running"], "only a running experiment is followed");
  const draft = request();
  await owner.submit(draft, [dataset("a")], [{ session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" },
    startMs: START, endMs: START + 6 * HOUR }]);
  draft.attachment.parameters.size = 99;
  assert.equal(created[0]!.request.attachment.parameters.size, 3, "the submitted request is a copy");
  assert.deepEqual(created[0]!.inputs.map((item) => item.input.kind), ["IMPORTED_DATASET", "EXCHANGE_SERIES"]);
  assert.deepEqual(owner.snapshot().experiments.map((item) => item.experimentId), ["ex_new", "ex_done", "ex_running"]);
  assert.deepEqual(watched, ["ex_running", "ex_new"]);
  await owner.submitRobustness(draft, dataset("a"), { start_ms: 0, end_ms: 240_000, hypothesis: "h" });
  assert.deepEqual(robust[0]!.dataset, { dataset_id: "local-a", data_epoch: "epoch-a", interval: "1m" });
  assert.deepEqual(watched.slice(-1), ["ex_robust"], "a robustness check is followed like any running experiment");
  await owner.revealHoldout("ex_robust");
  assert.equal(owner.snapshot().experiments[0]!.experimentId, "ex_robust");
  await owner.cancel("ex_running");
  assert.equal(owner.snapshot().experiments.find((item) => item.experimentId === "ex_running")?.state, "CANCELLED");
  await assert.rejects(owner.submit(draft, [dataset("a")]), /RESEARCH_BATCH_UNSUPPORTED/, "one imported dataset alone is not a batch");
  await assert.rejects(owner.submit({ ...draft, pythonTrustedConfirmed: false }, [], [{ session: { exchange: "binance", marketType: "spot",
    symbol: "BTCUSDT", interval: "1m" }, startMs: START, endMs: START + HOUR }]), /RESEARCH_BATCH_UNSUPPORTED/);
  owner.dispose();
});
