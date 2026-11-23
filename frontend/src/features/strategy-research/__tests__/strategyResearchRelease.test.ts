import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";


const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../../");

test("the library flag and its flag-off fallbacks are retired", () => {
  assert.equal(existsSync(path.join(repoRoot, "frontend/src/features/research-data/researchDataFlags.ts")), false);
  const launch = readFileSync(path.join(repoRoot, "frontend/src/features/strategy-research/strategyResearchLaunch.ts"), "utf8");
  assert.doesNotMatch(launch, /resolveStrategyResearchBootstrap|local-legacy|backtest-legacy/);
  const env = readFileSync(path.join(repoRoot, "frontend/.env.example"), "utf8");
  assert.doesNotMatch(env, /VITE_RESEARCH_DATA_LIBRARY_ENABLED|VITE_BACKTEST_RESEARCH_ENABLED|VITE_BACKTEST_LEGACY_WORKBENCH_ENABLED/);
  const topBar = readFileSync(path.join(repoRoot, "frontend/src/app/WorkspaceNavigation.tsx"), "utf8");
  assert.match(topBar, /href="\/strategy\.html"/);
  assert.doesNotMatch(topBar, /href="\/backtest\.html"/);
});

test("release smoke entrypoints remain in the production Vite inputs", () => {
  const vite = readFileSync(path.join(repoRoot, "frontend/vite.config.js"), "utf8");
  assert.match(vite, /local\.html/);
  assert.match(vite, /backtest\.html/);
  assert.match(vite, /strategy\.html/);
});
