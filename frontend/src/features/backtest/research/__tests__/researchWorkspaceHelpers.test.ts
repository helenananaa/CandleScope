import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import test from "node:test";
import { createBacktestApi } from "../../backtestApi.js";
import { parseResearchObjectJson, parseResearchRunConfig, researchReplayHref } from "../backtestResearchAdvancedModel.js";
import { researchModeForTask, researchTaskForMode, strategyResearchModeHref, STRATEGY_RESEARCH_MODES } from "../backtestResearchModes.js";
import type { BacktestResearchTask } from "../backtestResearchTypes.js";

test("the research tools are gone; their task names map to the workspace fields ?mode= opens", () => {
  for (const file of ["../BacktestResearchApp.tsx", "../ResearchMarketChart.tsx", "../useBacktestResearchRuntime.ts", "../ResearchStrategyPanel.tsx"]) {
    assert.equal(existsSync(new URL(file, import.meta.url)), false, `${file} was removed in ADR-BACKTEST-015 P5d`);
  }
  assert.deepEqual(STRATEGY_RESEARCH_MODES, ["quick", "precise", "robust", "python", "multi", "replay"]);
  assert.equal(researchTaskForMode("quick"), null);
  const tasks: BacktestResearchTask[] = ["PRECISE_EXECUTION", "PARAMETER_ROBUSTNESS", "PYTHON_MODEL", "MULTI_MARKET", "REPLAY_REVIEW"];
  for (const task of tasks) assert.equal(researchTaskForMode(researchModeForTask(task)), task);
  assert.equal(strategyResearchModeHref("robust", { study: "st_0123456789", run: null }), "/strategy.html?mode=robust&study=st_0123456789");
});

test("an older launch context is read by its opaque id", async () => {
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(`${String(init?.method ?? "GET")} ${String(input)}`);
    return new Response(JSON.stringify({ context_id: "brc_context_12345678" }), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  try {
    await createBacktestApi("/api/v1/backtests").getResearchLaunchContext("brc_context_12345678");
    assert.deepEqual(calls, ["GET /api/v1/backtests/research/contexts/brc_context_12345678"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("the workspace's kept helpers fail closed", () => {
  assert.throws(() => parseResearchObjectJson("[]", "Run draft"), /must be a JSON object/);
  assert.deepEqual(parseResearchObjectJson('{"a": 1}', "Run draft"), { a: 1 });
  assert.deepEqual(parseResearchRunConfig(null), {});
  assert.deepEqual(parseResearchRunConfig({ config_json: "{bad" } as never), {});
  assert.equal(researchReplayHref({ bridgeId: "btrb_1", trainingRun: { run_id: "tr_12345678" } }), "/replay.html?run=tr_12345678");
  assert.equal(researchReplayHref({ trainingRun: { run_id: "bad id" } }), null);
  assert.equal(researchReplayHref({ bridgeId: "tr_guessed_12345678" }), null);
});
