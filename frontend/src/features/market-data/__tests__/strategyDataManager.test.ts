import assert from "node:assert/strict";
import test from "node:test";
import type { BacktestApiClient } from "../../backtest/backtestApi.js";
import type { BacktestRunRecord, BacktestReport, BacktestChartData } from "../../backtest/backtestTypes.js";
import { StrategyDataManager } from "../manager/strategyDataManager.js";

function run(runId: string, state = "COMPLETED"): BacktestRunRecord {
  return { run_id: runId, state, fidelity_mode: "BAR_APPROX", source_event_kind: "BAR", config_hash: "config:" + runId,
    dataset_id: "dataset", data_epoch: "epoch", snapshot_hash: "snapshot:" + runId,
    config_json: JSON.stringify({ start_time_ms: 1, end_time_ms: 100 }) };
}
function fixture(overrides: Partial<BacktestApiClient> = {}): BacktestApiClient {
  return {
    async getRun(runId: string) { return run(runId); },
    async getReport(runId: string): Promise<BacktestReport> {
      return { schemaVersion: "1", runId, fidelity_mode: "BAR_APPROX", source_event_kind: "BAR", report_label: "BAR_APPROX",
        hashes: { report: "report:" + runId }, metrics: { fill_count: 0, ambiguity_count: 0, rejected_order_count: 0,
          trade_count: 0, winning_trade_count: 0, win_rate: "0", realized_net_pnl: "0" },
        unmodeled: [], suitable_for: [], not_suitable_for: [], fills: [], trades: [] };
    },
    async getChart(runId: string): Promise<BacktestChartData> {
      return { run_id: runId, chart_hash: "chart:" + runId, symbol: "BTCUSDT", interval: "1m", bars: [], fills: [], equity_curve: [], truncated: false };
    },
    ...overrides,
  } as BacktestApiClient;
}

test("restoring a preparing run uses one stream and keeps results keyed by fixed identity", async () => {
  let gets = 0, streams = 0;
  const manager = new StrategyDataManager(fixture({
    async getRun(runId) { gets += 1; return run(runId, gets === 1 ? "PREPARING" : "COMPLETED"); },
    async streamRun(runId, _signal, onUpdate) {
      streams += 1;
      onUpdate?.({ type: "progress", run: run(runId, "RUNNING"), progress: { sequence: 10, generation: 1, state_hash: "checkpoint", created_at_ms: 1 } });
      onUpdate?.({ type: "completed", run: run(runId), progress: null });
      return run(runId);
    },
  }));
  const result = await manager.restoreRun("one");
  assert.equal(streams, 1);
  assert.equal(gets, 2, "one restore lookup and one committed-result identity lookup; no polling");
  assert.equal(result.cacheKey, "one|dataset|epoch|snapshot:one|report:one|chart:one");
  assert.equal(manager.diagnostics().streams, 0);
  assert.equal(manager.diagnostics().operations, 0);
  assert.equal(manager.diagnostics().results.entries, 1);
  manager.dispose();
});

test("aborting one consumer preserves siblings and disposal does not cancel durable runs", async () => {
  const entered = new Map<string, AbortSignal>();
  let cancellations = 0;
  const manager = new StrategyDataManager(fixture({
    async getRun(runId) { return run(runId, "RUNNING"); },
    async streamRun(runId, signal) {
      assert.ok(signal);
      entered.set(runId, signal);
      await new Promise<void>((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true }));
      return run(runId);
    },
    async cancelRun(runId) { cancellations += 1; return run(runId, "CANCELLED"); },
  }));
  const first = new AbortController();
  const a = manager.restoreRun("one", first.signal), b = manager.restoreRun("two");
  const aRejected = assert.rejects(a, { name: "AbortError" }), bRejected = assert.rejects(b, { name: "AbortError" });
  await Promise.resolve(); await Promise.resolve();
  assert.equal(manager.diagnostics().streams, 2);
  first.abort(); await aRejected;
  assert.equal(entered.get("two")!.aborted, false);
  assert.equal(manager.diagnostics().streams, 1);
  manager.dispose(); await bRejected;
  assert.equal(cancellations, 0);
  assert.equal(manager.diagnostics().operations, 0);
  assert.equal(manager.diagnostics().streams, 0);
});

test("missing stream transport fails instead of falling back to polling and explicit cancellation is separate", async () => {
  let gets = 0, cancellations = 0;
  const manager = new StrategyDataManager(fixture({
    async getRun(runId) { gets += 1; return run(runId, "RUNNING"); },
    async cancelRun(runId) { cancellations += 1; return run(runId, "CANCELLED"); },
  }));
  await assert.rejects(manager.restoreRun("one"), { code: "STRATEGY_STREAM_UNAVAILABLE" });
  assert.equal(gets, 1);
  assert.equal((await manager.cancelRun("one")).state, "CANCELLED");
  assert.equal(cancellations, 1);
  manager.dispose();
  await assert.rejects(manager.restoreRun("one"), { code: "STRATEGY_MANAGER_CLOSED" });
});

test("result retention is bounded and closing the owner clears only its own cache", async () => {
  const api = fixture(), first = new StrategyDataManager(api), sibling = new StrategyDataManager(api);
  await sibling.loadResult("shared");
  for (let i = 0; i < 10; i += 1) await first.loadResult("run-" + i);
  assert.equal(first.diagnostics().results.entries, 8);
  first.dispose();
  assert.equal(first.diagnostics().results.entries, 0);
  assert.equal(sibling.diagnostics().results.entries, 1);
  sibling.dispose();
});

test("comparison uses the requested ordered pair and rejects a response for another pair", async () => {
  const manager = new StrategyDataManager(fixture({
    async listRuns() { return [run("one"), run("two")]; },
    async compareRuns(left, right, signal) {
      assert.equal(left, "one");
      assert.equal(right, "two");
      assert.ok(signal);
      const side = (runId: string) => ({ runId, hashes: {}, equity: [], equityDaily: [], drawdownDaily: [], metrics: {} });
      return {
        schema: "RUN_COMPARE_V3",
        directComparisonAllowed: false,
        incompatibleFields: ["dataset"],
        comparisonContext: { leftHash: "left", rightHash: "right" },
        precisionExplanation: null,
        parameterDiff: {}, tradeDiff: {}, costDiff: {},
        fingerprintDiff: { version: "TRADE_FINGERPRINT_V2", available: false, addedCount: null,
          removedCount: null, unchangedCount: null, added: [], removed: [] },
        left: side(right), right: side(left),
      };
    },
  }));
  assert.deepEqual((await manager.listRuns()).map(item => item.run_id), ["one", "two"]);
  await assert.rejects(manager.compareRuns("one", "one"), { code: "COMPARISON_PAIR_INVALID" });
  await assert.rejects(manager.compareRuns("one", "two"), { code: "RESULT_IDENTITY_MISMATCH" });
  assert.equal(manager.diagnostics().operations, 0);
  manager.dispose();
});
