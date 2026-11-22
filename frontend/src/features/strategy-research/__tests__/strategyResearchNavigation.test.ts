import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import StrategyResearchApp from "../StrategyResearchApp.js";
import {
  parseStrategyResearchLaunch,
  strategyResearchDeepLinkSearch,
} from "../strategyResearchLaunch.js";
import { researchWorkspaceFocus } from "../strategyResearchMode.js";
import { StrategyResearchScriptPanel } from "../StrategyResearchScriptPanel.js";
import {
  createMemoryStrategyDraftAdapter,
  pendingStrategyDraftSave,
  StrategyDraftStore,
} from "../../backtest/chart-tester/StrategyDraftStore.js";


const here = path.dirname(fileURLToPath(import.meta.url));

test("TopBar strategy entry is /strategy.html and not a sibling 策略回测 link", () => {
  const topBar = readFileSync(path.resolve(here, "../../../app/TopBar.tsx"), "utf8") + readFileSync(path.resolve(here, "../../../app/WorkspaceNavigation.tsx"), "utf8");
  assert.match(topBar, /href="\/strategy\.html"/);
  assert.match(topBar, /ux\.research/);
  assert.doesNotMatch(topBar, /href="\/backtest\.html"/);
  assert.doesNotMatch(topBar, /shell\.backtest/);
});

test("backtest.html and its run, study and context links open in the workspace", () => {
  assert.equal(parseStrategyResearchLaunch({ pathname: "/backtest.html", search: "" }).kind, "advanced");
  const run = parseStrategyResearchLaunch({
    pathname: "/backtest.html",
    search: "?run=bt_0123456789abcdef",
  });
  assert.equal(run.kind, "deep-link");
  assert.equal(strategyResearchDeepLinkSearch(run), "?run=bt_0123456789abcdef");
  for (const intent of [parseStrategyResearchLaunch({ pathname: "/backtest.html", search: "" }), run,
    parseStrategyResearchLaunch({ pathname: "/strategy.html", search: "?study=st_0123456789abcdef" }),
    parseStrategyResearchLaunch({ pathname: "/strategy.html", search: "?context=brc_abcdefgh" })]) {
    const html = renderToStaticMarkup(React.createElement(StrategyResearchApp, { intent }));
    assert.doesNotMatch(html, /strategy-research-advanced/, `${intent.kind} opens the workspace (ADR-BACKTEST-015 P5d)`);
    assert.match(html, /strategy-research-shell/);
    assert.doesNotMatch(html, /research-mode-rail|monaco/i);
  }
});

test("?mode= opens the workspace field each research tool became", () => {
  assert.deepEqual(researchWorkspaceFocus("quick"), {});
  assert.deepEqual(researchWorkspaceFocus("precise"), { pane: "conditions", resultTab: "details" });
  assert.deepEqual(researchWorkspaceFocus("robust"), { robustness: true });
  assert.deepEqual(researchWorkspaceFocus("python"), { saved: true });
  assert.deepEqual(researchWorkspaceFocus("multi"), { batch: true });
  assert.deepEqual(researchWorkspaceFocus("replay"), { resultTab: "details" });
  const robust = renderToStaticMarkup(React.createElement(StrategyResearchApp, {
    intent: parseStrategyResearchLaunch({ pathname: "/strategy.html", search: "?mode=robust" }), initialMode: "robust",
  }));
  assert.doesNotMatch(robust, /strategy-research-advanced/);
  assert.match(robust, /strategy-research-shell/);
});

test("invalid deep link shows an actionable error and does not select a dataset", () => {
  const intent = parseStrategyResearchLaunch({
    pathname: "/backtest.html",
    search: "?run=not-a-run",
  });
  assert.equal(intent.kind, "invalid");
  const html = renderToStaticMarkup(
    React.createElement(StrategyResearchApp, {
      intent,
    }),
  );
  assert.match(html, /strategy-research-deep-link-error/);
  assert.doesNotMatch(html, /research-dataset-/);
  assert.doesNotMatch(html.toLowerCase(), /dataset id/);
});

