import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(here, "..");
const repoRoot = path.resolve(frontendRoot, "..");

export function runStrategyResearchSmoke(root = repoRoot) {
  const files = [
    "frontend/strategy.html",
    "frontend/local.html",
    "frontend/backtest.html",
    "frontend/src/strategy-main.tsx",
    "frontend/src/local-main.tsx",
    "frontend/src/backtest-main.tsx",
  ];
  for (const file of files) {
    if (!existsSync(path.join(root, file))) {
      throw new Error(`missing ${file}`);
    }
  }
  const topBar = readFileSync(path.join(root, "frontend/src/app/TopBar.tsx"), "utf8") + readFileSync(path.join(root, "frontend/src/app/WorkspaceNavigation.tsx"), "utf8");
  if (!topBar.includes('href="/strategy.html"')) {
    throw new Error("TopBar must link /strategy.html");
  }
  if (topBar.includes('href="/backtest.html"')) {
    throw new Error("TopBar must not keep a sibling /backtest.html entry");
  }
  // The flag-off fallbacks (standalone LocalApp, the BacktestApp wrapper, the research-disabled
  // screen and the library flag) are retired: every page opens the one strategy research app.
  const retired = [
    "frontend/src/features/backtest/BacktestApp.tsx",
    "frontend/src/features/backtest/research/BacktestResearchDisabled.tsx",
    "frontend/src/features/local-data/LocalApp.tsx",
    "frontend/src/features/research-data/researchDataFlags.ts",
  ];
  for (const file of retired) {
    if (existsSync(path.join(root, file))) {
      throw new Error(`retired fallback is back: ${file}`);
    }
  }
  const bootstrap = readFileSync(
    path.join(root, "frontend/src/features/strategy-research/strategyResearchBootstrap.tsx"),
    "utf8",
  );
  if (!bootstrap.includes("<StrategyResearchApp intent={intent} />")) {
    throw new Error("every page must open the strategy research app");
  }
  if (/LocalApp|BacktestApp\b|BacktestResearchDisabled|local-legacy|backtest-legacy|libraryEnabled/.test(bootstrap)) {
    throw new Error("the bootstrap must not route to a retired fallback");
  }
  const launch = readFileSync(
    path.join(root, "frontend/src/features/strategy-research/strategyResearchLaunch.ts"),
    "utf8",
  );
  if (!launch.includes('file === "local.html"') || !launch.includes('file === "backtest.html"')) {
    throw new Error("legacy URLs must parse");
  }
  const readme = readFileSync(path.join(root, "README.md"), "utf8");
  if (/Pine custom scripts are available in the LOCAL_OFFLINE/.test(readme)) {
    throw new Error("README must not claim unverified Pine offline capability");
  }
  return {
    ok: true,
    canonical: "/strategy.html",
    compatibility: ["/local.html", "/backtest.html"],
    retiredFallbacks: retired.length,
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = runStrategyResearchSmoke();
  process.stdout.write(`${JSON.stringify(result)}\n`);
}
