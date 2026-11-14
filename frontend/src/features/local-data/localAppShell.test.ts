import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";


const directory = dirname(fileURLToPath(import.meta.url));

test("imported analysis reuses shared chart controls, settings, export, and indicator surfaces", () => {
  const source = readFileSync(resolve(directory, "../strategy-research/StrategyResearchChart.tsx"), "utf8");

  assert.match(source, /<IndicatorPanel/);
  assert.match(source, /staticCatalog=\{indicatorCatalog\}/);
  assert.match(source, /<DrawingToolbar/);
  assert.match(source, /drawingTool=\{drawingTool\}/);
  assert.match(source, /<ExportPanel/);
  assert.match(source, /usePriceScalePrefs/);
  assert.match(source, /saveVisibleRangeForInterval/);
  assert.match(source, /<LocalIntervalSelector/);
  assert.match(source, /useLocalChartRuntime/);
  assert.match(source, /useLocalIndicatorRuntime/);
  assert.doesNotMatch(source, /LocalIndicatorPanel/);
  assert.doesNotMatch(source, /LOCAL_STATIC_INDICATOR_CATALOG/);
  assert.doesNotMatch(source, /from "\.\.\/market-data\/feed\/klineApi/);
});

test("the standalone LocalApp shell is retired; local.html opens the strategy research page", () => {
  assert.equal(existsSync(resolve(directory, "LocalApp.tsx")), false);
  const app = readFileSync(resolve(directory, "../strategy-research/StrategyResearchApp.tsx"), "utf8");
  assert.match(app, /useResearchDataLibrary/);
  assert.match(app, /useLocalIntervalSelection/);
});
