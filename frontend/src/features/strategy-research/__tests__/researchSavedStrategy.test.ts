import assert from "node:assert/strict";
import test from "node:test";
import type { StrategyRevisionRecord } from "../../backtest/backtestApi.js";
import { BUILTIN_RSI_REVISION, defaultParameters } from "../../backtest/builtinTemplate.js";
import { DEFAULT_STRATEGY_RUN_SETTINGS } from "../../../shared/strategyRunSettings.js";
import { StrategyDataManager, type StrategyDataApi } from "../../market-data/manager/strategyDataManager.js";

const source = { kind: "IMPORTED_DATASET" as const, datasetId: "local-a", dataEpoch: "epoch-a", interval: "1d", symbol: "BTCUSDT",
  startTimeMs: 0, endTimeMs: 200 * 86_400_000, quality: { status: "ok" as const, rows: 200, excludedRangeCount: 0, volumeAvailable: true } };

function api(calls: Array<[string, unknown]>): StrategyDataApi {
  return {
    async previewSnapshot(body: unknown) {
      calls.push(["preview", body]);
      return { data_epoch: "epoch-a", snapshot_hash: "sha256:" + "a".repeat(64), coverage_start_ms: 0, coverage_end_ms: 200 * 86_400_000,
        row_count: 200, quality: {}, fidelity_capabilities: ["BAR_APPROX"] };
    },
    async createStrategyRevision(body: unknown) { calls.push(["revision", body]); return { revision_id: "srv2_rsi", output_modes: ["SIGNAL"] }; },
    async smokeStrategyRevision(id: string, body: unknown) { calls.push(["smoke", { id, ...(body as object) }]); return {}; },
    async validate(body: unknown) { calls.push(["validate", body]); return {}; },
    async createRun(body: unknown) { calls.push(["run", body]); return { run_id: "bt_saved" }; },
    async inspectPythonBundle(zip: string) { calls.push(["inspect", zip]); return {}; },
  } as unknown as StrategyDataApi;
}

const pythonRevision = { revision_id: "srv2_bundle", provider_kind: "PYTHON_SOURCE", output_modes: ["TARGET_POSITION", "SIGNAL"],
  warmup_requirement: { bars: 3 }, parameter_schema: [{ name: "fast", default: 3 }] } as unknown as StrategyRevisionRecord;

test("a saved strategy runs over imported candles: smoked on the run's snapshot in its runtime, then validated and created", async () => {
  const calls: Array<[string, unknown]> = [];
  const manager = new StrategyDataManager(api(calls));
  const run = await manager.startSavedRevision({ source, settings: DEFAULT_STRATEGY_RUN_SETTINGS, revision: pythonRevision,
    outputMode: "SIGNAL", parameters: { fast: 2 }, python: { runtimeMode: "TRUSTED_LOCAL", trustedConfirmed: true } });
  assert.equal(run.run_id, "bt_saved");
  assert.deepEqual(calls.map(([name]) => name), ["preview", "smoke", "validate", "run"]);
  const smoke = calls[1]![1] as Record<string, unknown>;
  const body = calls[3]![1] as Record<string, unknown>;
  assert.deepEqual([smoke.id, smoke.snapshot_hash, smoke.python_runtime_mode, smoke.python_trusted_confirmed, smoke.parameters],
    ["srv2_bundle", "sha256:" + "a".repeat(64), "TRUSTED_LOCAL", true, { fast: 2 }]);
  assert.ok(Number(smoke.end_time_ms) - Number(smoke.start_time_ms) <= 7 * 86_400_000, "a smoke window is at most seven days");
  assert.deepEqual([body.strategy_revision_id, body.output_mode, body.parameters, body.python_runtime_mode, body.warmup_bars, body.dataset_id],
    ["srv2_bundle", "SIGNAL", { fast: 2 }, "TRUSTED_LOCAL", 3, "local-a"]);
  await assert.rejects(manager.startSavedRevision({ source, settings: DEFAULT_STRATEGY_RUN_SETTINGS, revision: pythonRevision,
    outputMode: "ORDER_INTENT", parameters: {} }), /output mode/);
  await assert.rejects(manager.startSavedRevision({ source, settings: { ...DEFAULT_STRATEGY_RUN_SETTINGS, fidelityPreference: "PRECISE" },
    revision: pythonRevision, outputMode: "SIGNAL", parameters: {} }), /bar execution/);
  await assert.rejects(manager.startSavedRevision({ source, settings: DEFAULT_STRATEGY_RUN_SETTINGS, outputMode: "SIGNAL", parameters: {},
    revision: { ...pythonRevision, provider_kind: "EXTERNAL_PROVIDER" } as StrategyRevisionRecord }), /output mode/,
    "an external model connects through its own panel");
});

test("the builtin RSI template is saved with its parameters, warms up by its length, and studio calls go through the manager", async () => {
  const calls: Array<[string, unknown]> = [];
  const manager = new StrategyDataManager(api(calls));
  await manager.createBuiltinRsiRevision();
  const body = calls[0]![1] as Record<string, unknown>;
  assert.deepEqual([body.language, body.base_revision_id], ["BUILTIN_TEMPLATE", BUILTIN_RSI_REVISION]);
  assert.deepEqual(defaultParameters(body.parameter_schema as Array<Record<string, unknown>>), { length: 24, oversold: 30, overbought: 70 });
  const builtin = { revision_id: "srv2_rsi", provider_kind: "BUILTIN_TEMPLATE", output_modes: ["SIGNAL"], warmup_requirement: {},
    parameter_schema: [] } as unknown as StrategyRevisionRecord;
  await manager.startSavedRevision({ source, settings: DEFAULT_STRATEGY_RUN_SETTINGS, revision: builtin, outputMode: "SIGNAL",
    parameters: { length: 24 }, warmupBars: 25 });
  const run = calls.find(([name]) => name === "run")![1] as Record<string, unknown>;
  assert.equal(run.warmup_bars, 25);
  assert.equal(run.python_runtime_mode, undefined, "a builtin has no Python runtime");
  await manager.pythonStudioApi().inspectPythonBundle("zip");
  assert.deepEqual(calls.at(-1), ["inspect", "zip"]);
  await assert.rejects(new StrategyDataManager({} as StrategyDataApi).pythonStudioApi().createPythonBundle("zip"), /unavailable/i);
});
