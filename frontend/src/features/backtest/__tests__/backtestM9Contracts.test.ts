import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// The research tools are gone (ADR-BACKTEST-015 P5d); these paths live in the research workspace.
const strategy = readFileSync(new URL("../../strategy-research/ResearchSavedStrategy.tsx", import.meta.url), "utf8");
const runPanel = readFileSync(new URL("../../strategy-research/StrategyResearchRunDetails.tsx", import.meta.url), "utf8");
const replay = runPanel;
const results = readFileSync(new URL("../chart-tester/ChartStrategyResultViews.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../backtestApi.ts", import.meta.url), "utf8");
const equity = readFileSync(new URL("../BacktestEquityCurve.tsx", import.meta.url), "utf8");
const projection = readFileSync(new URL("../chart-tester/chartStrategyResultProjection.ts", import.meta.url), "utf8");
const legacyMap = readFileSync(new URL("../../strategy-research/strategyResearchLegacyMap.ts", import.meta.url), "utf8");

test("M9 workspace exposes immutable revision compile, smoke, compare and clone paths", () => {
  for (const token of ["PythonStudioPanel", "createBuiltinRsiRevision", "startSavedRevision"]) {
    assert.match(strategy, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(runPanel, /deriveRun/);
  assert.match(replay, /revealReviewBridge/);
  assert.match(results, /tradeDiff/);
  for (const path of ["/strategy-revisions", "/signal-trace", "/compare/pair", "/clone", "/review-bridge", "/review-bridges/"]) {
    assert.ok(api.includes(path));
  }
  assert.match(legacyMap, /rsi-trace-pane/);
  assert.match(legacyMap, /status: "deferred"/);
});

test("M9 long curves and tables have explicit render bounds", () => {
  assert.match(results, /BacktestEquityCurve/);
  assert.match(equity, /boundBacktestProjectionRows\(data\)/);
  assert.match(projection, /limit = 2_000/);
  assert.match(projection, /slice\(-limit\)/);
});