test("ordinary script panel exposes advanced research without internal identity copy", () => {
  const html = renderToStaticMarkup(
    React.createElement(StrategyResearchScriptPanel, {
      cellScope: "strategy-research",
      session: { exchange: "local", marketType: "spot", symbol: "BTC-USDT", interval: "15m" },
      sourceKind: "IMPORTED_DATASET",
      draftId: null,
      barOnly: true,
      runStatus: "READY",
      needsData: false,
      onDraftId() {},
      onDraftRevision() {},
      onRun() {},
      onConfirmNeedsData() {},
      onOpenAdvanced() {},
    }),
  );
  assert.match(html, /strategy-research-open-advanced/);
  assert.doesNotMatch(html.toLowerCase(), /dataset id|data epoch|snapshot hash/);
});

test("as on the chart, the Python strategy panel offers Python only when strategies are named by language", () => {
  const panel = (languageFixed: boolean) => renderToStaticMarkup(
    React.createElement(StrategyResearchScriptPanel, {
      cellScope: "strategy-research",
      session: { exchange: "local", marketType: "spot", symbol: "BTC-USDT", interval: "15m" },
      sourceKind: "IMPORTED_DATASET", draftId: null, barOnly: true, runStatus: "READY", needsData: false,
      onDraftId() {}, onDraftRevision() {}, onRun() {}, onConfirmNeedsData() {}, onOpenAdvanced() {}, languageFixed,
    }),
  );
  const python = panel(true);
  assert.match(python, /strategy-research-template-PYTHON_SMA/);
  assert.doesNotMatch(python, /strategy-research-template-PINE_SAMPLED/, "Pine strategies are their own entry (ADR-BACKTEST-015 P5c4)");
  assert.match(panel(false), /strategy-research-template-PINE_SAMPLED/);
  const app = readFileSync(path.resolve(here, "../StrategyResearchApp.tsx"), "utf8");
  assert.match(app, /strategyList=\{strategyList\}/);
  assert.match(app, /languageFixed=\{strategyList\}/);
});

test("ordinary research persists edited source for remount and advanced draft lookup", async () => {
  const adapter = createMemoryStrategyDraftAdapter();
  const mountedStore = new StrategyDraftStore(adapter, () => 10);
  const initial = await mountedStore.save({
    id: "draft-research1",
    displayName: "Strategy",
    language: "pine",
    source: "template()",
    cursor: { line: 1, column: 1 },
  });
  const pending = pendingStrategyDraftSave({
    draft: initial,
    source: "edited()",
    cursor: { line: 2, column: 3 },
  });
  assert.ok(pending);
  await mountedStore.save(pending);

  const remountedStore = new StrategyDraftStore(adapter);
  const restored = await remountedStore.load(initial.id);
  assert.equal(restored.record?.source, "edited()");
  assert.deepEqual(restored.record?.cursor, { line: 2, column: 3 });

  const panelSource = readFileSync(path.resolve(here, "../StrategyResearchScriptPanel.tsx"), "utf8");
  assert.match(panelSource, /draftStore\.load\(draftId\)/);
  assert.match(panelSource, /await flushPendingDraft\(\)[\s\S]*onOpenAdvanced\?\.\(\)/);
  assert.match(panelSource, /beforeunload/);
});

test("the unified app no longer hosts the research tool", () => {
  const app = readFileSync(path.resolve(here, "../StrategyResearchApp.tsx"), "utf8");
  assert.doesNotMatch(app, /BacktestResearchApp|useBacktestResearchRuntime/);
  assert.doesNotMatch(app, /StrategyResearchModeRail|ResearchModeRailContext|createStrategyResearchContextSearch/);
  assert.match(app, /loadResearchLaunchContext/);
  assert.match(app, /experiments\.openStudy/);
  assert.match(app, /window\.history\.replaceState/);
  assert.doesNotMatch(app, /window\.location\.assign|strategy\.advancedNeedSource|strategy\.advancedNeedDraft/);
  const bridge = readFileSync(path.resolve(here, "../../backtest/chart-tester/ChartStrategyTesterCellBridge.tsx"), "utf8");
  assert.doesNotMatch(bridge, /buildBacktestResearchLaunchContext|createResearchLaunchContext/, "the chart hands off to the workspace");
});
