import assert from "node:assert/strict";
import test from "node:test";
import { buildRobustnessStudy } from "../../backtest/chart-tester/chartStrategyRunRequest.js";
import type { ChartStrategyRunRequest } from "../../backtest/chart-tester/chartStrategyTesterUiModel.js";
import type { SnapshotPreviewRequest, StrategyRevisionRecord } from "../../backtest/backtestApi.js";
import { RobustnessFormError, defaultRobustnessForm, robustnessPlan, robustnessStudyFields, studyRange } from "../researchRobustness.js";

const DAY = 86_400_000;
const START = Date.UTC(2024, 0, 1);
const daily = { interval: "1d", first_open_ms: START, last_open_ms: START + 199 * DAY };

test("a study covers whole bars of the research range, ending at the last bar's close", () => {
  assert.deepEqual(studyRange(daily, { startMs: START, endMs: daily.last_open_ms + 1 }),
    { startMs: START, endMs: START + 200 * DAY, intervalMs: DAY, bars: 200 });
  assert.deepEqual(studyRange(daily, { startMs: START + 1, endMs: START + 50 * DAY }),
    { startMs: START + DAY, endMs: START + 50 * DAY, intervalMs: DAY, bars: 49 }, "a partial first bar is left out");
  assert.equal(studyRange({ ...daily, interval: "1M" }, { startMs: START, endMs: START + DAY }), null, "months have no fixed length");
});

test("the form starts from today's parameters and plans folds the way the study will", () => {
  const range = studyRange(daily, { startMs: START, endMs: daily.last_open_ms + 1 })!;
  const form = defaultRobustnessForm(range, { fast: 3, label: "x", __pineInputs: {} });
  assert.deepEqual(JSON.parse(form.space), { fast: [3], label: ["x"] });
  assert.deepEqual([form.trainBars, form.testBars, form.stepBars, form.holdoutBars], [120, 40, 40, 0]);
  const custom = { ...form, hypothesis: " a faster SMA survives ", space: '{"fast": [2, 3, 5]}', trainBars: 110, testBars: 40,
    stepBars: 40, holdoutBars: 10, candidates: 2 };
  assert.deepEqual(robustnessPlan(custom, range), { folds: 2, candidates: 2, runs: 7 });
  const fields = robustnessStudyFields(custom, range);
  assert.deepEqual([fields.hypothesis, fields.parameter_space, fields.train_ms, fields.test_ms, fields.step_ms, fields.holdout_ms,
    fields.start_ms, fields.end_ms, fields.candidate_budget, fields.seed],
    ["a faster SMA survives", { fast: [2, 3, 5] }, 110 * DAY, 40 * DAY, 40 * DAY, 10 * DAY, START, START + 200 * DAY, 2, 24]);
  const refused = (change: Partial<typeof custom>) => {
    try { robustnessStudyFields({ ...custom, ...change }, range); } catch (error) { return (error as RobustnessFormError).key; }
    return null;
  };
  assert.equal(refused({ hypothesis: " " }), "researchRobustness.needHypothesis");
  assert.equal(refused({ space: '{"fast": []}' }), "researchRobustness.invalidSpace");
  assert.equal(refused({ space: '{"fast": [{"nested": 1}]}' }), "researchRobustness.invalidSpace");
  assert.equal(refused({ stepBars: 20 }), "researchRobustness.invalidWindows", "test windows never overlap");
  assert.equal(refused({ trainBars: 180 }), "researchRobustness.tooShort");
  assert.equal(refused({ advanced: '{"strategy_revision_id": "x"}' }), "researchRobustness.invalidAdvanced",
    "the strategy and data are the workspace's");
});

function request(language: "python" | "pine" = "python", trusted = true): ChartStrategyRunRequest {
  return { cellScope: "research", session: { exchange: "local", marketType: "spot", symbol: "BTCUSDT", interval: "1d" },
    draftId: "draft", draftContentRevision: 3, displayName: "SMA", language, pythonTrustedConfirmed: trusted,
    source: "class Strategy: ...", attachment: { schemaVersion: 1, strategyDraftId: "draft", strategyRevisionId: null,
      displayName: "SMA", language, parameters: { fast: 3 }, rangeMode: "ALL_AVAILABLE", customRange: null,
      fidelityPreference: "FAST", quickPresetId: "CRYPTO_SPOT_STANDARD_V1", autoRun: false } };
}

test("a robustness study freezes the Python strategy once and needs the data's contract history", async () => {
  const calls: unknown[] = [];
  let contract = "complete";
  const api = {
    async createStrategyRevision(body: { language: string }) {
      calls.push({ revision: body.language });
      return { revision_id: "srv2_robust", output_modes: ["TARGET_POSITION", "SIGNAL"] } as unknown as StrategyRevisionRecord;
    },
    async previewSnapshot(body: SnapshotPreviewRequest) {
      calls.push(body);
      return { data_epoch: "epoch-a", snapshot_hash: "sha256:" + "d".repeat(64), quality: { contract_data: { status: contract } } } as never;
    },
  };
  const dataset = { dataset_id: "local-a", data_epoch: "epoch-a", interval: "1d" };
  const fields = { start_ms: START, end_ms: START + 200 * DAY, hypothesis: "h" };
  const { study } = await buildRobustnessStudy({ api, request: request(), dataset, fields });
  assert.deepEqual(calls[1], { dataset_id: "local-a", data_epoch: "epoch-a", start_time_ms: START, end_time_ms: START + 200 * DAY - 1,
    interval: "1d", fidelity_mode: "BAR_APPROX", contract_data_mode: "HISTORICAL_CONTRACT_V1",
    account_model: "LINEAR_PERP_ONE_WAY_V2", funding_mode: "OFF" });
  assert.deepEqual([study.strategy_revision_id, study.dataset_snapshot_hash, study.parameters, study.python_runtime_mode,
    study.python_trusted_confirmed], ["srv2_robust", "sha256:" + "d".repeat(64), { fast: 3 }, "TRUSTED_LOCAL", true]);
  contract = "missing";
  await assert.rejects(buildRobustnessStudy({ api, request: request(), dataset, fields }), /CONTRACT_DATA_REQUIRED|contract/);
  await assert.rejects(buildRobustnessStudy({ api, request: request("pine"), dataset, fields }), /Python/);
  await assert.rejects(buildRobustnessStudy({ api, request: request("python", false), dataset, fields }), /Confirm/);
});
