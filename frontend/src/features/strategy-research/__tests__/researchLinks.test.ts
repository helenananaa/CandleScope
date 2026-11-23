import assert from "node:assert/strict";
import test from "node:test";
import type { BacktestResearchLaunchContext } from "../../backtest/backtestTypes.js";
import { launchContextState, researchRunSource } from "../researchLinks.js";

test("a linked run opens on the data it used", () => {
  assert.deepEqual(researchRunSource({ exchange: "local", start_time_ms: 0, end_time_ms: 99, interval: "1d" },
    { dataset_id: "local-a", data_epoch: "epoch-a" }), { datasetId: "local-a", dataEpoch: "epoch-a" });
  assert.deepEqual(researchRunSource({ exchange: "binance", market_type: "spot", symbol: "BTCUSDT", interval: "1m",
    start_time_ms: 1_000, end_time_ms: 59_999 }), { schemaVersion: "candlescope.research-source/1", kind: "EXCHANGE_SERIES",
    exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m", startMs: 1_000, endMs: 60_000 });
  assert.equal(researchRunSource({ exchange: "binance", start_time_ms: 0, end_time_ms: 1 }), null, "an unknown market stays unselected");
});

const context: BacktestResearchLaunchContext = {
  schema_version: "candlescope.backtest-research-launch-context/1", context_id: "brc_abcdefgh", context_hash: "sha256:x",
  source_workspace_id: "ws", source_cell_id: "cell", strategy_draft_id: "draft-1", strategy_revision_id: null, parameters: {},
  quick_preset_id: "CRYPTO_SPOT_STANDARD_V1", chart_session: { exchange: "binance", market_type: "spot", symbol: "BTCUSDT", interval: "15m" },
  range: { mode: "CUSTOM", start_time_ms: 0, end_time_ms: 899_999 }, dataset_identity: null, latest_run_id: "bt_1",
  baseline_run_id: null, entry_task: "PARAMETER_ROBUSTNESS", created_at_ms: 1,
};

test("an older launch context restores its chart, draft, run and research field", () => {
  const chart = launchContextState(context);
  assert.deepEqual(chart.source, { schemaVersion: "candlescope.research-source/1", kind: "CURRENT_CHART", workspaceId: "ws",
    cellId: "cell", exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "15m" });
  assert.deepEqual([chart.draftId, chart.runId, chart.mode], ["draft-1", "bt_1", "robust"]);
  const imported = launchContextState({ ...context, dataset_identity: { dataset_id: "local-a", data_epoch: "epoch-a", snapshot_hash: "s" } });
  assert.deepEqual(imported.source, { datasetId: "local-a", dataEpoch: "epoch-a" });
  const research = launchContextState({ ...context, source_workspace_id: "strategy-research", entry_task: null });
  assert.equal((research.source as { kind?: string }).kind, "EXCHANGE_SERIES", "the research page's own context names a range");
  assert.equal(research.mode, null);
});
